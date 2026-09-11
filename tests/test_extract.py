"""표 하나의 추출·검증 규칙. 실제 원본에서 본 행 모양을 합성 값으로 재현한다."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from deliciousmap.contracts import HeaderMap, SourceRef
from deliciousmap.extract import ValidationFailed, extract, parse_date
from deliciousmap.grid import Cell, Table

SOURCE = SourceRef(
    path=Path("gwangju/gwangju-city/expenses/1-1.xls"),
    source_hash="c" * 64,
    organization="gwangju-city",
    board="expenses",
    url="https://example.invalid/1",
    container="ole2",
    department="합성과",
)
HEADER: tuple[Cell, ...] = ("사용자", "사용일시", "사용장소", "집행목적", "금액")
MAPPING = HeaderMap(
    source_hash="c" * 64,
    table="sheet1",
    layout="table",
    header_rows=(2,),
    data_start_row=3,
    columns={"spent_on": 1, "merchant": 2, "purpose": 3, "amount_krw": 4},
    amount_multiplier=Decimal(1),
)


def table(*rows: tuple[Cell, ...]) -> Table:
    return Table("sheet1", "시트", (("□ 합성과 업무추진비",), HEADER, *rows))


def spend(day: int, merchant: str, amount: float) -> tuple[Cell, ...]:
    return ("과장", f"2026-01-{day:02d} 12:00", merchant, "간담회", amount)


@pytest.mark.parametrize(
    "terminator",
    [
        ("", "", "", "이", "하", "빈", "칸"),
        ("", "", "", "이하 없음."),
        ("", "", "이하 여백", "", ""),
        ("", "", ".", "", ""),
    ],
)
def test_terminator_and_punctuation_rows_are_not_expenses(terminator: tuple[Cell, ...]) -> None:
    result = extract(table(spend(5, "합성 식당", 62000.0), terminator), MAPPING, SOURCE)
    assert result.candidates == 1
    # 분모에서 뺀 행은 위치와 종류를 남긴다.
    assert result.excluded == ("sheet1:R4 blank",)


def test_zero_and_negative_amounts_are_kept_and_flagged_for_review() -> None:
    result = extract(
        table(spend(5, "합성 식당", 62000.0), spend(6, "합성 식당", -62000.0),
              spend(7, "합성 카페", 0.0)),
        MAPPING,
        SOURCE,
    )  # fmt: skip
    assert [str(record.amount_krw) for record in result.records] == ["62000", "-62000", "0"]
    assert result.review == ("sheet1:R4 non_positive_amount", "sheet1:R5 non_positive_amount")


def test_department_falls_back_to_the_source_when_the_table_has_no_such_column() -> None:
    """표에 부서 열이 없으면 출처가 밝힌 작성 부서로 보완한다. 둘 다 없으면 비운다."""
    result = extract(table(spend(5, "합성 식당", 62000.0)), MAPPING, SOURCE)
    assert [record.department for record in result.records] == ["합성과"]
    without = SOURCE.model_copy(update={"department": None})
    assert [
        record.department
        for record in extract(table(spend(5, "합성 식당", 62000.0)), MAPPING, without).records
    ] == [""]


def test_prefixed_subtotals_are_excluded_and_the_grand_total_is_checked() -> None:
    result = extract(
        table(
            spend(5, "합성 식당", 62000.0),
            ("", "1월 소계", "", "", 62000.0),
            spend(6, "합성 국밥", 27000.0),
            ("", "소 계", "", "", 27000.0),
            ("", "합 계", "", "2건", 89000.0),
        ),
        MAPPING,
        SOURCE,
    )
    assert (result.candidates, len(result.excluded), result.total_check) == (2, 3, "matched")


def test_unlabeled_total_row_is_recognized_by_its_count() -> None:
    result = extract(
        table(spend(5, "합성 식당", 62000.0), ("", "", "", "1건", 62000.0)), MAPPING, SOURCE
    )
    assert (result.candidates, result.total_check) == (1, "matched")


def test_stale_count_in_the_total_row_does_not_fail_a_matching_amount() -> None:
    result = extract(
        table(spend(5, "합성 식당", 62000.0), spend(6, "합성 국밥", 27000.0),
              ("", "계", "", "52건", 89000.0)),
        MAPPING,
        SOURCE,
    )  # fmt: skip
    assert result.total_check == "matched"


def test_amount_mismatch_still_fails() -> None:
    with pytest.raises(ValidationFailed, match="sheet1:R5 total amount mismatch"):
        extract(
            table(spend(5, "합성 식당", 62000.0), spend(6, "합성 국밥", 27000.0),
                  ("", "계", "", "", 62000.0)),
            MAPPING,
            SOURCE,
        )  # fmt: skip


@pytest.mark.parametrize("label", ["누계", "1월 누계", "1월 합계", "1분기 계", "1~3월 합계"])
def test_totals_with_an_unclear_scope_are_not_compared(label: str) -> None:
    """누계·기간 합계는 이전 표까지 더했을 수 있어 범위를 확정할 수 없다. 대조 불가로 남긴다."""
    result = extract(
        table(spend(5, "합성 식당", 62000.0), ("", label, "", "", 999999.0)), MAPPING, SOURCE
    )
    assert (result.candidates, result.excluded, result.total_check) == (
        1,
        ("sheet1:R4 unclear_total",),
        "ambiguous",
    )


def test_expense_before_the_data_start_fails_instead_of_being_skipped() -> None:
    """다른 표에서 배운 데이터 시작 위치가 이 표의 첫 지출을 건너뛰게 두지 않는다."""
    late = MAPPING.model_copy(update={"data_start_row": 4})
    with pytest.raises(ValidationFailed, match="sheet1:R3 expense before data start"):
        extract(table(spend(5, "합성 식당", 62000.0), spend(6, "합성 국밥", 27000.0)), late, SOURCE)
    # 헤더와 첫 지출 사이의 요약 행은 건너뛰어도 된다.
    summary = table(("", "계", "", "1건", 27000.0), spend(6, "합성 국밥", 27000.0))
    assert extract(summary, late, SOURCE).total_check == "matched"


def test_each_section_is_checked_against_its_own_total() -> None:
    """한 시트에 헤더를 되풀이한 두 구역이 있고, 구역마다 헤더 바로 아래에 계가 있다."""
    sheet = Table(
        "sheet1",
        "시트",
        (
            ("□ 합성과 업무추진비",),
            ("1) 시책업무추진비",),
            HEADER,
            ("", "계", "", "2건", 89000.0),
            spend(5, "합성 식당", 62000.0),
            spend(6, "합성 국밥", 27000.0),
            ("2) 기관운영업무추진비",),
            HEADER,
            ("", "계", "", "1건", 15000.0),
            spend(7, "합성 카페", 15000.0),
        ),
    )
    mapping = MAPPING.model_copy(update={"header_rows": (3,), "data_start_row": 5})
    result = extract(sheet, mapping, SOURCE)
    assert (result.candidates, result.total_check) == (3, "matched")
    broken = Table("sheet1", "시트", (*sheet.rows[:-1], spend(7, "합성 카페", 16000.0)))
    with pytest.raises(ValidationFailed, match="R9 total amount mismatch"):
        extract(broken, mapping, SOURCE)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("'25. 10. 17. 12:15", date(2025, 10, 17)),
        ("2026.3.4.(수)", date(2026, 3, 4)),
        ("26. 2. 27.(화) 12:47", date(2026, 2, 27)),
        ("2026/02/25 19:03", date(2026, 2, 25)),
        ("2026-04-9\n12:04", date(2026, 4, 9)),
    ],
)
def test_dates_seen_in_real_originals(value: str, expected: date) -> None:
    assert parse_date(value) == expected
