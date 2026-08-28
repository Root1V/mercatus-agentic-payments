"""Configuración central: qué protocolo de pago y qué backend de wallet usar.

Cambiar de mock a testnet, o de x402 a AP2, o de wallet local a Circle, es
siempre un cambio de `Settings` (variables de entorno o `.env`) -- nunca un
cambio de código en `server/`, `client/` ni en los ejemplos.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Mode(str, Enum):
    MOCK = "mock"
    TESTNET = "testnet"


class Protocol(str, Enum):
    X402 = "x402"
    AP2 = "ap2"


class WalletBackend(str, Enum):
    LOCAL = "local"
    CIRCLE = "circle"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_COMMERCE_", env_file=".env", extra="ignore")

    mode: Mode = Mode.MOCK
    protocol: Protocol = Protocol.X402
    wallet_backend: WalletBackend = WalletBackend.LOCAL

    # CAIP-2. Base Sepolia por defecto: es donde x402/Circle documentan sus
    # ejemplos de testnet con USDC, y coincide con la red que usa el
    # facilitator mock para construir PaymentRequirements realistas.
    network: str = "eip155:84532"

    # Solo se usa en mode=testnet (x402): a qué facilitator remoto verificar/liquidar.
    facilitator_url: str | None = None

    seller_pay_to_address: str | None = None
    buyer_private_key: SecretStr | None = None
    seller_private_key: SecretStr | None = None

    circle_api_key: SecretStr | None = None
    circle_entity_secret: SecretStr | None = None
    circle_buyer_wallet_id: str | None = None
    circle_seller_wallet_id: str | None = None

    # --- Dashboard: persistencia + auth (extra opcional "dashboard") ---------
    # Nada de esto se usa fuera de `agent_commerce.dashboard`/`agent_commerce.auth`;
    # queda opcional aquí (con defaults de desarrollo, nunca de producción) para
    # no romper Settings() para quien solo usa el framework como librería/CLI.
    database_url: str = "postgresql+psycopg://agent_commerce:agent_commerce@localhost:5432/agent_commerce"
    jwt_secret_key: SecretStr | None = None
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24
    admin_username: str | None = None
    admin_password: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
