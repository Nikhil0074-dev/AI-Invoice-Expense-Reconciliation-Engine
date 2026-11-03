from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_token, decode_token, hash_password, rate_limiter, verify_password
from app.db.session import get_db
from app.models import Organization, OrganizationMember, User
from app.schemas import (LoginIn, PasswordResetConfirm, PasswordResetRequest, RegisterIn, TokenOut, UserOut)

router = APIRouter(prefix="/auth", tags=["auth"])


def _limit(request: Request, bucket: str) -> None:
    ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"{bucket}:{ip}", get_settings().rate_limit_per_minute)


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    _limit(request, "register")
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise AppError("EMAIL_TAKEN", "An account with this email already exists.", 409)
    user = User(email=email, display_name=body.display_name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    org = Organization(name=(body.organization_name or f"{body.display_name}'s workspace").strip())
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="ADMIN"))
    db.commit()
    return TokenOut(access_token=create_token(user.id))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    _limit(request, "login")
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "Incorrect email or password.", 401)
    return TokenOut(access_token=create_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.post("/password-reset/request")
def reset_request(body: PasswordResetRequest, request: Request, db: Session = Depends(get_db)):
    """Always answers the same way (no account enumeration). Email delivery is not implemented: in
    non-production environments the reset token is returned so the flow can be tested end to end."""
    _limit(request, "reset")
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    resp: dict = {"message": "If the account exists, a reset link has been sent."}
    if user and get_settings().environment != "production":
        resp["dev_reset_token"] = create_token(user.id, "reset", minutes=30)
    return resp


@router.post("/password-reset/confirm")
def reset_confirm(body: PasswordResetConfirm, db: Session = Depends(get_db)):
    user = db.get(User, decode_token(body.token, "reset"))
    if not user:
        raise AppError("INVALID_TOKEN", "Invalid or expired token.", 401)
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"message": "Password updated."}
