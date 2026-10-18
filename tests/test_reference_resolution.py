"""
Test suite for Reference Resolution Layer (test_reference_resolution.py).
"""

import pytest
from agent_server.core.reference_resolver import ReferenceResolver
from agent_server.core.dialogue_state import DialogueState


@pytest.mark.asyncio
async def test_bare_followup_without_context_defers_to_llm():
    """Fresh session with 'tell me about reviews' — resolver defers to LLM, no hard halt."""
    resolver = ReferenceResolver()
    empty_state = DialogueState(session_id="empty-session")

    # 1. Bare followup without context — resolver no longer halts; LLM handles clarification
    res1 = resolver.resolve("tell me about reviews", empty_state)
    assert res1.requires_clarification is False
    assert res1.target_listing_id is None
    assert "No explicit reference" in res1.reason

    # 2. Ordinal reference without prior search
    res2 = resolver.resolve("the second one", empty_state)
    assert res2.target_listing_id is None


@pytest.mark.asyncio
async def test_ordinal_reference_resolution_after_search():
    """After a search, 'the second one' resolves to the 2nd item in last_shown_listings."""
    resolver = ReferenceResolver()
    state = DialogueState(
        session_id="search-session",
        last_shown_listings=[
            {"id": "item-1", "title": "First Item", "base_price": 100},
            {"id": "item-2", "title": "Second Item", "base_price": 200},
            {"id": "item-3", "title": "Third Item", "base_price": 300},
        ],
    )

    res = resolver.resolve("show me the second one", state)
    assert res.target_listing_id == "item-2"


@pytest.mark.asyncio
async def test_pronoun_reference_resolution_focused_item():
    """After viewing a product, 'it' or 'that one' resolves to the focused item."""
    resolver = ReferenceResolver()
    state = DialogueState(
        session_id="focused-session",
        focused_listing_id="item-focused-123",
    )

    res1 = resolver.resolve("what is the price of that one?", state)
    assert res1.target_listing_id == "item-focused-123"

    res2 = resolver.resolve("add it to cart", state)
    assert res2.target_listing_id == "item-focused-123"
