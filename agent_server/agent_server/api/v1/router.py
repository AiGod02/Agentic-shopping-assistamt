"""Agent API v1 Router."""

from fastapi import APIRouter

from agent_server.api.v1.agent import router as agent_router
from agent_server.api.v1.sessions import router as sessions_router

api_router = APIRouter()

api_router.include_router(agent_router, prefix="/agent", tags=["agent"])
api_router.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
