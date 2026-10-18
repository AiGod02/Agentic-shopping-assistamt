"""Sessions API — create, get, delete agent sessions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from agent_server.core.session_manager import SessionManager
from shared.auth.rbac import get_current_user, get_optional_user
from shared.db.session import get_db

router = APIRouter()


@router.post("")
async def create_session(
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent session (supports optional authenticated user or anonymous guest session)."""
    mgr = SessionManager(db)
    user_id = user.sub if user else None
    session = await mgr.create_session(user_id=user_id)
    return session


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Get session details including tool history."""
    mgr = SessionManager(db)
    session = await mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    user_id = user.sub if user else None
    session_owner = session.get("user_id")
    if session_owner and str(session_owner) != str(user_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this session")
    return session


@router.delete("/{session_id}")
async def end_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """End an agent session."""
    mgr = SessionManager(db)
    await mgr.end_session(session_id)
    return {"status": "ended", "session_id": session_id}
