"""`LedgerStore` respaldado por Postgres (o cualquier DB soportada por SQLAlchemy).

Recibe una `Session` ya construida (no un `sessionmaker`): quien construye
el store decide el ciclo de vida de la sesión -- en FastAPI, una por
request, vía `Depends(get_db)`.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent_commerce.db.models import LedgerEntryModel

from ..ports import LedgerEntry


def _to_entry(model: LedgerEntryModel) -> LedgerEntry:
    return LedgerEntry(
        id=model.id,
        timestamp=model.timestamp,
        protocol=model.protocol,
        capability=model.capability,
        service_id=model.service_id,
        payer=model.payer,
        pay_to=model.pay_to,
        amount_usd=model.amount_usd,
        settlement_id=model.settlement_id,
        status=model.status,
        detail=model.detail,
    )


class SqlLedgerStore:
    def __init__(self, db: Session) -> None:
        self._db = db

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
        model = LedgerEntryModel(
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
        self._db.add(model)
        self._db.commit()
        self._db.refresh(model)
        return _to_entry(model)

    def recent(self, limit: int = 50) -> list[LedgerEntry]:
        stmt = select(LedgerEntryModel).order_by(LedgerEntryModel.timestamp.desc()).limit(limit)
        return [_to_entry(m) for m in self._db.execute(stmt).scalars().all()]

    def stats(self) -> dict:
        total_calls = self._db.execute(select(func.count(LedgerEntryModel.id))).scalar_one()
        successful_calls = self._db.execute(
            select(func.count(LedgerEntryModel.id)).where(LedgerEntryModel.status == "ok")
        ).scalar_one()
        total_paid = self._db.execute(
            select(func.coalesce(func.sum(LedgerEntryModel.amount_usd), 0)).where(
                LedgerEntryModel.status == "ok"
            )
        ).scalar_one()

        by_protocol_rows = self._db.execute(
            select(LedgerEntryModel.protocol, func.count(LedgerEntryModel.id))
            .where(LedgerEntryModel.status == "ok")
            .group_by(LedgerEntryModel.protocol)
        ).all()

        total_paid_str = f"{Decimal(total_paid):.6f}".rstrip("0").rstrip(".") or "0"
        return {
            "total_calls": total_calls,
            "successful_calls": successful_calls,
            "failed_calls": total_calls - successful_calls,
            "total_paid_usd": total_paid_str,
            "calls_by_protocol": {protocol: count for protocol, count in by_protocol_rows},
        }
