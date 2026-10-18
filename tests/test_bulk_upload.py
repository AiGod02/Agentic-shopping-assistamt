"""
Test suite for catalog bulk upload (test_bulk_upload.py).
"""

import pytest
import io


@pytest.mark.asyncio
async def test_bulk_upload_valid_and_malformed_csv(merchant_client, merchant_setup):
    """Test CSV bulk upload with valid rows, currency symbols, N/A prices, and missing titles."""
    headers = {"Authorization": f"Bearer {merchant_setup['token_a']}"}

    csv_content = (
        "title,base_price,type,tags\n"
        "Valid Laptop,$19.99,product,laptop\n"
        "N/A Item,N/A,product,test\n"
        ",29.99,product,missing_title\n"
        "Valid Smartphone,299.99,electronics,phone\n"
    )

    files = {"file": ("catalog.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}

    res = await merchant_client.post("/api/v1/listings/bulk", headers=headers, files=files)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"

    data = res.json()
    assert "imported_count" in data
    assert "failed_count" in data
    assert "errors" in data
    assert "search_indexing_triggered" in data

    assert data["imported_count"] == 2, f"Expected 2 imported rows, got {data['imported_count']}"
    assert data["failed_count"] == 2, f"Expected 2 failed rows, got {data['failed_count']}"
    assert len(data["errors"]) == 2


@pytest.mark.asyncio
async def test_bulk_upload_file_too_large(merchant_client, merchant_setup):
    """File size exceeding 10MB limit returns 413 Request Entity Too Large."""
    headers = {"Authorization": f"Bearer {merchant_setup['token_a']}"}

    large_content = b"a" * (10 * 1024 * 1024 + 1024)
    files = {"file": ("large_catalog.csv", io.BytesIO(large_content), "text/csv")}

    res = await merchant_client.post("/api/v1/listings/bulk", headers=headers, files=files)
    assert res.status_code == 413, f"Expected 413, got {res.status_code}"
