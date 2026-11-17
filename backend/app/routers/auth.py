import os

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, User, UserRole
from ..schemas import (
    AuditLogRead,
    AuthResponse,
    SetPinRequest,
    UserCreate,
    UserLoginRequest,
    UserPinLoginRequest,
    UserRead,
)
from ..auth.security import (
    create_access_token,
    hash_password,
    hash_pin,
    verify_password,
    verify_pin,
)
from ..auth.dependencies import get_current_user, require_admin, require_any_authenticated
from ..services import log_action

router = APIRouter(prefix="/api/auth", tags=["auth"])
INSECURE_INITIAL_ADMIN_PASSWORD_VALUES = frozenset(
    {
        "change-me",
        "replace-with-a-strong-one-time-password",
        "replace-with-a-strong-password",
        "your-password",
    }
)


def user_to_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        is_active=user.is_active,
        has_trusted_pin=bool(user.trusted_pin_hash and user.trusted_device_id),
        created_at=user.created_at,
    )


def provision_initial_admin(db: Session) -> User | None:
    """Create the first administrator from environment configuration, once per database."""
    if db.scalar(select(func.count()).select_from(User)):
        return None

    email = os.getenv("INITIAL_ADMIN_EMAIL", "").strip().lower()
    name = os.getenv("INITIAL_ADMIN_NAME", "").strip()
    password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    if not email or not name or not password:
        raise RuntimeError(
            "No users exist. Set INITIAL_ADMIN_EMAIL, INITIAL_ADMIN_NAME, and "
            "INITIAL_ADMIN_PASSWORD before starting Udaya Library for the first time."
        )
    normalized_password = password.strip().lower()
    if (
        len(password) < 12
        or normalized_password in INSECURE_INITIAL_ADMIN_PASSWORD_VALUES
        or normalized_password.startswith(("replace-with-", "change-me", "your-"))
    ):
        raise RuntimeError("INITIAL_ADMIN_PASSWORD must contain at least 12 characters.")

    password_hash, salt = hash_password(password)
    admin = User(
        email=email,
        name=name,
        password_hash=password_hash,
        salt=salt,
        role=UserRole.ADMINISTRATOR.value,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    log_action(db, "initial_admin_created", admin.id, {"email": admin.email}, actor="system")
    return admin


@router.post("/login", response_model=AuthResponse)
def login(payload: UserLoginRequest, db: Session = Depends(get_db)):
    """Authenticate with email and password."""
    email_clean = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email_clean))
    if not user or not verify_password(payload.password, user.password_hash, user.salt):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This user account has been disabled.",
        )

    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        name=user.name,
        device_id=payload.device_id,
    )
    log_action(
        db,
        "user_logged_in",
        user.id,
        {"method": "password", "email": user.email},
        actor=user.email,
        actor_role=user.role,
        device_id=payload.device_id,
        entity_type="auth",
    )
    db.commit()

    return AuthResponse(access_token=token, user=user_to_read(user))


@router.post("/pin-login", response_model=AuthResponse)
def pin_login(payload: UserPinLoginRequest, db: Session = Depends(get_db)):
    """Fast login using trusted device ID and PIN."""
    email_clean = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email_clean))
    if (
        not user
        or not user.trusted_pin_hash
        or not user.trusted_device_id
        or user.trusted_device_id != payload.device_id
        or not verify_pin(payload.pin, user.trusted_pin_hash, user.salt)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid PIN or untrusted device. Please use email and password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This user account has been disabled.",
        )

    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        name=user.name,
        device_id=payload.device_id,
    )
    log_action(
        db,
        "user_logged_in",
        user.id,
        {"method": "device_pin", "email": user.email},
        actor=user.email,
        actor_role=user.role,
        device_id=payload.device_id,
        entity_type="auth",
    )
    db.commit()

    return AuthResponse(access_token=token, user=user_to_read(user))


@router.post("/set-pin", response_model=UserRead)
def set_device_pin(
    payload: SetPinRequest,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """Setup or update the trusted device PIN for the current user and device."""
    current_user.trusted_device_id = payload.device_id.strip()
    current_user.trusted_pin_hash = hash_pin(payload.pin.strip(), current_user.salt)
    log_action(
        db,
        "device_pin_configured",
        current_user.id,
        {"device_id": current_user.trusted_device_id},
        actor=current_user.email,
        actor_role=current_user.role,
        device_id=current_user.trusted_device_id,
        entity_type="auth",
    )
    db.commit()
    db.refresh(current_user)
    return user_to_read(current_user)


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(require_any_authenticated)):
    """Return currently authenticated user information."""
    return user_to_read(current_user)


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """(Administrator only) Create a new librarian or restricted librarian account."""
    email_clean = payload.email.strip().lower()
    existing = db.scalar(select(User).where(User.email == email_clean))
    if existing:
        raise HTTPException(status_code=409, detail="A user with this email already exists.")

    valid_roles = [r.value for r in UserRole]
    if payload.role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}",
        )

    pw_hash, salt = hash_password(payload.password)
    user = User(
        email=email_clean,
        name=payload.name.strip(),
        password_hash=pw_hash,
        salt=salt,
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log_action(
        db,
        "user_created",
        user.id,
        {"email": user.email, "role": user.role},
        actor=current_admin.email,
        actor_role=current_admin.role,
        entity_type="user",
    )
    db.commit()
    return user_to_read(user)


@router.get("/users", response_model=list[UserRead])
def list_users(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """(Administrator only) List all user accounts."""
    users = db.scalars(select(User).order_by(User.id.asc())).all()
    return [user_to_read(u) for u in users]


@router.get("/audit-logs", response_model=list[AuditLogRead])
def get_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    (Administrator only) View complete system audit history.
    Protected strictly from ordinary librarians and restricted users.
    """
    stmt = (
        select(AuditLog)
        .order_by(AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = db.scalars(stmt).all()
    return logs
