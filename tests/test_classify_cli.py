"""비식당 판별을 공개 CLI와 저장된 판정·공통 캐시로 관찰한다. 모델 응답만 합성한다."""

import json
from pathlib import Path

import pytest

from deliciousmap import gemini
from deliciousmap.storage import write_text
from deliciousmap.transport import REQUEST_TIMEOUT, HttpTransport
from tests.gwangju import FakeModel, header_answer, sheet_a, workbook
from tests.test_parse_cli import (
    DATA,
    ledger,
    payload,
    publish,
    record_spending,
    records,
    run,
)

SHEET = sheet_a(
    ("2026-01-05", "합성 식당", "간담회", 4.0, 62000.0),
    ("2026-01-06", "합성 마트", "물품 구입", 1.0, 30000.0),
    ("2026-01-07", "합성 식당", "간담회", 5.0, 71000.0),
    ("2026-01-08", "모호한 상호", "협의", 2.0, 20000.0),
)
VERDICTS = {"합성 식당": "restaurant", "합성 마트": "non_restaurant", "모호한 상호": "pending"}
# 2026-09-16 울산 실측: 상호 40개(classify.BATCH_SIZE) 한 묶음의 응답에 걸린 시간.
MEASURED_BATCH_SECONDS = 10.4


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


TAIL_SHEET = sheet_a(
    ("2026-02-02", "합성카페외 1", "간담회", 3.0, 33000.0),
    ("2026-02-03", "외갓집", "간담회", 2.0, 22000.0),
    ("2026-02-04", "외 1", "협의", 2.0, 11000.0),
)


def tail_parsed(root: Path) -> None:
    record_spending(root)
    publish(root, ("2월.xls", workbook(TAIL_SHEET)))
    assert run(root, "headermap", FakeModel(headers=[header_answer()])) == 0
    assert run(root, "parse") == 0


def asked(model: FakeModel) -> list[str]:
    """그 실행이 모델에 실제로 보인 상호. 캐시 키와 질문이 같은 이름인지 보는 자리다."""
    (prompt,) = model.calls("classify")
    return [line.split(". ", 1)[1] for line in prompt.splitlines()]


def cached(root: Path, verdicts: dict[str, str]) -> None:
    """공통 캐시를 키 정렬 JSONL로 미리 채운다. 이미 답한 이름을 다시 묻지 않는지 본다."""
    write_text(
        root / DATA / "_shared" / "classify.jsonl",
        "".join(
            json.dumps(
                {
                    "schema_version": 1,
                    "key": key,
                    "revision": 1,
                    "valid": True,
                    "evidence": "gemini-3.6-flash/classify-1",
                    "value": {"status": verdicts[key], "reason": "이미 답한 이름"},
                },
                ensure_ascii=False,
            )
            + "\n"
            for key in sorted(verdicts)
        ),
    )


def test_the_unnamed_companion_tail_is_cut_from_the_name_the_classifier_reads(
    tmp_path: Path, configured: None
) -> None:
    """판별이 읽는 이름에서 꼬리말을 뗀다. 레코드의 원본 표기는 바뀌지 않는다(#137)."""
    tail_parsed(tmp_path)
    model = FakeModel(verdict=lambda name: "restaurant")
    assert run(tmp_path, "classify", model) == 0
    # 모델에 보이는 표기도 뗀 이름이어야 캐시 키와 질문이 같은 이름을 가리킨다.
    assert sorted(asked(model)) == ["외 1", "외갓집", "합성카페"]
    assert {item["key"] for item in shared(tmp_path)} == {"합성카페", "외갓집", "외 1"}
    # 레코드의 원본 표기는 어느 단계에서도 바뀌지 않는다.
    assert [item["merchant"] for item in records(tmp_path)] == ["합성카페외 1", "외갓집", "외 1"]


def test_a_cached_cut_name_is_reused_without_a_call(tmp_path: Path, configured: None) -> None:
    """뗀 이름이 이미 공통 캐시에 있으면 묻지 않는다. 기존 항목도 덮어쓰지 않는다(#137)."""
    cached(tmp_path, {"합성카페": "restaurant", "외갓집": "restaurant", "외 1": "pending"})
    before = shared(tmp_path)
    tail_parsed(tmp_path)
    model = FakeModel()
    assert run(tmp_path, "classify", model) == 0
    assert model.prompts == []
    assert [status for status, _ in decisions(tmp_path)] == ["restaurant", "restaurant", "pending"]
    assert shared(tmp_path) == before


def test_a_manual_correction_matches_the_cut_name(tmp_path: Path, configured: None) -> None:
    """사람 보정도 뗀 이름으로 맞는다. 보정 파일의 상호가 뗀 이름과 같으면 적용된다(#137)."""
    tail_parsed(tmp_path)
    correct(tmp_path, "합성카페", "restaurant")
    assert run(tmp_path, "classify", FakeModel(verdict=lambda name: "pending")) == 0
    assert decisions(tmp_path)[0] == ("restaurant", "manual: 담당자가 업소 정보를 확인")
    # 보정이 맞은 상호는 캐시를 채우지 않는다.
    assert {item["key"] for item in shared(tmp_path)} == {"외갓집", "외 1"}


def test_a_confirmed_restored_name_wins_over_the_cut_name(tmp_path: Path, configured: None) -> None:
    """확정 복원명 → 꼬리말을 뗀 이름 → 원본 표기 순이다. 복원명이 앞선다(#137)."""
    tail_parsed(tmp_path)
    record_id = records(tmp_path)[0]["record_id"]
    write_text(
        tmp_path / DATA / "manual" / "gwangju" / "restore.jsonl",
        json.dumps(
            {
                "schema_version": 1,
                "scope": {
                    "city": "gwangju",
                    "merchant": "합성카페외 1",
                    "record_id": record_id,
                },
                "restored_merchant": "합성카페 본점",
                "evidence": "기관의 다른 공개자료에서 전체 상호를 확인",
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    model = FakeModel(verdict=lambda name: "restaurant")
    assert run(tmp_path, "classify", model) == 0
    assert "합성카페 본점" in asked(model)
    assert "합성카페" not in asked(model)


def test_model_requests_wait_longer_than_a_board_fetch(configured: None) -> None:
    """상호 40개 한 묶음은 10.4초 걸렸다(2026-09-16 울산 실측). 게시판 기본 대기로는 매번 끊긴다.

    상수끼리 견주면 값을 낮춰도 통과하므로 실측의 몇 배인지를 초 단위로 못 박는다.
    """
    models = gemini.models_from_environment()

    assert models is not None
    assert REQUEST_TIMEOUT < MEASURED_BATCH_SECONDS
    for model in (models.comparator, models.header_mapper, models.classifier):
        transport = model.transport
        assert isinstance(transport, HttpTransport)
        # 실측의 다섯 배는 기다린다. 제공자가 느려진 날에도 판별을 통째로 잃지 않는다.
        assert transport.timeout >= 5 * MEASURED_BATCH_SECONDS
