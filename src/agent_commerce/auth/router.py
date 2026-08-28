"""`POST /api/auth/login` (compatible con `OAuth2PasswordRequestForm`, así el
botón "Authorize" de `/docs` funciona sin nada especial) y `GET /api/auth/me`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_commerce.config import get_settings
from agent_commerce.db.models import UserModel
from agent_commerce.db.session import get_db

from .dependencies import get_current_user
from .schemas import Token, UserOut
from .security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> Token:
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AGENT_COMMERCE_JWT_SECRET_KEY no está configurado",
        )

    user = db.execute(
        select(UserModel).where(UserModel.username == form_data.username)
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        user.username,
        expires_minutes=settings.jwt_expires_minutes,
        secret_key=settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
def me(current_user: UserModel = Depends(get_current_user)) -> UserModel:
    return current_user
