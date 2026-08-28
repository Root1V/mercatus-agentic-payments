"""`LedgerStore` en memoria -- para tests, sin Postgres."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from ..ports import LedgerEntry


class InMemoryLedgerStore:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self._next_id = 1

    def record(
        self,
        *,
        protocol: str,
        capability: str,
        service_id: str,
        payer: str,
        pay_to: str,
        amount_usd: Decimal,
        settlement_id: str,
        status: str,
        detail: str | None = None,
    ) -> LedgerEntry:
        entry = LedgerEntry(
            id=self._next_id,
            timestamp=datetime.now(UTC),
            protocol=protocol,
            capability=capability,
            service_id=service_id,
            payer=payer,
            pay_to=pay_to,
            amount_usd=amount_usd,
            settlement_id=settlement_id,
            status=status,
            detail=detail,
        )
        self._next_id += 1
        self._entries.insert(0, entry)
        return entry

    def recent(self, limit: int = 50) -> list[LedgerEntry]:
        return self._entries[:limit]

    def stats(self) -> dict:
        ok_entries = [e for e in self._entries if e.status == "ok"]
        total_paid = sum((e.amount_usd for e in ok_entries), start=Decimal(0))
        by_protocol: dict[str, int] = {}
        for entry in ok_entries:
            by_protocol[entry.protocol] = by_protocol.get(entry.protocol, 0) + 1
        total_paid_str = f"{total_paid:.6f}".rstrip("0").rstrip(".") or "0"
        return {
            "total_calls": len(self._entries),
            "successful_calls": len(ok_entries),
            "failed_calls": len(self._entries) - len(ok_entries),
            "total_paid_usd": total_paid_str,
            "calls_by_protocol": by_protocol,
        }
