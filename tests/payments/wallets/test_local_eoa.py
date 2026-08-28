from __future__ import annotations

from agent_commerce.payments.wallets.local_eoa import LocalEoaSigner


def test_local_eoa_signer_has_valid_checksum_address() -> None:
    signer = LocalEoaSigner()
    assert signer.address.startswith("0x")
    assert len(signer.address) == 42


def test_local_eoa_signer_is_deterministic_from_private_key() -> None:
    key = "0x" + "11" * 32
    signer_a = LocalEoaSigner(private_key=key)
    signer_b = LocalEoaSigner(private_key=key)
    assert signer_a.address == signer_b.address


def test_local_eoa_signer_sign_message_recovers_to_its_own_address() -> None:
    from eth_account import Account
    from eth_account.messages import encode_defunct

    signer = LocalEoaSigner()
    message = b"hola agentic commerce"
    signature = signer.sign_message(message)

    recovered = Account.recover_message(encode_defunct(primitive=message), signature=signature)
    assert recovered.lower() == signer.address.lower()
