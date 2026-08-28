"""Dependencia de FastAPI que exige un JWT válido: `Depends(get_current_user)`."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_commerce.config import get_settings
from agent_commerce.db.models import UserModel
from agent_commerce.db.session import get_db

from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Credenciales inválidas o expiradas",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> UserModel:
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AGENT_COMMERCE_JWT_SECRET_KEY no está configurado",
        )
    try:
        username = decode_access_token(
            token,
            secret_key=settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )
    except JWTError as exc:
        raise _credentials_error from exc

    user = db.execute(select(UserModel).where(UserModel.username == username)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise _credentials_error
    return user
