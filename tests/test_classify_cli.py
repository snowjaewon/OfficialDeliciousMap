"""비식당 판별을 공개 CLI와 저장된 판정·공통 캐시로 관찰한다. 모델 응답만 합성한다."""

import json
from pathlib import Path

import pytest

from deliciousmap.storage import write_text
from tests.gwangju import FakeModel, header_answer, sheet_a, workbook
from tests.test_parse_cli import DATA, ledger, payload, publish, record_spending, run

SHEET = sheet_a(
    ("2026-01-05", "합성 식당", "간담회", 4.0, 62000.0),
    ("2026-01-06", "합성 마트", "물품 구입", 1.0, 30000.0),
    ("2026-01-07", "합성 식당", "간담회", 5.0, 71000.0),
    ("2026-01-08", "모호한 상호", "협의", 2.0, 20000.0),
)
VERDICTS = {"합성 식당": "restaurant", "합성 마트": "non_restaurant", "모호한 상호": "pending"}


def parsed(root: Path) -> None:
    record_spending(root)
    publish(root, ("1월.xls", workbook(SHEET)))
    assert run(root, "headermap", FakeModel(headers=[header_answer()])) == 0
    assert run(root, "parse") == 0


def decisions(root: Path) -> list[tuple[str, str]]:
    return [(item["status"], item["evidence"]) for item in payload(root, "classify")["decisions"]]


def shared(root: Path) -> list[dict]:
    path = root / DATA / "_shared" / "classify.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def correct(root: Path, merchant: str, status: str) -> None:
    write_text(
        root / DATA / "manual" / "gwangju" / "classify.jsonl",
        json.dumps(
            {
                "schema_version": 1,
                "city": "gwangju",
                "merchant": merchant,
                "status": status,
                "evidence": "담당자가 업소 정보를 확인",
            },
            ensure_ascii=False,
        )
        + "\n",
    )


def test_unique_merchants_are_classified_once_and_shared_across_runs(
    tmp_path: Path, configured: None
) -> None:
    parsed(tmp_path)
    model = FakeModel(verdict=VERDICTS.__getitem__)
    assert run(tmp_path, "classify", model) == 0
    (prompt,) = model.calls("classify")
    # 고유 상호만 한 번씩 묻고 목적·금액은 싣지 않는다.
    assert sorted(prompt.splitlines()) == ["1. 모호한 상호", "2. 합성 마트", "3. 합성 식당"]
    assert [status for status, _ in decisions(tmp_path)] == [
        "restaurant",
        "non_restaurant",
        "restaurant",
        "pending",
    ]
    assert decisions(tmp_path)[0][1] == "llm gemini-3.6-flash/classify-1 r1: 합성"
    assert {item["key"]: item["value"]["status"] for item in shared(tmp_path)} == {
        "합성 식당": "restaurant",
        "합성 마트": "non_restaurant",
        "모호한 상호": "pending",
    }
    assert [item["kind"] for item in ledger(tmp_path) if item["purpose"] == "classification"] == [
        "reservation",
        "settlement",
    ]
    again = FakeModel()
    assert run(tmp_path, "classify", again) == 0
    assert again.prompts == []


def test_manual_correction_wins_without_rewriting_the_shared_cache(
    tmp_path: Path, configured: None
) -> None:
    parsed(tmp_path)
    assert run(tmp_path, "classify", FakeModel(verdict=VERDICTS.__getitem__)) == 0
    before = shared(tmp_path)
    correct(tmp_path, "모호한 상호", "restaurant")
    again = FakeModel()
    assert run(tmp_path, "classify", again) == 0
    assert again.prompts == []
    assert decisions(tmp_path)[3] == ("restaurant", "manual: 담당자가 업소 정보를 확인")
    assert shared(tmp_path) == before


@pytest.mark.parametrize("failure", ["unavailable", "mismatched"])
def test_failed_classification_is_pending_and_asked_again_next_run(
    tmp_path: Path, configured: None, failure: str
) -> None:
    parsed(tmp_path)
    if failure == "unavailable":
        model = FakeModel(classify_failure=OSError("synthetic outage"))
    else:
        # 모델이 상호 표기를 바꿔 답하면 그 묶음 전체를 쓰지 않는다.
        model = FakeModel(verdict=VERDICTS.__getitem__, rename={"합성 마트": "다른 마트"})
    assert run(tmp_path, "classify", model) == 0
    reason = "unavailable" if failure == "unavailable" else "invalid_response"
    assert set(decisions(tmp_path)) == {("pending", f"unclassified: {reason}")}
    assert not (tmp_path / DATA / "_shared" / "classify.jsonl").exists()
    retry = FakeModel(verdict=VERDICTS.__getitem__)
    assert run(tmp_path, "classify", retry) == 0
    assert len(retry.calls("classify")) == 1
    assert decisions(tmp_path)[1][0] == "non_restaurant"


def test_without_a_model_every_merchant_stays_pending(
    tmp_path: Path, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY")
    assert run(tmp_path, "classify") == 0
    assert set(decisions(tmp_path)) == {("pending", "unclassified: model_not_configured")}
