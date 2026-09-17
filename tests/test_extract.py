"""표 하나의 추출·검증 규칙. 실제 원본에서 본 행 모양을 합성 값으로 재현한다."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from deliciousmap.contracts import (
    ExpenseScope,
    HeaderMap,
    Record,
    RecordOrigin,
    RepeatConfirmation,
    RepeatDecision,
    RepeatedExpenses,
    SourceRef,
    SpentOn,
)
from deliciousmap.extract import ValidationFailed, extract, merge_repeats, parse_spent_on
from deliciousmap.grid import Cell, Span, Table

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


def table(*rows: tuple[Cell, ...], spans: tuple[Span, ...] = ()) -> Table:
    return Table("sheet1", "시트", (("□ 합성과 업무추진비",), HEADER, *rows), spans)


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


def test_merged_cells_are_read_from_the_row_that_holds_them() -> None:
    """2026-09-13 남구 실측: 한 지출의 일자·목적이 다음 행과 세로로 병합되어 있다.

    이어짐 행이 병합의 값을 읽는 것은 추측이 아니라 원본을 보이는 대로 읽는 일이다.
    날짜 열에 한정하지 않는다 — 같은 병합이 덮은 집행목적도 함께 이어받는다.
    """
    sheet = table(
        ("과장", "2026-03-17 12:30", "합성 식당", "간담회", 62000.0),
        ("과장", "", "합성 찻집", "", 27000.0),
        spans=(Span(4, 1, 3), Span(4, 3, 3)),
    )
    result = extract(sheet, MAPPING, SOURCE)
    assert [record.spent_on for record in result.records] == [SpentOn(2026, 3, 17)] * 2
    assert [record.purpose for record in result.records] == ["간담회"] * 2
    assert [record.merchant for record in result.records] == ["합성 식당", "합성 찻집"]


def test_a_blank_date_that_is_not_merged_is_still_unreadable() -> None:
    """병합이 아닌 그냥 빈 칸은 읽지 않는다. 위 행의 날짜를 가져다 쓰면 추측이 된다."""
    sheet = table(
        ("과장", "2026-03-17 12:30", "합성 식당", "간담회", 62000.0),
        ("과장", "", "합성 찻집", "", 27000.0),
    )
    with pytest.raises(ValidationFailed, match="R4 spent_on"):
        extract(sheet, MAPPING, SOURCE)


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


def test_ceremonial_payment_without_a_place_is_kept_as_a_masked_payee() -> None:
    """2026-09-13 북구 실측: 애경사 축·조의금은 상호 칸이 아예 비어 있다. 받는 사람이 개인이다.

    지출은 실제로 있었으므로 장부에서 지우지 않고 가린 표시로 남긴다(#51 사용자 결정과 같다).
    """
    purpose = "2026. 1월중 소속직원 애경사 축·조의금 지급"
    ceremony = ("과장", "2026-01-20 00:00", "", purpose, 350000.0)
    (record,) = extract(table(ceremony), MAPPING, SOURCE).records
    assert record.merchant == "개인(성명 비공개)"
    assert record.purpose == purpose
    # 경조사가 아닌데 상호가 비어 있으면 그대로 실패한다. 무엇이 빠졌는지 알 수 없다.
    with pytest.raises(ValidationFailed, match="sheet1:R3 merchant"):
        extract(table(("과장", "2026-01-20 00:00", "", "간담회", 350000.0)), MAPPING, SOURCE)


def test_section_title_in_the_date_column_is_not_an_expense() -> None:
    """2026-09-13 북구 실측: 구역 제목이 날짜 열에 온다. 상호도 금액도 없으면 지출이 아니다."""
    result = extract(
        table(spend(5, "합성 식당", 62000.0), ("", "○ 구정현안 시책추진"),
              spend(6, "합성 국밥", 27000.0)),
        MAPPING,
        SOURCE,
    )  # fmt: skip
    assert (result.candidates, result.excluded) == (2, ("sheet1:R4 note",))


@pytest.mark.parametrize(
    "row",
    [
        # 2026-09-17 대구 실측. 구역에 집행이 없다는 표기를 글자마다 칸을 나눠 적거나
        # 구역 딱지·연번과 함께 적는다. 금액이 없거나 0이고 집행일도 없다.
        ("1", "해", "당", "없", "음"),
        ("시책추진 (203-03)", "해", "당", "없", "음"),
        ("차 및 음료 등", "", "해당없음", "", 0.0),
        ("업무추진회의 행사, 간담회 등", "", "이하 빈칸", "", ""),
        ("", "내", "용", "없", "음"),
        ("회의 및 간담회", "집", "행내", "역없", "음"),
        ("회의 및 간담회", "-", "없음", "-", 0.0),
    ],
)
def test_a_no_spending_note_beside_a_section_label_is_not_an_expense(
    row: tuple[Cell, ...],
) -> None:
    result = extract(
        table(spend(5, "합성 식당", 62000.0), row, ("", "합 계", "", "", 62000.0)),
        MAPPING,
        SOURCE,
    )
    assert (result.candidates, result.excluded, result.total_check) == (
        1,
        ("sheet1:R4 note", "sheet1:R5 total"),
        "matched",
    )


@pytest.mark.parametrize(
    ("row", "item"),
    [
        # 집행일이 읽히면 지출이다. 상호에 `없음`이 들어 있어도 지운 행으로 보지 않는다.
        (("과장", "2026-01-06 12:00", "걱정없음 식당", "간담회", 0.0), None),
        # 날짜 칸에 숫자가 있으면 지출 후보로 남는다. 연도 근거 없이는 읽히지 않는 표기
        # (`260106`)라도 집행 없음 표기로 지우지 않고 집행일 실패로 알린다.
        (("과장", "260106", "합성 식당", "특이사항 없음", 0.0), "spent_on"),
        # 금액이 있으면 집행 없음 표기가 아니다. 날짜를 못 읽은 지출로 남는다.
        (("과장", "", "해당없음", "간담회", 27000.0), "spent_on"),
    ],
)
def test_a_no_spending_phrase_does_not_hide_a_dated_or_paid_row(
    row: tuple[Cell, ...], item: str | None
) -> None:
    sheet = table(spend(5, "합성 식당", 62000.0), row)
    if item is None:
        assert extract(sheet, MAPPING, SOURCE).candidates == 2
    else:
        with pytest.raises(ValidationFailed, match=f"R4 {item}"):
            extract(sheet, MAPPING, SOURCE)


def test_total_row_with_only_an_amount_is_recognized_and_checked() -> None:
    """2026-09-13 광산구 실측: 헤더 바로 아래에 금액만 적은 합계 행이 온다. 딱지도 건수도 없다.

    집행일시·사용장소가 비어 있어 지출 1건일 수 없다. 합계로 보고 그 값을 대조한다.
    """
    result = extract(
        table(("", "", "", "", 89000.0), spend(5, "합성 식당", 62000.0),
              spend(6, "합성 국밥", 27000.0)),
        MAPPING,
        SOURCE,
    )  # fmt: skip
    assert (result.candidates, result.excluded, result.total_check) == (
        2,
        ("sheet1:R3 total",),
        "matched",
    )
    # 합이 맞지 않으면 지나가지 않는다.
    with pytest.raises(ValidationFailed, match="sheet1:R3 total amount mismatch"):
        extract(
            table(("", "", "", "", 88000.0), spend(5, "합성 식당", 62000.0),
                  spend(6, "합성 국밥", 27000.0)),
            MAPPING,
            SOURCE,
        )  # fmt: skip


@pytest.mark.parametrize(
    ("last_subtotal", "last_spend"),
    [
        (("", "", "", "1건", 27000.0), (spend(6, "합성 국밥", 27000.0),)),
        # 집행이 없는 마지막 구역의 소계(`0건 | 0`).
        (("", "", "", "0건", 0.0), ()),
    ],
)
def test_an_unlabeled_row_matching_the_spending_since_the_last_subtotal_is_a_subtotal(
    last_subtotal: tuple[Cell, ...], last_spend: tuple[tuple[Cell, ...], ...]
) -> None:
    """2026-09-17 수성구 실측: 구분마다 `소계`를 적다가 마지막 구분의 소계만 딱지를 빠뜨린다.

    그 행은 표 전체 합과 맞지 않지만 앞 소계 뒤의 지출 합과는 맞는다. 소계로 보고 넘긴다.
    """
    whole = 62000.0 + sum(float(row[4]) for row in last_spend)  # type: ignore[arg-type]
    result = extract(
        table(
            spend(5, "합성 식당", 62000.0),
            ("", "소계", "", "1건", 62000.0),
            *last_spend,
            last_subtotal,
            ("", "총 계", "", "", whole),
        ),
        MAPPING,
        SOURCE,
    )
    assert (result.candidates, result.total_check) == (1 + len(last_spend), "matched")


def test_an_unlabeled_row_matching_neither_the_table_nor_the_last_segment_fails() -> None:
    with pytest.raises(ValidationFailed, match="sheet1:R6 total amount mismatch"):
        extract(
            table(
                spend(5, "합성 식당", 62000.0),
                ("", "소계", "", "1건", 62000.0),
                spend(6, "합성 국밥", 27000.0),
                ("", "", "", "1건", 26000.0),
            ),
            MAPPING,
            SOURCE,
        )


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


def test_a_table_that_ends_before_the_learned_data_start_has_no_expense() -> None:
    """헤더만 있는 시트(대전 서구 실측)에 다른 표에서 배운 시작 위치가 표 밖을 가리킨다."""
    late = MAPPING.model_copy(update={"data_start_row": 4})
    found = extract(table(), late, SOURCE)
    assert (found.records, found.candidates, found.excluded) == ((), 0, ())


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
        ("'25. 10. 17. 12:15", SpentOn(2025, 10, 17)),
        ("2026.3.4.(수)", SpentOn(2026, 3, 4)),
        ("26. 2. 27.(화) 12:47", SpentOn(2026, 2, 27)),
        ("2026/02/25 19:03", SpentOn(2026, 2, 25)),
        ("2026-04-9\n12:04", SpentOn(2026, 4, 9)),
    ],
)
def test_dates_seen_in_real_originals(value: str, expected: SpentOn) -> None:
    assert parse_spent_on(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # 2026-09-13 광주 서구 실측: 날짜 서식이 아닌 칸에 든 엑셀 일련값. 정수부가 날짜이고
        # 소수부가 시각이다(46024.70763888889 = 2026-01-02 16:59).
        (46024.70763888889, SpentOn(2026, 1, 2)),
        (46114.0, SpentOn(2026, 4, 2)),
        # 일련값의 범위 밖은 날짜로 읽지 않는다. 금액·인원이 날짜가 되지 않게 한다.
        (2026.5, None),
        (99999.25, None),
    ],
)
def test_excel_serial_dates_carry_a_time_of_day(value: float, expected: SpentOn | None) -> None:
    """날짜 칸이 시각을 함께 담은 일련값으로 온다. 정수가 아니라고 날짜가 아닌 것은 아니다."""
    assert parse_spent_on(value) == expected


def test_month_and_day_with_a_time_are_not_read_as_a_two_digit_year() -> None:
    """2026-09-13 동구 실측: `03.03. 12:25`는 3월 3일 12시 25분이다. 2003년 3월 12일이 아니다.

    뒤에 시각이 붙은 표기를 두 자리 연도로 읽으면 연도가 통째로 어긋난 레코드가 조용히 생긴다.
    """
    assert parse_spent_on("03.03. 12:25", 2026) == SpentOn(2026, 3, 3)
    assert parse_spent_on("03.03. 12:25") is None
    # 두 자리 연도 표기는 그대로 읽는다. 시각이 붙어도 마지막 칸이 날짜다.
    assert parse_spent_on("26.01.26. 12:25", 2026) == SpentOn(2026, 1, 26)
    assert parse_spent_on("'25. 10. 17. 12:15") == SpentOn(2025, 10, 17)


def test_soft_hyphens_are_not_part_of_a_date() -> None:
    """2026-09-18 북구 실측: PDF가 `2026\u00ad04\u00ad14 12:40`처럼 보이지 않는 이음표를 싣는다.

    U+00AD는 줄을 나눌 때만 보이는 서식 글자다. 원본에 적힌 날짜는 2026년 4월 14일이며
    이 글자를 값으로 읽으면 그 원본 전체가 집행일 실패로 남는다.
    """
    assert parse_spent_on("2026\u00ad04\u00ad14 12:40") == SpentOn(2026, 4, 14)
    assert parse_spent_on("2026.\u00ad04.14.") == SpentOn(2026, 4, 14)


def test_repeated_separators_read_the_same_date() -> None:
    """2026-09-13 동구 실측: `2026..03.24.`는 구분자가 두 번 찍힌 오타다.

    같은 날짜를 같게 읽는 일이며 원본에 없는 값을 채우지 않는다.
    """
    assert parse_spent_on("2026..03.24.") == SpentOn(2026, 3, 24)
    assert parse_spent_on("2026. . 3. 24.") == SpentOn(2026, 3, 24)
    assert parse_spent_on("2026년 3월 24일") == SpentOn(2026, 3, 24)


def test_six_digit_dates_are_read_only_with_a_year_hint_that_matches() -> None:
    """2026-09-13 광산구 실측: 헤더 없는 표의 `260117`.

    금액도 여섯 자리가 흔해 연도 근거 없이는 여섯 자리를 날짜로 보지 않는다.
    """
    assert parse_spent_on("260117", 2026) == SpentOn(2026, 1, 17)
    assert parse_spent_on("260117") is None
    assert parse_spent_on("260117", 2025) is None
    # 같은 표의 금액 칸(`104000`). 연도 근거가 있어도 날짜가 되지 않는다.
    assert parse_spent_on("104000", 2026) is None
    assert parse_spent_on(104000.0, 2026) is None
    # 숫자 칸으로 온 같은 표기도 같게 읽는다.
    assert parse_spent_on(260117.0, 2026) == SpentOn(2026, 1, 17)


def test_three_digit_year_is_read_only_when_one_digit_makes_the_hint() -> None:
    """2026-09-13 서구 실측: `206/05/08`은 연도 한 자리가 빠져 어떤 연도로도 읽히지 않는 표기다.

    연도 근거에 한 자리를 끼워 넣어 정확히 같아질 때만 그 연도로 읽는다. 월·일은 고쳐 읽지 않는다.
    """
    assert parse_spent_on("206/05/08 20:41", 2026) == SpentOn(2026, 5, 8)
    assert parse_spent_on("206/05/08 20:41") is None
    assert parse_spent_on("205/05/08", 2026) is None
    # 네 자리로 적힌 연도는 근거와 달라도 그대로 읽는다(#119 결정). 기간 밖의 유효한 날짜를 고쳐
    # 읽지 않는 규칙 그대로이며, 2060년은 읽힌 뒤 기간 밖으로 걸러진다.
    assert parse_spent_on("2060/05/08", 2026) == SpentOn(2060, 5, 8)


def test_a_month_without_a_day_is_read_with_an_empty_day() -> None:
    """2026-09-13 동구 실측: 현금 경조사 지출의 일자 칸이 `2026.03.`처럼 달까지만 적혀 있다.

    오타가 아니라 원본이 일부러 비운 칸이다. 없는 일자를 그 달 1일·말일로 채우지 않고 빈 값으로
    두며, 사람이 보는 자리에는 원본 표기를 그대로 쓴다.
    """
    read = parse_spent_on("2026.03.")
    assert read == SpentOn(2026, 3)
    assert read is not None and read.day is None
    assert str(read) == "2026.03."
    # 일이 있는 표기는 지금과 같이 읽고 같게 보인다.
    assert parse_spent_on("2026.03.24.") == SpentOn(2026, 3, 24)
    assert str(parse_spent_on("2026.03.24.")) == "2026-03-24"


@pytest.mark.parametrize("value", ["2026.03.", "2026. 3.", "2026.03", "2026-03"])
def test_a_month_notation_comes_back_as_the_original_wrote_it(value: str) -> None:
    """마침표는 실측한 표기이고, 붙임표는 표기가 없을 때 집행일이 스스로 쓰는 모양이다."""
    assert parse_spent_on(value) == SpentOn(2026, 3)
    assert str(parse_spent_on(value)) == value


@pytest.mark.parametrize(
    "value", ["2026년 3월", "2026/3", "2026.", "2026", "202603", "104000", "13.5"]
)
def test_a_month_notation_that_was_not_measured_is_not_guessed(value: str) -> None:
    """실측하지 않은 구분자와 달을 적지 않은 값은 읽지 않는다. 여섯 자리 금액도 달이 아니다."""
    assert parse_spent_on(value) is None


def test_an_original_that_omits_one_day_still_yields_its_other_expenses() -> None:
    """일자 하나가 비었다고 그 원본 전체가 레코드를 내지 못하던 자리다(2026-09-13 동구 실측).

    현금으로 낸 부의금이라 장소 칸도 비어 있고 목적만 적혀 있다.
    """
    ceremony = ("과장", "2026.03.", "", "통합돌봄과 직원(부의금)지급", 50000.0)
    result = extract(table(ceremony, spend(5, "합성 식당", 62000.0)), MAPPING, SOURCE)
    assert [str(record.spent_on) for record in result.records] == ["2026.03.", "2026-01-05"]
    assert [record.merchant for record in result.records] == ["개인(성명 비공개)", "합성 식당"]
    assert result.candidates == 2


def test_a_yearless_date_takes_its_year_from_the_posting_title() -> None:
    """표에 제목 행이 없어 모델이 연도를 못 읽은 원본(대전 유성구 PDF 실측)."""
    yearless = ("구청장", "6월 5일", "합성 식당", "간담회", 62000.0)
    titled = SOURCE.model_copy(update={"title": "2026년 6월 단체장 업무추진비 집행내역"})
    result = extract(table(yearless), MAPPING, titled)
    assert [str(record.spent_on) for record in result.records] == ["2026-06-05"]
    # 제목이 기간을 밝히지 않으면 연도를 짐작하지 않는다.
    for title in (None, "업무추진비 집행내역"):
        with pytest.raises(ValidationFailed, match="spent_on"):
            extract(table(yearless), MAPPING, SOURCE.model_copy(update={"title": title}))


def test_a_month_only_expense_outside_the_period_is_kept_out_of_range() -> None:
    """달 단위 집행일도 대상 기간으로 가른다. 그 달의 구간이 겹쳐야 레코드가 된다."""
    result = extract(
        table(("과장", "2025.12.", "", "직원 부의금 지급", 50000.0),
              ("과장", "2026.03.", "", "직원 축의금 지급", 50000.0)),
        MAPPING,
        SOURCE,
    )  # fmt: skip
    assert (result.candidates, result.out_of_range) == (2, 1)
    assert [str(record.spent_on) for record in result.records] == ["2026.03."]


def original(number: int, posted: str) -> SourceRef:
    """게시일이 다른 합성 원본. 해시는 번호로 구별한다."""
    return SOURCE.model_copy(
        update={
            "source_hash": f"{number:x}" * 64,
            "path": Path(f"gwangju/gwangju-city/expenses/{number}-1.xls"),
            "posted": date.fromisoformat(posted),
        }
    )


def spent(
    source: SourceRef, row: int, day: int, merchant: str, amount: int, purpose: str = "간담회"
) -> Record:
    return Record(
        record_id=f"{source.source_hash[:16]}-sheet1-R{row}",
        spent_on=date(2026, 1, day),
        organization=source.organization,
        department="합성과",
        merchant=merchant,
        purpose=purpose,
        amount_krw=Decimal(amount),
        source_hash=source.source_hash,
        source_location=f"sheet1:R{row}",
    )


def test_cumulative_repost_keeps_the_first_publication_and_lists_the_later_original() -> None:
    """누적 파일이 앞 파일의 지출을 다시 실으면 반복된 지출은 한 건이다. 출처는 모두 남는다."""
    month, quarter = original(1, "2026-02-27"), original(2, "2026-04-15")
    records = (
        spent(month, 4, 5, "합성 식당", 62000),
        spent(month, 5, 6, "합성 카페", 9000),
        spent(quarter, 4, 5, "합성 식당", 62000),
        spent(quarter, 5, 6, "합성 카페", 9000),
        spent(quarter, 6, 20, "합성 국밥", 27000),
    )
    merged = merge_repeats(records, (month, quarter))
    assert [record.record_id for record in merged.records] == [
        records[0].record_id,
        records[1].record_id,
        records[4].record_id,
    ]
    assert merged.records[0].repeats == (
        RecordOrigin(source_hash=quarter.source_hash, location="sheet1:R4"),
    )
    assert merged.records[2].repeats == ()
    assert merged.tally == RepeatedExpenses(merged_expenses=2, merged_records=2)


def test_rewritten_purposes_do_not_keep_the_same_expense_twice() -> None:
    """재게시는 집행목적 표기를 다시 쓴다. 목적은 동일성 키가 아니다."""
    month, quarter = original(1, "2026-02-27"), original(2, "2026-04-15")
    records = (
        spent(month, 4, 5, "합성 식당", 62000, "현안 논의"),
        spent(month, 5, 6, "합성 카페", 9000, "직원 격려"),
        spent(quarter, 4, 5, "합성 식당", 62000, "현안 논의 간담회 비용 집행"),
        spent(quarter, 5, 6, "합성 카페", 9000, "직원 격려 다과 구입"),
        spent(quarter, 6, 20, "합성 국밥", 27000),
    )
    merged = merge_repeats(records, (month, quarter))
    assert [record.source_hash for record in merged.records] == [
        month.source_hash,
        month.source_hash,
        quarter.source_hash,
    ]
    assert merged.tally == RepeatedExpenses(merged_expenses=2, merged_records=2)


def test_reposted_month_only_expenses_merge_without_mixing_in_the_dated_ones() -> None:
    """달 단위 집행일도 같은 지출로 가린다. 일이 빈 날짜와 일이 있는 날짜는 같은 집행일이 아니다."""
    month, quarter = original(1, "2026-02-27"), original(2, "2026-04-15")
    ceremony = SpentOn(2026, 1, notation="2026.01.")
    records = (
        spent(month, 4, 5, "합성 식당", 62000).model_copy(update={"spent_on": ceremony}),
        spent(month, 5, 6, "합성 카페", 9000),
        spent(quarter, 4, 5, "합성 식당", 62000).model_copy(update={"spent_on": ceremony}),
        spent(quarter, 5, 6, "합성 카페", 9000),
        # 같은 달·상호·금액이지만 일이 적혀 있다. 앞의 지출과 같은 집행일이 아니다.
        spent(quarter, 6, 5, "합성 식당", 62000),
    )
    merged = merge_repeats(records, (month, quarter))
    assert [record.record_id for record in merged.records] == [
        records[0].record_id,
        records[1].record_id,
        records[4].record_id,
    ]
    assert merged.records[0].repeats == (
        RecordOrigin(source_hash=quarter.source_hash, location="sheet1:R4"),
    )
    assert merged.tally == RepeatedExpenses(merged_expenses=2, merged_records=2)


def test_repetition_inside_one_original_is_not_reduced() -> None:
    """한 장부가 같은 값을 두 번 적었으면 두 번 썼다고 말한 것이다(실측: 경조사 5만 원 두 건)."""
    source = original(1, "2026-02-27")
    records = (
        spent(source, 4, 7, "개인(성명 비공개)", 50000, "직원 부의금 지급"),
        spent(source, 5, 7, "개인(성명 비공개)", 50000, "직원 부의금 지급"),
    )
    merged = merge_repeats(records, (source,))
    assert merged.records == records
    assert merged.tally == RepeatedExpenses()


def test_a_single_shared_expense_is_left_alone_and_counted() -> None:
    """함께 싣는 지출이 1건뿐이면 재게시인지 별개 지출인지 가를 근거가 없다."""
    first, second = original(1, "2026-02-27"), original(2, "2026-03-06")
    records = (
        spent(first, 4, 5, "합성 식당", 62000),
        spent(first, 5, 6, "합성 카페", 9000),
        spent(second, 4, 5, "합성 식당", 62000),
        spent(second, 5, 7, "합성 국밥", 27000),
    )
    merged = merge_repeats(records, (first, second))
    assert merged.records == records
    assert all(record.repeats == () for record in merged.records)
    assert merged.tally == RepeatedExpenses(unmerged_expenses=1, unmerged_records=1)


def test_a_wholly_repeated_original_still_needs_two_shared_expenses() -> None:
    """한 건짜리 원본은 그 한 건이 다른 원본에 있으면 늘 포함이 된다. 그것은 근거가 아니다."""
    once, later = original(1, "2026-02-27"), original(2, "2026-04-15")
    records = (
        spent(once, 4, 5, "합성 식당", 62000),
        spent(later, 4, 5, "합성 식당", 62000),
        spent(later, 5, 20, "합성 카페", 9000),
    )
    merged = merge_repeats(records, (once, later))
    assert merged.records == records
    assert merged.tally == RepeatedExpenses(unmerged_expenses=1, unmerged_records=1)


def test_a_repost_that_lists_the_expense_twice_keeps_both() -> None:
    """겹친 원본들 중 한 원본이 적은 최대 건수를 남긴다. 재게시가 건수를 줄이지 않는다."""
    first, later = original(1, "2026-02-27"), original(2, "2026-04-15")
    records = (
        spent(first, 4, 5, "개인(성명 비공개)", 50000),
        spent(first, 5, 6, "합성 카페", 9000),
        spent(later, 4, 5, "개인(성명 비공개)", 50000),
        spent(later, 5, 5, "개인(성명 비공개)", 50000),
        spent(later, 6, 6, "합성 카페", 9000),
    )
    merged = merge_repeats(records, (first, later))
    assert [record.source_location for record in merged.records] == [
        "sheet1:R5",
        "sheet1:R4",
        "sheet1:R5",
    ]
    assert [record.source_hash for record in merged.records] == [
        first.source_hash,
        later.source_hash,
        later.source_hash,
    ]
    assert merged.tally == RepeatedExpenses(merged_expenses=2, merged_records=2)


def test_other_departments_and_organizations_are_never_the_same_expense() -> None:
    first, second = original(1, "2026-02-27"), original(2, "2026-03-06")
    other = spent(second, 4, 5, "합성 식당", 62000).model_copy(update={"department": "합성2과"})
    records = (spent(first, 4, 5, "합성 식당", 62000), other)
    merged = merge_repeats(records, (first, second))
    assert merged.records == records
    assert merged.tally == RepeatedExpenses()


def test_a_group_merges_only_the_originals_that_are_reposts_of_each_other() -> None:
    """한 묶음에 재게시 관계가 아닌 원본이 섞이면 그 원본의 레코드는 남고 수에 드러난다."""
    first, second, apart = (
        original(1, "2026-02-27"),
        original(2, "2026-04-15"),
        original(3, "2026-05-18"),
    )
    records = (
        spent(first, 4, 5, "합성 식당", 62000),
        spent(first, 5, 6, "합성 카페", 9000),
        spent(second, 4, 5, "합성 식당", 62000),
        spent(second, 5, 6, "합성 카페", 9000),
        spent(apart, 4, 5, "합성 식당", 62000),
        spent(apart, 5, 20, "합성 국밥", 27000),
    )
    merged = merge_repeats(records, (first, second, apart))
    assert [record.source_hash for record in merged.records] == [
        first.source_hash,
        first.source_hash,
        apart.source_hash,
        apart.source_hash,
    ]
    assert merged.tally == RepeatedExpenses(
        merged_expenses=2, merged_records=2, unmerged_expenses=1, unmerged_records=1
    )


def confirm(
    *sources: SourceRef,
    decision: RepeatDecision = "same_expense",
    day: int = 5,
    merchant: str = "합성 식당",
    amount: int = 62000,
) -> RepeatConfirmation:
    """사람이 원본을 대조해 남긴 지출 묶음 판정. 범위는 레코드가 아니라 지출 하나다."""
    return RepeatConfirmation(
        scope=ExpenseScope(
            city="gwangju",
            organization=SOURCE.organization,
            department="합성과",
            spent_on=date(2026, 1, day),
            merchant=merchant,
            amount_krw=Decimal(amount),
            sources=tuple(source.source_hash for source in sources),
        ),
        decision=decision,
        evidence=", ".join(source.path.name for source in sources),
    )


def test_a_confirmed_group_is_merged_without_two_shared_expenses() -> None:
    """근거가 한 건뿐이라 코드가 남긴 묶음도 사람이 같은 지출로 확정하면 합친다."""
    first, second = original(1, "2026-02-27"), original(2, "2026-04-15")
    records = (
        spent(first, 4, 5, "합성 식당", 62000),
        spent(second, 4, 5, "합성 식당", 62000),
        spent(second, 5, 20, "합성 카페", 9000),
    )
    merged = merge_repeats(records, (first, second), (confirm(first, second),))
    assert [record.record_id for record in merged.records] == [
        records[0].record_id,
        records[2].record_id,
    ]
    # 확인 결과로 합쳐도 출처는 모두 남는다.
    assert merged.records[0].repeats == (
        RecordOrigin(source_hash=second.source_hash, location="sheet1:R4"),
    )
    assert merged.tally == RepeatedExpenses(confirmed_expenses=1, confirmed_records=1)


def test_a_group_confirmed_as_separate_expenses_is_kept_and_stops_being_evidence() -> None:
    """확정은 기준보다 먼저 적용한다. 별개 지출로 확정한 묶음은 재게시의 근거가 되지 못한다."""
    first, second = original(1, "2026-02-27"), original(2, "2026-04-15")
    records = (
        spent(first, 4, 5, "합성 식당", 62000),
        spent(first, 5, 6, "합성 카페", 9000),
        spent(second, 4, 5, "합성 식당", 62000),
        spent(second, 5, 6, "합성 카페", 9000),
    )
    apart = confirm(first, second, decision="separate_expenses")
    merged = merge_repeats(records, (first, second), (apart,))
    # 함께 실은 지출 둘 중 하나가 별개로 확정되면 남은 근거는 한 건뿐이라 카페도 합치지 않는다.
    assert merged.records == records
    assert merged.tally == RepeatedExpenses(
        unmerged_expenses=1, unmerged_records=1, separate_expenses=1, separate_records=1
    )


def test_a_confirmation_for_an_expense_the_ledger_does_not_carry_is_rejected() -> None:
    """장부에 없는 묶음을 가리키는 확정은 낡은 기록이다. 확인했다고 여긴 채 지나가지 않는다."""
    first, second = original(1, "2026-02-27"), original(2, "2026-04-15")
    records = (spent(first, 4, 5, "합성 식당", 62000), spent(second, 4, 20, "합성 카페", 9000))
    with pytest.raises(ValueError, match="not in the ledger"):
        merge_repeats(records, (first, second), (confirm(first, second),))


def test_one_expense_cannot_be_confirmed_twice() -> None:
    """한 묶음에 확정이 둘이면 어느 쪽이 사람의 결론인지 알 수 없다."""
    first, second = original(1, "2026-02-27"), original(2, "2026-04-15")
    records = (spent(first, 4, 5, "합성 식당", 62000), spent(second, 4, 5, "합성 식당", 62000))
    both = (confirm(first, second), confirm(first, second, decision="separate_expenses"))
    with pytest.raises(ValueError, match="two repeat confirmations"):
        merge_repeats(records, (first, second), both)


def test_a_confirmation_counts_only_what_it_merged_beyond_the_criterion() -> None:
    """기준이 이미 합친 수는 자동 판정의 몫이다. 확정이 더 합친 만큼만 사람이 적용한 수다."""
    first, second, third = (
        original(1, "2026-02-02"),
        original(2, "2026-03-03"),
        original(3, "2026-04-01"),
    )
    records = (
        spent(first, 4, 5, "합성 식당", 62000),
        spent(second, 4, 5, "합성 식당", 62000),
        spent(second, 5, 6, "합성 카페", 9000),
        spent(third, 4, 5, "합성 식당", 62000),
        spent(third, 5, 6, "합성 카페", 9000),
    )
    merged = merge_repeats(records, (first, second, third), (confirm(first, second),))
    assert [record.record_id for record in merged.records] == [
        records[0].record_id,
        records[2].record_id,
    ]
    # 확정한 두 원본만 적었어도 그 원본과 이어진 원본까지 한 지출이 된다.
    assert merged.records[0].repeats == (
        RecordOrigin(source_hash=second.source_hash, location="sheet1:R4"),
        RecordOrigin(source_hash=third.source_hash, location="sheet1:R4"),
    )
    assert merged.tally == RepeatedExpenses(
        merged_expenses=2, merged_records=2, confirmed_expenses=1, confirmed_records=1
    )


def test_a_separate_confirmation_speaks_only_for_the_originals_it_names() -> None:
    """확정이 뒷받침하는 것은 그 줄이 적은 원본들뿐이다. 다른 원본이 남긴 것까지 세지 않는다."""
    first, second, third = (
        original(1, "2026-02-02"),
        original(2, "2026-03-03"),
        original(3, "2026-04-01"),
    )
    records = (
        spent(first, 4, 5, "합성 식당", 62000),
        spent(second, 4, 5, "합성 식당", 62000),
        spent(third, 4, 5, "합성 식당", 62000),
    )
    merged = merge_repeats(
        records, (first, second, third), (confirm(first, second, decision="separate_expenses"),)
    )
    assert merged.records == records
    # 확정이 적은 두 원본은 1건, 확정이 말하지 않은 셋째 원본은 가를 근거가 없어 남은 1건이다.
    assert merged.tally == RepeatedExpenses(
        unmerged_expenses=1, unmerged_records=1, separate_expenses=1, separate_records=1
    )


def test_a_repost_relation_that_contradicts_a_separate_confirmation_is_rejected() -> None:
    """세 번째 원본을 거쳐 이어지면 사람이 가른 두 원본이 한 건이 된다. 조용히 합치지 않는다."""
    first, second, third = (
        original(1, "2026-02-02"),
        original(2, "2026-03-03"),
        original(3, "2026-04-01"),
    )
    records = (
        spent(first, 4, 5, "합성 식당", 62000),
        spent(first, 5, 6, "합성 카페", 9000),
        spent(second, 4, 5, "합성 식당", 62000),
        spent(second, 5, 7, "합성 국밥", 27000),
        # 셋째 원본이 앞의 두 원본과 각각 2건씩 함께 실어 기준으로는 셋이 이어진다.
        spent(third, 4, 5, "합성 식당", 62000),
        spent(third, 5, 6, "합성 카페", 9000),
        spent(third, 6, 7, "합성 국밥", 27000),
    )
    apart = confirm(first, second, decision="separate_expenses")
    with pytest.raises(ValueError, match="confirmed to be separate"):
        merge_repeats(records, (first, second, third), (apart,))


def test_the_won_amount_hold_applies_only_to_a_declared_thousand_won_table() -> None:
    # 천원 표의 원 단위 행 보류는 사람이 틀을 확인해 선언한 HTML 표의 결정이다(ADR-0008).
    # 모델이 천원으로 판정한 표는 그 판정이 틀렸을 수도 있어 같은 규칙을 걸지 않는다.
    rows = table(spend(5, "합성 식당", 62.0), spend(6, "합성 행사장", 12000.0))
    thousand = MAPPING.model_copy(update={"amount_multiplier": Decimal(1000)})
    assert [record.amount_krw for record in extract(rows, thousand, SOURCE).records] == [
        Decimal(62000),
        Decimal(12000000),
    ]
    with pytest.raises(ValidationFailed, match="sheet1:R4 amount_unit"):
        extract(rows, thousand.model_copy(update={"declared": True}), SOURCE)


def test_a_declared_table_drops_only_the_row_whose_use_date_is_unreadable() -> None:
    """선언 표(ADR-0008)는 한 줄이 읽히지 않는다고 표 전체를 죽이지 않는다(기장군 실측).

    빠진 줄은 후보 수(분모)에 그대로 남는다 — 날짜를 못 읽었다는 이유로 후보에서 빼지 않는
    것이 폴백 정책이다. 레코드가 되지 않은 자리와 사유는 제외 목록에 남는다.
    """
    rows = table(
        spend(5, "합성 식당", 62000.0),
        ("과장", "6.27.(금)", "합성 찻집", "간담회", 27000.0),
        spend(7, "합성 국밥", 31000.0),
    )
    result = extract(rows, MAPPING.model_copy(update={"declared": True}), SOURCE)
    assert [record.merchant for record in result.records] == ["합성 식당", "합성 국밥"]
    assert (result.candidates, result.out_of_range) == (3, 0)
    assert result.excluded == ("sheet1:R4 spent_on",)


def test_a_declared_table_drops_only_the_row_whose_amount_is_unreadable() -> None:
    """금액 칸에 숫자 대신 `원`을 적은 줄(기장군 정관읍 실측)도 집행일 실패와 같이 그 줄만 뺀다.

    #205 사용자 결정. 값을 고쳐 읽지 않고(`원`을 0으로 읽지 않는다) 자리와 사유만 남긴다.
    """
    rows = table(
        spend(5, "합성 식당", 62000.0),
        ("과장", "2026-01-06 12:00", "합성 찻집", "간담회", "원"),
        spend(7, "합성 국밥", 31000.0),
    )
    result = extract(rows, MAPPING.model_copy(update={"declared": True}), SOURCE)
    assert [record.merchant for record in result.records] == ["합성 식당", "합성 국밥"]
    assert (result.candidates, result.out_of_range) == (3, 0)
    assert result.excluded == ("sheet1:R4 amount_krw",)


def test_a_declared_table_drops_only_the_row_whose_merchant_is_blank() -> None:
    """상호가 빈 격려금·축의금 줄(기장군 R365 실측)도 그 줄만 뺀다. 사용목적으로 채우지 않는다."""
    rows = table(
        spend(5, "합성 식당", 62000.0),
        ("과장", "2026-01-06 12:00", "", "방문단 환송연 격려금", 258000.0),
        spend(7, "합성 국밥", 31000.0),
    )
    result = extract(rows, MAPPING.model_copy(update={"declared": True}), SOURCE)
    assert [record.merchant for record in result.records] == ["합성 식당", "합성 국밥"]
    assert (result.candidates, result.out_of_range) == (3, 0)
    assert result.excluded == ("sheet1:R4 merchant",)


def test_a_declared_table_keeps_every_dropped_row_in_the_denominator() -> None:
    """세 사유가 섞여도 `records + out_of_range + 행 단위 제외 = candidates`다(ADR-0008)."""
    rows = table(
        spend(5, "합성 식당", 62000.0),
        ("과장", "6.27.(금)", "합성 찻집", "간담회", 27000.0),
        ("과장", "2026-01-06 12:00", "", "간담회", 9000.0),
        ("과장", "2026-01-07 12:00", "합성 국밥", "간담회", "원"),
        ("과장", "2025-12-30 12:00", "합성 분식", "간담회", 8000.0),
    )
    result = extract(rows, MAPPING.model_copy(update={"declared": True}), SOURCE)
    assert [record.merchant for record in result.records] == ["합성 식당"]
    assert result.excluded == (
        "sheet1:R4 spent_on",
        "sheet1:R5 merchant",
        "sheet1:R6 amount_krw",
    )
    assert result.candidates == len(result.records) + result.out_of_range + len(result.excluded)
    assert (result.candidates, result.out_of_range) == (5, 1)


@pytest.mark.parametrize(
    ("row", "item"),
    [
        (("과장", "6.27.(금)", "합성 찻집", "간담회", 27000.0), "spent_on"),
        (("과장", "2026-01-06 12:00", "", "간담회", 9000.0), "merchant"),
        (("과장", "2026-01-06 12:00", "합성 찻집", "간담회", "원"), "amount_krw"),
    ],
)
def test_a_model_mapped_table_fails_whole_on_any_row(row: tuple[Cell, ...], item: str) -> None:
    """모델이 매핑한 표는 매핑 자체가 틀렸을 수 있어 한 줄만 떼어 낼 근거가 없다(ADR-0008)."""
    rows = table(spend(5, "합성 식당", 62000.0), row)
    with pytest.raises(ValidationFailed, match=f"sheet1:R4 {item}"):
        extract(rows, MAPPING, SOURCE)


def test_a_declared_table_whose_every_row_fails_for_mixed_reasons_still_fails_whole() -> None:
    """상호·금액·집행일이 섞여 한 줄도 읽지 못했어도 틀의 문제로 보아 원본 전체를 남긴다."""
    rows = table(
        ("과장", "2026-01-06 12:00", "", "간담회", 9000.0),
        ("과장", "2026-01-07 12:00", "합성 국밥", "간담회", "원"),
        ("과장", "6.27.(금)", "합성 찻집", "간담회", 27000.0),
    )
    with pytest.raises(ValidationFailed, match="sheet1:R3 merchant"):
        extract(rows, MAPPING.model_copy(update={"declared": True}), SOURCE)


def test_a_declared_table_whose_every_row_is_undated_still_fails_whole() -> None:
    """한 줄도 읽지 못했다면 그것은 한 줄의 문제가 아니라 틀의 문제다.

    행 단위 제외가 "후보는 있는데 레코드는 0건"을 조용히 통과시키지 않게 한다(폴백 정책:
    설명되지 않은 0건은 실패다).
    """
    rows = table(
        ("과장", "6.27.(금)", "합성 찻집", "간담회", 27000.0),
        ("과장", "5.20.(화)", "합성 국밥", "간담회", 31000.0),
    )
    with pytest.raises(ValidationFailed, match="sheet1:R3 spent_on"):
        extract(rows, MAPPING.model_copy(update={"declared": True}), SOURCE)
