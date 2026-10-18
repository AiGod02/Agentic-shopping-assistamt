"""
Test suite for intent handlers (test_intent_handlers.py).
"""

import pytest
from agent_server.core.intent_classifier import IntentClassifier, IntentResult


@pytest.mark.asyncio
async def test_compare_products_intent_handling(agent_client, merchant_setup):
    """Test COMPARE_PRODUCTS intent fires compare_products tool, not search_listings."""
    listing_a_id = str(merchant_setup["listing_a"].id)
    listing_b_id = str(merchant_setup["listing_b"].id)

    res = await agent_client.post(
        "/api/v1/agent/chat",
        json={"message": f"compare listing {listing_a_id} and {listing_b_id}"},
    )
    assert res.status_code == 200
    data = res.json()
    tools = [tc["tool"] for tc in data.get("tool_calls", [])]

    assert ("compare_products" in tools or "compare_listings" in tools), f"Expected 'compare_products' or 'compare_listings' in tool calls, got {tools}"
    assert "search_listings" not in tools, "COMPARE_PRODUCTS incorrectly fell back to search_listings!"


@pytest.mark.asyncio
async def test_checkout_intent_handling(agent_client):
    """Test CHECKOUT intent fires checkout/view_cart tool, not search_listings."""
    res = await agent_client.post(
        "/api/v1/agent/chat",
        json={"message": "proceed to checkout"},
    )
    assert res.status_code == 200
    data = res.json()
    tools = [tc["tool"] for tc in data.get("tool_calls", [])]

    assert ("checkout" in tools or "view_cart" in tools), f"Expected checkout/view_cart in tool calls, got {tools}"
    assert "search_listings" not in tools, "CHECKOUT intent incorrectly fell back to search_listings!"


@pytest.mark.parametrize(
    "phrase,expected_intent",
    [
        ("search for wireless headphones", "SEARCH_PRODUCTS"),
        ("show me details of this item", "GET_PRODUCT_DETAILS"),
        ("what do customer reviews say?", "GET_REVIEWS"),
        ("is this item available?", "CHECK_AVAILABILITY"),
        ("add this to my cart", "ADD_TO_CART"),
        ("show my shopping cart", "VIEW_CART"),
        ("where is my order status?", "TRACK_ORDER"),
        ("cancel my order", "CANCEL_ORDER"),
    ],
)

@pytest.mark.asyncio
async def test_intent_classifier_vocabulary(phrase, expected_intent):
    """Parametrized test for intent classifier mapping across vocabulary."""
    from agent_server.core.llm_router import LLMRouter
    classifier = IntentClassifier(LLMRouter())
    res = await classifier.classify(phrase)
    assert res.intent == expected_intent, f"Phrase '{phrase}' classified as '{res.intent}', expected '{expected_intent}'"
