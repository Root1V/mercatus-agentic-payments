"""Contrato de la API de socio de AIBank (hoy Aerarium), contra el puerto.

Cada test es un escenario del doc 11 §5 (modelo A, numerados como allá) o del
doc 13 §6 (modelo B), con el resultado que el banco real da -- verificado
contra su código (`services/mercatus/handlers.go`, `86731d1`) donde los docs
no alcanzan. Solo usan `AIBankApi`/`HolderChannel`: corren contra cualquier
implementación del fixture `aibank` (ver `conftest.py`). Lo que necesita
controles que solo tiene el mock (reloj, congelar, otra integración) está en
`test_mock_aibank.py`."""

from __future__ import annotations

import pytest

from agent_commerce.payments.aibank_api import AIBankError, Intent
from agent_commerce.payments.aibank_signing import AgentIdentity, generate_agent_key, public_jwk
from tests.payments.aibank_env import AIBankEnv

_ONE_TENTH_OF_A_CENT = 1_000  # $0.001 en micras


async def _expect(code: str, awaitable: object) -> AIBankError:
    with pytest.raises(AIBankError) as excinfo:
        await awaitable  # type: ignore[misc]
    assert excinfo.value.code == code
    return excinfo.value


# --- Modelo A ---------------------------------------------------------------


async def test_01_happy_path_authorize_get_capture(aibank: AIBankEnv) -> None:
    payer, payee = (
        await aibank.funded_account("payer"),
        await aibank.funded_account("payee", balance=0),
    )

    authorization = await aibank.authorize(
        payer_account_id=payer,
        payee_account_id=payee,
        amount=_ONE_TENTH_OF_A_CENT,
        idempotency_key=aibank.key("cart_01"),
    )
    assert authorization.status == "authorized"
    assert authorization.authorization_id.startswith("auth_")
    assert not authorization.replayed

    detail = await aibank.api.get_authorization(authorization.authorization_id)
    assert (detail.payer_account_id, detail.payee_account_id, detail.amount) == (
        payer,
        payee,
        1_000,
    )

    captured = await aibank.api.capture(authorization.authorization_id)
    assert captured.status == "captured"
    assert captured.settled_at is not None


async def test_02_retry_with_same_key_replays_the_original(aibank: AIBankEnv) -> None:
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    kwargs = {
        "payer_account_id": payer,
        "payee_account_id": payee,
        "amount": 1_000,
        "idempotency_key": aibank.key(),
    }

    first = await aibank.authorize(**kwargs)  # type: ignore[arg-type]
    retry = await aibank.authorize(**kwargs)  # type: ignore[arg-type]

    assert retry.replayed
    assert retry.authorization_id == first.authorization_id


async def test_03_same_key_with_another_amount_is_rejected(aibank: AIBankEnv) -> None:
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    key = aibank.key()
    await aibank.authorize(
        payer_account_id=payer, payee_account_id=payee, amount=1_000, idempotency_key=key
    )

    await _expect(
        "idempotency_key_reused",
        aibank.authorize(
            payer_account_id=payer, payee_account_id=payee, amount=2_000, idempotency_key=key
        ),
    )


async def test_04_missing_idempotency_key_is_malformed(aibank: AIBankEnv) -> None:
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    await _expect(
        "malformed_request",
        aibank.authorize(
            payer_account_id=payer, payee_account_id=payee, amount=1_000, idempotency_key=""
        ),
    )


async def test_05_insufficient_funds(aibank: AIBankEnv) -> None:
    payer = await aibank.funded_account("payer", balance=100_000)
    payee = await aibank.funded_account("payee")
    error = await _expect(
        "insufficient_funds",
        aibank.authorize(
            payer_account_id=payer,
            payee_account_id=payee,
            amount=999_000_000,
            idempotency_key=aibank.key("k"),
        ),
    )
    assert error.status == 402


async def test_06_capturing_twice_returns_the_same_capture(aibank: AIBankEnv) -> None:
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    authorization = await aibank.authorize(
        payer_account_id=payer,
        payee_account_id=payee,
        amount=1_000,
        idempotency_key=aibank.key("k"),
    )
    first = await aibank.api.capture(authorization.authorization_id)
    second = await aibank.api.capture(authorization.authorization_id)
    assert second.status == "captured"
    assert second.settled_at == first.settled_at


async def test_08_to_10_seller_verification(aibank: AIBankEnv) -> None:
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    other = await aibank.funded_account("other")
    authorization = await aibank.authorize(
        payer_account_id=payer,
        payee_account_id=payee,
        amount=1_000,
        idempotency_key=aibank.key("k"),
    )
    auth_id = authorization.authorization_id

    ok = await aibank.api.get_authorization(
        auth_id, expected_amount=1_000, expected_payee_account_id=payee
    )
    assert ok.authorization_id == auth_id
    await _expect("amount_mismatch", aibank.api.get_authorization(auth_id, expected_amount=2_000))
    await _expect(
        "recipient_mismatch", aibank.api.get_authorization(auth_id, expected_payee_account_id=other)
    )


async def test_11_paying_yourself_is_rejected(aibank: AIBankEnv) -> None:
    account = await aibank.funded_account()
    await _expect(
        "same_account",
        aibank.authorize(
            payer_account_id=account,
            payee_account_id=account,
            amount=1_000,
            idempotency_key=aibank.key("k"),
        ),
    )


async def test_12_unknown_account(aibank: AIBankEnv) -> None:
    payee = await aibank.funded_account("payee")
    await _expect(
        "account_not_found",
        aibank.authorize(
            payer_account_id="acc_" + "0" * 32,
            payee_account_id=payee,
            amount=1_000,
            idempotency_key=aibank.key("k"),
        ),
    )


async def test_16_17_refund_only_what_was_captured(aibank: AIBankEnv) -> None:
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    authorization = await aibank.authorize(
        payer_account_id=payer,
        payee_account_id=payee,
        amount=10_000,
        idempotency_key=aibank.key("k"),
    )
    await _expect("nothing_to_refund", aibank.api.refund(authorization.authorization_id))

    await aibank.api.capture(authorization.authorization_id)
    refund = await aibank.api.refund(authorization.authorization_id)
    assert (refund.status, refund.refunded, refund.refundable) == ("refunded", 10_000, 0)


async def test_partial_refunds_until_the_total(aibank: AIBankEnv) -> None:
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    authorization = await aibank.authorize(
        payer_account_id=payer,
        payee_account_id=payee,
        amount=10_000,
        idempotency_key=aibank.key("k"),
    )
    await aibank.api.capture(authorization.authorization_id)

    partial = await aibank.api.refund(authorization.authorization_id, amount=3_000)
    assert (partial.status, partial.refunded, partial.refunded_total, partial.refundable) == (
        "partially_refunded",
        3_000,
        3_000,
        7_000,
    )
    await _expect(
        "refund_exceeds_capture", aibank.api.refund(authorization.authorization_id, amount=8_000)
    )
    rest = await aibank.api.refund(authorization.authorization_id)
    assert (rest.status, rest.refunded, rest.refundable) == ("refunded", 7_000, 0)


async def test_recapturing_a_refunded_authorization_confirms_the_capture(aibank: AIBankEnv) -> None:
    """AE-14: capturar algo ya cobrado, aunque después se haya devuelto, es
    `200` con el mismo `settled_at` y el estado de hoy -- un reintento de
    captura confirma que se hizo, sin obligar a un `GET` para averiguarlo."""
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    authorization = await aibank.authorize(
        payer_account_id=payer,
        payee_account_id=payee,
        amount=1_000,
        idempotency_key=aibank.key("k"),
    )
    captured = await aibank.api.capture(authorization.authorization_id)
    await aibank.api.refund(authorization.authorization_id)

    again = await aibank.api.capture(authorization.authorization_id)
    assert again.status == "refunded"
    assert again.settled_at == captured.settled_at


async def test_repeating_a_full_refund_moves_nothing(aibank: AIBankEnv) -> None:
    """AE-08: repetir el reembolso de algo ya devuelto entero es `200` con
    `refunded: 0` -- un reintento por timeout no es un error."""
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    authorization = await aibank.authorize(
        payer_account_id=payer,
        payee_account_id=payee,
        amount=1_000,
        idempotency_key=aibank.key("k"),
    )
    await aibank.api.capture(authorization.authorization_id)
    await aibank.api.refund(authorization.authorization_id)
    again = await aibank.api.refund(authorization.authorization_id)
    assert (again.status, again.refunded, again.refundable) == ("refunded", 0, 0)


async def test_18_opening_the_same_account_twice_returns_it(aibank: AIBankEnv) -> None:
    first = await aibank.api.open_account(owner_reference="test-idempotent-agent-18")
    again = await aibank.api.open_account(owner_reference="test-idempotent-agent-18")
    assert again.account_id == first.account_id
    assert first.account_id.startswith("acc_")


async def test_19_currency_not_enabled(aibank: AIBankEnv) -> None:
    await _expect(
        "currency_mismatch", aibank.api.open_account(owner_reference="test-eur", currency="EUR")
    )


async def test_unknown_authorization(aibank: AIBankEnv) -> None:
    await _expect("authorization_not_found", aibank.api.capture("auth_" + "0" * 32))


# --- Modelo B ---------------------------------------------------------------


async def test_21_full_flow_request_approve_poll_pay_capture(aibank: AIBankEnv) -> None:
    payee = await aibank.funded_account("payee")
    request = await aibank.api.create_consent_request(
        agent_id=(await aibank.default_agent()).agent_id,
        purpose="Pagos del agente de investigación",
        max_per_operation=5_000_000,
        max_total=50_000_000,
    )
    pending = await aibank.api.get_consent_request(request.consent_request_id)
    assert (pending.status, pending.mandate_id, pending.account_id) == ("pending", None, None)

    holder = await aibank.holder()
    await aibank.holders.approve(
        holder,
        request.handoff_code,
        account_id=holder.account_id,
        max_per_operation=5_000_000,
        max_total=50_000_000,
    )
    approved = await aibank.api.get_consent_request(request.consent_request_id)
    # Recién acá Mercatus conoce la cuenta: la eligió el titular. Y la conoce
    # con el id de la API de socio (`acc_`), no con el del canal del titular
    # (AE-06): son dos espacios de identificadores.
    assert approved.status == "approved"
    assert approved.account_id is not None and approved.account_id.startswith("acc_")
    assert approved.account_id != holder.account_id
    assert approved.mandate_id is not None

    authorization = await aibank.authorize(
        payer_account_id=approved.account_id,
        payee_account_id=payee,
        amount=1_000,
        idempotency_key=aibank.key("cart_b"),
        mandate_id=approved.mandate_id,
    )
    captured = await aibank.api.capture(authorization.authorization_id)
    assert captured.status == "captured"


async def test_22_consent_without_purpose_is_malformed(aibank: AIBankEnv) -> None:
    await _expect(
        "malformed_request",
        aibank.api.create_consent_request(
            agent_id=(await aibank.default_agent()).agent_id, purpose="", max_total=1_000
        ),
    )


async def test_23_over_the_per_operation_limit(aibank: AIBankEnv) -> None:
    payee = await aibank.funded_account("payee")
    mandate, _ = await aibank.mandate(max_per_operation=1_000, max_total=10_000)
    error = await _expect(
        "mandate_limit_exceeded",
        aibank.authorize(
            payer_account_id=mandate.account_id,
            payee_account_id=payee,
            amount=2_000,
            idempotency_key=aibank.key("k"),
            mandate_id=mandate.mandate_id,
        ),
    )
    # 422 y no 402: hay saldo, lo que falta es permiso.
    assert error.status == 422


async def test_over_the_total_limit_counts_live_holds(aibank: AIBankEnv) -> None:
    payee = await aibank.funded_account("payee")
    mandate, _ = await aibank.mandate(max_per_operation=1_000, max_total=2_000)
    for label in ("a", "b"):  # dos retenciones SIN capturar ya consumen el tope
        await aibank.authorize(
            payer_account_id=mandate.account_id,
            payee_account_id=payee,
            amount=1_000,
            idempotency_key=aibank.key(label),
            mandate_id=mandate.mandate_id,
        )
    await _expect(
        "mandate_limit_exceeded",
        aibank.authorize(
            payer_account_id=mandate.account_id,
            payee_account_id=payee,
            amount=1_000,
            idempotency_key=aibank.key("c"),
            mandate_id=mandate.mandate_id,
        ),
    )


async def test_mandate_limit_and_missing_funds_are_different_errors(aibank: AIBankEnv) -> None:
    payee = await aibank.funded_account("payee")
    mandate, _ = await aibank.mandate(holder_balance=500)
    await _expect(
        "insufficient_funds",
        aibank.authorize(
            payer_account_id=mandate.account_id,
            payee_account_id=payee,
            amount=1_000,
            idempotency_key=aibank.key("k"),
            mandate_id=mandate.mandate_id,
        ),
    )


async def test_titular_can_grant_less_but_never_more(aibank: AIBankEnv) -> None:
    lower, _ = await aibank.mandate(max_total=10_000, granted_total=4_000)
    assert (lower.max_total, lower.remaining) == (4_000, 4_000)

    request = await aibank.api.create_consent_request(
        agent_id=(await aibank.default_agent()).agent_id,
        purpose="x",
        max_per_operation=1_000,
        max_total=10_000,
    )
    holder = await aibank.holder()
    await _expect(
        "limit_above_requested",
        aibank.holders.approve(
            holder,
            request.handoff_code,
            account_id=holder.account_id,
            max_per_operation=1_000,
            max_total=20_000,
        ),
    )
    # Sin tope concedido = sin tope: también excede lo pedido.
    await _expect(
        "limit_above_requested",
        aibank.holders.approve(
            holder,
            request.handoff_code,
            account_id=holder.account_id,
            max_per_operation=1_000,
            max_total=None,
        ),
    )


async def test_rejected_request_never_becomes_a_mandate(aibank: AIBankEnv) -> None:
    request = await aibank.api.create_consent_request(
        agent_id=(await aibank.default_agent()).agent_id, purpose="x", max_total=10_000
    )
    holder = await aibank.holder()
    await aibank.holders.reject(holder, request.handoff_code)

    rejected = await aibank.api.get_consent_request(request.consent_request_id)
    assert (rejected.status, rejected.mandate_id) == ("rejected", None)
    await _expect(
        "already_resolved",
        aibank.holders.approve(
            holder,
            request.handoff_code,
            account_id=holder.account_id,
            max_per_operation=None,
            max_total=10_000,
        ),
    )


async def test_titular_cannot_grant_over_someone_elses_account(aibank: AIBankEnv) -> None:
    request = await aibank.api.create_consent_request(
        agent_id=(await aibank.default_agent()).agent_id, purpose="x", max_total=10_000
    )
    ana, beto = await aibank.holder(), await aibank.holder()
    await _expect(
        "not_found",
        aibank.holders.approve(
            ana,
            request.handoff_code,
            account_id=beto.account_id,
            max_per_operation=None,
            max_total=10_000,
        ),
    )


async def test_revocation_blocks_new_payments_but_not_live_holds(aibank: AIBankEnv) -> None:
    payee = await aibank.funded_account("payee")
    mandate, holder = await aibank.mandate()
    live = await aibank.authorize(
        payer_account_id=mandate.account_id,
        payee_account_id=payee,
        amount=1_000,
        idempotency_key=aibank.key("live"),
        mandate_id=mandate.mandate_id,
    )
    await aibank.holders.revoke(holder, mandate.mandate_id)

    revoked = await aibank.api.get_mandate(mandate.mandate_id)
    assert revoked.status == "revoked"
    assert revoked.revoked_at is not None
    error = await _expect(
        "mandate_revoked",
        aibank.authorize(
            payer_account_id=mandate.account_id,
            payee_account_id=payee,
            amount=1_000,
            idempotency_key=aibank.key("after"),
            mandate_id=mandate.mandate_id,
        ),
    )
    assert error.status == 403
    # Del otro lado puede haber un vendedor que ya entregó (doc 13 §4).
    assert (await aibank.api.capture(live.authorization_id)).status == "captured"


async def test_declared_payer_must_match_the_mandate(aibank: AIBankEnv) -> None:
    payee = await aibank.funded_account("payee")
    mandate, _ = await aibank.mandate()
    other = await aibank.holder()
    await _expect(
        "mandate_account_not_covered",
        aibank.authorize(
            payer_account_id=other.account_id,
            payee_account_id=payee,
            amount=1_000,
            idempotency_key=aibank.key("k"),
            mandate_id=mandate.mandate_id,
        ),
    )


async def test_unknown_mandate(aibank: AIBankEnv) -> None:
    await _expect(
        "mandate_not_found", aibank.api.get_mandate("00000000-0000-0000-0000-000000000000")
    )


async def test_consumed_and_remaining_follow_captures_and_refunds(aibank: AIBankEnv) -> None:
    payee = await aibank.funded_account("payee")
    mandate, _ = await aibank.mandate(max_per_operation=10_000, max_total=50_000)
    authorization = await aibank.authorize(
        payer_account_id=mandate.account_id,
        payee_account_id=payee,
        amount=10_000,
        idempotency_key=aibank.key("k"),
        mandate_id=mandate.mandate_id,
    )
    await aibank.api.capture(authorization.authorization_id)
    after_capture = await aibank.api.get_mandate(mandate.mandate_id)
    assert (after_capture.consumed, after_capture.remaining) == (10_000, 40_000)

    await aibank.api.refund(authorization.authorization_id, amount=4_000)
    after_refund = await aibank.api.get_mandate(mandate.mandate_id)
    assert (after_refund.consumed, after_refund.remaining) == (6_000, 44_000)


async def test_capturing_and_refunding_on_the_customers_account(aibank: AIBankEnv) -> None:
    """En el modelo B el pagador NO es de la integración: igual puede
    capturar y reembolsar porque el receptor sí lo es (`resolveOwnedAuthorization`)."""
    payee = await aibank.funded_account("payee")
    mandate, _ = await aibank.mandate()
    authorization = await aibank.authorize(
        payer_account_id=mandate.account_id,
        payee_account_id=payee,
        amount=1_000,
        idempotency_key=aibank.key("k"),
        mandate_id=mandate.mandate_id,
    )
    await aibank.api.capture(authorization.authorization_id)
    assert (await aibank.api.refund(authorization.authorization_id)).status == "refunded"


async def test_the_payee_of_a_mandate_payment_must_be_ours(aibank: AIBankEnv) -> None:
    """Un mandato autoriza a sacar dinero de la cuenta del titular, nunca a
    elegir dónde termina: el receptor tiene que ser de la integración."""
    mandate, _ = await aibank.mandate()
    stranger = await aibank.holder()
    await _expect(
        "account_not_found",
        aibank.authorize(
            payer_account_id=mandate.account_id,
            payee_account_id=stranger.account_id,
            amount=1_000,
            idempotency_key=aibank.key("k"),
            mandate_id=mandate.mandate_id,
        ),
    )


# --- Contrato 1.1: identidad del agente (AE-10/AE-11) -----------------------


async def test_a_payment_signed_by_another_agent_cannot_use_the_account(aibank: AIBankEnv) -> None:
    """Modelo A: la sub-cuenta es de un agente; firmar con otro es
    `403 account_agent_scope`."""
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    intruder = await aibank.agent("Otro agente")
    error = await _expect(
        "account_agent_scope",
        aibank.authorize(
            payer_account_id=payer, payee_account_id=payee, amount=1_000, idempotency_key=aibank.key(), agent=intruder
        ),
    )
    assert error.status == 403


async def test_a_seller_account_without_agent_collects_but_cannot_pay(aibank: AIBankEnv) -> None:
    seller, buyer = await aibank.seller_account(), await aibank.funded_account("buyer")
    paid = await aibank.authorize(payer_account_id=buyer, payee_account_id=seller, amount=1_000, idempotency_key=aibank.key())
    assert paid.status == "authorized"
    await _expect(
        "account_agent_scope",
        aibank.authorize(payer_account_id=seller, payee_account_id=buyer, amount=1, idempotency_key=aibank.key()),
    )


async def test_the_body_agent_must_own_the_signing_key(aibank: AIBankEnv) -> None:
    """Sin la firma, `agent_id` sería solo lo que dice la plataforma: firmar
    con la clave de B un pago que dice ser de A es `401 agent_signature_invalid`."""
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    a, b = await aibank.default_agent(), await aibank.agent("Agente B")
    impostor = AgentIdentity(agent_id=a.agent_id, key_id=b.key_id, private_key=b.private_key)
    error = await _expect(
        "agent_signature_invalid",
        aibank.authorize(
            payer_account_id=payer, payee_account_id=payee, amount=1_000, idempotency_key=aibank.key(), agent=impostor
        ),
    )
    assert error.status == 401


async def test_a_key_the_bank_never_saw_is_rejected(aibank: AIBankEnv) -> None:
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    a = await aibank.default_agent()
    forged = AgentIdentity(agent_id=a.agent_id, key_id=a.key_id, private_key=generate_agent_key())
    await _expect(
        "agent_signature_invalid",
        aibank.authorize(
            payer_account_id=payer, payee_account_id=payee, amount=1_000, idempotency_key=aibank.key(), agent=forged
        ),
    )


async def test_the_intent_is_validated(aibank: AIBankEnv) -> None:
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    await _expect(
        "malformed_request",
        aibank.authorize(
            payer_account_id=payer,
            payee_account_id=payee,
            amount=1_000,
            idempotency_key=aibank.key(),
            intent=Intent(reference=aibank.key(), description="x" * 141),
        ),
    )


async def test_a_consent_request_needs_an_agent(aibank: AIBankEnv) -> None:
    await _expect("malformed_request", aibank.api.create_consent_request(agent_id="", purpose="x", max_total=1_000))


async def test_a_mandate_only_serves_its_own_agent(aibank: AIBankEnv) -> None:
    payee = await aibank.funded_account("payee")
    mandate, _ = await aibank.mandate()
    other = await aibank.agent("Agente de compras")
    error = await _expect(
        "mandate_agent_scope",
        aibank.authorize(
            payer_account_id=mandate.account_id,
            payee_account_id=payee,
            amount=1_000,
            idempotency_key=aibank.key(),
            mandate_id=mandate.mandate_id,
            agent=other,
        ),
    )
    assert error.status == 403


async def test_rotating_a_key_keeps_the_agent_and_its_accounts(aibank: AIBankEnv) -> None:
    """AE-11: rotar no da de baja al agente ni toca sus permisos; las dos
    claves valen hasta retirar la vieja, y la última viva no se retira."""
    payer, payee = await aibank.funded_account("payer"), await aibank.funded_account("payee")
    old = await aibank.default_agent()
    new_private = generate_agent_key()
    new_key = await aibank.api.add_agent_key(old.agent_id, public_key=public_jwk(new_private))
    new = AgentIdentity(agent_id=old.agent_id, key_id=new_key.key_id, private_key=new_private)

    for identity in (old, new):  # durante la rotación valen las dos
        await aibank.authorize(
            payer_account_id=payer, payee_account_id=payee, amount=1_000, idempotency_key=aibank.key(), agent=identity
        )
    await aibank.api.retire_agent_key(old.agent_id, old.key_id)
    await _expect(
        "agent_signature_invalid",
        aibank.authorize(
            payer_account_id=payer, payee_account_id=payee, amount=1_000, idempotency_key=aibank.key(), agent=old
        ),
    )
    await aibank.authorize(
        payer_account_id=payer, payee_account_id=payee, amount=1_000, idempotency_key=aibank.key(), agent=new
    )
    await _expect("agent_last_key", aibank.api.retire_agent_key(new.agent_id, new.key_id))


async def test_a_revoked_agent_can_no_longer_pay_or_ask(aibank: AIBankEnv) -> None:
    agent = await aibank.agent("Agente que se da de baja")
    payer = await aibank.funded_account("payer", agent=agent)
    payee = await aibank.funded_account("payee")
    await aibank.api.revoke_agent(agent.agent_id)

    assert (await aibank.api.get_agent(agent.agent_id)).status == "revoked"
    await _expect(
        "agent_signature_invalid",
        aibank.authorize(
            payer_account_id=payer, payee_account_id=payee, amount=1_000, idempotency_key=aibank.key(), agent=agent
        ),
    )
    await _expect(
        "agent_revoked", aibank.api.create_consent_request(agent_id=agent.agent_id, purpose="x", max_total=1_000)
    )


async def test_an_account_belongs_to_one_agent(aibank: AIBankEnv) -> None:
    owner = f"test-bound-{aibank.key()}"
    a, b = await aibank.default_agent(), await aibank.agent("Agente B")
    await aibank.api.open_account(owner_reference=owner, agent_id=a.agent_id)
    again = await aibank.api.open_account(owner_reference=owner, agent_id=a.agent_id)  # repetir no es error
    assert again.account_id.startswith("acc_")
    await _expect("account_agent_conflict", aibank.api.open_account(owner_reference=owner, agent_id=b.agent_id))


async def test_an_agent_is_registered_with_its_key(aibank: AIBankEnv) -> None:
    agent = await aibank.default_agent()
    registered = await aibank.api.get_agent(agent.agent_id)
    assert registered.agent_id.startswith("agt_")
    assert registered.status == "active"
    assert [k.key_id for k in registered.keys] == [agent.key_id]
    assert registered.keys[0].key_id.startswith("key_")
