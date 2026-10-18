"""
Listings API — CRUD endpoints for polymorphic listings.
"""

import datetime
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.models.listing import Listing
from merchant_server.domain.models.variant import Variant
from merchant_server.domain.repositories.listing_repo import ListingRepository
from shared.auth.rbac import Role, get_current_user, require_permission
from shared.db.session import get_db
from shared.observability.logging import get_logger
from shared.schemas.base import PaginatedResponse, BaseSchema

logger = get_logger(__name__)
router = APIRouter()


def _parse_price(val: Any) -> float:
    """Parse price string/number safely handling currency symbols, separators, and blanks."""
    if val is None:
        raise ValueError("Missing title or base_price")
    s = str(val).strip()
    if not s or s.upper() in ("N/A", "NULL", "NONE", ""):
        raise ValueError(f"Price is invalid or N/A: {val}")
    cleaned = re.sub(r"[^\d.-]", "", s.replace(",", ""))
    if not cleaned or cleaned in ("-", ".", "-."):
        raise ValueError(f"Invalid price format: {val}")
    try:
        price = float(cleaned)
        if price < 0:
            raise ValueError(f"Price cannot be negative: {val}")
        return price
    except Exception as e:
        raise ValueError(f"Invalid price format '{val}': {str(e)}")


# ── Request/Response Schemas ──────────────────────────────────────

class VariantCreate(BaseModel):
    name: str
    sku: str | None = None
    price_override: float | None = None
    inventory_count: int = 0
    attributes: dict[str, Any] = Field(default_factory=dict)


class ListingCreate(BaseModel):
    type: str = Field(..., description="product | hotel | rental | service | real_estate | electronics")
    title: str = Field(..., max_length=500)
    description: str | None = None
    base_price: float = Field(..., gt=0)
    currency: str = "USD"
    location: dict[str, Any] | None = None
    media: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    variants: list[VariantCreate] = Field(default_factory=list)


class ListingUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    base_price: float | None = None
    status: str | None = None
    location: dict[str, Any] | None = None
    media: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = None


class VariantResponse(BaseSchema):
    id: str
    name: str
    sku: str | None
    price_override: float | None
    inventory_count: int
    attributes: dict[str, Any]
    is_active: bool


class ListingResponse(BaseSchema):
    id: str
    merchant_id: str
    type: str
    title: str
    description: str | None
    base_price: float
    currency: str
    status: str
    location: dict[str, Any] | None
    media: list[dict[str, Any]]
    metadata: dict[str, Any]
    tags: list[str]
    rating_avg: float
    rating_count: int
    variants: list[VariantResponse] = Field(default_factory=list)


class ReviewResponse(BaseSchema):
    id: str
    user_id: str
    rating: int
    title: str | None
    body: str | None
    is_verified: bool
    created_at: datetime.datetime


ReviewResponse.model_rebuild()


def _review_to_response(review: Any) -> ReviewResponse:
    return ReviewResponse(
        id=str(review.id),
        user_id=str(review.user_id),
        rating=review.rating,
        title=review.title,
        body=review.body,
        is_verified=review.is_verified,
        created_at=review.created_at,
    )


def _listing_to_response(listing: Listing) -> ListingResponse:
    return ListingResponse(
        id=str(listing.id),
        merchant_id=str(listing.merchant_id),
        type=listing.type,
        title=listing.title,
        description=listing.description,
        base_price=float(listing.base_price),
        currency=listing.currency,
        status=listing.status,
        location=listing.location,
        media=listing.media,
        metadata=listing.metadata_,
        tags=listing.tags or [],
        rating_avg=float(listing.rating_avg),
        rating_count=listing.rating_count,
        variants=[
            VariantResponse(
                id=str(v.id), name=v.name, sku=v.sku,
                price_override=float(v.price_override) if v.price_override else None,
                inventory_count=v.inventory_count, attributes=v.attributes, is_active=v.is_active,
            )
            for v in (listing.variants or [])
        ],
    )


# ── Endpoints ─────────────────────────────────────────────────────

@router.get("", response_model=PaginatedResponse[ListingResponse])
async def list_listings(
    type: str | None = None,
    status: str | None = Query(None),
    min_price: float | None = None,
    max_price: float | None = None,
    q: str | None = None,
    tags: str | None = None,
    merchant_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List listings with optional filters, search, and pagination."""
    repo = ListingRepository(db)
    parsed_tags = tags.split(",") if tags else None
    items, total = await repo.list_listings(
        merchant_id=uuid.UUID(merchant_id) if merchant_id else None,
        listing_type=type,
        status=status,
        min_price=min_price,
        max_price=max_price,
        search_query=q,
        tags=parsed_tags,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return PaginatedResponse.create(
        items=[_listing_to_response(i) for i in items],
        total=total, page=page, page_size=page_size,
    )


@router.get("/{listing_id}", response_model=ListingResponse)
async def get_listing(listing_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get a single listing by ID (cached with jitter to prevent stampedes)."""
    import json
    import random
    from shared.db.redis_client import RedisCache

    cache = RedisCache(prefix="listing:detail", ttl=300)
    
    try:
        cached = await cache.get(str(listing_id))
        if cached:
            return ListingResponse.model_validate_json(cached)
    except Exception:
        pass  # Fall back to DB if Redis is unreachable

    repo = ListingRepository(db)
    listing = await repo.get_by_id(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
        
    response_data = _listing_to_response(listing)
    
    try:
        jitter = random.randint(-30, 30)
        await cache.set(str(listing_id), response_data.model_dump_json(), ttl=300 + jitter)
    except Exception:
        pass

    return response_data


@router.post(
    "",
    response_model=ListingResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("listings:write"))],
)
async def create_listing(
    body: ListingCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new listing (merchant only)."""
    listing = Listing(
        merchant_id=user.merchant_id,
        type=body.type,
        title=body.title,
        description=body.description,
        base_price=body.base_price,
        currency=body.currency,
        status="draft",
        location=body.location,
        media=body.media,
        metadata_=body.metadata,
        tags=body.tags,
    )
    for v in body.variants:
        listing.variants.append(
            Variant(
                name=v.name, sku=v.sku, price_override=v.price_override,
                inventory_count=v.inventory_count, attributes=v.attributes,
            )
        )

    repo = ListingRepository(db)
    listing = await repo.create(listing)
    
    from merchant_server.tasks.celery_app import sync_search_index
    sync_search_index.apply_async(args=[str(listing.id)])
    
    return _listing_to_response(listing)


@router.post(
    "/bulk-upload",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("listings:write"))],
)
async def bulk_upload_catalog(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk upload catalog listings via JSON or CSV file."""
    import csv
    import io
    import json

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds 10MB limit",
        )

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds 10MB limit",
        )

    filename = file.filename.lower() if file.filename else ""
    repo = ListingRepository(db)
    created_count = 0
    failed_count = 0
    errors: list[dict[str, Any]] = []
    listings_to_sync = []

    if filename.endswith(".json"):
        try:
            data = json.loads(content.decode("utf-8"))
        except Exception as e:
            logger.error("bulk_upload_json_decode_failed", filename=file.filename, error=str(e))
            raise HTTPException(status_code=400, detail=f"Invalid JSON file format: {str(e)}")

        items = data if isinstance(data, list) else [data]
        for idx, item in enumerate(items, start=1):
            try:
                if not isinstance(item, dict):
                    raise ValueError("JSON item must be an object")
                title = item.get("title") or item.get("name")
                if not title:
                    raise ValueError("Missing title")
                price_raw = item.get("base_price") if "base_price" in item else item.get("price")
                base_price = _parse_price(price_raw)

                listing = Listing(
                    merchant_id=user.merchant_id,
                    type=item.get("type", "product"),
                    title=title,
                    description=item.get("description", ""),
                    base_price=base_price,
                    currency=item.get("currency", "USD"),
                    status="active",
                    media=item.get("media", []),
                    metadata_=item.get("metadata", {}),
                    tags=item.get("tags", []),
                )
                created = await repo.create(listing)
                listings_to_sync.append(str(created.id))
                created_count += 1
            except Exception as ex:
                logger.error("bulk_upload_json_row_error", row=idx, merchant_id=str(user.merchant_id), error=str(ex))
                errors.append({"row": idx, "error": str(ex)})
                failed_count += 1

    elif filename.endswith(".csv"):
        try:
            text_stream = io.StringIO(content.decode("utf-8-sig"))
            reader = csv.DictReader(text_stream)
        except Exception as e:
            logger.error("bulk_upload_csv_decode_failed", filename=file.filename, error=str(e))
            raise HTTPException(status_code=400, detail=f"Invalid CSV file format: {str(e)}")

        for idx, row in enumerate(reader, start=2):
            try:
                title = row.get("title") or row.get("name") or row.get("Title")
                if not title:
                    raise ValueError("Missing title")
                price_raw = row.get("base_price") or row.get("price") or row.get("Price")
                base_price = _parse_price(price_raw)

                tags_raw = row.get("tags") or row.get("Tags") or ""
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
                listing = Listing(
                    merchant_id=user.merchant_id,
                    type=row.get("type") or row.get("Type") or "product",
                    title=title,
                    description=row.get("description") or row.get("Description") or "",
                    base_price=base_price,
                    currency=row.get("currency") or "USD",
                    status="active",
                    tags=tags,
                )
                created = await repo.create(listing)
                listings_to_sync.append(str(created.id))
                created_count += 1
            except Exception as ex:
                logger.error("bulk_upload_csv_row_error", row=idx, merchant_id=str(user.merchant_id), error=str(ex))
                errors.append({"row": idx, "error": str(ex)})
                failed_count += 1
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format. Please upload a .json or .csv catalog file.")

    search_indexing_triggered = False
    if listings_to_sync:
        try:
            from merchant_server.tasks.celery_app import sync_search_index
            for lid in listings_to_sync:
                sync_search_index.apply_async(args=[lid])
            search_indexing_triggered = True
        except Exception as ex:
            logger.error("bulk_upload_celery_dispatch_failed", count=len(listings_to_sync), merchant_id=str(user.merchant_id), error=str(ex))
            search_indexing_triggered = False

    return {
        "status": "completed",
        "imported_count": created_count,
        "failed_count": failed_count,
        "errors": errors,
        "search_indexing_triggered": search_indexing_triggered,
    }


@router.patch(
    "/{listing_id}",
    response_model=ListingResponse,
    dependencies=[Depends(require_permission("listings:write"))],
)
async def update_listing(
    listing_id: uuid.UUID,
    body: ListingUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a listing."""
    repo = ListingRepository(db)
    existing = await repo.get_by_id(listing_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    if user.role not in (Role.ADMIN, "admin") and str(existing.merchant_id) != str(user.merchant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden: You do not own this listing")

    update_data = body.model_dump(exclude_unset=True)
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")
    listing = await repo.update(listing_id, **update_data)

    # Invalidate cache
    try:
        from shared.db.redis_client import RedisCache
        cache = RedisCache(prefix="listing:detail")
        await cache.delete(str(listing_id))
    except Exception:
        pass

    from merchant_server.tasks.celery_app import sync_search_index
    sync_search_index.apply_async(args=[str(listing.id)])

    return _listing_to_response(listing)


@router.get("/{listing_id}/reviews", response_model=PaginatedResponse[ReviewResponse])
async def list_reviews(
    listing_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    try:
        from merchant_server.domain.repositories.review_repo import ReviewRepository
        repo = ReviewRepository(db)
        items, total = await repo.list_listing_reviews(
            listing_id=listing_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return PaginatedResponse.create(
            items=[_review_to_response(i) for i in items],
            total=total, page=page, page_size=page_size,
        )
    except Exception as e:
        import traceback
        logger.error("list_reviews_error", error=str(e), tb=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"list_reviews_error: {str(e)}")


@router.delete(
    "/{listing_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("listings:delete"))],
)
async def delete_listing(
    listing_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a listing."""
    repo = ListingRepository(db)
    existing = await repo.get_by_id(listing_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    if user.role not in (Role.ADMIN, "admin") and str(existing.merchant_id) != str(user.merchant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden: You do not own this listing")

    deleted = await repo.soft_delete(listing_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Listing not found")

    # Invalidate cache
    try:
        from shared.db.redis_client import RedisCache
        cache = RedisCache(prefix="listing:detail")
        await cache.delete(str(listing_id))
    except Exception:
        pass

