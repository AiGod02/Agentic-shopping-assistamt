"""
API v1 Router — aggregates all route modules.
"""

from fastapi import APIRouter

from merchant_server.api.v1.listings import router as listings_router
from merchant_server.api.v1.cart import router as cart_router
from merchant_server.api.v1.orders import router as orders_router
from merchant_server.api.v1.merchants import router as merchants_router
from merchant_server.api.v1.availability import router as availability_router
from merchant_server.api.v1.bookings import router as bookings_router
from merchant_server.api.v1.analytics import router as analytics_router
from merchant_server.api.v1.admin import router as admin_router
from merchant_server.api.v1.subscriptions import router as subscriptions_router

api_router = APIRouter()

api_router.include_router(listings_router, prefix="/listings", tags=["listings"])
api_router.include_router(cart_router, prefix="/cart", tags=["cart"])
api_router.include_router(orders_router, prefix="/orders", tags=["orders"])
api_router.include_router(merchants_router, prefix="/merchants", tags=["merchants"])
api_router.include_router(availability_router, prefix="/availability", tags=["availability"])
api_router.include_router(bookings_router, prefix="/bookings", tags=["bookings"])
api_router.include_router(analytics_router, prefix="/analytics", tags=["analytics"])
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])
api_router.include_router(subscriptions_router, prefix="/subscriptions", tags=["subscriptions"])


