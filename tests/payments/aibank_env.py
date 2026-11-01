"""Entorno de AIBank para los tests de contrato (`test_aibank_contract.py`).

Los tests de contrato hablan SOLO con el puerto (`AIBankApi` +
`HolderChannel`), así que corren igual contra cualquier implementación: hoy
`MockAIBank`; cuando exista el cliente HTTP, también contra el sandbox real
(otro parámetro del fixture `aibank` en `conftest.py`)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from agent_commerce.payments.aibank_api import AIBankApi, HolderChannel, Mandate, TestHolder


@dataclass
class AIBankEnv:
    __test__ = False

    api: AIBankApi
    holders: HolderChannel
    kind: str = "mock"  # "mock" | "sandbox"

    def key(self, label: str = "k") -> str:
        """Una `Idempotency-Key` única por llamada: contra un sandbox que
        persiste entre corridas, una clave fija reencontraría el pago de una
        corrida anterior (replay o `idempotency_key_reused`)."""
        return f"{label}-{uuid.uuid4().hex}"

    async def funded_account(self, label: str = "agent", *, balance: int = 10_000_000) -> str:
        """Una sub-cuenta nueva de la integración con saldo de sandbox. El
        `owner_reference` es único por llamada: contra un sandbox compartido,
        reusarlo devolvería la cuenta de otra corrida (es idempotente)."""
        account = await self.api.open_account(
            owner_reference=f"test-{label}-{uuid.uuid4().hex[:12]}", initial_balance=balance
        )
        return account.account_id

    async def holder(self, *, balance: int = 50_000_000) -> TestHolder:
        return await self.holders.create_test_holder(name="Titular de prueba", initial_balance=balance)

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
            purpose="Pagos del agente de pruebas de Mercatus",
            max_per_operation=max_per_operation,
            max_total=max_total,
        )
        holder = await self.holder(balance=holder_balance)
        await self.holders.approve(
            holder,
            request.handoff_code,
            account_id=holder.account_id,
            max_per_operation=granted_per_operation if granted_per_operation is not None else max_per_operation,
            max_total=granted_total if granted_total is not None else max_total,
        )
        approved = await self.api.get_consent_request(request.consent_request_id)
        assert approved.mandate_id is not None
        return await self.api.get_mandate(approved.mandate_id), holder
