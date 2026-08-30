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
    AIBANK = "aibank"


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

    # --- AIBank (riel de banco propio, RM-18) ---------------------------------
    # Solo aplica con protocol=aibank. Sin valores, en modo mock se generan
    # cuenta/api key efímeras al vuelo (mismo criterio que LocalEoaSigner sin
    # private_key) -- fijalos solo si necesitás reusar la misma cuenta entre
    # corridas (p. ej. contra un AIBank real el día que exista uno).
    aibank_buyer_account_id: str | None = None
    aibank_buyer_api_key: SecretStr | None = None
    aibank_seller_account_id: str | None = None
    aibank_seller_api_key: SecretStr | None = None

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

    # --- LLM (Prometheus, plataforma de inferencia local, repo hermano
    # "edge-ai-inference") -- usado por el playground de agentes (RM-11+).
    # Nada de esto se usa fuera de `agent_commerce.llm`/`agent_commerce.agentloop`;
    # queda opcional para no romper Settings() en el resto del framework.
    llm_auth_base_url: str = "http://localhost:9000"
    # Puerto por defecto del gateway de Prometheus (8000) choca con el del
    # propio dashboard: en un despliegue conjunto hay que reconfigurar uno
    # de los dos, por eso este default apunta a 8001.
    llm_gateway_base_url: str = "http://localhost:8001"
    llm_client_id: str | None = None
    llm_client_secret: SecretStr | None = None
    llm_model: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
