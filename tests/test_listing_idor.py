"""
Test suite for Listing IDOR protection (test_listing_idor.py).
"""

import pytest
import uuid


@pytest.mark.asyncio
async def test_listing_idor_patch_delete(merchant_client, merchant_setup):
    """Merchant B cannot update or delete Merchant A's listing (403/404)."""
    listing_a_id = str(merchant_setup["listing_a"].id)
    headers_b = {"Authorization": f"Bearer {merchant_setup['token_b']}"}

    # Merchant B tries to update Merchant A's listing
    patch_res = await merchant_client.patch(
        f"/api/v1/listings/{listing_a_id}",
        json={"title": "Hacked Title by Merchant B"},
        headers=headers_b,
    )
    assert patch_res.status_code in (403, 404), f"Expected 403/404, got {patch_res.status_code}"

    # Merchant B tries to delete Merchant A's listing
    delete_res = await merchant_client.delete(
        f"/api/v1/listings/{listing_a_id}",
        headers=headers_b,
    )
    assert delete_res.status_code in (403, 404), f"Expected 403/404, got {delete_res.status_code}"


@pytest.mark.asyncio
async def test_merchant_owner_can_update_own_listing(merchant_client, merchant_setup):
    """Merchant A can update their own listing and changes persist."""
    listing_a_id = str(merchant_setup["listing_a"].id)
    headers_a = {"Authorization": f"Bearer {merchant_setup['token_a']}"}

    new_title = f"Updated Title {uuid.uuid4().hex[:4]}"
    patch_res = await merchant_client.patch(
        f"/api/v1/listings/{listing_a_id}",
        json={"title": new_title},
        headers=headers_a,
    )
    assert patch_res.status_code == 200, f"Expected 200, got {patch_res.status_code}"
    assert patch_res.json()["title"] == new_title

    # Confirm read-back
    get_res = await merchant_client.get(f"/api/v1/listings/{listing_a_id}")
    assert get_res.json()["title"] == new_title
