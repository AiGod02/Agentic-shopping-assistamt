"""
Commerce Tools — concrete tool implementations that call the merchant/payment APIs.

Each tool is registered with the ToolRegistry and callable by the agent orchestrator.
"""

from __future__ import annotations

from typing import Any

import httpx

from agent_server.config import settings
from agent_server.core.search import WeaviateSearch
from agent_server.core.tool_registry import ToolCategory, ToolDefinition, ToolParameter, tool_registry
from shared.middleware.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from shared.observability.logging import get_logger

logger = get_logger(__name__)

merchant_breaker = CircuitBreaker("merchant-api", CircuitBreakerConfig(failure_threshold=5, timeout_seconds=30))
payment_breaker = CircuitBreaker("payment-api", CircuitBreakerConfig(failure_threshold=5, timeout_seconds=30))

_http_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client


# ────────────────────────────────────────────────────────────────
#  SEARCH TOOLS
# ────────────────────────────────────────────────────────────────

def _get_search_engine():
    """Get the configured search backend — ChromaDB for local, Weaviate for production."""
    if settings.search_backend == "chromadb":
        from agent_server.core.chroma_search import ChromaSearch
        return ChromaSearch()
    else:
        from agent_server.core.search import WeaviateSearch
        return WeaviateSearch()


async def search_listings(
    query: str,
    type: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    tags: str | None = None,
    limit: int = 10,
    active_merchant_id: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Search listings using hybrid semantic + keyword search with PostgreSQL fallback."""
    search = _get_search_engine()
    merchant_id = active_merchant_id or kwargs.get("active_merchant_id") or None
    results = await search.hybrid_search(
        query=query,
        listing_type=type,
        min_price=min_price,
        max_price=max_price,
        tags=tags.split(",") if tags else None,
        limit=limit,
        merchant_id=merchant_id,
    )
    source = results[0].get("source", "unknown") if results else "none"
    return {"results": results, "count": len(results), "query": query, "search_backend": source}


async def get_listing_details(
    listing_id: str,
    active_merchant_id: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Get full details of a specific listing."""
    client = await _get_client()
    params = {}
    merchant_id = active_merchant_id or kwargs.get("active_merchant_id")
    if merchant_id:
        params["merchant_id"] = merchant_id

    @merchant_breaker.protect
    async def _call():
        resp = await client.get(
            f"{settings.merchant_server_url}/api/v1/listings/{listing_id}",
            params=params if params else None,
        )
        resp.raise_for_status()
        return resp.json()

    return await _call()


async def get_listing_reviews(listing_id: str, page: int = 1, **kwargs) -> dict[str, Any]:
    """Get user reviews and ratings for a listing."""
    client = await _get_client()

    @merchant_breaker.protect
    async def _call():
        resp = await client.get(
            f"{settings.merchant_server_url}/api/v1/listings/{listing_id}/reviews",
            params={"page": page}
        )
        resp.raise_for_status()
        return resp.json()

    return await _call()


async def compare_listings(
    listing_ids: list[str],
    active_merchant_id: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Get details for multiple listings for comparison."""
    client = await _get_client()
    compared_items = []
    merchant_id = active_merchant_id or kwargs.get("active_merchant_id")
    for lid in listing_ids:
        params = {}
        if merchant_id:
            params["merchant_id"] = merchant_id
        try:
            resp = await client.get(
                f"{settings.merchant_server_url}/api/v1/listings/{lid}",
                params=params if params else None,
            )
            if resp.status_code == 200:
                compared_items.append(resp.json())
        except Exception as e:
            logger.warning("compare_listings_fetch_failed", listing_id=lid, error=str(e))
    return {"compared_items": compared_items, "count": len(compared_items)}


async def check_availability(
    listing_id: str,
    check_in: str | None = None,
    check_out: str | None = None,
    active_merchant_id: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Check availability for a listing (hotels, rentals, services)."""
    client = await _get_client()
    params = {}
    if check_in:
        params["from_date"] = check_in
    if check_out:
        params["to_date"] = check_out
    merchant_id = active_merchant_id or kwargs.get("active_merchant_id")
    if merchant_id:
        params["merchant_id"] = merchant_id

    @merchant_breaker.protect
    async def _call():
        resp = await client.get(
            f"{settings.merchant_server_url}/api/v1/availability/listing/{listing_id}",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    return await _call()


# ────────────────────────────────────────────────────────────────
#  CART TOOLS
# ────────────────────────────────────────────────────────────────

async def view_cart(user_token: str = "", session_id: str = "", **kwargs) -> dict[str, Any]:
    """View the current user's shopping cart."""
    client = await _get_client()
    headers = {}
    if user_token:
        headers["Authorization"] = f"Bearer {user_token}"
    sid = session_id or kwargs.get("session_id")
    if sid:
        headers["X-Session-ID"] = str(sid)

    @merchant_breaker.protect
    async def _call():
        resp = await client.get(
            f"{settings.merchant_server_url}/api/v1/cart",
            headers=headers if headers else None,
        )
        resp.raise_for_status()
        return resp.json()

    return await _call()


async def add_to_cart(
    listing_id: str,
    quantity: int = 1,
    variant_id: str | None = None,
    check_in: str | None = None,
    check_out: str | None = None,
    guests: int | None = None,
    user_token: str = "",
    session_id: str = "",
    **kwargs,
) -> dict[str, Any]:
    """Add an item to the user's cart."""
    client = await _get_client()
    body = {"listing_id": listing_id, "quantity": quantity}
    if variant_id:
        body["variant_id"] = variant_id
    if check_in:
        body["check_in"] = check_in
    if check_out:
        body["check_out"] = check_out
    if guests:
        body["guests"] = guests

    headers = {}
    if user_token:
        headers["Authorization"] = f"Bearer {user_token}"
    sid = session_id or kwargs.get("session_id")
    if sid:
        headers["X-Session-ID"] = str(sid)

    @merchant_breaker.protect
    async def _call():
        resp = await client.post(
            f"{settings.merchant_server_url}/api/v1/cart/items",
            json=body,
            headers=headers if headers else None,
        )
        resp.raise_for_status()
        return resp.json()


    return await _call()


async def remove_from_cart(item_id: str, user_token: str = "", session_id: str = "", **kwargs) -> dict[str, Any]:
    """Remove an item from the cart."""
    client = await _get_client()
    headers = {}
    if user_token:
        headers["Authorization"] = f"Bearer {user_token}"
    sid = session_id or kwargs.get("session_id")
    if sid:
        headers["X-Session-ID"] = str(sid)

    @merchant_breaker.protect
    async def _call():
        resp = await client.delete(
            f"{settings.merchant_server_url}/api/v1/cart/items/{item_id}",
            headers=headers if headers else None,
        )
        resp.raise_for_status()
        return resp.json()

    return await _call()


# ────────────────────────────────────────────────────────────────
#  ORDER TOOLS
# ────────────────────────────────────────────────────────────────

async def checkout(
    payment_gateway: str = "razorpay",
    user_token: str = "",
    **kwargs,
) -> dict[str, Any]:
    """Proceed to checkout — creates order and payment intent."""
    import hashlib

    # Build deterministic idempotency key based on cart contents
    cart_res = await view_cart(user_token=user_token, **kwargs)
    cart_id = cart_res.get("id") or cart_res.get("cart_id") or "cart"
    items = cart_res.get("items", [])

    item_strings = []
    for item in items:
        item_id = item.get("listing_id") or item.get("id") or ""
        qty = item.get("quantity") or item.get("qty") or 1
        item_strings.append(f"{item_id}:{qty}")

    cart_signature = hashlib.sha256(
        "|".join(sorted(item_strings)).encode()
    ).hexdigest()
    idempotency_key = f"checkout-{cart_id}-{cart_signature}"

    client = await _get_client()
    if not user_token:
        import uuid
        from shared.auth.jwt_handler import JWTHandler
        jwt_h = JWTHandler(secret_key=settings.jwt_secret_key)
        user_token = jwt_h.create_access_token(
            user_id=str(uuid.uuid4()),
            role="customer",
        )
    headers = {"Authorization": f"Bearer {user_token}"}

    @merchant_breaker.protect
    async def _call():
        resp = await client.post(
            f"{settings.merchant_server_url}/api/v1/cart/checkout",
            json={
                "idempotency_key": idempotency_key,
                "payment_gateway": payment_gateway,
            },
            headers=headers if headers else None,
        )
        resp.raise_for_status()
        return resp.json()

    return await _call()


async def get_order_status(order_id: str, user_token: str = "", **kwargs) -> dict[str, Any]:
    """Get the status of an order."""
    client = await _get_client()

    @merchant_breaker.protect
    async def _call():
        resp = await client.get(
            f"{settings.merchant_server_url}/api/v1/orders/{order_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp.raise_for_status()
        return resp.json()

    return await _call()


async def list_orders(user_token: str = "", **kwargs) -> dict[str, Any]:
    """List all orders for the current user."""
    client = await _get_client()

    @merchant_breaker.protect
    async def _call():
        resp = await client.get(
            f"{settings.merchant_server_url}/api/v1/orders",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp.raise_for_status()
        return resp.json()

    return await _call()


async def cancel_order(order_id: str, user_token: str = "", **kwargs) -> dict[str, Any]:
    """Cancel an order."""
    client = await _get_client()

    @merchant_breaker.protect
    async def _call():
        resp = await client.post(
            f"{settings.merchant_server_url}/api/v1/orders/{order_id}/cancel",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp.raise_for_status()
        return resp.json()

    return await _call()


# ────────────────────────────────────────────────────────────────
#  BOOKING TOOLS
# ────────────────────────────────────────────────────────────────

async def list_bookings(user_token: str = "", **kwargs) -> dict[str, Any]:
    """List all bookings for the current user."""
    client = await _get_client()

    @merchant_breaker.protect
    async def _call():
        resp = await client.get(
            f"{settings.merchant_server_url}/api/v1/bookings",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp.raise_for_status()
        return resp.json()

    return await _call()


async def cancel_booking(booking_id: str, user_token: str = "", **kwargs) -> dict[str, Any]:
    """Cancel a booking."""
    client = await _get_client()

    @merchant_breaker.protect
    async def _call():
        resp = await client.post(
            f"{settings.merchant_server_url}/api/v1/bookings/{booking_id}/cancel",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp.raise_for_status()
        return resp.json()

    return await _call()


async def get_merchant_info(
    merchant_id: str | None = None,
    active_merchant_id: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Get merchant profile & settings (business hours, policies, contact info)."""
    client = await _get_client()
    target_id = merchant_id or active_merchant_id or kwargs.get("active_merchant_id")
    if not target_id:
        return {"error": "No merchant_id provided"}

    @merchant_breaker.protect
    async def _call():
        resp = await client.get(
            f"{settings.merchant_server_url}/api/v1/merchants/public/{target_id}"
        )
        resp.raise_for_status()
        return resp.json()

    try:
        return await _call()
    except Exception as e:
        logger.warning("get_merchant_info_failed", error=str(e), merchant_id=target_id)
        return {"error": str(e)}


# ────────────────────────────────────────────────────────────────
#  REGISTER ALL TOOLS
# ────────────────────────────────────────────────────────────────

def register_all_tools() -> None:
    """Register all commerce tools with the global registry."""

    tool_registry.register(ToolDefinition(
        name="search_listings",
        description=(
            "DISCOVERY ONLY: Use this to find and browse listings when the user wants to explore, find, or purchase something new. "
            "Trigger phrases: 'I want to buy', 'show me', 'find me', 'do you have', 'looking for', 'search for'. "
            "NEVER use this for review/opinion/feedback queries (e.g. 'what do users say?', 'is it good?', 'reviews'). "
            "NEVER pass the user's raw conversational sentence as query — extract only the core product keyword (e.g. 'laptop', 'macbook', 'headphones')."
        ),
        category=ToolCategory.SEARCH,
        parameters=[
            ToolParameter(name="query", type="string", description="Core product/category keyword ONLY (e.g. 'laptop', 'macbook pro', 'running shoes'). Never a full sentence."),
            ToolParameter(name="type", type="string", description="Filter by type: product, hotel, rental, service, real_estate, electronics", required=False,
                          enum=["product", "hotel", "rental", "service", "real_estate", "electronics"]),
            ToolParameter(name="min_price", type="number", description="Minimum price filter", required=False),
            ToolParameter(name="max_price", type="number", description="Maximum price filter", required=False),
            ToolParameter(name="tags", type="string", description="Comma-separated tags to filter by", required=False),
            ToolParameter(name="limit", type="integer", description="Max results to return (default 10)", required=False),
        ],
        handler=search_listings,
    ))

    tool_registry.register(ToolDefinition(
        name="get_listing_details",
        description="Fetch comprehensive factual data for a specific listing. Use this to answer questions about technical specs, amenities, weight, dimensions, or merchant data. This is the primary tool for factual grounding.",
        category=ToolCategory.SEARCH,
        parameters=[
            ToolParameter(name="listing_id", type="string", description="The listing UUID"),
        ],
        handler=get_listing_details,
    ))

    tool_registry.register(ToolDefinition(
        name="get_listing_reviews",
        description=(
            "REVIEWS & OPINIONS ONLY: Retrieve real user reviews, ratings, and qualitative feedback for a specific listing. "
            "Trigger phrases: 'what do users say', 'what do people think', 'reviews', 'is it good', 'opinions', 'feedback', 'worth buying', 'how is the quality'. "
            "If you do not yet have the listing_id, first call search_listings to find the product, then immediately call this tool with the returned ID — do NOT show the search results to the user, it is an internal lookup step."
        ),
        category=ToolCategory.SEARCH,
        parameters=[
            ToolParameter(name="listing_id", type="string", description="The listing UUID"),
            ToolParameter(name="page", type="integer", description="Page number for pagination", required=False),
        ],
        handler=get_listing_reviews,
    ))

    tool_registry.register(ToolDefinition(
        name="check_availability",
        description="Check if a hotel, rental, or service is available for specific dates. Map phrases like 'is it free?', 'can I stay on X date?', or 'show availability' to this tool.",
        category=ToolCategory.SEARCH,
        parameters=[
            ToolParameter(name="listing_id", type="string", description="The listing UUID"),
            ToolParameter(name="check_in", type="string", description="Check-in date (YYYY-MM-DD)", required=False),
            ToolParameter(name="check_out", type="string", description="Check-out date (YYYY-MM-DD)", required=False),
        ],
        handler=check_availability,
    ))

    tool_registry.register(ToolDefinition(
        name="view_cart",
        description="View the current cart. Map phrases like 'what's in my bag?', 'show my cart', or 'how much is the total?' to this tool.",
        category=ToolCategory.CART,
        parameters=[],
        handler=view_cart,
    ))

    tool_registry.register(ToolDefinition(
        name="add_to_cart",
        description="Use this when the user expresses a desire to buy, save, grab, or reserve a listing. Map phrases like 'I want this', 'I'll take it', 'Put it in my bag', or 'Reserve this for me' to this tool.",
        category=ToolCategory.CART,
        parameters=[
            ToolParameter(name="listing_id", type="string", description="The listing UUID to add"),
            ToolParameter(name="quantity", type="integer", description="Quantity (default 1)", required=False),
            ToolParameter(name="variant_id", type="string", description="Specific variant UUID", required=False),
            ToolParameter(name="check_in", type="string", description="Check-in date for bookings (YYYY-MM-DD)", required=False),
            ToolParameter(name="check_out", type="string", description="Check-out date for bookings (YYYY-MM-DD)", required=False),
            ToolParameter(name="guests", type="integer", description="Number of guests", required=False),
        ],
        handler=add_to_cart,
        requires_confirmation=True,
    ))

    tool_registry.register(ToolDefinition(
        name="remove_from_cart",
        description="Remove a specific item from the cart.",
        category=ToolCategory.CART,
        parameters=[
            ToolParameter(name="item_id", type="string", description="Cart item UUID to remove"),
        ],
        handler=remove_from_cart,
    ))

    tool_registry.register(ToolDefinition(
        name="checkout",
        description="Proceed to payment and final order placement. Use this when the user is 'ready', 'done shopping', wants to 'pay', or 'finish the order'.",
        category=ToolCategory.ORDER,
        parameters=[
            ToolParameter(name="payment_gateway", type="string", description="Payment method: razorpay or stripe (default razorpay)", required=False, enum=["razorpay", "stripe"]),
        ],
        handler=checkout,
        requires_confirmation=True,
    ))

    tool_registry.register(ToolDefinition(
        name="get_order_status",
        description="Check the status of a specific order.",
        category=ToolCategory.ORDER,
        parameters=[
            ToolParameter(name="order_id", type="string", description="Order UUID"),
        ],
        handler=get_order_status,
    ))

    tool_registry.register(ToolDefinition(
        name="list_orders",
        description="List previous orders. Map phrases like 'where is my stuff?', 'show my history', or 'previous orders' to this tool.",
        category=ToolCategory.ORDER,
        parameters=[],
        handler=list_orders,
    ))

    tool_registry.register(ToolDefinition(
        name="cancel_order",
        description="Cancel a pending order.",
        category=ToolCategory.ORDER,
        parameters=[
            ToolParameter(name="order_id", type="string", description="Order UUID to cancel"),
        ],
        handler=cancel_order,
        requires_confirmation=True,
    ))

    tool_registry.register(ToolDefinition(
        name="list_bookings",
        description="List all bookings (hotel, rental, service) for the current user.",
        category=ToolCategory.BOOKING,
        parameters=[],
        handler=list_bookings,
    ))

    tool_registry.register(ToolDefinition(
        name="cancel_booking",
        description="Cancel a booking.",
        category=ToolCategory.BOOKING,
        parameters=[
            ToolParameter(name="booking_id", type="string", description="Booking UUID to cancel"),
        ],
        handler=cancel_booking,
        requires_confirmation=True,
    ))

    tool_registry.register(ToolDefinition(
        name="get_merchant_info",
        description="Get merchant information including business hours, policies, contact info, and location.",
        category=ToolCategory.SEARCH,
        parameters=[
            ToolParameter(name="merchant_id", type="string", description="Merchant UUID", required=False),
        ],
        handler=get_merchant_info,
    ))

    tool_registry.register(ToolDefinition(
        name="compare_listings",
        description="Compare specs, prices, and ratings of multiple listings by their IDs.",
        category=ToolCategory.SEARCH,
        parameters=[
            ToolParameter(name="listing_ids", type="array", description="List of listing UUIDs to compare", required=True),
        ],
        handler=compare_listings,
    ))

    tool_registry.register(ToolDefinition(
        name="compare_products",
        description="Compare specs, prices, and ratings of multiple listings by their IDs.",
        category=ToolCategory.SEARCH,
        parameters=[
            ToolParameter(name="listing_ids", type="array", description="List of listing UUIDs to compare", required=True),
        ],
        handler=compare_listings,
    ))

    # Long-Term Episodic Memory Tool
    async def remember_user_preference(preference_text: str, user_id: str = "", **kwargs) -> dict[str, Any]:
        """Save a user fact, context, or preference to long-term episodic memory."""
        if not user_id:
            return {"status": "error", "message": "User not authenticated, cannot save preference"}
            
        from agent_server.core.chroma_search import ChromaSearch
        search = ChromaSearch()
        await search.save_user_memory(user_id, preference_text)
        return {"status": "success", "message": f"Successfully remembered: '{preference_text}'"}

    async def web_search_product(query: str, **kwargs) -> dict[str, Any]:
        """Search the web for external product reviews, benchmark comparisons, or information when not found in local store."""
        import httpx
        try:
            url = "https://html.duckduckgo.com/html/"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
                res = await client.post(url, data={"q": query}, headers=headers)
                if res.status_code == 200:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(res.text, "html.parser")
                    results = [a.get_text(strip=True) for a in soup.find_all("a", class_="result__snippet")[:3] if a.get_text(strip=True)]
                    if results:
                        return {"status": "success", "query": query, "snippets": results}
        except Exception as e:
            logger.warning("web_search_failed", error=str(e))
        return {
            "status": "fallback",
            "query": query,
            "message": f"Use LLM internal parametric knowledge to answer user question about '{query}'."
        }

    tool_registry.register(ToolDefinition(
        name="web_search_product",
        description="Search the live web for external product reviews, specs, comparisons, or info when an item is not in the store database or the user asks for external web reviews.",
        category=ToolCategory.SEARCH,
        parameters=[
            ToolParameter(name="query", type="string", description="The search query for external product reviews or specs"),
        ],
        handler=web_search_product,
    ))

    logger.info("all_tools_registered", count=len(tool_registry.list_tools()))
