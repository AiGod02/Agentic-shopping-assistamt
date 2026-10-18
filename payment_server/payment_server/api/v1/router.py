"""
Payment API v1 Router.
"""

from fastapi import APIRouter

from payment_server.api.v1.payments import router as payments_router
from payment_server.api.v1.webhooks import router as webhooks_router

api_router = APIRouter()

api_router.include_router(payments_router, prefix="/payments", tags=["payments"])
api_router.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
