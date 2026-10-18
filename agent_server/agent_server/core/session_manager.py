"""
Session Manager — conversation state, tool history, and context persistence.

Sessions are persisted in PostgreSQL with Redis caching for fast access.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agent_server.config import settings
from shared.db.redis_client import get_redis
from shared.observability.logging import get_logger

logger = get_logger(__name__)


class SessionManager:
    """Manages agent conversation sessions.

    Session data:
    - context: accumulated facts, user preferences, current intent
    - tool_history: ordered list of tool calls and results
    - messages: conversation messages for LLM context window
    """

    REDIS_PREFIX = "agent:session:"
    SESSION_TTL = int(timedelta(minutes=settings.session_ttl_minutes).total_seconds())

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_session(self, user_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        """Create a new agent session."""
        if session_id:
            try:
                session_id = str(uuid.UUID(str(session_id)))
            except ValueError:
                session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(session_id)))
        else:
            session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=settings.session_ttl_minutes)

        session_data = {
            "id": session_id,
            "user_id": user_id,
            "state": "active",
            "context": {"dialogue_state": {}},
            "tool_history": [],
            "messages": [],
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        # Check if user_id exists in users table (only registered users can be stored in user_id FK)
        db_user_id = None
        if user_id:
            try:
                u_uuid = uuid.UUID(str(user_id))
                res = await self.db.execute(
                    text("SELECT id FROM users WHERE id = :uid"),
                    {"uid": u_uuid}
                )
                if res.fetchone() is not None:
                    db_user_id = str(u_uuid)
                else:
                    session_data["context"]["guest_user_id"] = str(user_id)
            except Exception:
                db_user_id = None

        # Persist to DB
        await self.db.execute(
            text("""
                INSERT INTO agent_sessions (id, user_id, state, context, tool_history, expires_at)
                VALUES (:id, :uid, 'active', :ctx, :th, :exp)
            """),
            {
                "id": session_id,
                "uid": db_user_id,
                "ctx": json.dumps(session_data["context"]),
                "th": json.dumps(session_data["tool_history"]),
                "exp": expires_at,
            },
        )
        await self.db.commit()

        # Cache in Redis
        try:
            redis = await get_redis()
            await redis.setex(
                f"{self.REDIS_PREFIX}{session_id}",
                self.SESSION_TTL,
                json.dumps(session_data, default=str),
            )
        except Exception:
            pass  # If Redis fails, DB is source of truth

        logger.info("session_created", session_id=session_id, user_id=user_id)
        return session_data

    def _is_valid_uuid(self, val: str) -> bool:
        try:
            uuid.UUID(str(val))
            return True
        except ValueError:
            return False

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session — tries Redis cache first, falls back to DB."""
        if not self._is_valid_uuid(session_id):
            session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(session_id)))

        # Try Redis
        try:
            redis = await get_redis()
            cached = await redis.get(f"{self.REDIS_PREFIX}{session_id}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass

        # Fall back to DB
        result = await self.db.execute(
            text("SELECT id, user_id, state, context, tool_history, expires_at FROM agent_sessions WHERE id = :id"),
            {"id": session_id},
        )
        row = result.fetchone()
        if not row:
            return None

        session_data = {
            "id": str(row[0]),
            "user_id": str(row[1]) if row[1] else None,
            "state": row[2],
            "context": row[3] if isinstance(row[3], dict) else json.loads(row[3] or "{}"),
            "tool_history": row[4] if isinstance(row[4], list) else json.loads(row[4] or "[]"),
            "messages": [],
            "expires_at": str(row[5]),
        }
        # Restore messages from context if they were persisted there
        ctx_messages = session_data["context"].get("_messages")
        if ctx_messages:
            session_data["messages"] = ctx_messages

        # Re-cache
        try:
            redis = await get_redis()
            await redis.setex(
                f"{self.REDIS_PREFIX}{session_id}",
                self.SESSION_TTL,
                json.dumps(session_data, default=str),
            )
        except Exception:
            pass

        return session_data

    async def update_session(
        self,
        session_id: str,
        context: dict[str, Any] | None = None,
        tool_call: dict[str, Any] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Update session state."""
        session = await self.get_session(session_id)
        if not session:
            return None

        if context:
            session["context"].update(context)

        if tool_call:
            session["tool_history"].append({
                **tool_call,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        if messages is not None:
            session["messages"] = messages
            # Also persist messages inside context so they survive Redis eviction
            session["context"]["_messages"] = messages

        # Update DB (persist context which now also stores messages)
        await self.db.execute(
            text("""
                UPDATE agent_sessions SET context = :ctx, tool_history = :th
                WHERE id = :id
            """),
            {
                "id": session_id,
                "ctx": json.dumps(session["context"]),
                "th": json.dumps(session["tool_history"], default=str),
            },
        )
        await self.db.commit()

        # Update Redis
        try:
            redis = await get_redis()
            await redis.setex(
                f"{self.REDIS_PREFIX}{session_id}",
                self.SESSION_TTL,
                json.dumps(session, default=str),
            )
        except Exception:
            pass

        return session

    async def end_session(self, session_id: str) -> None:
        """Mark session as ended."""
        if not self._is_valid_uuid(session_id):
            return

        await self.db.execute(
            text("UPDATE agent_sessions SET state = 'ended' WHERE id = :id"),
            {"id": session_id},
        )
        await self.db.commit()

        try:
            redis = await get_redis()
            await redis.delete(f"{self.REDIS_PREFIX}{session_id}")
        except Exception:
            pass

        logger.info("session_ended", session_id=session_id)

    async def get_dialogue_state(self, session_id: str) -> DialogueState:
        """Retrieve the DialogueState object for a session."""
        from agent_server.core.dialogue_state import DialogueState
        session = await self.get_session(session_id)
        if not session:
            return DialogueState(session_id=session_id)
        ctx = session.get("context", {})
        ds_dict = ctx.get("dialogue_state", {})
        ds = DialogueState.from_dict(ds_dict)
        ds.session_id = session_id
        if "merchant_id" in ctx:
            ds.merchant_id = ctx["merchant_id"]
        return ds

    async def update_dialogue_state(self, session_id: str, state: DialogueState) -> None:
        """Persist DialogueState back to PostgreSQL and Redis."""
        session = await self.get_session(session_id)
        if not session:
            return
        context = session.get("context", {})
        context["dialogue_state"] = state.to_dict()
        if state.last_shown_listings:
            context["last_seen_listings"] = state.last_shown_listings
        await self.update_session(session_id, context=context)
