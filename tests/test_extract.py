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
)
from deliciousmap.extract import ValidationFailed, extract, merge_repeats, parse_date
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
        evidence="두 원본의 대상기간이 겹치고 뒤 원본이 앞 기간을 다시 실었다(합성)",
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
