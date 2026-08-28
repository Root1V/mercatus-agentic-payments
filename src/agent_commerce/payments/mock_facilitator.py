"""Facilitator x402 100% en memoria, sin RPC ni fondos reales.

Satisface directamente el protocolo `FacilitatorClient` de x402
(`verify`/`settle`/`get_supported`) -- no pasa por `x402Facilitator` +
`ExactEvmScheme` facilitator, porque esa ruta real simula la transferencia
on-chain vía Multicall3 contra un nodo RPC, algo fuera de alcance para un
modo sin red.

Lo que SÍ es real aquí: la verificación de la firma EIP-712 de la
autorización EIP-3009 (`TransferWithAuthorization`) usa exactamente el
mismo hash y la misma recuperación de firma ECDSA que usaría un
facilitator real (reutiliza `x402.mechanisms.evm.eip712` y
`x402.mechanisms.evm.verify`). Lo simulado es solo la liquidación: en vez
de invocar `transferWithAuthorization` en el contrato USDC real, mueve
saldos en un diccionario en memoria.
"""

from __future__ import annotations

import time
from uuid import uuid4

from x402 import (
    PaymentPayload,
    PaymentRequirements,
    SettleResponse,
    SupportedKind,
    SupportedResponse,
    VerifyResponse,
)
from x402.mechanisms.evm.eip712 import hash_eip3009_authorization
from x402.mechanisms.evm.types import ExactEIP3009Authorization, ExactEIP3009Payload
from x402.mechanisms.evm.utils import get_evm_chain_id, hex_to_bytes
from x402.mechanisms.evm.verify import verify_eoa_signature

# Saldo simulado con el que arranca cualquier dirección pagadora la primera
# vez que se le consulta -- en unidades atómicas de USDC (6 decimales), o
# sea 10**9 USDC. No hay paso de "fondeo" en modo mock: el objetivo es
# probar el protocolo de pago, no simular escasez económica.
_MOCK_STARTING_BALANCE = 10**15


class MockFacilitator:
    """Facilitator en memoria para el esquema `exact` (EIP-3009) de x402."""

    def __init__(self, *, network: str, facilitator_address: str) -> None:
        self._network = network
        self._facilitator_address = facilitator_address
        self._used_nonces: set[str] = set()
        self._balances: dict[tuple[str, str], int] = {}
        self.ledger: list[SettleResponse] = []

    def _balance(self, asset: str, address: str) -> int:
        key = (asset.lower(), address.lower())
        if key not in self._balances:
            self._balances[key] = _MOCK_STARTING_BALANCE
        return self._balances[key]

    def get_supported(self) -> SupportedResponse:
        return SupportedResponse(
            kinds=[SupportedKind(x402_version=2, scheme="exact", network=self._network)],
            signers={"eip155": [self._facilitator_address]},
        )

    async def verify(
        self, payload: PaymentPayload, requirements: PaymentRequirements
    ) -> VerifyResponse:
        return self._verify(payload, requirements)

    def _verify(self, payload: PaymentPayload, requirements: PaymentRequirements) -> VerifyResponse:
        if payload.accepted.scheme != "exact":
            return VerifyResponse(is_valid=False, invalid_reason="unsupported_scheme")
        if str(payload.accepted.network) != str(requirements.network):
            return VerifyResponse(is_valid=False, invalid_reason="network_mismatch")

        evm_payload = ExactEIP3009Payload.from_dict(payload.payload)
        auth = evm_payload.authorization
        payer = auth.from_address

        extra = requirements.extra or {}
        if "name" not in extra or "version" not in extra:
            return VerifyResponse(is_valid=False, invalid_reason="missing_eip712_domain", payer=payer)
        if auth.to.lower() != requirements.pay_to.lower():
            return VerifyResponse(is_valid=False, invalid_reason="recipient_mismatch", payer=payer)
        if int(auth.value) != int(requirements.amount):
            return VerifyResponse(is_valid=False, invalid_reason="amount_mismatch", payer=payer)

        now = int(time.time())
        if int(auth.valid_before) <= now:
            return VerifyResponse(is_valid=False, invalid_reason="valid_before_expired", payer=payer)
        if int(auth.valid_after) > now:
            return VerifyResponse(is_valid=False, invalid_reason="valid_after_future", payer=payer)
        if auth.nonce in self._used_nonces:
            return VerifyResponse(is_valid=False, invalid_reason="nonce_already_used", payer=payer)

        try:
            chain_id = get_evm_chain_id(str(requirements.network))
        except ValueError:
            return VerifyResponse(
                is_valid=False, invalid_reason="failed_to_get_network_config", payer=payer
            )

        digest = hash_eip3009_authorization(
            ExactEIP3009Authorization(
                from_address=auth.from_address,
                to=auth.to,
                value=auth.value,
                valid_after=auth.valid_after,
                valid_before=auth.valid_before,
                nonce=auth.nonce,
            ),
            chain_id=chain_id,
            verifying_contract=requirements.asset,
            token_name=extra["name"],
            token_version=extra["version"],
        )

        if not evm_payload.signature:
            return VerifyResponse(is_valid=False, invalid_reason="missing_signature", payer=payer)
        try:
            valid = verify_eoa_signature(digest, hex_to_bytes(evm_payload.signature), payer)
        except ValueError:
            valid = False
        if not valid:
            return VerifyResponse(is_valid=False, invalid_reason="invalid_signature", payer=payer)

        if self._balance(requirements.asset, payer) < int(auth.value):
            return VerifyResponse(is_valid=False, invalid_reason="insufficient_funds", payer=payer)

        return VerifyResponse(is_valid=True, payer=payer)

    async def settle(
        self, payload: PaymentPayload, requirements: PaymentRequirements
    ) -> SettleResponse:
        verify_result = self._verify(payload, requirements)
        if not verify_result.is_valid:
            return SettleResponse(
                success=False,
                error_reason=verify_result.invalid_reason,
                payer=verify_result.payer,
                transaction="",
                network=requirements.network,
            )

        evm_payload = ExactEIP3009Payload.from_dict(payload.payload)
        auth = evm_payload.authorization
        payer = auth.from_address
        asset = requirements.asset
        value = int(auth.value)

        self._balances[(asset.lower(), payer.lower())] = self._balance(asset, payer) - value
        self._balances[(asset.lower(), auth.to.lower())] = self._balance(asset, auth.to) + value
        self._used_nonces.add(auth.nonce)

        result = SettleResponse(
            success=True,
            payer=payer,
            transaction=f"0xmock{uuid4().hex}",
            network=requirements.network,
            amount=auth.value,
        )
        self.ledger.append(result)
        return result
