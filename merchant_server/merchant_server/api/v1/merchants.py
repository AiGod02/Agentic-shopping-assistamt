"""
Merchants API — onboarding, authentication, and profile management.

Security: All merchant-specific endpoints enforce tenant isolation by extracting
merchant_id from the JWT token. A merchant can NEVER access another merchant's data.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from passlib.hash import bcrypt
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from merchant_server.domain.models.merchant import Merchant
from merchant_server.domain.models.user import User
from merchant_server.domain.repositories.merchant_repo import MerchantRepository
from shared.auth.jwt_handler import JWTHandler, TokenPair
from shared.auth.rbac import Role, get_current_user, require_role
from shared.db.session import get_db
from shared.schemas.base import BaseSchema

router = APIRouter()


# ── Request/Response Schemas ──────────────────────────────────────

class MerchantRegisterRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8)
    full_name: str
    phone: str | None = None
    business_name: str
    business_type: str  # retail | hospitality | rental | service
    tax_id: str | None = None


class MerchantResponse(BaseSchema):
    id: str
    user_id: str
    business_name: str
    business_type: str
    verification_status: str
    is_active: bool
    tax_id: str | None = None
    commission_rate: float | None = None
    payout_account: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)


class MerchantProfileUpdate(BaseModel):
    business_name: str | None = None
    business_type: str | None = None
    tax_id: str | None = None
    payout_account: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LoginResponse(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    merchant_id: str | None
    role: str
    business_name: str | None = None


# ── Helper ────────────────────────────────────────────────────────

def _get_jwt_handler() -> JWTHandler:
    """Create a JWTHandler from settings."""
    from merchant_server.config import settings
    return JWTHandler(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.jwt_access_token_expire_minutes,
        refresh_token_expire_days=settings.jwt_refresh_token_expire_days,
    )


def _merchant_to_response(merchant: Merchant) -> MerchantResponse:
    return MerchantResponse(
        id=str(merchant.id),
        user_id=str(merchant.user_id),
        business_name=merchant.business_name,
        business_type=merchant.business_type,
        verification_status=merchant.verification_status,
        is_active=merchant.is_active,
        tax_id=merchant.tax_id,
        commission_rate=float(merchant.commission_rate) if merchant.commission_rate else None,
        payout_account=merchant.payout_account or {},
        settings=merchant.settings or {},
    )


def _enforce_merchant_ownership(user_token, merchant_id: uuid.UUID) -> None:
    """Raise 403 if the requesting user is not the owner (unless admin)."""
    if user_token.role == Role.ADMIN.value:
        return  # Admins can access any merchant
    if not user_token.merchant_id or str(merchant_id) != user_token.merchant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this merchant's data",
        )


# ── Public Endpoints (no auth required) ──────────────────────────

@router.post("/register", response_model=dict, status_code=status.HTTP_201_CREATED)
async def register_merchant(body: MerchantRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new merchant with user account."""
    from sqlalchemy import select

    # Check existing user
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    # Create user
    user = User(
        email=body.email,
        password_hash=bcrypt.hash(body.password),
        full_name=body.full_name,
        phone=body.phone,
        role="merchant",
    )
    db.add(user)
    await db.flush()

    # Create merchant
    merchant = Merchant(
        user_id=user.id,
        business_name=body.business_name,
        business_type=body.business_type,
        tax_id=body.tax_id,
    )
    db.add(merchant)
    await db.flush()
    await db.refresh(merchant)

    return {
        "user_id": str(user.id),
        "merchant_id": str(merchant.id),
        "status": "pending_verification",
    }


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate merchant and return JWT tokens."""
    from sqlalchemy import select

    stmt = select(User).where(User.email == body.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not bcrypt.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Get merchant ID
    repo = MerchantRepository(db)
    merchant = await repo.get_by_user_id(user.id)
    merchant_id = str(merchant.id) if merchant else None

    jwt_handler = _get_jwt_handler()
    token_pair = jwt_handler.create_token_pair(
        user_id=str(user.id),
        role=user.role,
        merchant_id=merchant_id,
    )

    return LoginResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        user_id=str(user.id),
        merchant_id=merchant_id,
        role=user.role,
        business_name=merchant.business_name if merchant else None,
    )


@router.post("/refresh", response_model=dict)
async def refresh_token(body: RefreshRequest):
    """Exchange a valid refresh token for a new access token."""
    jwt_handler = _get_jwt_handler()
    try:
        payload = await jwt_handler.verify_token(body.refresh_token)
        if payload.token_type != "refresh":
            raise HTTPException(status_code=400, detail="Invalid token type — expected refresh token")

        new_access = jwt_handler.create_access_token(
            user_id=payload.sub,
            role=payload.role,
            merchant_id=payload.merchant_id,
        )
        return {
            "access_token": new_access,
            "token_type": "bearer",
            "expires_in": jwt_handler.access_token_expire_minutes * 60,
        }
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")


@router.post("/guest-token", response_model=dict)
async def create_guest_token():
    """Issue a cryptographically signed guest JWT for anonymous shopping."""
    jwt_handler = _get_jwt_handler()
    guest_uuid = str(uuid.uuid4())
    access_token = jwt_handler.create_access_token(
        user_id=guest_uuid,
        role="customer",
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": guest_uuid,
        "role": "customer",
        "is_guest": True,
        "expires_in": jwt_handler.access_token_expire_minutes * 60,
    }



@router.get("/public/{merchant_id}", response_model=MerchantResponse)
async def get_merchant_public(merchant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Public endpoint to fetch basic merchant profile and settings (hours, policies, contact)."""
    print(f"DEBUG: get_merchant_public called with {merchant_id}")
    repo = MerchantRepository(db)
    merchant = await repo.get_by_id(merchant_id)
    print(f"DEBUG: merchant found = {merchant}")
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return _merchant_to_response(merchant)


# ── Protected Endpoints (auth required) ──────────────────────────

@router.post(
    "/logout",
    dependencies=[Depends(require_role(Role.MERCHANT, Role.ADMIN))],
)
async def logout(request: Request):
    """Logout — blacklist the current access token."""
    user = request.state.user
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    jwt_handler = _get_jwt_handler()
    await jwt_handler.blacklist_token(user)
    return {"status": "logged_out"}


@router.get(
    "/me",
    response_model=MerchantResponse,
    dependencies=[Depends(require_role(Role.MERCHANT))],
)
async def get_current_merchant(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current authenticated merchant's profile.

    merchant_id is extracted from the JWT — no URL parameter needed.
    This is the secure way to fetch merchant data.
    """
    if not user.merchant_id:
        raise HTTPException(status_code=404, detail="No merchant profile associated with this account")

    repo = MerchantRepository(db)
    merchant = await repo.get_by_id(uuid.UUID(user.merchant_id))
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")

    return _merchant_to_response(merchant)


@router.put(
    "/me",
    response_model=MerchantResponse,
    dependencies=[Depends(require_role(Role.MERCHANT))],
)
async def update_current_merchant(
    body: MerchantProfileUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current merchant's profile. Only own profile can be updated."""
    if not user.merchant_id:
        raise HTTPException(status_code=404, detail="No merchant profile associated with this account")

    repo = MerchantRepository(db)
    merchant = await repo.get_by_id(uuid.UUID(user.merchant_id))
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(merchant, key):
            setattr(merchant, key, value)
    await db.flush()
    await db.refresh(merchant)

    return _merchant_to_response(merchant)


@router.get(
    "/{merchant_id}",
    response_model=MerchantResponse,
    dependencies=[Depends(require_role(Role.ADMIN, Role.MERCHANT))],
)
async def get_merchant(
    merchant_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a merchant by ID. Enforces ownership — merchants can only view their own profile."""
    _enforce_merchant_ownership(user, merchant_id)

    repo = MerchantRepository(db)
    merchant = await repo.get_by_id(merchant_id)
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return _merchant_to_response(merchant)


@router.post(
    "/{merchant_id}/verify",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def verify_merchant(merchant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Admin-only: verify a merchant."""
    repo = MerchantRepository(db)
    updated = await repo.update_verification(merchant_id, "verified")
    if not updated:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return {"status": "verified", "merchant_id": str(merchant_id)}
