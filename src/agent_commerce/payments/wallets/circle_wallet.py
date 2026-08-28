"""Adaptador OPCIONAL de wallet: custodia vía Circle Developer-Controlled Wallets.

Implementa el mismo puerto `WalletSigner` que `local_eoa.py`. El paquete
base de `agent_commerce` no depende de `circle-developer-controlled-wallets`
-- por eso todo import del SDK de Circle aquí es perezoso (dentro de
`__init__`), y solo falla si de verdad se pide `wallet_backend=circle` sin
tener instalado el extra `agent-commerce[circle]`.

Nota de verificación pendiente (ver docs/roadmap.md, RM-06): el nombre exacto
del método de firma EIP-712 tipada en `circle.web3.developer_controlled_wallets`
no se pudo confirmar sin credenciales reales de Circle. El candidato más
plausible, usado abajo, es `SignatureApi.sign_typed_data` con un
`SignTypedDataForDeveloperRequest`; si el SDK instalado difiere, esta es la
única función que hay que ajustar -- el resto del framework no cambia,
porque todo lo demás programa contra `WalletSigner`, no contra Circle.
"""

from __future__ import annotations

import json
from typing import Any


class CircleWalletSigner:
    """Firma EIP-712/EIP-191 delegando la custodia de la clave a un wallet
    developer-controlled de Circle, en vez de guardar una clave privada en
    el proceso de `agent_commerce`.
    """

    def __init__(self, *, wallet_id: str, api_key: str, entity_secret: str) -> None:
        try:
            from circle.web3 import developer_controlled_wallets as circle_dcw
            from circle.web3 import utils as circle_utils
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ImportError(
                "El backend de wallet 'circle' requiere el extra opcional: "
                "pip install 'agent-commerce[circle]'"
            ) from exc

        self._wallet_id = wallet_id
        self._client = circle_utils.init_developer_controlled_wallets_client(
            api_key=api_key, entity_secret=entity_secret
        )
        self._wallets_api = circle_dcw.WalletsApi(self._client)
        self._signature_api = circle_dcw.SignatureApi(self._client)
        self._sign_request_cls = circle_dcw.SignTypedDataForDeveloperRequest
        self._address: str | None = None

    @property
    def address(self) -> str:
        if self._address is None:
            wallet = self._wallets_api.get_wallet(id=self._wallet_id).data.wallet
            self._address = wallet.address
        return self._address

    def sign_typed_data(
        self,
        domain: Any,
        types: dict[str, list[Any]],
        primary_type: str,
        message: dict[str, Any],
    ) -> bytes:
        domain_dict = domain if isinstance(domain, dict) else _domain_to_dict(domain)
        types_dict = {
            name: [_field_to_dict(f) for f in fields] for name, fields in types.items()
        }
        typed_data = {
            "types": {"EIP712Domain": _domain_type_fields(domain_dict), **types_dict},
            "primaryType": primary_type,
            "domain": domain_dict,
            "message": _hex_encode_bytes(message),
        }
        request = self._sign_request_cls(
            wallet_id=self._wallet_id, data=json.dumps(typed_data)
        )
        response = self._signature_api.sign_typed_data_for_developer(request)
        return bytes.fromhex(response.data.signature.removeprefix("0x"))

    def sign_message(self, message: bytes) -> bytes:
        raise NotImplementedError(
            "CircleWalletSigner.sign_message (EIP-191) aun no esta verificado contra el "
            "SDK real de Circle -- necesario solo para el adaptador AP2 en modo testnet "
            "con wallet_backend=circle. Ver docs/roadmap.md RM-06."
        )


def _domain_to_dict(domain: Any) -> dict[str, Any]:
    return {
        "name": domain.name,
        "version": domain.version,
        "chainId": domain.chain_id,
        "verifyingContract": domain.verifying_contract,
    }


def _domain_type_fields(domain_dict: dict[str, Any]) -> list[dict[str, str]]:
    field_types = {
        "name": "string",
        "version": "string",
        "chainId": "uint256",
        "verifyingContract": "address",
    }
    return [{"name": k, "type": field_types[k]} for k in domain_dict if k in field_types]


def _field_to_dict(field: Any) -> dict[str, str]:
    return field if isinstance(field, dict) else {"name": field.name, "type": field.type}


def _hex_encode_bytes(message: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (f"0x{value.hex()}" if isinstance(value, bytes | bytearray) else value)
        for key, value in message.items()
    }
