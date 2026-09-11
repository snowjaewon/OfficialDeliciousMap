"""공통 LLM 예산의 예약·정산·누적 보존. 모델 호출·업소 판정·사람 확정은 하지 않는다."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Literal

from deliciousmap.contracts import LedgerEntry
from deliciousmap.storage import append_ledger, read_ledger

POLICY_VERSION = "budget-1"
# 프로젝트 전체 기간의 누적 한도. 날짜·월·도시·실행마다 초기화하지 않는다.
LIMIT_USD = Decimal("15")

Reason = Literal["unknown_prior_usage", "budget_exhausted", "concurrent_execution"]
Purpose = Literal[
    "header_mapping", "classification", "extraction_fallback", "restoration_comparison"
]


class BudgetUnavailable(Exception):
    """호출하지 않는다는 결정. 안전한 사유 코드만 전달한다."""

    def __init__(self, reason: Reason) -> None:
        self.reason: Reason = reason
        super().__init__(reason)


class Reservation:
    """예약 한 건. 실제 사용량을 확인했을 때만 정산한다."""

    def __init__(self, path: Path, entry: LedgerEntry) -> None:
        self._path = path
        self._entry = entry
        self.settled = False

    @property
    def entry_id(self) -> str:
        return self._entry.entry_id

    def settle(self, amount_usd: Decimal, evidence: str) -> None:
        """예약을 실제 사용액으로 대체한다. 사용량을 모르면 부르지 않는다."""
        if self.settled:
            raise ValueError("a reservation can be settled only once")
        append_ledger(
            self._path,
            LedgerEntry(
                entry_id=self._entry.entry_id,
                kind="settlement",
                purpose=self._entry.purpose,
                model=self._entry.model,
                amount_usd=amount_usd,
                evidence=evidence,
            ),
        )
        self.settled = True


class Budget:
    """장부 하나가 모든 LLM 용도의 예약·정산을 소유한다. 호출자는 잔액을 따로 세지 않는다."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def lock_path(self) -> Path:
        return self.path.with_suffix(".lock")

    def committed(self) -> Decimal:
        """확인한 기존 사용액·정산액·진행 중 예약액의 합."""
        entries = read_ledger(self.path)
        if not any(entry.kind == "prior_usage" for entry in entries):
            # 제공자의 사용량 기록으로 확인한 값이 없으면 잔액을 가정하지 않는다.
            raise BudgetUnavailable("unknown_prior_usage")
        settled = {entry.entry_id for entry in entries if entry.kind == "settlement"}
        return sum(
            (
                entry.amount_usd
                for entry in entries
                if entry.kind != "reservation" or entry.entry_id not in settled
            ),
            Decimal(0),
        )

    @contextmanager
    def reserve(
        self, entry_id: str, purpose: Purpose, model: str, ceiling_usd: Decimal, evidence: str
    ) -> Iterator[Reservation]:
        """예약을 남긴 뒤에만 호출을 허용한다. 잠금은 호출·정산까지 유지해 직렬화한다."""
        if ceiling_usd <= 0:
            raise ValueError("a reservation requires a positive cost ceiling")
        with self._locked():
            if self.committed() + ceiling_usd > LIMIT_USD:
                raise BudgetUnavailable("budget_exhausted")
            entry = LedgerEntry(
                entry_id=entry_id,
                kind="reservation",
                purpose=purpose,
                model=model,
                amount_usd=ceiling_usd,
                evidence=evidence,
            )
            append_ledger(self.path, entry)
            yield Reservation(self.path, entry)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """공유 집행을 보장할 수 없으면 직렬화한다. 남은 잠금은 담당자가 지운다."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise BudgetUnavailable("concurrent_execution") from None
        try:
            yield
        finally:
            os.close(handle)
            self.lock_path.unlink(missing_ok=True)
