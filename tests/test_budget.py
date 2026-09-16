"""공통 LLM 예산의 예약 종결과 누적액을 검증한다."""

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from deliciousmap.budget import Budget
from deliciousmap.contracts import ClassificationReply, LedgerEntry, Usage
from deliciousmap.storage import append_ledger, read_ledger

PRIOR = Decimal("2.50")
CEILING = Decimal("1.00")


@pytest.fixture
def path(tmp_path: Path) -> Path:
    ledger = tmp_path / "llm-budget.jsonl"
    append_ledger(
        ledger,
        LedgerEntry(
            entry_id="prior-usage",
            kind="prior_usage",
            purpose="prior_usage",
            model=None,
            amount_usd=PRIOR,
            evidence="provider usage record",
        ),
    )
    return ledger


def spend(path: Path, request: Callable[[], ClassificationReply]) -> ClassificationReply:
    return Budget(path).spend(
        "request-1",
        "classification",
        "test-model",
        CEILING,
        "classification of one merchant",
        request,
        lambda usage: Decimal(usage.input_tokens + usage.output_tokens) / 1_000_000,
    )


def kinds(path: Path) -> list[str]:
    return [entry.kind for entry in read_ledger(path)]


def test_reported_usage_settles_the_reservation(path: Path) -> None:
    usage = Usage(input_tokens=200, output_tokens=100)
    spend(path, lambda: ClassificationReply(status="error", error="invalid_response", usage=usage))

    assert kinds(path) == ["prior_usage", "reservation", "settlement"]
    assert Budget(path).committed() == PRIOR + Decimal("0.0003")


def test_a_call_that_got_no_response_releases_the_reservation(path: Path) -> None:
    spend(path, lambda: ClassificationReply(status="error", error="unavailable"))

    entries = read_ledger(path)
    assert kinds(path) == ["prior_usage", "reservation", "release"]
    assert entries[-1].amount_usd == 0
    assert entries[-1].evidence == "usage unavailable: no response received"
    assert Budget(path).committed() == PRIOR


def test_a_response_without_usage_keeps_the_reservation(path: Path) -> None:
    spend(path, lambda: ClassificationReply(status="error", error="invalid_response"))

    assert kinds(path) == ["prior_usage", "reservation"]
    assert Budget(path).committed() == PRIOR + CEILING


def test_a_failing_request_keeps_the_reservation(path: Path) -> None:
    def request() -> ClassificationReply:
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        spend(path, request)

    assert kinds(path) == ["prior_usage", "reservation"]
    assert Budget(path).committed() == PRIOR + CEILING
