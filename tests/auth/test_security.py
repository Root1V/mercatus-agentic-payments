from __future__ import annotations

import pytest
from jose import JWTError

from agent_commerce.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_is_not_the_plain_text() -> None:
    hashed = hash_password("supersecret123")
    assert hashed != "supersecret123"
    assert hashed.startswith("$2b$")


def test_verify_password_accepts_correct_and_rejects_wrong() -> None:
    hashed = hash_password("supersecret123")
    assert verify_password("supersecret123", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_access_token_roundtrip() -> None:
    token = create_access_token(
        "carlos", expires_minutes=5, secret_key="dev-secret", algorithm="HS256"
    )
    assert decode_access_token(token, secret_key="dev-secret", algorithm="HS256") == "carlos"


def test_access_token_rejected_with_wrong_secret() -> None:
    token = create_access_token(
        "carlos", expires_minutes=5, secret_key="dev-secret", algorithm="HS256"
    )
    with pytest.raises(JWTError):
        decode_access_token(token, secret_key="wrong-secret", algorithm="HS256")


def test_expired_token_is_rejected() -> None:
    token = create_access_token(
        "carlos", expires_minutes=-1, secret_key="dev-secret", algorithm="HS256"
    )
    with pytest.raises(JWTError):
        decode_access_token(token, secret_key="dev-secret", algorithm="HS256")
