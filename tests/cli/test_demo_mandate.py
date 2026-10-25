"""`agent-commerce demo --aibank-model mandate`: el modelo B de AIBank de
punta a punta desde la CLI (pedido de permiso, decisión simulada del
titular, pagos sobre la cuenta del cliente) contra un vendedor real en
uvicorn -- y la validación de opciones que solo aplican a ese modelo."""

from __future__ import annotations

import socket

from typer.testing import CliRunner

from agent_commerce.cli.main import app

runner = CliRunner()

_MANDATE = ["demo", "--protocol", "ap2", "--ap2-settlement", "aibank", "--aibank-model", "mandate"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(*args: str):
    return runner.invoke(app, [*args, "--port", str(_free_port())])


def test_pays_until_the_limit_the_titular_granted() -> None:
    result = _run(*_MANDATE, "--granted-total", "0.002")

    assert result.exit_code == 0, result.output
    assert "tope total:       $0.002 (pedido: $0.003)" in result.output
    assert "pago 1/4: ok · consumido $0.001 de $0.002" in result.output
    assert "pago 2/4: ok · consumido $0.002 de $0.002" in result.output
    # Falta de permiso, no de saldo -- el spec insiste en no confundirlos.
    assert "pago 3/4: RECHAZADO (mandate_limit_exceeded)" in result.output
    assert "No es falta de saldo" in result.output
    assert "consumido:        $0.002 de $0.002" in result.output


def test_revocation_stops_the_next_payment() -> None:
    result = _run(*_MANDATE, "--revoke-after", "1", "--payments", "2")

    assert result.exit_code == 0, result.output
    assert "pago 1/2: ok" in result.output
    assert "pago 2/2: RECHAZADO (mandate_revoked)" in result.output
    assert "estado:           revoked" in result.output


def test_rejected_consent_never_pays() -> None:
    result = _run(*_MANDATE, "--titular-rejects")

    assert result.exit_code == 0, result.output
    assert "estado:           rejected" in result.output
    assert "pago " not in result.output


def test_titular_cannot_grant_more_than_requested() -> None:
    result = _run(*_MANDATE, "--granted-total", "0.01")

    assert result.exit_code == 0, result.output
    assert "cannot_raise_requested_limits" in result.output
    assert "pago " not in result.output


def test_mandate_options_require_the_mandate_model() -> None:
    result = runner.invoke(app, ["demo", "--payments", "3"])

    assert result.exit_code == 2
    assert "--payments" in result.output


def test_mandate_model_requires_ap2_over_aibank() -> None:
    result = runner.invoke(app, ["demo", "--aibank-model", "mandate"])

    assert result.exit_code == 2
    assert "--ap2-settlement aibank" in result.output


def test_rejects_non_positive_amounts() -> None:
    result = runner.invoke(app, [*_MANDATE, "--max-total", "0"])

    assert result.exit_code == 2
    assert "--max-total" in result.output
