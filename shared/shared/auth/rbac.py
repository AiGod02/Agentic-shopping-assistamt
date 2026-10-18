"""
RBAC — Role-Based Access Control for FastAPI endpoints.

Provides a dependency injection system for permission checks.
"""

from enum import Enum
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from shared.auth.jwt_handler import JWTHandler, TokenPayload


class Role(str, Enum):
    """System roles."""

    ADMIN = "admin"
    MERCHANT = "merchant"
    CUSTOMER = "customer"
    AGENT = "agent"  # internal agent/service role


# Permission matrix: role -> set of allowed permissions
PERMISSIONS: dict[Role, set[str]] = {
    Role.ADMIN: {
        "users:read",
        "users:write",
        "users:delete",
        "merchants:read",
        "merchants:write",
        "merchants:verify",
        "listings:read",
        "listings:write",
        "listings:delete",
        "orders:read",
        "orders:write",
        "orders:cancel",
        "payments:read",
        "payments:refund",
        "bookings:read",
        "bookings:write",
        "bookings:cancel",
        "analytics:read",
        "audit:read",
        "webhooks:manage",
        "system:manage",
    },
    Role.MERCHANT: {
        "listings:read",
        "listings:write",
        "listings:delete",
        "orders:read",
        "orders:write",
        "bookings:read",
        "bookings:write",
        "analytics:read",
        "webhooks:manage",
        "merchants:read",
    },
    Role.CUSTOMER: {
        "listings:read",
        "cart:read",
        "cart:write",
        "orders:read",
        "orders:create",
        "orders:cancel",
        "bookings:read",
        "bookings:create",
        "bookings:cancel",
        "payments:create",
        "reviews:write",
        "users:read",
    },
    Role.AGENT: {
        "listings:read",
        "cart:read",
        "cart:write",
        "orders:read",
        "orders:create",
        "bookings:read",
        "bookings:create",
        "payments:create",
        "search:execute",
        "sessions:manage",
    },
}


def has_permission(role: Role, permission: str) -> bool:
    """Check if a role has a specific permission."""
    perms = PERMISSIONS.get(role, set())
    return permission in perms


class RBACDependency:
    """FastAPI dependency for role-based access control.

    Usage:
        @router.get("/admin/users", dependencies=[Depends(require_role(Role.ADMIN))])
        async def list_users(): ...

        @router.post("/cart", dependencies=[Depends(require_permission("cart:write"))])
        async def add_to_cart(): ...
    """

    def __init__(
        self,
        allowed_roles: list[Role] | None = None,
        required_permissions: list[str] | None = None,
    ) -> None:
        self.allowed_roles = allowed_roles
        self.required_permissions = required_permissions

    async def __call__(self, request: Request) -> TokenPayload:
        token_payload: TokenPayload | None = getattr(request.state, "user", None)
        if token_payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

        user_role = Role(token_payload.role)

        # Check role allowlist
        if self.allowed_roles and user_role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user_role.value}' is not authorized for this resource",
            )

        # Check granular permissions
        if self.required_permissions:
            for perm in self.required_permissions:
                if not has_permission(user_role, perm):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Missing permission: {perm}",
                    )

        return token_payload


def require_role(*roles: Role) -> RBACDependency:
    """Create a dependency that requires one of the specified roles."""
    return RBACDependency(allowed_roles=list(roles))


def require_permission(*permissions: str) -> RBACDependency:
    """Create a dependency that requires all specified permissions."""
    return RBACDependency(required_permissions=list(permissions))


def require_role_and_permission(
    roles: list[Role], permissions: list[str]
) -> RBACDependency:
    """Create a dependency requiring both role and permissions."""
    return RBACDependency(allowed_roles=roles, required_permissions=permissions)


async def get_current_user(request: Request) -> TokenPayload:
    """FastAPI dependency to extract the current authenticated user from request.state.

    NOTE: This is MERCHANT dashboard auth only. Do not apply to customer-facing/public endpoints —
    see the auth domain table in autfix.md for the correct pattern.
    """
    user: TokenPayload | None = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


async def get_optional_user(request: Request) -> TokenPayload | None:
    """FastAPI dependency to optionally extract the current user (None if unauthenticated)."""
    return getattr(request.state, "user", None)
