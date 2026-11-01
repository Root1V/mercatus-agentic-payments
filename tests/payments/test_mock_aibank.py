"""Escenarios del contrato que necesitan controles que solo tiene `MockAIBank`
-- reloj, congelar una cuenta, una segunda integración, scopes -- y la
conversión a micras. El resto del contrato está en `test_aibank_contract.py`,
que corre contra cualquier implementación del puerto."""

from __future__ import annotations

from decimal import Decimal

import pytest

from agent_commerce.payments.aibank_api import (
    SCOPE_PAYMENTS_READ,
    AIBankError,
    micros_to_usd,
    usd_to_micros,
)
from agent_commerce.payments.mock_aibank import (
    AUTHORIZATION_TTL_SECONDS,
    CONSENT_REQUEST_TTL_SECONDS,
    MockAIBank,
)
from tests.payments.aibank_env import AIBankEnv


class _Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def _env(bank: MockAIBank, client_id: str = "mercatus_test", **kwargs: object) -> AIBankEnv:
    secret = bank.register_integration(client_id, **kwargs)  # type: ignore[arg-type]
    return AIBankEnv(api=bank.client(client_id, secret), holders=bank.holder_channel())


async def test_07_an_uncaptured_hold_expires_and_the_money_returns() -> None:
    clock = _Clock()
    bank = MockAIBank(clock=clock)
    env = _env(bank)
    payer, payee = (
        await env.funded_account("payer", balance=5_000),
        await env.funded_account("payee"),
    )
    authorization = await env.authorize(
        payer_account_id=payer, payee_account_id=payee, amount=1_000, idempotency_key="k"
    )
    assert bank.available_balance(payer) == 4_000  # retenido, no movido

    clock.now += AUTHORIZATION_TTL_SECONDS + 1
    # Venció y el barrendero todavía no la liberó (AE-14).
    with pytest.raises(AIBankError, match="authorization_expired"):
        await env.api.capture(authorization.authorization_id)
    # Ya liberada, sin cobrarse nunca: el dinero volvió al pagador.
    assert (await env.api.get_authorization(authorization.authorization_id)).status == "expired"
    assert bank.available_balance(payer) == 5_000
    with pytest.raises(AIBankError, match="authorization_not_capturable"):
        await env.api.capture(authorization.authorization_id)


async def test_13_another_integrations_account_looks_nonexistent() -> None:
    bank = MockAIBank()
    ours, theirs = _env(bank, "mercatus"), _env(bank, "otra_plataforma")
    payee = await ours.funded_account("payee")
    foreign = await theirs.funded_account("foreign")
    authorization = await theirs.authorize(
        payer_account_id=foreign,
        payee_account_id=await theirs.funded_account("x"),
        amount=1,
        idempotency_key="k",
    )

    with pytest.raises(AIBankError, match="account_not_found"):
        await ours.authorize(
            payer_account_id=foreign, payee_account_id=payee, amount=1, idempotency_key="k"
        )
    # Ni confirmar ni negar: una autorización ajena responde como inexistente.
    with pytest.raises(AIBankError, match="authorization_not_found"):
        await ours.api.get_authorization(authorization.authorization_id)


async def test_the_same_idempotency_key_in_two_integrations_are_different_payments() -> None:
    bank = MockAIBank()
    a, b = _env(bank, "a"), _env(bank, "b")
    first = await a.authorize(
        payer_account_id=await a.funded_account(),
        payee_account_id=await a.funded_account(),
        amount=1,
        idempotency_key="cart_1",
    )
    second = await b.authorize(
        payer_account_id=await b.funded_account(),
        payee_account_id=await b.funded_account(),
        amount=1,
        idempotency_key="cart_1",
    )
    assert not second.replayed
    assert second.authorization_id != first.authorization_id


async def test_14_read_only_token_cannot_authorize() -> None:
    bank = MockAIBank()
    writer = _env(bank, "mercatus")
    payer, payee = await writer.funded_account(), await writer.funded_account()
    secret = bank.register_integration("mercatus_lectura", scopes=[SCOPE_PAYMENTS_READ])
    reader = bank.client("mercatus_lectura", secret)
    with pytest.raises(AIBankError, match="insufficient_scope") as excinfo:
        await reader.authorize(
            payer_account_id=payer,
            payee_account_id=payee,
            amount=1,
            idempotency_key="k",
            agent=await writer.default_agent(),
            intent=writer.intent(),
        )
    assert excinfo.value.status == 403


async def test_wrong_secret_is_invalid_credential() -> None:
    bank = MockAIBank()
    bank.register_integration("mercatus")
    with pytest.raises(AIBankError, match="invalid_credential") as excinfo:
        await bank.client("mercatus", "secreto-equivocado").open_account(owner_reference="x")
    assert excinfo.value.status == 401


async def test_frozen_account_rejects_movements() -> None:
    bank = MockAIBank()
    env = _env(bank)
    payer, payee = await env.funded_account(), await env.funded_account()
    bank.freeze_account(payer)
    with pytest.raises(AIBankError, match="account_frozen"):
        await env.authorize(
            payer_account_id=payer, payee_account_id=payee, amount=1, idempotency_key="k"
        )


async def test_a_pending_consent_request_expires_after_an_hour() -> None:
    clock = _Clock()
    bank = MockAIBank(clock=clock)
    env = _env(bank)
    request = await env.api.create_consent_request(
        agent_id=(await env.default_agent()).agent_id, purpose="x", max_total=1_000
    )
    clock.now += CONSENT_REQUEST_TTL_SECONDS + 1

    assert (await env.api.get_consent_request(request.consent_request_id)).status == "expired"
    holder = await env.holder()
    with pytest.raises(AIBankError, match="expired"):
        await env.holders.approve(
            holder,
            request.handoff_code,
            account_id=holder.account_id,
            max_per_operation=None,
            max_total=1_000,
        )


async def test_an_expired_mandate_stops_paying() -> None:
    clock = _Clock()
    bank = MockAIBank(clock=clock)
    env = _env(bank)
    payee = await env.funded_account("payee")
    mandate, _ = await env.mandate()
    clock.now += 31 * 86400  # el titular lo concedió por 30 días

    assert (await env.api.get_mandate(mandate.mandate_id)).status == "expired"
    with pytest.raises(AIBankError, match="mandate_expired"):
        await env.authorize(
            payer_account_id=mandate.account_id,
            payee_account_id=payee,
            amount=1_000,
            idempotency_key="k",
            mandate_id=mandate.mandate_id,
        )


async def test_another_integration_cannot_see_or_use_our_mandate() -> None:
    bank = MockAIBank()
    ours, theirs = _env(bank, "mercatus"), _env(bank, "otra_plataforma")
    mandate, _ = await ours.mandate()
    with pytest.raises(AIBankError, match="mandate_not_found"):
        await theirs.api.get_mandate(mandate.mandate_id)
    with pytest.raises(AIBankError, match="mandate_not_found"):
        await theirs.authorize(
            payer_account_id=mandate.account_id,
            payee_account_id=await theirs.funded_account(),
            amount=1_000,
            idempotency_key="k",
            mandate_id=mandate.mandate_id,
        )


@pytest.mark.parametrize(
    ("usd", "micros"),
    [("0.001", 1_000), ("$1", 1_000_000), (Decimal("0.000001"), 1), ("10", 10_000_000), ("0", 0)],
)
def test_usd_to_micros_is_exact(usd: str | Decimal, micros: int) -> None:
    assert usd_to_micros(usd) == micros


@pytest.mark.parametrize("usd", ["0.0000001", "1.2345678", "abc", "NaN"])
def test_usd_to_micros_rejects_instead_of_rounding(usd: str) -> None:
    with pytest.raises(ValueError):
        usd_to_micros(usd)


@pytest.mark.parametrize(
    ("micros", "usd"), [(1_000, "0.001"), (10_000_000, "10"), (0, "0"), (2_500_000, "2.5")]
)
def test_micros_to_usd_is_exact_and_readable(micros: int, usd: str) -> None:
    assert str(micros_to_usd(micros)) == usd
