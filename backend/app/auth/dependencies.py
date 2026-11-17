from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, UserRole
from .security import decode_access_token


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """
    Validate the Authorization Bearer token and return the current active User.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = int(payload.get("sub", 0))
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or not found.",
        )

    return user


def get_optional_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    """
    Return authenticated user if Authorization header is provided, else None.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload:
        return None
    try:
        user_id = int(payload.get("sub", 0))
        user = db.get(User, user_id)
        if user and user.is_active:
            return user
    except Exception:
        pass
    return None


def get_authenticated_device_id(
    authorization: str | None = Header(default=None),
    x_device_id: str | None = Header(default=None),
    current_user: User = Depends(get_current_user),
) -> str:
    """Return the device identity carried by the authenticated request."""
    del current_user
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token) or {}
    device_id = payload.get("device_id") or x_device_id
    return str(device_id).strip() if device_id else "device-local"


def require_role(allowed_roles: list[str]):
    """
    Factory dependency checking that the current user has one of the allowed roles.
    Raises 403 Forbidden if the role is insufficient.
    """
    def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Required role(s): {', '.join(allowed_roles)}.",
            )
        return user

    return role_checker


# Role convenience dependencies
require_admin = require_role([UserRole.ADMINISTRATOR.value])
require_librarian = require_role([UserRole.ADMINISTRATOR.value, UserRole.LIBRARIAN.value])
require_any_authenticated = require_role([
    UserRole.ADMINISTRATOR.value,
    UserRole.LIBRARIAN.value,
    UserRole.RESTRICTED_LIBRARIAN.value,
])
