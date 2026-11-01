"""Dónde viven las claves de los agentes ante AIBank/Aerarium (M-11, M-12, M-15).

Cada agente firma sus pagos con su propia clave Ed25519 (`aibank_signing.py`).
Esa clave privada la genera Mercatus y nunca sale de Mercatus -- y tiene que
sobrevivir a un reinicio: si no, cada arranque registra un agente nuevo y los
permisos que los titulares concedieron al anterior dejan de servir.

- **Cifrada en reposo** con Fernet (AES-128-CBC + HMAC-SHA256) y una clave
  maestra que viene de `AGENT_COMMERCE_AIBANK_KEY_ENCRYPTION_KEY`, nunca de la
  base. En la base solo hay texto cifrado: quien lee la base sin la clave
  maestra no puede firmar por ningún agente.
- **Por banco**: el registro se identifica por `scope` (la URL del banco y la
  integración) y por `label` (qué agente de Mercatus es). Un agente del
  sandbox no sirve en producción, ni al revés.
- **Rotación sin baja** (AE-11): se guarda la clave nueva ANTES de retirar la
  vieja en el banco. Si algo falla en el medio, lo guardado siempre es una
  clave que el banco acepta -- la vieja vale 7 días más.

Antes de producción esto pasa a un gestor de claves (KMS/HSM), condición que
Aerarium pondrá en el contrato (AE-11): la interfaz `AgentKeyStore` es el
punto donde se enchufa.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from .aibank_signing import AgentIdentity, generate_agent_key, public_jwk

if TYPE_CHECKING:
    from .aibank_api import AIBankApi
    from .aibank_credential import AIBankSubAccount
    from .protocols.ap2_protocol import AP2Protocol


class AgentKeyCipher:
    """Cifra y descifra la clave privada de un agente con la clave maestra."""

    def __init__(self, master_key: str) -> None:
        try:
            self._fernet = Fernet(master_key.encode())
        except ValueError as exc:
            raise ValueError(
                "AGENT_COMMERCE_AIBANK_KEY_ENCRYPTION_KEY no es una clave Fernet válida "
                "(32 bytes en base64 url-safe). Generá una con: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from exc

    @staticmethod
    def generate_master_key() -> str:
        return Fernet.generate_key().decode()

    def encrypt(self, private_key: Ed25519PrivateKey) -> str:
        raw = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        return self._fernet.encrypt(raw).decode()

    def decrypt(self, token: str) -> Ed25519PrivateKey:
        try:
            raw = self._fernet.decrypt(token.encode())
        except InvalidToken as exc:
            raise ValueError(
                "no se pudo descifrar la clave del agente: la clave maestra no es la que la cifró"
            ) from exc
        return Ed25519PrivateKey.from_private_bytes(raw)


@dataclass(frozen=True)
class StoredAgent:
    scope: str  # banco + integración, p. ej. "http://localhost:8081#mercatus_sandbox"
    label: str  # qué agente de Mercatus, p. ej. "dashboard_buyer"
    agent_id: str
    agent_name: str
    key_id: str
    encrypted_private_key: str
    account_id: str | None = None  # su sub-cuenta del modelo A, si tiene


class AgentKeyStore(Protocol):
    def get(self, scope: str, label: str) -> StoredAgent | None: ...

    def save(self, agent: StoredAgent) -> None:
        """Crea o reemplaza el registro de `(scope, label)`."""
        ...

    def delete(self, scope: str, label: str) -> None:
        """Olvida el agente (tras darlo de baja en el banco)."""
        ...


class InMemoryAgentKeyStore:
    def __init__(self) -> None:
        self._agents: dict[tuple[str, str], StoredAgent] = {}

    def get(self, scope: str, label: str) -> StoredAgent | None:
        return self._agents.get((scope, label))

    def save(self, agent: StoredAgent) -> None:
        self._agents[(agent.scope, agent.label)] = agent

    def delete(self, scope: str, label: str) -> None:
        self._agents.pop((scope, label), None)


def identity_of(stored: StoredAgent, cipher: AgentKeyCipher) -> AgentIdentity:
    return AgentIdentity(
        agent_id=stored.agent_id, key_id=stored.key_id, private_key=cipher.decrypt(stored.encrypted_private_key)
    )


def load_or_register_buyer(
    *,
    protocol: AP2Protocol,
    store: AgentKeyStore,
    cipher: AgentKeyCipher,
    scope: str,
    label: str,
    agent_name: str,
) -> AIBankSubAccount:
    """El agente comprador `label` con su sub-cuenta, listo para pagar: el
    guardado si existe (mismo agente, misma cuenta, mismos permisos que antes
    del reinicio), o uno nuevo registrado en el banco y guardado cifrado.
    Síncrono: se usa al arrancar o en la primera petición."""
    from .aibank_credential import AIBankSubAccount

    stored = store.get(scope, label)
    if stored is not None and stored.account_id is not None:
        return AIBankSubAccount(account_id=stored.account_id, agent=identity_of(stored, cipher))

    buyer = protocol.provision_aibank_buyer(agent_name=agent_name)
    assert buyer.agent is not None
    store.save(
        StoredAgent(
            scope=scope,
            label=label,
            agent_id=buyer.agent.agent_id,
            agent_name=agent_name,
            key_id=buyer.agent.key_id,
            encrypted_private_key=cipher.encrypt(buyer.agent.private_key),
            account_id=buyer.account_id,
        )
    )
    return buyer


async def rotate_agent_key(
    *,
    api: AIBankApi,
    current: AgentIdentity,
    store: AgentKeyStore | None = None,
    cipher: AgentKeyCipher | None = None,
    scope: str | None = None,
    label: str | None = None,
) -> AgentIdentity:
    """Rota la clave de un agente sin darlo de baja (AE-11): registra la nueva,
    la GUARDA, y recién después retira la vieja en el banco. Si el retiro
    falla, la vieja vence sola a los 7 días y lo guardado ya es la nueva.
    Sin `store` (banco simulado) solo rota en el banco."""
    stored: StoredAgent | None = None
    if store is not None:
        # Validar ANTES de tocar el banco: si no, quedaría registrada una
        # clave que no está guardada en ningún lado.
        assert cipher is not None and scope is not None and label is not None
        stored = store.get(scope, label)
        if stored is None or stored.agent_id != current.agent_id:
            raise ValueError(f"no hay un agente guardado como {label!r} para este banco")

    new_private = generate_agent_key()
    new_key = await api.add_agent_key(current.agent_id, public_key=public_jwk(new_private))
    rotated = AgentIdentity(agent_id=current.agent_id, key_id=new_key.key_id, private_key=new_private)
    if store is not None and stored is not None and cipher is not None:
        store.save(replace(stored, key_id=rotated.key_id, encrypted_private_key=cipher.encrypt(new_private)))
    await api.retire_agent_key(current.agent_id, current.key_id)
    return rotated
