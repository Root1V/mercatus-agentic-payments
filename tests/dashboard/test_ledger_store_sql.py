from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from agent_commerce.dashboard.adapters.sql_ledger_store import SqlLedgerStore


def test_record_and_recent(db_session: Session) -> None:
    store = SqlLedgerStore(db_session)
    entry = store.record(
        protocol="x402", capability="summarize", service_id="text-summarizer",
        payer="0xBUYER", pay_to="0xSELLER", amount_usd=Decimal("0.001"),
        settlement_id="0xmockabc", status="ok",
    )
    assert entry.id == 1

    recent = store.recent()
    assert len(recent) == 1
    assert recent[0].protocol == "x402"
    assert recent[0].amount_usd == Decimal("0.001")


def test_recent_orders_newest_first(db_session: Session) -> None:
    store = SqlLedgerStore(db_session)
    for i in range(3):
        store.record(
            protocol="x402", capability="summarize", service_id="text-summarizer",
            payer=f"0xBUYER{i}", pay_to="0xSELLER", amount_usd=Decimal("0.001"),
            settlement_id=f"0xmock{i}", status="ok",
        )
    recent = store.recent()
    assert [e.payer for e in recent] == ["0xBUYER2", "0xBUYER1", "0xBUYER0"]


def test_stats_aggregates_by_protocol_and_status(db_session: Session) -> None:
    store = SqlLedgerStore(db_session)
    store.record(
        protocol="x402", capability="summarize", service_id="text-summarizer",
        payer="a", pay_to="b", amount_usd=Decimal("0.001"), settlement_id="1", status="ok",
    )
    store.record(
        protocol="ap2", capability="summarize", service_id="text-summarizer",
        payer="a", pay_to="b", amount_usd=Decimal("0.002"), settlement_id="2", status="ok",
    )
    store.record(
        protocol="x402", capability="summarize", service_id="?",
        payer="a", pay_to="", amount_usd=Decimal(0), settlement_id="", status="error",
        detail="boom",
    )

    stats = store.stats()
    assert stats["total_calls"] == 3
    assert stats["successful_calls"] == 2
    assert stats["failed_calls"] == 1
    assert stats["total_paid_usd"] == "0.003"
    assert stats["calls_by_protocol"] == {"x402": 1, "ap2": 1}


def test_stats_on_empty_store(db_session: Session) -> None:
    stats = SqlLedgerStore(db_session).stats()
    assert stats == {
        "total_calls": 0,
        "successful_calls": 0,
        "failed_calls": 0,
        "total_paid_usd": "0",
        "calls_by_protocol": {},
    }
