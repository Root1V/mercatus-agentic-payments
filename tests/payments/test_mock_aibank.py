"""Cobertura directa de `MockAIBank` (RM-18): autorizar/capturar/consultar/
reembolsar, sin pasar por el transporte de AP2 -- ver
`tests/payments/protocols/test_ap2_aibank_settlement.py` para eso."""

from __future__ import annotations

from decimal import Decimal

import pytest

from agent_commerce.payments.aibank_credential import AIBankCredential
from agent_commerce.payments.mock_aibank import AIBankError, MockAIBank


def test_authorize_then_capture_moves_the_balance() -> None:
    bank = MockAIBank()
    buyer = AIBankCredential()
    seller = AIBankCredential()

    authorization = bank.authorize(
        credential=buyer, pay_to_account_id=seller.account_id, amount=Decimal(10), idempotency_key="k1"
    )
    assert authorization.status == "authorized"

    captured = bank.capture(authorization_id=authorization.id, credential=buyer)
    assert captured.status == "captured"
    assert bank.get(authorization.id).status == "captured"


def test_repeated_idempotency_key_returns_the_same_authorization() -> None:
    bank = MockAIBank()
    buyer = AIBankCredential()
    seller = AIBankCredential()

    first = bank.authorize(
        credential=buyer, pay_to_account_id=seller.account_id, amount=Decimal(5), idempotency_key="same"
    )
    second = bank.authorize(
        credential=buyer, pay_to_account_id=seller.account_id, amount=Decimal(5), idempotency_key="same"
    )
    assert first.id == second.id


def test_insufficient_funds_is_rejected() -> None:
    bank = MockAIBank()
    buyer = AIBankCredential()
    seller = AIBankCredential()

    with pytest.raises(AIBankError, match="insufficient_funds"):
        bank.authorize(
            credential=buyer,
            pay_to_account_id=seller.account_id,
            amount=Decimal(999999999999),
            idempotency_key="k1",
        )


def test_capturing_someone_elses_authorization_is_rejected() -> None:
    bank = MockAIBank()
    buyer = AIBankCredential()
    seller = AIBankCredential()
    other = AIBankCredential()

    authorization = bank.authorize(
        credential=buyer, pay_to_account_id=seller.account_id, amount=Decimal(1), idempotency_key="k1"
    )
    with pytest.raises(AIBankError, match="authorization_belongs_to_another_account"):
        bank.capture(authorization_id=authorization.id, credential=other)


def test_refund_only_the_payee_can_do_it_and_reverses_the_balance() -> None:
    bank = MockAIBank()
    buyer = AIBankCredential()
    seller = AIBankCredential()

    authorization = bank.authorize(
        credential=buyer, pay_to_account_id=seller.account_id, amount=Decimal(7), idempotency_key="k1"
    )
    bank.capture(authorization_id=authorization.id, credential=buyer)

    with pytest.raises(AIBankError, match="only_the_payee_can_refund"):
        bank.refund(authorization_id=authorization.id, credential=buyer)

    refunded = bank.refund(authorization_id=authorization.id, credential=seller)
    assert refunded.status == "refunded"


def test_wrong_api_key_for_a_known_account_is_rejected() -> None:
    bank = MockAIBank()
    buyer = AIBankCredential()
    seller = AIBankCredential()
    # Primera llamada "abre" la cuenta con ese api_key.
    bank.authorize(
        credential=buyer, pay_to_account_id=seller.account_id, amount=Decimal(1), idempotency_key="k1"
    )

    impostor = AIBankCredential(account_id=buyer.account_id, api_key="wrong")
    with pytest.raises(AIBankError, match="invalid_credential"):
        bank.authorize(
            credential=impostor, pay_to_account_id=seller.account_id, amount=Decimal(1), idempotency_key="k2"
        )
