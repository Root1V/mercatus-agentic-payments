"""CLI de agent_commerce: `agent-commerce <comando>`.

Comandos:
- `serve-example`: levanta el vendedor de ejemplo (text-summarizer) monetizado.
- `demo`: corre la demo agente-a-agente de punta a punta e imprime el ledger.
- `catalog list`: lista los servicios del catálogo semilla.
- `call`: como agente comprador, descubre y paga un servicio del catálogo.
- `create-admin`: crea el único usuario admin del dashboard (sin auto-registro).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

from agent_commerce.config import Mode, Protocol, Settings, SettlementRail

app = typer.Typer(help="Framework de doble cara para agentic commerce (x402 + AP2).")
catalog_app = typer.Typer(help="Consultar el catálogo de servicios.")
app.add_typer(catalog_app, name="catalog")

# repo_root/src/agent_commerce/cli/main.py -> repo_root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CATALOG_PATH = _REPO_ROOT / "data" / "catalog.sample.json"


def _ensure_examples_importable() -> None:
    """`examples/` no se instala como parte del paquete (son demos, no
    librería) -- solo hace falta en el path para los comandos que los usan,
    y solo funciona corriendo desde un checkout del repo (instalación
    editable), nunca desde una wheel instalada normal."""
    repo_root_str = str(_REPO_ROOT)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


@app.command("serve-example")
def serve_example(
    protocol: Protocol = typer.Option(Protocol.X402, "--protocol"),
    ap2_settlement: SettlementRail = typer.Option(
        SettlementRail.X402, "--ap2-settlement", help="Solo con --protocol ap2: riel de liquidación (RM-18)."
    ),
    mode: Mode = typer.Option(Mode.MOCK, "--mode"),
    port: int = typer.Option(8901, "--port"),
) -> None:
    """Levanta el vendedor de ejemplo (text-summarizer) monetizado en :port."""
    import uvicorn

    from agent_commerce.payments.factory import build_payer_credential, get_payment_protocol

    _ensure_examples_importable()
    from examples.seller_text_summarizer.app import build_app

    settings = Settings(protocol=protocol, mode=mode, ap2_settlement=ap2_settlement)
    seller_signer = build_payer_credential(role="seller", settings=settings)
    payment_protocol = get_payment_protocol(settings)
    fastapi_app = build_app(protocol=payment_protocol, pay_to=seller_signer.address)

    typer.echo(f"pay_to={seller_signer.address} protocol={protocol.value} mode={mode.value} port={port}")
    uvicorn.run(fastapi_app, host="127.0.0.1", port=port)


@app.command("demo")
def demo(
    protocol: Protocol = typer.Option(Protocol.X402, "--protocol"),
    ap2_settlement: SettlementRail = typer.Option(
        SettlementRail.X402, "--ap2-settlement", help="Solo con --protocol ap2: riel de liquidación (RM-18)."
    ),
    mode: Mode = typer.Option(Mode.MOCK, "--mode"),
    port: int = typer.Option(8901, "--port"),
) -> None:
    """Corre la demo agente-a-agente de punta a punta (vendedor + comprador)."""
    _ensure_examples_importable()
    from examples.agent_to_agent_demo import run_demo

    asyncio.run(run_demo(protocol.value, mode.value, port, ap2_settlement=ap2_settlement.value))


@catalog_app.command("list")
def catalog_list(
    catalog_path: Path = typer.Option(_DEFAULT_CATALOG_PATH, "--catalog-path"),
) -> None:
    """Lista los servicios disponibles en el catálogo."""
    from agent_commerce.catalog.registry import InMemoryServiceRegistry

    registry = InMemoryServiceRegistry.from_json_file(catalog_path)
    for listing in registry.all():
        typer.echo(f"{listing.id:20s} {listing.price_usd:>10s}  {listing.name} -- {listing.description}")


@catalog_app.command("seed")
def catalog_seed(
    catalog_path: Path = typer.Option(_DEFAULT_CATALOG_PATH, "--catalog-path"),
) -> None:
    """Siembra el catálogo persistido (Postgres) desde un JSON, si está vacío.

    Requiere el extra `dashboard` instalado y `AGENT_COMMERCE_DATABASE_URL`
    apuntando a una base ya migrada (`alembic upgrade head`)."""
    from agent_commerce.dashboard.adapters.sql_catalog_store import SqlCatalogStore
    from agent_commerce.db.session import build_session_factory

    session_factory = build_session_factory()
    db = session_factory()
    try:
        store = SqlCatalogStore(db)
        inserted = store.seed_from_json_if_empty(str(catalog_path))
    finally:
        db.close()

    if inserted:
        typer.echo(f"Catálogo sembrado: {inserted} listing(s) insertado(s) desde {catalog_path}.")
    else:
        typer.echo("El catálogo ya tenía datos -- no se sembró nada.")


@app.command("call")
def call(
    capability: str = typer.Argument(..., help="Palabra clave a buscar en el catálogo, p. ej. 'summarize'"),
    text: str = typer.Option(..., "--text", help="Texto a enviar como payload {'text': ...}"),
    protocol: Protocol = typer.Option(Protocol.X402, "--protocol"),
    ap2_settlement: SettlementRail = typer.Option(
        SettlementRail.X402, "--ap2-settlement", help="Solo con --protocol ap2: riel de liquidación (RM-18)."
    ),
    mode: Mode = typer.Option(Mode.MOCK, "--mode"),
    catalog_path: Path = typer.Option(_DEFAULT_CATALOG_PATH, "--catalog-path"),
) -> None:
    """Como agente comprador: descubre y paga un servicio del catálogo por `capability`."""
    from agent_commerce.catalog.registry import InMemoryServiceRegistry
    from agent_commerce.client.paying_agent import PayingAgent
    from agent_commerce.payments.factory import build_payer_credential, get_payment_protocol

    async def _run() -> None:
        settings = Settings(protocol=protocol, mode=mode, ap2_settlement=ap2_settlement)
        buyer_signer = build_payer_credential(role="buyer", settings=settings)
        payment_protocol = get_payment_protocol(settings)
        catalog = InMemoryServiceRegistry.from_json_file(catalog_path)

        async with PayingAgent(protocol=payment_protocol, signer=buyer_signer, catalog=catalog) as agent:
            result = await agent.call_service(capability, {"text": text})

        typer.echo(f"resultado: {result.data}")
        if result.receipt:
            typer.echo(
                f"pagado: ${result.receipt.amount_usd} via {result.receipt.protocol} "
                f"(settlement_id={result.receipt.settlement_id})"
            )

    asyncio.run(_run())


@app.command("create-admin")
def create_admin_command(
    username: str = typer.Option(None, "--username", envvar="AGENT_COMMERCE_ADMIN_USERNAME"),
    password: str = typer.Option(None, "--password", envvar="AGENT_COMMERCE_ADMIN_PASSWORD"),
) -> None:
    """Crea el único usuario admin del dashboard. Sin endpoint de registro:
    esta es la única forma de dar de alta un usuario."""
    from agent_commerce.auth.bootstrap import AdminAlreadyExistsError, create_admin
    from agent_commerce.db.session import build_session_factory

    if not username:
        username = typer.prompt("Usuario admin")
    if not password:
        password = typer.prompt("Contraseña", hide_input=True, confirmation_prompt=True)

    session_factory = build_session_factory()
    db = session_factory()
    try:
        try:
            user = create_admin(db, username=username, password=password)
        except AdminAlreadyExistsError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    finally:
        db.close()

    typer.echo(f"Usuario admin '{user.username}' creado (id={user.id}).")


@app.command("dashboard")
def dashboard_command(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Levanta el dashboard interactivo (requiere Postgres migrado y el extra `dashboard`)."""
    import uvicorn

    from agent_commerce.dashboard.app import build_dashboard_app

    settings = Settings()
    fastapi_app = build_dashboard_app(settings)
    typer.echo(f"Dashboard en http://{host}:{port} (modo={settings.mode.value})")
    uvicorn.run(fastapi_app, host=host, port=port)


if __name__ == "__main__":
    app()
