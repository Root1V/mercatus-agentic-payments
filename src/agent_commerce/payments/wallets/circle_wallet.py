"""Adaptador OPCIONAL de wallet: custodia vía Circle Developer-Controlled Wallets.

Implementa el mismo puerto `WalletSigner` que `local_eoa.py`. El paquete
base de `agent_commerce` no depende de `circle-developer-controlled-wallets`
-- por eso todo import del SDK de Circle aquí es perezoso (dentro de
`__init__`), y solo falla si de verdad se pide `wallet_backend=circle` sin
tener instalado el extra `agent-commerce[circle]`.

Verificado contra el SDK real instalado (`circle-developer-controlled-wallets`
9.6.0, ver docs/roadmap.md RM-06) inspeccionando su código fuente -- no
requiere credenciales para eso, solo el paquete instalado. Tres cosas que la
implementación anterior asumía mal:

1. La clase es `SigningApi` (no `SignatureApi`), y sus métodos son
   `sign_typed_data`/`sign_message` (no `..._for_developer` -- ese sufijo no
   existe en esta versión del SDK).
2. El request de EIP-712 es `SignTypedDataRequest` (no
   `SignTypedDataForDeveloperRequest`, que no existe).
3. Ambos requests (`SignTypedDataRequest` y `SignMessageRequest`) exigen un
   campo `entity_secret_ciphertext` -- el entity secret RSA-cifrado con la
   clave pública de Circle, que Circle exige que sea *distinto en cada
   request* (no se puede cachear ni reusar). Se genera con
   `circle_utils.generate_entity_secret_ciphertext(api_key, entity_secret_hex)`,
   que internamente pide la clave pública de Circle (con caché de proceso, así
   que solo la primera llamada hace red) y cifra localmente -- por eso hay que
   guardar `api_key`/`entity_secret` en la instancia, no solo pasarlos una vez
   al construir el cliente.

`entity_secret` debe ser el string hex de 64 caracteres (32 bytes) que Circle
entrega al configurar el entity secret de la cuenta -- no un secreto
arbitrario.
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

            # `circle.web3.__init__` no reexporta `utils` y el paquete no trae
            # `py.typed` -- el import funciona en runtime (Python resuelve el
            # submódulo directo), pero mypy lo analiza igual y no lo detecta.
            from circle.web3 import utils as circle_utils  # type: ignore[attr-defined]
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ImportError(
                "El backend de wallet 'circle' requiere el extra opcional: "
                "pip install 'agent-commerce[circle]'"
            ) from exc

        self._wallet_id = wallet_id
        # Se guardan para regenerar entity_secret_ciphertext en cada firma
        # (Circle lo exige único por request, ver nota del módulo).
        self._api_key = api_key
        self._entity_secret = entity_secret
        self._generate_ciphertext = circle_utils.generate_entity_secret_ciphertext

        self._client = circle_utils.init_developer_controlled_wallets_client(
            api_key=api_key, entity_secret=entity_secret
        )
        self._wallets_api = circle_dcw.WalletsApi(self._client)
        self._signing_api = circle_dcw.SigningApi(self._client)
        self._sign_typed_data_request_cls = circle_dcw.SignTypedDataRequest
        self._sign_message_request_cls = circle_dcw.SignMessageRequest
        self._address: str | None = None

    @property
    def address(self) -> str:
        if self._address is None:
            wallet = self._wallets_api.get_wallet(id=self._wallet_id).data.wallet
            self._address = wallet.address
        return self._address

    def _ciphertext(self) -> str:
        return self._generate_ciphertext(self._api_key, self._entity_secret)

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
        request = self._sign_typed_data_request_cls(
            wallet_id=self._wallet_id,
            data=json.dumps(typed_data),
            entity_secret_ciphertext=self._ciphertext(),
        )
        response = self._signing_api.sign_typed_data(request)
        return bytes.fromhex(response.data.signature.removeprefix("0x"))

    def sign_message(self, message: bytes) -> bytes:
        # `encoded_by_hex=True` + mensaje como hex "0x..." evita cualquier
        # ambigüedad de encoding con datos binarios arbitrarios (p. ej. el
        # JSON canónico de un mandato AP2). El endpoint de Circle aplica el
        # prefijo EIP-191 ("\x19Ethereum Signed Message:\n<len>") del lado
        # del servidor -- no hace falta agregarlo acá.
        request = self._sign_message_request_cls(
            wallet_id=self._wallet_id,
            message=f"0x{message.hex()}",
            encoded_by_hex=True,
            entity_secret_ciphertext=self._ciphertext(),
        )
        response = self._signing_api.sign_message(request)
        return bytes.fromhex(response.data.signature.removeprefix("0x"))


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
