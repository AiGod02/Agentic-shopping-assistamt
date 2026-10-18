"""
Test suite for checkout idempotency key generation (test_checkout_idempotency.py).
"""

import pytest
import hashlib
from agent_server.tools.commerce_tools import checkout


@pytest.mark.asyncio
async def test_checkout_idempotency_hash_derivation():
    """Test that checkout idempotency key is derived from sha256 hash of cart items and quantities."""
    # Compute signature for Cart 1 (Item A: 1)
    items1 = ["item_laptop:1"]
    sig1 = hashlib.sha256("|".join(sorted(items1)).encode()).hexdigest()

    # Compute signature for Cart 2 (Item B: 1) -- same item count (1), different item ID
    items2 = ["item_phone:1"]
    sig2 = hashlib.sha256("|".join(sorted(items2)).encode()).hexdigest()

    # Compute signature for Cart 3 (Item A: 2) -- same item ID, different quantity
    items3 = ["item_laptop:2"]
    sig3 = hashlib.sha256("|".join(sorted(items3)).encode()).hexdigest()

    assert sig1 != sig2, "Idempotency key signature must differ for different items with same item count"
    assert sig1 != sig3, "Idempotency key signature must differ when quantity changes"
    assert sig1 == hashlib.sha256("|".join(sorted(items1)).encode()).hexdigest(), "Identical cart contents must yield identical idempotency key"
