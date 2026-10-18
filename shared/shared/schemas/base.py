"""
Base Schemas — shared Pydantic models used across all services.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class BaseSchema(BaseModel):
    """Base schema with common configuration."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
    )


class TimestampMixin(BaseModel):
    """Mixin for created_at / updated_at fields."""

    created_at: datetime
    updated_at: datetime


class PaginationParams(BaseModel):
    """Pagination request parameters."""

    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PaginatedResponse(BaseSchema, Generic[T]):
    """Paginated response wrapper."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def create(
        cls, items: list[T], total: int, page: int, page_size: int
    ) -> "PaginatedResponse[T]":
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size,
        )


class ErrorResponse(BaseSchema):
    """Standardized error response."""

    error: str
    detail: str | None = None
    code: str | None = None
    request_id: str | None = None


class HealthResponse(BaseSchema):
    """Health check response."""

    status: str = "healthy"
    service: str
    version: str = "0.1.0"
    checks: dict[str, str] = Field(default_factory=dict)


class LocationSchema(BaseSchema):
    """Location data."""

    lat: float | None = None
    lng: float | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    postal_code: str | None = None


class MoneySchema(BaseSchema):
    """Monetary value representation."""

    amount: float
    currency: str = "USD"


class MediaSchema(BaseSchema):
    """Media item (image, video, etc.)."""

    url: str
    type: str = "image"  # image | video | document
    alt: str | None = None
    size_bytes: int | None = None
