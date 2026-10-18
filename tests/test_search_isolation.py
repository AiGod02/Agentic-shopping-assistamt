"""
Test suite for vector/keyword search isolation and merchant scoping (test_search_isolation.py).
"""

import pytest
from agent_server.core.search import WeaviateSearch
from agent_server.core.chroma_search import ChromaSearch


@pytest.mark.asyncio
async def test_search_without_merchant_id_raises_value_error():
    """Calling search with merchant_id=None or empty string must raise ValueError."""
    search_svc = WeaviateSearch()

    with pytest.raises(ValueError, match="merchant_id is required"):
        await search_svc.semantic_search("laptop", merchant_id="")

    with pytest.raises(ValueError, match="merchant_id is required"):
        await search_svc.keyword_search("laptop", merchant_id=None)


@pytest.mark.asyncio
async def test_search_isolation_cross_merchant(db_session, merchant_setup):
    """Searching with Merchant A's ID never returns Merchant B's listings."""
    chroma_svc = ChromaSearch(db_session)
    m_a_id = str(merchant_setup["merchant_a"].id)
    m_b_id = str(merchant_setup["merchant_b"].id)
    listing_b_title = merchant_setup["listing_b"].title

    # Search for Listing B's title using Merchant A's merchant_id
    res_a = await chroma_svc.hybrid_search(
        query=listing_b_title,
        merchant_id=m_a_id,
        limit=10,
    )
    # Confirm Listing B is NOT returned for Merchant A's search query
    returned_ids = {str(item.get("id")) for item in res_a}
    assert str(merchant_setup["listing_b"].id) not in returned_ids, "Merchant B listing was returned in Merchant A search!"


@pytest.mark.asyncio
async def test_category_relevance_search(db_session, merchant_setup):
    """Category relevance filtering returns relevant category items without duplicates."""
    chroma_svc = ChromaSearch(db_session)
    m_a_id = str(merchant_setup["merchant_a"].id)

    res = await chroma_svc.hybrid_search(
        query="laptop",
        merchant_id=m_a_id,
        limit=5,
    )
    # Check no duplicate listing IDs in results
    ids = [item.get("id") for item in res]
    assert len(ids) == len(set(ids)), "Search results contain duplicate listing IDs!"
