"""헤더 매핑과 추출을 공개 CLI와 저장된 산출물로 관찰한다. 모델·게시판 응답만 합성한다."""

import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from deliciousmap.cli import main
from deliciousmap.storage import write_text
from tests.gwangju import (
    ANSWER_B,
    FakeBoardTransport,
    FakeModel,
    Post,
    city,
    gemini_reply,
    header_answer,
    sheet_a,
    sheet_b,
    workbook,
)

DATA = Path("저장소") / "data"


def record_spending(root: Path, amount: str = "0.35") -> None:
    write_text(
        root / DATA / "_shared" / "llm-budget.jsonl",
        json.dumps(
            {
                "schema_version": 1,
                "entry_id": "prior-usage",
                "kind": "prior_usage",
                "purpose": "prior_usage",
                "model": None,
                "amount_usd": amount,
                "evidence": "제공자 사용량 기록으로 확인한 기존 사용액",
            },
            ensure_ascii=False,
        )
        + "\n",
    )


def run(
    root: Path, stage: str, model: FakeModel | None = None, board: FakeBoardTransport | None = None
) -> int:
    return main(
        [
            stage,
            "--city",
            "gwangju",
            "--raw-root",
            str(root / "외부 원본"),
            "--data-root",
            str(root / DATA),
            "--output-root",
            str(root / "출력"),
        ],
        cities=(city(),),
        model_transport=model,
        board_transport=board,
    )


def payload(root: Path, stage: str) -> dict:
    path = root / DATA / "gwangju" / f"{stage}.json"
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


def records(root: Path) -> list[dict[str, str]]:
    with (root / DATA / "gwangju" / "records.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def ledger(root: Path) -> list[dict]:
    path = root / DATA / "_shared" / "llm-budget.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def publish(root: Path, *files: tuple[str, bytes], department: str = "합성과") -> list[str]:
    """게시글마다 원본 하나를 올리고 fetch한다. 원본 해시를 게시 순서대로 돌려준다."""
    posts = tuple(
        Post(
            100 - index,
            f"2026년 합성 집행내역 {index}",
            department,
            datetime(2026, 4, 1).date(),
            (file,),
        )
        for index, file in enumerate(files)
    )
    assert run(root, "fetch", board=FakeBoardTransport(posts)) == 0
    return [item["source_hash"] for item in payload(root, "fetch")["sources"]]


QUARTER = sheet_a(
    ("2026-01-05\n12:07", "합성 식당", "현안 업무 협의 간담회", 4.0, 62000.0),
    (
        datetime(2026, 2, 3, 12, 4),
        "합성 카페",
        "직원 격려 다과 구입 담당 010-1234-5678",
        20.0,
        93000.0,
    ),
    ("2025-12-30\n11:46", "합성 복집", "연말 업무 협의", 6.0, 117000.0),
)
MAY = sheet_b((datetime(2026, 5, 7, 12, 0), "업무 협의 간담회", 56000.0, "합성 한우촌"))


def test_verified_mappings_extract_every_candidate_and_reuse_the_header_cache(
    tmp_path: Path, configured: None
) -> None:
    record_spending(tmp_path)
    first, second, third = publish(
        tmp_path,
        ("1분기.xls", workbook(QUARTER, [])),
        (
            "1분기 다른 부서.xls",
            workbook(sheet_a(("2026-03-02", "합성 국밥", "협의", 3.0, 27000.0))),
        ),
        ("5월.xls", workbook(MAY)),
    )
    model = FakeModel(headers=[header_answer(), ANSWER_B])
    assert run(tmp_path, "headermap", model) == 0
    # 같은 헤더 서명의 두 번째 원본은 캐시로 매핑하고 모델을 부르지 않는다.
    assert len(model.calls("headermap")) == 2
    mapped = payload(tmp_path, "headermap")
    assert mapped["unresolved"] == []
    cache = {item["source_hash"]: item["cache"] for item in mapped["mappings"]}
    assert cache[first] == cache[second] != cache[third]
    assert "R3: [1]사용자 | [2]사용일시" in model.calls("headermap")[0]

    assert run(tmp_path, "parse") == 0
    rows = records(tmp_path)
    assert [(row["spent_on"], row["merchant"], row["amount_krw"]) for row in rows] == [
        ("2026-01-05", "합성 식당", "62000"),
        ("2026-02-03", "합성 카페", "93000"),
        ("2026-03-02", "합성 국밥", "27000"),
        ("2026-05-07", "합성 한우촌", "56000"),
    ]
    # 부서 열이 없는 표에서는 게시판 목록이 밝힌 작성 부서를 쓴다.
    assert {row["department"] for row in rows} == {"합성과"}
    assert rows[1]["purpose"] == "직원 격려 다과 구입 담당"
    assert rows[0]["source_location"] == "sheet1:R4"
    assert "합성과장" not in json.dumps(rows, ensure_ascii=False)
    report = {item["source_hash"]: item for item in payload(tmp_path, "parse")["sources"]}
    assert report[first] == {
        "source_hash": first,
        "status": "parsed",
        "reason": None,
        "detail": "",
        "candidates": 3,
        "records": 2,
        "out_of_range": 1,
        "excluded": ["sheet1:R7 total"],
        "review": [],
        "total_check": "matched",
    }
    assert payload(tmp_path, "parse")["reporting_period"] == "2026-01-01/2026-06-30"

    spent = [item for item in ledger(tmp_path) if item["purpose"] == "header_mapping"]
    assert [item["kind"] for item in spent] == ["reservation", "settlement"] * 2
    assert all(item["model"] == "gemini-3.6-flash" for item in spent)

    # 다시 실행하면 모든 표가 캐시로 매핑된다.
    again = FakeModel()
    assert run(tmp_path, "headermap", again) == 0
    assert again.prompts == []


def test_failed_cache_hit_is_asked_once_more_then_left_unresolved(
    tmp_path: Path, configured: None
) -> None:
    record_spending(tmp_path)
    broken = sheet_a(("2026-01-05", "합성 식당", "협의", 4.0, 62000.0), total=False)
    broken.append(("", "", "계", "", "", "1건", 99999.0, "", ""))
    good, bad = publish(
        tmp_path, ("정상.xls", workbook(QUARTER)), ("합계 불일치.xls", workbook(broken))
    )
    model = FakeModel(headers=[header_answer(), header_answer()])
    assert run(tmp_path, "headermap", model) == 0
    prompts = model.calls("headermap")
    assert len(prompts) == 2
    assert "이전 판정의 코드 검증 실패: sheet1:R5 total amount mismatch" in prompts[1]
    assert payload(tmp_path, "headermap")["unresolved"] == [
        {
            "source_hash": bad,
            "reason": "validation_failed",
            "detail": "sheet1:R5 total amount mismatch",
        }
    ]
    assert run(tmp_path, "parse") == 0
    report = {item["source_hash"]: item for item in payload(tmp_path, "parse")["sources"]}
    assert report[bad]["status"] == "unresolved"
    assert report[bad]["candidates"] is None
    # 실패한 원본의 일부는 확정하지 않고 다른 원본의 레코드는 보존한다.
    assert {row["source_hash"] for row in records(tmp_path)} == {good}


@pytest.mark.parametrize("recovers", [True, False])
def test_cache_miss_gets_one_retry_with_the_failure_reason(
    tmp_path: Path, configured: None, recovers: bool
) -> None:
    record_spending(tmp_path)
    (source,) = publish(tmp_path, ("1분기.xls", workbook(QUARTER)))
    wrong = header_answer(spent_on=4)
    model = FakeModel(headers=[wrong, header_answer() if recovers else wrong, header_answer()])
    assert run(tmp_path, "headermap", model) == 0
    prompts = model.calls("headermap")
    # 최초 호출과 재호출 한 번뿐이다. 세 번째 답은 쓰이지 않는다.
    assert len(prompts) == 2
    assert "코드 검증 실패" not in prompts[0]
    assert "이전 판정의 코드 검증 실패: sheet1:R4 spent_on" in prompts[1]
    mapped = payload(tmp_path, "headermap")
    if recovers:
        assert mapped["unresolved"] == []
        assert [item["source_hash"] for item in mapped["mappings"]] == [source]
    else:
        assert mapped["mappings"] == []
        assert mapped["unresolved"] == [
            {"source_hash": source, "reason": "validation_failed", "detail": "sheet1:R4 spent_on"}
        ]


def test_rerun_reuses_recorded_answers_instead_of_asking_again(
    tmp_path: Path, configured: None
) -> None:
    """원본 해시와 호출 이력으로 자동 중복 호출을 막는다. 표마다 호출 한도는 실행을 넘어 남는다."""
    record_spending(tmp_path)
    (source,) = publish(tmp_path, ("1분기.xls", workbook(QUARTER)))
    wrong = header_answer(spent_on=4)
    assert run(tmp_path, "headermap", FakeModel(headers=[wrong, wrong])) == 0
    again = FakeModel(headers=[header_answer()])
    assert run(tmp_path, "headermap", again) == 0
    assert again.prompts == []
    assert payload(tmp_path, "headermap")["unresolved"][0]["reason"] == "validation_failed"
    history = tmp_path / DATA / "gwangju" / "headermap-answers-v1.jsonl"
    entries = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
    assert [entry["revision"] for entry in entries] == [1, 2]
    assert all(entry["value"]["answer"] == wrong for entry in entries)
    assert source[:16] in entries[0]["evidence"]


def test_truncated_reply_is_recorded_and_not_asked_again_automatically(
    tmp_path: Path, configured: None
) -> None:
    """잘린 응답은 자동 재호출하지 않고 파일 단위 미해결로 남긴다. 다음 실행도 과금하지 않는다."""
    record_spending(tmp_path)
    (source,) = publish(tmp_path, ("1분기.xls", workbook(QUARTER)))
    truncated = gemini_reply(header_answer(), finish_reason="MAX_TOKENS")
    first = FakeModel(headers=[truncated, header_answer()])
    assert run(tmp_path, "headermap", first) == 0
    assert len(first.calls("headermap")) == 1
    expected = [{"source_hash": source, "reason": "incomplete_response", "detail": "sheet1"}]
    assert payload(tmp_path, "headermap")["unresolved"] == expected
    again = FakeModel(headers=[header_answer()])
    assert run(tmp_path, "headermap", again) == 0
    assert again.prompts == []
    assert payload(tmp_path, "headermap")["unresolved"] == expected


def test_card_layout_is_unsupported_without_a_retry(tmp_path: Path, configured: None) -> None:
    record_spending(tmp_path)
    (source,) = publish(tmp_path, ("카드형.xls", workbook(QUARTER)))
    card = {**header_answer(), "layout": "key_value"}
    model = FakeModel(headers=[card, header_answer()])
    assert run(tmp_path, "headermap", model) == 0
    assert len(model.calls("headermap")) == 1
    assert payload(tmp_path, "headermap")["unresolved"] == [
        {"source_hash": source, "reason": "unsupported_layout", "detail": "sheet1"}
    ]


def test_same_header_at_different_rows_reuses_the_cache_without_churn(
    tmp_path: Path, configured: None
) -> None:
    """같은 헤더가 원본마다 다른 행에 있어도 캐시 변형을 모두 보고, 재실행에 이력을 늘리지 않음."""
    record_spending(tmp_path)
    shifted = [(), *QUARTER]
    publish(
        tmp_path,
        ("3행 헤더.xls", workbook(QUARTER)),
        ("4행 헤더.xls", workbook(shifted)),
        (
            "3행 헤더 다른 부서.xls",
            workbook(sheet_a(("2026-03-02", "합성 국밥", "협의", 3.0, 27000.0))),
        ),
        (
            "4행 헤더 다른 부서.xls",
            workbook([(), *sheet_a(("2026-03-03", "합성 칼국수", "협의", 2.0, 18000.0))]),
        ),
    )
    model = FakeModel(headers=[header_answer(), header_answer(header=4)])
    assert run(tmp_path, "headermap", model) == 0
    assert len(model.calls("headermap")) == 2
    assert payload(tmp_path, "headermap")["unresolved"] == []
    cache = tmp_path / DATA / "_shared" / "headermap.jsonl"
    before = cache.read_text(encoding="utf-8")
    again = FakeModel()
    assert run(tmp_path, "headermap", again) == 0
    assert again.prompts == []
    assert cache.read_text(encoding="utf-8") == before
    assert len(before.splitlines()) == 2


def test_recorded_answer_that_validates_is_used_without_a_model(
    tmp_path: Path, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_spending(tmp_path)
    publish(tmp_path, ("1분기.xls", workbook(QUARTER)))
    assert run(tmp_path, "headermap", FakeModel(headers=[header_answer()])) == 0
    (tmp_path / DATA / "_shared" / "headermap.jsonl").unlink()
    monkeypatch.delenv("GEMINI_API_KEY")
    assert run(tmp_path, "headermap") == 0
    assert payload(tmp_path, "headermap")["unresolved"] == []


@pytest.mark.parametrize(
    ("setup", "reason"),
    [("no_model", "model_not_configured"), ("no_prior_usage", "unknown_prior_usage")],
)
def test_mapping_that_cannot_be_requested_leaves_the_original_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setup: str, reason: str
) -> None:
    if setup == "no_prior_usage":
        monkeypatch.setenv("GEMINI_API_KEY", "합성-제미나이-키")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-3.6-flash")
        monkeypatch.setenv("GEMINI_INPUT_USD_PER_MTOK", "1.50")
        monkeypatch.setenv("GEMINI_OUTPUT_USD_PER_MTOK", "7.50")
    (source,) = publish(tmp_path, ("1분기.xls", workbook(QUARTER)))
    model = FakeModel(headers=[header_answer()])
    assert run(tmp_path, "headermap", model) == 0
    assert model.prompts == []
    assert payload(tmp_path, "headermap")["unresolved"] == [
        {"source_hash": source, "reason": reason, "detail": "sheet1"}
    ]
    assert run(tmp_path, "parse") == 0
    parsed = payload(tmp_path, "parse")
    assert parsed["empty_reason"] == "no records in the reporting period"
    assert parsed["sources"][0]["status"] == "unresolved"
    assert records(tmp_path) == []


def test_unsupported_original_is_not_sent_to_the_model(tmp_path: Path, configured: None) -> None:
    record_spending(tmp_path)
    (source,) = publish(tmp_path, ("집행내역.pdf", b"%PDF-1.7 synthetic"))
    model = FakeModel()
    assert run(tmp_path, "headermap", model) == 0
    assert model.prompts == []
    assert payload(tmp_path, "headermap")["unresolved"] == [
        {"source_hash": source, "reason": "unsupported_format", "detail": ""}
    ]


@pytest.mark.parametrize(
    ("row", "detail"),
    [
        (("2026-13-40", "합성 식당", "협의", 4.0, 62000.0), "sheet1:R4 spent_on"),
        (("2026-01-05", "", "협의", 4.0, 62000.0), "sheet1:R4 merchant"),
        (("2026-01-05", "합성 식당", "협의", 4.0, "육만원"), "sheet1:R4 amount_krw"),
    ],
)
def test_one_unreadable_candidate_fails_the_whole_original(
    tmp_path: Path, configured: None, row: tuple, detail: str
) -> None:
    record_spending(tmp_path)
    sheet = sheet_a(row, ("2026-01-06", "합성 국밥", "협의", 3.0, 27000.0), total=False)
    (source,) = publish(tmp_path, ("1분기.xls", workbook(sheet)))
    model = FakeModel(headers=[header_answer(), header_answer()])
    assert run(tmp_path, "headermap", model) == 0
    assert payload(tmp_path, "headermap")["unresolved"] == [
        {"source_hash": source, "reason": "validation_failed", "detail": detail}
    ]


def test_empty_table_is_not_treated_as_no_spending(tmp_path: Path, configured: None) -> None:
    record_spending(tmp_path)
    (source,) = publish(tmp_path, ("빈 표.xls", workbook(sheet_a(total=False))))
    model = FakeModel(headers=[header_answer()])
    assert run(tmp_path, "headermap", model) == 0
    assert run(tmp_path, "parse") == 0
    (report,) = payload(tmp_path, "parse")["sources"]
    assert (report["status"], report["reason"], report["candidates"]) == (
        "unresolved",
        "no_candidates",
        0,
    )


def test_parse_counts_why_each_original_was_left_out_of_the_submission(
    tmp_path: Path, configured: None
) -> None:
    """장부는 11개를 그대로 싣고, 대상에서 뺀 이유는 사유별 수로 남는다."""
    record_spending(tmp_path)
    posts = (
        Post(
            100,
            "2026년 1분기 업무추진비 집행내역(합성과)",
            "합성과",
            datetime(2026, 4, 1).date(),
            (("1분기.xls", workbook(QUARTER, [])),),
        ),
        Post(
            99,
            "2025년 4분기 업무추진비 집행내역(합성과)",
            "합성과",
            datetime(2026, 1, 8).date(),
            (("작년 4분기.xls", workbook(QUARTER, [])),),
        ),
        Post(
            98,
            "업무추진비 공개 안내",
            "합성과",
            datetime(2026, 5, 1).date(),
            (("안내.xls", workbook(QUARTER, [])),),
        ),
        Post(
            97,
            "2024년 1분기 업무추진비 집행내역(합성과)",
            "합성과",
            datetime(2024, 3, 2).date(),
            (("2024.xls", workbook(QUARTER, [])),),
        ),
        Post(
            96,
            "2023년 업무추진비 집행내역(합성과)",
            "합성과",
            datetime(2023, 2, 2).date(),
            (("2023.xls", workbook(QUARTER, [])),),
        ),
    )
    assert run(tmp_path, "fetch", board=FakeBoardTransport(posts)) == 0
    assert len(payload(tmp_path, "fetch")["sources"]) == 5

    assert run(tmp_path, "headermap", FakeModel(headers=[header_answer()])) == 0
    assert run(tmp_path, "parse") == 0

    parsed = payload(tmp_path, "parse")
    assert parsed["excluded_sources"] == {
        "posted_out_of_range": 2,
        "declared_out_of_range": 1,
        "undeclared_in_year": 1,
    }
    # 대상 하나만 읽었고 수집 장부는 줄지 않았다.
    assert len(parsed["sources"]) == 1
    assert len(payload(tmp_path, "fetch")["sources"]) == 5


def test_a_parse_artifact_from_the_previous_schema_asks_for_a_rerun(
    tmp_path: Path, configured: None, capsys: pytest.CaptureFixture[str]
) -> None:
    record_spending(tmp_path)
    publish(tmp_path, ("1분기.xls", workbook(QUARTER, [])))
    assert run(tmp_path, "headermap", FakeModel(headers=[header_answer()])) == 0
    assert run(tmp_path, "parse") == 0

    path = tmp_path / DATA / "gwangju" / "parse.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["schema_version"] -= 1
    del envelope["payload"]["excluded_sources"]
    write_text(path, json.dumps(envelope, ensure_ascii=False))

    assert run(tmp_path, "classify") == 1
    assert "cause=regeneration-required" in capsys.readouterr().err
