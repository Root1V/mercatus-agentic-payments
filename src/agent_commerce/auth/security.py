"""Hashing de contraseñas (passlib/bcrypt) y JWT (python-jose).

Nota de instalación: `passlib==1.7.4` referencia `bcrypt.__about__.__version__`,
un atributo que `bcrypt>=4.1` eliminó -- por eso `pyproject.toml` fija
`bcrypt<4.1` en el extra `dashboard` (ver pyca/bcrypt#684). Si algún día se
actualiza passlib y deja de necesitar el pin, quitarlo de ahí también.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    subject: str, *, expires_minutes: int, secret_key: str, algorithm: str
) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_access_token(token: str, *, secret_key: str, algorithm: str) -> str:
    """Devuelve el `sub` (username) del token, o levanta `JWTError` si es
    inválido/expiró (dejar que el llamador lo traduzca a 401)."""
    payload = jwt.decode(token, secret_key, algorithms=[algorithm])
    subject = payload.get("sub")
    if not subject:
        raise JWTError("token sin 'sub'")
    return str(subject)
