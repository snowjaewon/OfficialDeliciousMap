"""합쳐 적은 상호를 사람 확인으로 가르는 일을 공개 CLI와 산출물로 관찰한다.

[#117](https://github.com/snowjaewon/OfficialDeliciousMap/issues/117)의 계약이다. 규칙은
조회만 나누어 해 보고, 레코드를 가르는 것은 `data/manual/<city>/merchants.jsonl`의 확인뿐이다.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from deliciousmap import merchants
from deliciousmap.contracts import ParseOutput
from deliciousmap.pipeline import ExecutionContext
from deliciousmap.storage import ArtifactStore, read_records, write_text
from tests.fakes import FakeTransport, naver_body
from tests.gwangju import FakeModel, header_answer, sheet_a, workbook
from tests.test_geocoding_cli import (
    confirmation_file,
    lookup,
    payload,
    prepare,
    run_cli,
    save_input,
)
from tests.test_naver_lookup_cli import run_cli as run_lookup_cli
from tests.test_parse_cli import DATA, publish, record_spending, records, run
from tests.test_parse_cli import payload as parse_payload
from tests.test_restoration_cli import classify_records

MERGED = "시골밥집, 데이지"
ONE_PLACE = "본죽&비빔밥"
PRICED = "낙지촌 96,000원 / 엠지(MG)블루 17,500"


def save_merchants(root: Path, *entries: dict) -> None:
    write_text(
        root / DATA / "manual" / "gwangju" / "merchants.jsonl",
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
    )


def merchant_entry(merchant: str, merchants: list[str], **overrides: object) -> dict:
    entry: dict = {
        "schema_version": 1,
        "scope": {
            "city": "gwangju",
            "merchant": merchant,
            "organization": None,
            "source_hash": None,
            "record_id": None,
        },
        "merchants": merchants,
        "evidence": "원본 한 행의 상호 칸에 업소 둘이 적힌 것을 게시 원문에서 확인",
        "references": [],
    }
    entry.update(overrides)
    return entry


def parse_merged(root: Path) -> None:
    """합쳐 적은 상호 한 건과 구분자가 든 한 업소 한 건을 원본에서 읽는다."""
    record_spending(root)
    publish(
        root,
        (
            "1분기.xls",
            workbook(
                sheet_a(
                    ("2026-01-05", MERGED, "현안 업무 협의 간담회", 4.0, 62000.0),
                    ("2026-01-06", ONE_PLACE, "직원 격려 다과", 3.0, 27000.0),
                )
            ),
        ),
    )
    assert run(root, "headermap", FakeModel(headers=[header_answer()])) == 0


def totals(root: Path) -> Decimal:
    """커밋된 장부에서 다시 센 지출 총액. 세는 규칙은 운영 코드의 것을 그대로 쓴다."""
    return merchants.expense_total(read_records(root / DATA / "gwangju" / "records.csv"))


def test_without_confirmation_a_merged_merchant_stays_one_record(
    tmp_path: Path, configured: None
) -> None:
    parse_merged(tmp_path)
    assert run(tmp_path, "parse") == 0
    rows = records(tmp_path)
    assert [(row["merchant"], row["amount_krw"]) for row in rows] == [
        (MERGED, "62000"),
        (ONE_PLACE, "27000"),
    ]
    assert {row["expense_id"] for row in rows} == {""}
    assert totals(tmp_path) == Decimal(89000)


def test_confirmed_two_merchants_split_the_expense_and_leave_both_amounts_empty(
    tmp_path: Path, configured: None
) -> None:
    parse_merged(tmp_path)
    assert run(tmp_path, "parse") == 0
    before = totals(tmp_path)

    save_merchants(tmp_path, merchant_entry(MERGED, ["시골밥집", "데이지"]))
    assert run(tmp_path, "parse") == 0
    rows = records(tmp_path)
    assert [(row["merchant"], row["amount_krw"]) for row in rows] == [
        ("시골밥집", ""),
        ("데이지", ""),
        (ONE_PLACE, "27000"),
    ]
    # 나뉜 두 레코드는 같은 지출을 가리키고, 금액은 그 지출에 그대로 남는다(ADR-0007).
    assert rows[0]["expense_id"] == rows[1]["expense_id"] != ""
    assert rows[0]["expense_amount_krw"] == rows[1]["expense_amount_krw"] == "62000"
    assert len({row["record_id"] for row in rows}) == 3
    assert totals(tmp_path) == before == Decimal(89000)
    report = parse_payload(tmp_path, "parse")["sources"][0]
    assert (report["candidates"], report["records"]) == (2, 3)


def test_confirmed_single_merchant_does_not_split_the_record(
    tmp_path: Path, configured: None
) -> None:
    parse_merged(tmp_path)
    save_merchants(tmp_path, merchant_entry(ONE_PLACE, [ONE_PLACE]))
    assert run(tmp_path, "parse") == 0
    rows = records(tmp_path)
    assert [(row["merchant"], row["amount_krw"]) for row in rows] == [
        (MERGED, "62000"),
        (ONE_PLACE, "27000"),
    ]
    # 한 업소라는 확인도 판정이므로 그 지출은 가르지 못한 것으로 세지 않는다.
    assert rows[1]["expense_id"] != ""
    assert totals(tmp_path) == Decimal(89000)


def test_a_single_merchant_line_cannot_rename_the_record(tmp_path: Path, configured: None) -> None:
    """상호 복원은 파일도 의미도 다르다. 확인 줄로 이름을 바꾸지 않는다."""
    parse_merged(tmp_path)
    save_merchants(tmp_path, merchant_entry(ONE_PLACE, ["본죽"]))
    assert run(tmp_path, "parse") == 1


def merged_records(tmp_path: Path, **changes: object) -> ExecutionContext:
    """geocode가 볼 레코드 하나를 바꾸어 다시 저장하고 판별도 다시 남긴다."""
    context = prepare(tmp_path)
    store = ArtifactStore(context.paths, context.target)
    record = store.load("parse", ParseOutput).records[0]
    store.save("parse", ParseOutput(records=(record.model_copy(update=changes),)))
    classify_records(context)
    return context


def empty_lookup() -> dict:
    query = lookup()
    query["facts"] = []
    query["candidates"] = []
    return query


def reason(context: ExecutionContext) -> str:
    return payload(context, "geocode")["results"][0]["reason"]


def test_a_merged_merchant_without_confirmation_is_held_not_reported_as_no_candidates(
    tmp_path: Path,
) -> None:
    context = merged_records(tmp_path, merchant=MERGED)
    save_input(context, empty_lookup())
    assert run_cli(context, "geocode") == 0
    assert reason(context) == "merged_merchant"


def test_a_record_without_a_separator_keeps_its_own_reason(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    save_input(context, empty_lookup())
    assert run_cli(context, "geocode") == 0
    assert reason(context) == "no_candidates"


def test_a_confirmed_merchant_keeps_its_own_reason(tmp_path: Path) -> None:
    """한 업소라는 확인이 붙은 레코드는 합쳐 적은 상호로 보류하지 않는다."""
    context = merged_records(
        tmp_path,
        merchant=ONE_PLACE,
        expense={"expense_id": "r1", "amount_krw": "1000"},
    )
    save_input(context, empty_lookup())
    assert run_cli(context, "geocode") == 0
    assert reason(context) == "no_candidates"


def test_a_matched_merchant_with_a_separator_stays_matched(tmp_path: Path) -> None:
    """기존 확정은 하나도 바뀌지 않는다. 구분자가 있어도 근거가 맞으면 확정이다."""
    context = merged_records(tmp_path, merchant=ONE_PLACE)
    query = lookup()
    query["facts"][0]["merchant"] = ONE_PLACE
    query["candidates"][0]["merchant"] = ONE_PLACE
    save_input(context, query)
    assert run_cli(context, "geocode") == 0
    assert reason(context) == "matched"


def test_a_human_confirmed_place_with_a_separator_stays_confirmed(tmp_path: Path) -> None:
    """사람이 확정한 업소는 상호에 구분자가 있어도 그대로 확정이다."""
    context = merged_records(tmp_path, merchant=ONE_PLACE)
    query = lookup()
    query["facts"] = []
    save_input(context, query)
    write_text(
        confirmation_file(context),
        json.dumps(
            {
                "scope": {"city": "seoul", "merchant": ONE_PLACE},
                "candidate_source": query["candidates"][0]["source"],
                "merchant": "같은 식당",
                "branch": "부산점",
                "address": "부산 합성로 10",
                "evidence": "게시 원문과 지역검색 후보의 주소가 같은 업소임을 대조",
                "references": [],
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    assert run_cli(context, "geocode") == 0
    assert reason(context) == "human_confirmed"


def test_a_lookup_failure_is_never_hidden_behind_the_merged_merchant_hold(
    tmp_path: Path,
) -> None:
    """제공자 장애를 보류로 바꾸면 실행이 종료 0으로 지나간다."""
    context = merged_records(tmp_path, merchant=MERGED)
    broken = lookup()
    broken["status"] = "error"
    broken["error"] = "unavailable"
    broken["facts"] = []
    broken["candidates"] = []
    save_input(context, broken)
    assert run_cli(context, "geocode") == 1
    assert reason(context) == "lookup_error"


def test_the_thousand_separator_does_not_split_the_lookup_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_ID", "합성-검색-아이디")
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_SECRET", "합성-검색-비밀값")
    context = merged_records(tmp_path, merchant=PRICED)
    save_input(context, empty_lookup())
    transport = FakeTransport(naver_body(), naver_body(), naver_body())
    assert run_lookup_cli(context, "geocode", transport=transport) == 0
    # 나눈 이름은 조회만 더 해 캐시에 쌓는다. 판정은 그대로 보류다.
    assert [item["query"] for item in transport.requests] == [
        PRICED,
        "낙지촌 96,000원",
        "엠지(MG)블루 17,500",
    ]
    assert reason(context) == "merged_merchant"


def divided_build(tmp_path: Path) -> ExecutionContext:
    """같은 지출에서 나뉜 레코드 둘 가운데 하나만 좌표를 받은 제출."""
    context = prepare(tmp_path)
    store = ArtifactStore(context.paths, context.target)
    record = store.load("parse", ParseOutput).records[0]
    expense = {"expense_id": "r1", "amount_krw": "62000"}
    store.save(
        "parse",
        ParseOutput(
            records=(
                record.model_copy(
                    update={"record_id": "r1#1", "amount_krw": None, "expense": expense}
                ),
                record.model_copy(
                    update={
                        "record_id": "r1#2",
                        "merchant": "합쳐 적힌 다른 업소",
                        "amount_krw": None,
                        "expense": expense,
                        "source_location": "sheet1:R2b",
                    }
                ),
            )
        ),
    )
    classify_records(context)
    first = lookup()
    first["scope"]["record_id"] = "r1#1"
    second = empty_lookup()
    second["scope"]["record_id"] = "r1#2"
    save_input(context, first, second)
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0
    return context


def test_marker_detail_tells_how_many_visits_have_no_amount(tmp_path: Path) -> None:
    """금액 미상 방문을 밝히지 않으면 합계가 방문 전부를 더한 값으로 읽힌다(ADR-0007)."""
    context = divided_build(tmp_path)
    directory = context.paths.output_root / context.target.city.slug
    [marker] = json.loads((directory / "markers.json").read_text(encoding="utf-8"))["markers"]
    assert (marker["visit_count"], marker["unpriced_visit_count"]) == (1, 1)
    assert marker["total_amount_krw"] == "0"
    ledger = json.loads((directory / "records.json").read_text(encoding="utf-8"))["records"]
    assert [item["amount_krw"] for item in ledger] == [None, None]


def test_coverage_reports_the_expenses_it_could_not_split_by_merchant(tmp_path: Path) -> None:
    context = merged_records(tmp_path, merchant=MERGED)
    save_input(context, empty_lookup())
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0
    page = (context.paths.output_root / "seoul" / "index.html").read_text(encoding="utf-8")
    assert "상호 칸에 업소 둘 이상이 적힌 지출 1건은 사람 확인 전이라" in page
    assert "업소별로 가르지 못하고 레코드 하나로 남습니다" in page
    # 지도에 오르지 못한 수는 사유별 줄이 따로 낸다. 이 줄이 그 말을 대신하지 않는다.
    assert "합쳐 적은 상호 1건" in page
