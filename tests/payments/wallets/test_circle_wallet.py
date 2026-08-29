"""Tests de `CircleWalletSigner` contra los tipos reales del SDK instalado
(`agent-commerce[circle]`) -- se mockean solo las llamadas de red
(`WalletsApi`/`SigningApi`/`generate_entity_secret_ciphertext`), nunca los
modelos pydantic de request/response, para que un cambio de forma en el SDK
real rompa estos tests en vez de pasar en silencio. Sin credenciales reales
de Circle: eso queda documentado como pendiente en el propio módulo (RM-06).

Si el extra `circle` no está instalado, estos tests se saltan (no fallan) --
es opcional, igual que en el resto del framework.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

circle_dcw = pytest.importorskip("circle.web3.developer_controlled_wallets")
circle_utils = pytest.importorskip("circle.web3.utils")

from agent_commerce.payments.wallets.circle_wallet import CircleWalletSigner

_WALLET_ADDRESS = "0xAbC1230000000000000000000000000000dEaD"
_SIGNATURE_HEX = "0x" + "11" * 65


class _FakeWalletsApi:
    def __init__(self) -> None:
        self.get_wallet_calls: list[str] = []

    def get_wallet(self, *, id: str):
        self.get_wallet_calls.append(id)
        # `WalletResponseData.wallet` es un wrapper `oneOf` (`WalletsDataWalletsInner`)
        # sobre `EOAWallet`/`SCAWallet`, no un `Wallet` plano -- se envuelve la
        # instancia concreta como `actual_instance`.
        wallet = circle_dcw.EOAWallet(
            id=id,
            address=_WALLET_ADDRESS,
            blockchain=circle_dcw.Blockchain.BASE_MINUS_SEPOLIA,
            create_date=datetime.now(UTC),
            update_date=datetime.now(UTC),
            custody_type=circle_dcw.CustodyType.DEVELOPER,
            state=circle_dcw.WalletState.LIVE,
            wallet_set_id="wallet-set-1",
            account_type=circle_dcw.AccountType.EOA,
        )
        wrapped = circle_dcw.WalletsDataWalletsInner(wallet)
        return circle_dcw.WalletResponse(data=circle_dcw.WalletResponseData(wallet=wrapped))


class _FakeSigningApi:
    def __init__(self) -> None:
        self.typed_data_requests: list[object] = []
        self.message_requests: list[object] = []

    def sign_typed_data(self, request: object):
        self.typed_data_requests.append(request)
        return circle_dcw.SignatureResponse(
            data=circle_dcw.SignatureResponseData(signature=_SIGNATURE_HEX)
        )

    def sign_message(self, request: object):
        self.message_requests.append(request)
        return circle_dcw.SignatureResponse(
            data=circle_dcw.SignatureResponseData(signature=_SIGNATURE_HEX)
        )


@pytest.fixture
def signer(monkeypatch: pytest.MonkeyPatch) -> tuple[CircleWalletSigner, _FakeWalletsApi, _FakeSigningApi, list[str]]:
    fake_wallets_api = _FakeWalletsApi()
    fake_signing_api = _FakeSigningApi()
    ciphertexts_generated: list[str] = []

    def fake_generate_ciphertext(api_key: str, entity_secret_hex: str) -> str:
        ciphertext = f"ciphertext-{len(ciphertexts_generated)}"
        ciphertexts_generated.append(ciphertext)
        return ciphertext

    monkeypatch.setattr(
        circle_utils, "init_developer_controlled_wallets_client", lambda **kwargs: object()
    )
    monkeypatch.setattr(circle_utils, "generate_entity_secret_ciphertext", fake_generate_ciphertext)
    monkeypatch.setattr(circle_dcw, "WalletsApi", lambda client: fake_wallets_api)
    monkeypatch.setattr(circle_dcw, "SigningApi", lambda client: fake_signing_api)

    instance = CircleWalletSigner(wallet_id="wallet-1", api_key="test-api-key", entity_secret="a" * 64)
    return instance, fake_wallets_api, fake_signing_api, ciphertexts_generated


def test_address_fetches_wallet_once_and_caches(signer) -> None:
    instance, fake_wallets_api, _, _ = signer

    assert instance.address == _WALLET_ADDRESS
    assert instance.address == _WALLET_ADDRESS
    assert fake_wallets_api.get_wallet_calls == ["wallet-1"]


def test_sign_typed_data_builds_correct_request(signer) -> None:
    instance, _, fake_signing_api, ciphertexts = signer

    domain = {"name": "AgentCommerce", "version": "1", "chainId": 84532, "verifyingContract": "0x0"}
    types = {"Payment": [{"name": "amount", "type": "uint256"}]}
    message = {"amount": b"\x01\x02"}

    signature = instance.sign_typed_data(domain, types, "Payment", message)

    assert signature == bytes.fromhex(_SIGNATURE_HEX.removeprefix("0x"))
    assert len(fake_signing_api.typed_data_requests) == 1
    request = fake_signing_api.typed_data_requests[0]
    assert request.wallet_id == "wallet-1"
    assert request.entity_secret_ciphertext == ciphertexts[0]

    typed_data = json.loads(request.data)
    assert typed_data["primaryType"] == "Payment"
    assert typed_data["domain"] == domain
    assert typed_data["types"]["Payment"] == types["Payment"]
    assert "EIP712Domain" in typed_data["types"]
    assert typed_data["message"]["amount"] == "0x0102"  # bytes -> hex en el payload


def test_sign_message_builds_correct_request(signer) -> None:
    instance, _, fake_signing_api, ciphertexts = signer

    signature = instance.sign_message(b"hello")

    assert signature == bytes.fromhex(_SIGNATURE_HEX.removeprefix("0x"))
    assert len(fake_signing_api.message_requests) == 1
    request = fake_signing_api.message_requests[0]
    assert request.wallet_id == "wallet-1"
    assert request.message == "0x68656c6c6f"
    assert request.encoded_by_hex is True
    assert request.entity_secret_ciphertext == ciphertexts[0]


def test_entity_secret_ciphertext_is_regenerated_on_every_call(signer) -> None:
    """Circle exige que `entity_secret_ciphertext` sea distinto en cada
    request -- si se cacheara, las llamadas de firma reales fallarían."""
    instance, _, fake_signing_api, ciphertexts = signer

    instance.sign_message(b"first")
    instance.sign_message(b"second")

    assert len(ciphertexts) == 2
    assert ciphertexts[0] != ciphertexts[1]
    assert fake_signing_api.message_requests[0].entity_secret_ciphertext == ciphertexts[0]
    assert fake_signing_api.message_requests[1].entity_secret_ciphertext == ciphertexts[1]


def test_missing_circle_extra_raises_clear_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins
    from collections.abc import Mapping, Sequence

    real_import = builtins.__import__

    def blocking_import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] | None = (),
        level: int = 0,
    ) -> object:
        if name == "circle" or name.startswith("circle."):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocking_import)

    with pytest.raises(ImportError, match="agent-commerce\\[circle\\]"):
        CircleWalletSigner(wallet_id="w", api_key="k", entity_secret="a" * 64)
