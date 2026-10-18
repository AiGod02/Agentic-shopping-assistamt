"""
Agent API — the main chat endpoint and tool discovery.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agent_server.core.orchestrator import AgentOrchestrator
from agent_server.core.session_manager import SessionManager
from agent_server.core.tool_registry import tool_registry
from agent_server.tools.commerce_tools import register_all_tools
from shared.auth.rbac import get_current_user, get_optional_user
from shared.db.session import get_db
from shared.observability.request_context import new_trace_id, set_trace, trace_log

router = APIRouter()

# Register tools on import
register_all_tools()


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(..., min_length=1, max_length=2000)
    llm_provider: str | None = None  # Override default provider
    merchant_id: str | None = None  # Bind chat session to a specific storefront


class ChatResponse(BaseModel):
    session_id: str
    response: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):

    """Send a message to the commerce agent.

    The agent will:
    1. Understand the user's intent
    2. Decide which tools to call
    3. Execute tools against the merchant/payment APIs
    4. Return a natural language response with results
    """
    session_mgr = SessionManager(db)

    import uuid

    # ── TRACE: assign a unique trace_id for this HTTP request ──
    trace_id = new_trace_id()
    set_trace(trace_id)
    trace_log("http_request_received",
              method="POST", path="/api/v1/agent/chat",
              session_id=body.session_id or "(new)",
              msg_preview=body.message[:60])

    # Create or retrieve session
    user_id = user.sub if user else None
    if body.session_id:
        session = await session_mgr.get_session(body.session_id)
        if not session:
            session = await session_mgr.create_session(session_id=body.session_id, user_id=user_id)
        session_id = session["id"]
    else:
        session = await session_mgr.create_session(user_id=user_id)
        session_id = session["id"]

    context = session.get("context", {}) or {}
    context_updated = False

    # Bind session to merchant context if provided (with validation)
    if body.merchant_id:
        try:
            m_uuid = uuid.UUID(body.merchant_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid merchant_id format: '{body.merchant_id}'")

        from sqlalchemy import text
        res = await db.execute(
            text("SELECT id, status FROM merchants WHERE id = :m_id"),
            {"m_id": m_uuid}
        )
        m_row = res.fetchone()
        if not m_row:
            raise HTTPException(status_code=404, detail=f"Merchant '{body.merchant_id}' not found")
        if m_row.status != "active":
            raise HTTPException(status_code=400, detail=f"Merchant '{body.merchant_id}' is inactive ({m_row.status})")

        context["merchant_id"] = str(m_uuid)
        context_updated = True

    # For guest sessions, ensure a unique session-scoped guest_user_id exists
    if not user:
        if "guest_user_id" not in context:
            context["guest_user_id"] = str(uuid.uuid4())
            context_updated = True
        effective_user_id = context["guest_user_id"]
    else:
        effective_user_id = user.sub

    if context_updated:
        await session_mgr.update_session(session_id, context=context)

    # Process message
    orchestrator = AgentOrchestrator(session_mgr, body.llm_provider)

    # Extract JWT token from header for forwarding to merchant API
    raw_auth = request.headers.get("Authorization", "")
    user_token = ""
    if raw_auth.startswith("Bearer "):
        user_token = raw_auth[7:]

    if not user_token:
        from shared.auth.jwt_handler import JWTHandler
        from agent_server.config import settings as agent_settings
        jwt_h = JWTHandler(secret_key=agent_settings.jwt_secret_key)
        user_token = jwt_h.create_access_token(
            user_id=effective_user_id,
            role="customer",
        )


    result = await orchestrator.process_message(
        session_id=session_id,
        user_message=body.message,
        user_token=user_token,
    )

    trace_log("http_response_ready",
              session_id=result["session_id"],
              tools_called=[t.get("tool") for t in result.get("tool_calls", [])],
              response_len=len(result["response"]))

    # Persist conversation messages so LLM has multi-turn context on subsequent requests
    session_after = await session_mgr.get_session(result["session_id"])
    if session_after is not None:
        existing_messages: list[dict] = session_after.get("messages") or []
        existing_messages.append({"role": "user", "content": body.message})
        existing_messages.append({"role": "assistant", "content": result["response"]})
        # Keep only last 20 messages (10 turns) to stay within context window
        existing_messages = existing_messages[-20:]
        await session_mgr.update_session(result["session_id"], messages=existing_messages)

    return ChatResponse(
        session_id=result["session_id"],
        response=result["response"],
        tool_calls=result.get("tool_calls", []),
    )


@router.get("/tools")
async def list_available_tools():
    """List all available commerce tools the agent can use."""
    tools = tool_registry.list_tools()
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category.value,
                "parameters": [
                    {
                        "name": p.name,
                        "type": p.type,
                        "description": p.description,
                        "required": p.required,
                    }
                    for p in t.parameters
                ],
                "requires_confirmation": t.requires_confirmation,
            }
            for t in tools
        ],
        "total": len(tools),
    }


@router.post("/webhook/index-listing")
async def index_listing_webhook(payload: dict[str, Any]):
    """Internal webhook for the merchant server to index new listings into the configured search backend."""
    from agent_server.tools.commerce_tools import _get_search_engine
    engine = _get_search_engine()
    success = await engine.create_listing_object(payload)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to index listing")
    return {"status": "indexed"}


@router.get("/search")
async def search_listings_endpoint(
    q: str,
    type: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    tags: str | None = None,
    limit: int = 10,
):
    """Search listings using semantic/keyword search via agent tools."""
    from agent_server.tools.commerce_tools import search_listings
    return await search_listings(
        query=q,
        type=type,
        min_price=min_price,
        max_price=max_price,
        tags=tags,
        limit=limit,
    )


@router.post("/guest-token", response_model=dict)
async def create_agent_guest_token():
    """Issue a cryptographically signed guest JWT for anonymous shopping."""
    import uuid
    from shared.auth.jwt_handler import JWTHandler
    from agent_server.config import settings as agent_settings
    jwt_h = JWTHandler(secret_key=agent_settings.jwt_secret_key)
    guest_uuid = str(uuid.uuid4())
    access_token = jwt_h.create_access_token(
        user_id=guest_uuid,
        role="customer",
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": guest_uuid,
        "role": "customer",
        "is_guest": True,
        "expires_in": jwt_h.access_token_expire_minutes * 60,
    }

