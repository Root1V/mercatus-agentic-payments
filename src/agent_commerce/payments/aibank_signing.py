"""Firma de los pagos de cada agente ante AIBank/Aerarium (AE-10, contrato 1.1).

RFC 9421 (HTTP Message Signatures) con Ed25519, exactamente como lo verifica
el banco (`services/agents/httpsig.go` en Root1V/aerarium-agentic-banking):

- La firma cubre `@method`, `@path` y `content-digest` -- el SHA-256 del
  cuerpo exacto (RFC 9530): cambiar el monto, el receptor, el agente o la
  intención la invalida.
- `keyid` es el `key_...` de la clave, no el `agt_...` del agente: con varias
  claves vivas durante una rotación, el banco tiene que saber con cuál
  verificar (AE-11).
- `created` acota la reutilización: el banco rechaza firmas de más de 5
  minutos o con fecha futura.

Sin la firma, `agent_id` es solo lo que dice la plataforma; con ella, es una
prueba de qué agente pagó.
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

SIGNATURE_LABEL = "sig1"
REQUIRED_COMPONENTS = ("@method", "@path", "content-digest")
MAX_SIGNATURE_AGE_SECONDS = 5 * 60
_MAX_CLOCK_SKEW_SECONDS = 60


class SignatureError(Exception):
    """La firma falta, está mal formada, venció o no corresponde."""


@dataclass(frozen=True)
class AgentIdentity:
    """Con qué firma un agente sus pagos: su `agt_...`, la `key_...` vigente y
    la clave privada. La privada nunca sale de Mercatus."""

    agent_id: str
    key_id: str
    private_key: Ed25519PrivateKey


def generate_agent_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def public_jwk(key: Ed25519PrivateKey | Ed25519PublicKey) -> dict[str, str]:
    """La clave pública como JWK (`OKP`/`Ed25519`), la forma que pide
    `POST /v1/agents`."""
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    raw = public.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode()}


def public_key_from_jwk(jwk: dict[str, str]) -> Ed25519PublicKey:
    if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519" or not jwk.get("x"):
        raise ValueError("la clave tiene que ser un JWK OKP/Ed25519")
    x = jwk["x"]
    raw = base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
    return Ed25519PublicKey.from_public_bytes(raw)


def content_digest(body: bytes) -> str:
    return "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode() + ":"


def _signature_base(method: str, path: str, digest: str, params: str) -> str:
    return (
        f'"@method": {method.upper()}\n'
        f'"@path": {path}\n'
        f'"content-digest": {digest}\n'
        f'"@signature-params": {params}'
    )


def sign_request(
    method: str, path: str, body: bytes, identity: AgentIdentity, *, created: int | None = None
) -> dict[str, str]:
    """Los tres encabezados que firman la petición: `Content-Digest`,
    `Signature-Input` y `Signature`."""
    digest = content_digest(body)
    created = int(time.time()) if created is None else created
    params = f'("@method" "@path" "content-digest");created={created};keyid="{identity.key_id}";alg="ed25519"'
    signature = identity.private_key.sign(_signature_base(method, path, digest, params).encode())
    return {
        "Content-Digest": digest,
        "Signature-Input": f"{SIGNATURE_LABEL}={params}",
        "Signature": f"{SIGNATURE_LABEL}=:{base64.b64encode(signature).decode()}:",
    }


_INPUT = re.compile(r'^(?P<label>[a-z0-9_-]+)=\((?P<components>[^)]*)\)(?P<rest>(;[a-z]+=("[^"]*"|\d+))*)$')
_PARAM = re.compile(r';([a-z]+)=("([^"]*)"|(\d+))')


def verify_request(
    method: str,
    path: str,
    body: bytes,
    headers: dict[str, str],
    public_key_for: Callable[[str], Ed25519PublicKey],
    *,
    now: float | None = None,
) -> str:
    """Lo que hace el banco al recibir un pago firmado. Devuelve el `keyid`
    que firmó; `public_key_for(keyid)` levanta `SignatureError` si la clave no
    existe, venció o es de un agente dado de baja."""
    # Los nombres de encabezado no distinguen mayúsculas (RFC 9110).
    lowered = {name.lower(): value for name, value in headers.items()}
    signature_input, signature = lowered.get("signature-input", ""), lowered.get("signature", "")
    if not signature_input and not signature:
        raise SignatureError("falta la firma")
    match = _INPUT.match(signature_input.strip())
    if match is None:
        raise SignatureError("Signature-Input ilegible")
    label = match["label"]
    components = tuple(c.strip('"') for c in match["components"].split())
    if components != REQUIRED_COMPONENTS:
        raise SignatureError("la firma tiene que cubrir @method, @path y content-digest")
    params = {m[1]: m[3] if m[3] is not None else m[4] for m in _PARAM.finditer(match["rest"])}
    if params.get("alg", "ed25519") != "ed25519":
        raise SignatureError("algoritmo no admitido")
    if "created" not in params or "keyid" not in params:
        raise SignatureError("faltan created o keyid")
    age = (time.time() if now is None else now) - int(params["created"])
    if age > MAX_SIGNATURE_AGE_SECONDS or age < -_MAX_CLOCK_SKEW_SECONDS:
        raise SignatureError("firma vencida o con fecha futura")
    digest = lowered.get("content-digest", "")
    if digest != content_digest(body):
        raise SignatureError("Content-Digest no corresponde al cuerpo")
    prefix = f"{label}=:"
    if not signature.startswith(prefix) or not signature.endswith(":"):
        raise SignatureError("Signature ilegible")
    try:
        raw_signature = base64.b64decode(signature[len(prefix) : -1], validate=True)
    except ValueError as exc:
        raise SignatureError("Signature ilegible") from exc
    public_key = public_key_for(params["keyid"])
    raw_params = signature_input.strip()[len(label) + 1 :]
    try:
        public_key.verify(raw_signature, _signature_base(method, path, digest, raw_params).encode())
    except InvalidSignature as exc:
        raise SignatureError("la firma no corresponde a la petición") from exc
    return params["keyid"]
