"""Entorno de AIBank para los tests de contrato (`test_aibank_contract.py`).

Los tests de contrato hablan SOLO con el puerto (`AIBankApi` +
`HolderChannel`), así que corren igual contra cualquier implementación: hoy
`MockAIBank`; cuando exista el cliente HTTP, también contra el sandbox real
(otro parámetro del fixture `aibank` en `conftest.py`)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from agent_commerce.payments.aibank_api import (
    AIBankApi,
    Authorization,
    HolderChannel,
    Intent,
    Mandate,
    TestHolder,
)
from agent_commerce.payments.aibank_signing import AgentIdentity, generate_agent_key, public_jwk


@dataclass
class AIBankEnv:
    __test__ = False

    api: AIBankApi
    holders: HolderChannel
    kind: str = "mock"  # "mock" | "sandbox"
    _default_agent: AgentIdentity | None = None

    async def agent(self, name: str = "Agente de pruebas de Mercatus") -> AgentIdentity:
        """Un agente nuevo, registrado con una clave Ed25519 nueva (1.1)."""
        private_key = generate_agent_key()
        agent = await self.api.register_agent(name=name, public_key=public_jwk(private_key))
        return AgentIdentity(
            agent_id=agent.agent_id, key_id=agent.keys[0].key_id, private_key=private_key
        )

    async def default_agent(self) -> AgentIdentity:
        if self._default_agent is None:
            self._default_agent = await self.agent()
        return self._default_agent

    def intent(self, description: str = "Prueba de contrato: un servicio del catálogo") -> Intent:
        return Intent(reference=self.key("task"), description=description)

    async def authorize(
        self,
        *,
        payer_account_id: str,
        payee_account_id: str,
        amount: int,
        idempotency_key: str,
        mandate_id: str | None = None,
        agent: AgentIdentity | None = None,
        intent: Intent | None = None,
    ) -> Authorization:
        """`api.authorize` firmado por el agente de pruebas (o el indicado)."""
        return await self.api.authorize(
            payer_account_id=payer_account_id,
            payee_account_id=payee_account_id,
            amount=amount,
            idempotency_key=idempotency_key,
            mandate_id=mandate_id,
            agent=agent or await self.default_agent(),
            intent=intent or self.intent(),
        )

    def key(self, label: str = "k") -> str:
        """Una `Idempotency-Key` única por llamada: contra un sandbox que
        persiste entre corridas, una clave fija reencontraría el pago de una
        corrida anterior (replay o `idempotency_key_reused`)."""
        return f"{label}-{uuid.uuid4().hex}"

    async def funded_account(
        self, label: str = "agent", *, balance: int = 10_000_000, agent: AgentIdentity | None = None
    ) -> str:
        """Una sub-cuenta nueva de la integración con saldo de sandbox, atada al
        agente de pruebas (o al indicado) para que pueda pagar. El
        `owner_reference` es único por llamada: contra un sandbox compartido,
        reusarlo devolvería la cuenta de otra corrida (es idempotente)."""
        owner = agent or await self.default_agent()
        account = await self.api.open_account(
            owner_reference=f"test-{label}-{uuid.uuid4().hex[:12]}",
            initial_balance=balance,
            agent_id=owner.agent_id,
        )
        return account.account_id

    async def seller_account(self) -> str:
        """Una sub-cuenta SIN agente, como la de un vendedor: cobra, no paga."""
        account = await self.api.open_account(
            owner_reference=f"test-seller-{uuid.uuid4().hex[:12]}"
        )
        return account.account_id

    async def holder(self, *, balance: int = 50_000_000) -> TestHolder:
        return await self.holders.create_test_holder(
            name="Titular de prueba", initial_balance=balance
        )

    async def mandate(
        self,
        *,
        max_per_operation: int = 5_000_000,
        max_total: int = 50_000_000,
        granted_per_operation: int | None = None,
        granted_total: int | None = None,
        holder_balance: int = 50_000_000,
    ) -> tuple[Mandate, TestHolder]:
        """El modelo B completo hasta tener un mandato activo: pedir →
        titular aprueba (por defecto exactamente lo pedido) → consultar."""
        request = await self.api.create_consent_request(
            agent_id=(await self.default_agent()).agent_id,
            purpose="Pagos del agente de pruebas de Mercatus",
            max_per_operation=max_per_operation,
            max_total=max_total,
        )
        holder = await self.holder(balance=holder_balance)
        await self.holders.approve(
            holder,
            request.handoff_code,
            account_id=holder.account_id,
            max_per_operation=granted_per_operation
            if granted_per_operation is not None
            else max_per_operation,
            max_total=granted_total if granted_total is not None else max_total,
        )
        approved = await self.api.get_consent_request(request.consent_request_id)
        assert approved.mandate_id is not None
        return await self.api.get_mandate(approved.mandate_id), holder
