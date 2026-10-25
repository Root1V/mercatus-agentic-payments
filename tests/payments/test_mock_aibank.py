"""Cobertura directa de `MockAIBank` (RM-18): autorizar/capturar/consultar/
reembolsar, sin pasar por el transporte de AP2 -- ver
`tests/payments/protocols/test_ap2_aibank_settlement.py` para eso."""

from __future__ import annotations

import time
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


def test_capturing_an_already_captured_authorization_is_idempotent() -> None:
    """Q9 de la respuesta de AIBank: un segundo `capture` sobre una
    autorización ya capturada devuelve la misma autorización en vez de
    fallar -- un reintento por timeout de red no debe verse como un error."""
    bank = MockAIBank()
    buyer = AIBankCredential()
    seller = AIBankCredential()

    authorization = bank.authorize(
        credential=buyer, pay_to_account_id=seller.account_id, amount=Decimal(3), idempotency_key="k1"
    )
    first = bank.capture(authorization_id=authorization.id, credential=buyer)
    second = bank.capture(authorization_id=authorization.id, credential=buyer)

    assert first.status == second.status == "captured"
    # El saldo no se movió dos veces.
    assert bank.get(authorization.id).amount == Decimal(3)


def test_capturing_an_expired_authorization_is_rejected() -> None:
    """Q8 de la respuesta de AIBank: 15 minutos de vigencia, liberación
    automática al vencer."""
    bank = MockAIBank()
    buyer = AIBankCredential()
    seller = AIBankCredential()

    authorization = bank.authorize(
        credential=buyer, pay_to_account_id=seller.account_id, amount=Decimal(1), idempotency_key="k1"
    )
    authorization.expires_at = time.time() - 1  # simula que vencieron los 15 minutos

    with pytest.raises(AIBankError, match="authorization_expired"):
        bank.capture(authorization_id=authorization.id, credential=buyer)
    assert bank.get(authorization.id).status == "expired"


def test_paying_yourself_is_rejected() -> None:
    """Q14 de la respuesta de AIBank: pagador y receptor no pueden ser la
    misma cuenta."""
    bank = MockAIBank()
    buyer = AIBankCredential()

    with pytest.raises(AIBankError, match="same_account"):
        bank.authorize(
            credential=buyer, pay_to_account_id=buyer.account_id, amount=Decimal(1), idempotency_key="k1"
        )


def _grant_mandate(
    bank: MockAIBank,
    *,
    account_id: str = "acc_titular",
    max_per_operation: Decimal = Decimal(50),
    max_total: Decimal = Decimal(500),
    purpose: str = "Pagos del agente de investigación de Acme S.A.",
):
    """Atajo de test para el flujo completo del modelo B (doc 13 §3.1-§3.2):
    pedir consentimiento y simular que el titular lo aprueba en su app --
    `simulate_titular_approval` no tiene equivalente real, ver su docstring."""
    request = bank.request_consent(
        currency="USD", max_per_operation=max_per_operation, max_total=max_total, purpose=purpose
    )
    return bank.simulate_titular_approval(consent_request_id=request.id, account_id=account_id), request


def test_model_b_full_flow_request_approve_pay_capture() -> None:
    """Escenario 21 de `13-spec-modelos-a-y-b.md` §6."""
    bank = MockAIBank()
    seller = AIBankCredential()
    mandate, request = _grant_mandate(bank)

    assert request.status == "approved"  # `_grant_mandate` ya la aprobó
    fetched = bank.get_consent_request(request.id)
    assert fetched is not None and fetched.status == "approved" and fetched.mandate_id == mandate.id

    authorization = bank.authorize_with_mandate(
        mandate_id=mandate.id,
        payer_account_id="acc_titular",
        pay_to_account_id=seller.account_id,
        amount=Decimal(10),
        idempotency_key="cart_demo_002",
    )
    assert authorization.status == "authorized"
    captured = bank.capture(authorization_id=authorization.id, payer_account_id="acc_titular")
    assert captured.status == "captured"


def test_model_b_querying_a_still_pending_request() -> None:
    """Escenario 23 de doc 13 §6."""
    bank = MockAIBank()
    request = bank.request_consent(
        currency="USD", max_per_operation=Decimal(1), max_total=Decimal(1), purpose="test"
    )
    fetched = bank.get_consent_request(request.id)
    assert fetched is not None and fetched.status == "pending" and fetched.mandate_id is None


def test_model_b_request_consent_without_purpose_is_rejected() -> None:
    """Escenario 22 de doc 13 §6."""
    bank = MockAIBank()
    with pytest.raises(AIBankError, match="malformed_request"):
        bank.request_consent(currency="USD", max_per_operation=Decimal(1), max_total=Decimal(1), purpose="")


def test_model_b_paying_over_the_per_operation_limit_is_rejected() -> None:
    """Escenario 25 de doc 13 §6: 422 mandate_limit_exceeded, no insufficient_funds."""
    bank = MockAIBank()
    seller = AIBankCredential()
    mandate, _ = _grant_mandate(bank, max_per_operation=Decimal(5))

    with pytest.raises(AIBankError, match="mandate_limit_exceeded"):
        bank.authorize_with_mandate(
            mandate_id=mandate.id,
            payer_account_id="acc_titular",
            pay_to_account_id=seller.account_id,
            amount=Decimal(6),
            idempotency_key="k1",
        )


def test_model_b_paying_after_revocation_is_rejected() -> None:
    """Escenario 26 de doc 13 §6."""
    bank = MockAIBank()
    seller = AIBankCredential()
    mandate, _ = _grant_mandate(bank)
    bank.revoke_mandate(mandate.id)

    with pytest.raises(AIBankError, match="mandate_revoked"):
        bank.authorize_with_mandate(
            mandate_id=mandate.id,
            payer_account_id="acc_titular",
            pay_to_account_id=seller.account_id,
            amount=Decimal(1),
            idempotency_key="k1",
        )


def test_model_b_declaring_a_different_payer_account_is_rejected() -> None:
    """Escenario 27 de doc 13 §6."""
    bank = MockAIBank()
    seller = AIBankCredential()
    mandate, _ = _grant_mandate(bank, account_id="acc_titular_real")

    with pytest.raises(AIBankError, match="mandate_account_not_covered"):
        bank.authorize_with_mandate(
            mandate_id=mandate.id,
            payer_account_id="acc_otra_cuenta",
            pay_to_account_id=seller.account_id,
            amount=Decimal(1),
            idempotency_key="k1",
        )


def test_model_b_using_an_unknown_mandate_is_rejected() -> None:
    """Escenario 28 de doc 13 §6."""
    bank = MockAIBank()
    seller = AIBankCredential()

    with pytest.raises(AIBankError, match="mandate_not_found"):
        bank.authorize_with_mandate(
            mandate_id="mandate_que_no_existe",
            payer_account_id="acc_titular",
            pay_to_account_id=seller.account_id,
            amount=Decimal(1),
            idempotency_key="k1",
        )


def test_model_b_consumed_and_remaining_reflect_open_and_refunded_authorizations() -> None:
    """Escenario 29 de doc 13 §6 -- y la nota de §3.4: `consumed` se deriva
    del estado vivo, no de un contador aparte."""
    bank = MockAIBank()
    seller = AIBankCredential()
    mandate, _ = _grant_mandate(bank, max_per_operation=Decimal(100), max_total=Decimal(100))

    authorization = bank.authorize_with_mandate(
        mandate_id=mandate.id,
        payer_account_id="acc_titular",
        pay_to_account_id=seller.account_id,
        amount=Decimal(30),
        idempotency_key="k1",
    )
    usage = bank.mandate_usage(mandate.id)
    assert usage.consumed == Decimal(30) and usage.remaining == Decimal(70)

    bank.capture(authorization_id=authorization.id, payer_account_id="acc_titular")
    bank.refund(authorization_id=authorization.id, credential=seller)

    usage_after_refund = bank.mandate_usage(mandate.id)
    assert usage_after_refund.consumed == Decimal(0) and usage_after_refund.remaining == Decimal(100)


def test_model_b_approving_the_same_consent_request_twice_is_rejected() -> None:
    """Escenario 30 de doc 13 §6."""
    bank = MockAIBank()
    request = bank.request_consent(
        currency="USD", max_per_operation=Decimal(1), max_total=Decimal(1), purpose="test"
    )
    bank.simulate_titular_approval(consent_request_id=request.id, account_id="acc_titular")

    with pytest.raises(AIBankError, match="consent_request_already_resolved"):
        bank.simulate_titular_approval(consent_request_id=request.id, account_id="acc_titular")


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


def test_model_b_titular_can_grant_less_but_never_more_than_requested() -> None:
    """Doc 13 §3.2: el titular puede bajar los topes, nunca subirlos."""
    bank = MockAIBank()
    request = bank.request_consent(
        currency="USD", max_per_operation=Decimal(5), max_total=Decimal(50), purpose="test"
    )
    with pytest.raises(AIBankError, match="cannot_raise_requested_limits"):
        bank.simulate_titular_approval(
            consent_request_id=request.id, account_id="acc_titular", max_total=Decimal(51)
        )

    mandate = bank.simulate_titular_approval(
        consent_request_id=request.id, account_id="acc_titular", max_total=Decimal(20)
    )
    assert mandate.max_total == Decimal(20) and mandate.max_per_operation == Decimal(5)


def test_model_b_rejected_request_cannot_be_approved_afterwards() -> None:
    bank = MockAIBank()
    request = bank.request_consent(
        currency="USD", max_per_operation=Decimal(1), max_total=Decimal(1), purpose="test"
    )
    rejected = bank.simulate_titular_rejection(consent_request_id=request.id)
    assert rejected.status == "rejected" and rejected.mandate_id is None

    with pytest.raises(AIBankError, match="consent_request_already_resolved"):
        bank.simulate_titular_approval(consent_request_id=request.id, account_id="acc_titular")
