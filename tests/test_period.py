"""게시글 제목이 밝히는 지출 기간. 2026-09-12 광주시청 게시판 제목 10,476건 전수 실측이다.

제목 표기는 합성 부서명으로 바꿔 실었고, 기간 표기 자체는 실측한 모양 그대로다.
"""

from datetime import date

import pytest

from deliciousmap.contracts import SpentOn
from deliciousmap.period import (
    END,
    START,
    Span,
    contains,
    declared,
    exclusion,
    months,
    span,
    targets,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # 게시일 2026 구간에서 실측한 12종.
        ("2026년 1월 업무추진비 집행내역(합성과)", Span(date(2026, 1, 1), date(2026, 1, 31))),
        ("2026년 1분기 업무추진비 집행내역(합성과)", Span(date(2026, 1, 1), date(2026, 3, 31))),
        ("2026년 1~2월 업무추진비 집행내역(합성과)", Span(date(2026, 1, 1), date(2026, 2, 28))),
        ("2026년 2월~4월 업무추진비 집행내역(합성과)", Span(date(2026, 2, 1), date(2026, 4, 30))),
        ("2026년 1~2분기 업무추진비 집행내역(합성과)", Span(date(2026, 1, 1), date(2026, 6, 30))),
        ("2026년 1,2분기 업무추진비 집행내역(합성과)", Span(date(2026, 1, 1), date(2026, 6, 30))),
        # 「년」 없이 마침표만 찍은 표기. 실측 1건(seq 10911).
        ("2026. 1분기 업무추진비 사용내역(합성과)", Span(date(2026, 1, 1), date(2026, 3, 31))),
        # 두 자리 연도가 제목 끝 괄호에 붙은 표기. 실측 2건(seq 11006·11007).
        ("합성과 업무추진비 (26년1~2분기)", Span(date(2026, 1, 1), date(2026, 6, 30))),
        # 분기 뒤 괄호로 달을 덧붙인 표기. 앞의 분기가 밝힌 기간을 쓴다.
        (
            "2025년 4분기(12월) 업무추진비 집행내역(합성과)",
            Span(date(2025, 10, 1), date(2025, 12, 31)),
        ),
        ("2025년 하반기 업무추진비 공개", Span(date(2025, 7, 1), date(2025, 12, 31))),
        ("2025년 업무추진비 집행내역(합성과)", Span(date(2025, 1, 1), date(2025, 12, 31))),
        # 구분자를 빠뜨린 오기(seq 10839). 분기를 짐작하지 않고 그 해 전체로만 읽는다.
        ("2025년 34분기 업무추진비 집행내역(합성과)", Span(date(2025, 1, 1), date(2025, 12, 31))),
        # 게시판 전체에서 더 실측한 두 종. 분수형 분기와 하이픈 범위다.
        ("2020년도 1/4분기 업무추진비 집행내역(합성과)", Span(date(2020, 1, 1), date(2020, 3, 31))),
        ("2020년 3-4분기 업무추진비 집행내역(합성과)", Span(date(2020, 7, 1), date(2020, 12, 31))),
        # 쉼표로 두 달을 이어 적은 표기. 게시판 전체에서 22건이며 분기의 쉼표와 같은 뜻이다.
        ("2023년 8,9월 업무추진비 사용내역(합성과)", Span(date(2023, 8, 1), date(2023, 9, 30))),
        # 두 자리 달과 연말 범위.
        ("2025년 10~12월 업무추진비 집행내역(합성과)", Span(date(2025, 10, 1), date(2025, 12, 31))),
        ("2024년 2월 업무추진비 집행내역(합성과)", Span(date(2024, 2, 1), date(2024, 2, 29))),
        # 부산시청 게시판에서 실측한 `제N분기`. 그 해 전체로 읽으면 3·4분기 게시글이
        # 상반기 대상으로 들어온다(2026-09-14 실측 4건).
        ("2026년 제1분기 업무추진비 집행내역(합성과)", Span(date(2026, 1, 1), date(2026, 3, 31))),
        ("2026년 제3분기 업무추진비 집행내역(합성과)", Span(date(2026, 7, 1), date(2026, 9, 30))),
        ("합성과 2026년도 2분기 업무추진비 내역", Span(date(2026, 4, 1), date(2026, 6, 30))),
        # 해 뒤 마침표에 달을 붙여 제목 끝 괄호에 둔 표기(대구 수성구 만촌1동장 8건 ·
        # 부산 중구 1건, 2026-09-17 실측)는 게시일이 없는 게시판에서만 읽는다. 게시일이 있으면
        # 지금처럼 그 해 전체다(아래 `test_a_dotted_month_is_read_only_without_a_posting_date`).
        ("합성동장업무추진비(2026.1)", Span(date(2026, 1, 1), date(2026, 12, 31))),
    ],
)
def test_title_declares_the_measured_spending_period(title: str, expected: Span) -> None:
    assert declared(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "업무추진비 공개 안내",
        "합성과 업무추진비 집행내역",
        "",
    ],
)
def test_title_without_a_measured_period_declares_nothing(title: str) -> None:
    """기간을 밝히지 않은 제목은 짐작하지 않는다. 대상 여부는 그 사실대로 정해진다."""
    assert declared(title) is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # 서울 구로 게시판(2026-09-14 실측 28건)은 해를 `년` 없이 제목 맨 앞에 적는다. 달은
        # 해 바로 뒤(3건)나 제목 끝 괄호(25건)에 둔다.
        ("2026 3월 합성과시책추진업무추진비 공개", Span(date(2026, 3, 1), date(2026, 3, 31))),
        (
            "2026 합성국 기관운영업무추진비 집행내역(4월)",
            Span(date(2026, 4, 1), date(2026, 4, 30)),
        ),
        (
            "2025 합성국 및 합성과 시책추진업무추진비 집행내역 (12월)",
            Span(date(2025, 12, 1), date(2025, 12, 31)),
        ),
        # 광주 게시판에도 해 바로 뒤의 달이 4건 있고, 그중 한 건은 범위다.
        (
            "2012 1월 ~4월 합성과 업무추진비집행내역",
            Span(date(2012, 1, 1), date(2012, 4, 30)),
        ),
    ],
)
def test_a_bare_year_at_the_start_declares_the_month_beside_it_or_at_the_end(
    title: str, expected: Span
) -> None:
    assert declared(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        # 달이 없는 모양은 실측하지 않았다. 그 해 전체로 넓히지 않는다.
        "2026 합성국 기관운영업무추진비 집행내역",
        # 제목 끝이 아닌 괄호의 달은 실측하지 않았다.
        "2026 합성국 업무추진비(4월) 집행내역",
        # 해가 제목 맨 앞이 아니다.
        "합성국 2026 업무추진비 집행내역(4월)",
        # 달 뒤에 붙은 글자와 분기 뒤 괄호의 달은 실측하지 않았다.
        "2026 3월분 합성과 업무추진비 집행내역",
        "2026 1분기 합성과 업무추진비 집행내역(3월)",
    ],
)
def test_a_bare_year_reads_only_the_measured_month_positions(title: str) -> None:
    """기간을 밝히지 않은 제목은 짐작하지 않는다. 대상 여부는 그 사실대로 정해진다."""
    assert declared(title) is None


def test_reporting_period_is_the_first_half_of_2026() -> None:
    assert (START, END) == (date(2026, 1, 1), date(2026, 6, 30))


@pytest.mark.parametrize(
    ("posted", "title", "expected"),
    [
        # 게시일도 제목도 대상 기간을 가리킨다.
        (date(2026, 4, 2), "2026년 1분기 업무추진비 사용내역(합성과)", True),
        (date(2026, 6, 29), "2026년 2분기 업무추진비 집행내역(합성과)", True),
        (date(2026, 6, 11), "합성과 업무추진비 (26년1~2분기)", True),
        # 2026년에 올렸지만 지출은 지난해다.
        (date(2026, 1, 8), "2025년 4분기 업무추진비 집행내역(합성과)", False),
        (date(2026, 1, 13), "2024년 10~12월 업무추진비 집행내역(합성과)", False),
        # 지출 기간은 대상이지만 게시일이 대상 연도 밖이다.
        (date(2025, 12, 30), "2026년 1분기 업무추진비 집행내역(합성과)", False),
        # 기간을 밝히지 않은 제목은 대상에 넣지 않는다.
        (date(2026, 5, 1), "업무추진비 공개 안내", False),
        # 게시일이 없는 게시판(대구 수성구 해마다의 화면)은 제목이 밝힌 해와 기간으로 가른다.
        (None, "2026년 1분기 업무추진비 집행내역(합성과)", True),
        (None, "2026년 7월 업무추진비 집행내역(합성과)", False),
        (date(2026, 5, 1), None, False),
        # 목록 구조를 읽지 않는 게시판은 게시일도 제목도 주지 않는다. 가를 근거가 없으면
        # 걸러 0건으로 만들지 않고 뒤 단계가 다루게 둔다.
        (None, None, True),
    ],
)
def test_submission_target_needs_both_the_posting_year_and_the_title_period(
    posted: date | None, title: str | None, expected: bool
) -> None:
    assert targets(posted, title) is expected


def test_an_unreadable_title_is_left_out_even_when_posted_in_the_target_year() -> None:
    """의도한 결정이다. 제목이 기간을 밝히지 않으면 게시일만으로 대상에 넣지 않는다.

    실측(2026-09-12): 게시일이 2026년이면서 제목의 기간을 읽지 못한 게시글은 0건이다. 이 값이
    0이 아니게 되면 그 글은 조용히 빠지므로, 표기를 실측해 파서에 더해야 한다.
    """
    assert targets(date(2026, 5, 1), "합성과 업무추진비 집행내역") is False


def test_a_dotted_month_is_read_only_without_a_posting_date() -> None:
    """게시일이 있는 게시판의 같은 표기(부산 중구 실측 1건)는 읽지 않는다.

    읽으면 커밋된 부산 산출물이 코드와 어긋난다. 부산은 다른 담당자 영역이라 이 규칙을 넓히는
    일은 후속 이슈로 남긴다(2026-09-18 사용자 결정).
    """
    assert exclusion(date(2026, 9, 1), "합성과과장급이상업무추진비사용내역(2026.7)") is None
    assert exclusion(None, "합성과과장급이상업무추진비사용내역(2026.7)") == "declared_out_of_range"


def test_a_period_that_ends_before_it_starts_is_not_read() -> None:
    """거꾸로 적힌 범위는 뒤집어 고치지 않는다. 밝히지 않은 것으로 둔다."""
    assert declared("2026년 4~1분기 업무추진비 집행내역(합성과)") is None


@pytest.mark.parametrize(
    ("posted", "title", "expected"),
    [
        # 대상인 게시글은 사유가 없다.
        (date(2026, 4, 2), "2026년 1분기 업무추진비 사용내역(합성과)", None),
        # 가를 근거가 없는 게시판도 대상이라 사유가 없다.
        (None, None, None),
        # 게시일이 대상 연도 밖이다. 제목의 기간은 보지 않는다.
        (date(2025, 12, 30), "2026년 1분기 업무추진비 집행내역(합성과)", "posted_out_of_range"),
        (date(2024, 3, 2), "2024년 1분기 업무추진비 집행내역(합성과)", "posted_out_of_range"),
        # 게시일이 없으면 제목이 해와 기간을 밝힐 때만 제목으로 가른다(2026-09-17 사용자 결정,
        # 대구 수성구 461건).
        (None, "2026년 1분기 업무추진비 집행내역(합성과)", None),
        (None, "2017. 4월 업무추진비 집행내역 공개", "declared_out_of_range"),
        # 게시일이 없는 게시판(대구 수성구)의 `(2026.N)`은 그 달로 읽는다.
        (None, "합성동장업무추진비(2026.3)", None),
        (None, "합성동장업무추진비(2026.8)", "declared_out_of_range"),
        # 해가 없는 제목은 게시일 없이 해를 정할 수 없다. 게시일을 읽지 못한 갈래로 센다.
        (None, "6월 업무추진비 사용 내역", "posted_out_of_range"),
        (None, "업무추진비 공개 안내", "posted_out_of_range"),
        # 게시일은 대상 연도인데 지출은 지난해다.
        (date(2026, 1, 8), "2025년 4분기 업무추진비 집행내역(합성과)", "declared_out_of_range"),
        # 게시일은 대상 연도인데 제목이 기간을 밝히지 않았다. 감시 지점이다.
        (date(2026, 5, 1), "업무추진비 공개 안내", "undeclared_in_year"),
        (date(2026, 5, 1), None, "undeclared_in_year"),
    ],
)
def test_exclusion_names_why_a_posting_is_not_a_target(
    posted: date | None, title: str | None, expected: str | None
) -> None:
    assert exclusion(posted, title) == expected


@pytest.mark.parametrize(
    ("posted", "title", "expected"),
    [
        # 울산시청 시장 게시판은 연도 없이 달만 적는다(2026-09-14 실측 `6월 업무추진비 사용 내역`).
        # 지출은 게시보다 먼저이므로 게시일 이전의 가장 가까운 그 달이다.
        (date(2026, 7, 23), "6월 업무추진비 사용 내역", None),
        (date(2026, 6, 30), "6월 업무추진비 사용 내역", None),
        (date(2026, 8, 10), "7월 업무추진비 사용 내역", "declared_out_of_range"),
        # 게시월보다 뒤인 달은 지난해다. 올해로 읽으면 대상이 되므로 이 줄이 해를 가른다.
        (date(2026, 1, 5), "6월 업무추진비 사용 내역", "declared_out_of_range"),
        # 게시월과 같은 달은 올해다.
        (date(2026, 1, 5), "1월 업무추진비 사용 내역", None),
        # 서울 성북 게시판(2026-09-14 실측 4건)은 달을 제목 가운데에 띄어 쓰거나 제목 끝
        # 괄호에 둔다.
        (date(2026, 2, 4), "합성과 1월 시책추진업무추진비 공개", None),
        (date(2026, 7, 15), "합성과 6월 시책추진업무추진비 공개", None),
        (date(2026, 9, 3), "합성과 시책추진업무추진비 집행내역 공개(8월)", "declared_out_of_range"),
        # 실측하지 않은 표기는 짐작하지 않는다: 범위, 달 뒤에 붙은 글자.
        (date(2026, 7, 23), "6~7월 업무추진비 사용 내역", "undeclared_in_year"),
        (date(2026, 7, 23), "합성과 6월 ~ 7월 업무추진비 사용 내역", "undeclared_in_year"),
        (date(2026, 7, 23), "합성과 1 ~ 3월 업무추진비 사용 내역", "undeclared_in_year"),
        (date(2026, 7, 23), "5월분 업무추진비 사용 내역", "undeclared_in_year"),
        # 해를 잘못 적은 제목은 해 없는 제목이 아니다. 오기를 짐작하지 않는다(서울 성동·성북 실측).
        (
            date(2026, 2, 2),
            "2026월 1월 합성과 시책추진업무추진비 집행내역 공개",
            "undeclared_in_year",
        ),
        (date(2026, 5, 2), "합성동 업무추진비 집행내역 공개(206.4월)", "undeclared_in_year"),
        (date(2026, 3, 5), "합성과 업무추진비 사용내역(202년 2월)", "undeclared_in_year"),
    ],
)
def test_a_month_without_a_year_is_the_latest_such_month_by_the_posting_date(
    posted: date, title: str, expected: str | None
) -> None:
    assert exclusion(posted, title) == expected


@pytest.mark.parametrize(
    ("posted", "title"),
    [
        (date(2026, 4, 2), "2026년 1분기 업무추진비 사용내역(합성과)"),
        (date(2026, 1, 8), "2025년 4분기 업무추진비 집행내역(합성과)"),
        (date(2026, 5, 1), "업무추진비 공개 안내"),
        (date(2024, 3, 2), "2024년 1분기 업무추진비 집행내역(합성과)"),
        (None, None),
    ],
)
def test_target_is_the_absence_of_an_exclusion_reason(
    posted: date | None, title: str | None
) -> None:
    """두 함수가 같은 판단을 낸다. 사유를 붙이는 일이 대상 판정을 바꾸지 않는다."""
    assert targets(posted, title) is (exclusion(posted, title) is None)


@pytest.mark.parametrize(
    ("spent_on", "expected"),
    [
        # 일이 있는 집행일은 그 하루다. 판정이 지금과 같다.
        (SpentOn(2026, 3, 17), Span(date(2026, 3, 17), date(2026, 3, 17))),
        # 일이 빈 집행일은 그 달 전체다. 1일·말일 어느 쪽으로도 좁히지 않는다.
        (SpentOn(2026, 3), Span(date(2026, 3, 1), date(2026, 3, 31))),
        (SpentOn(2026, 2), Span(date(2026, 2, 1), date(2026, 2, 28))),
    ],
)
def test_spending_day_points_at_a_span(spent_on: SpentOn, expected: Span) -> None:
    assert span(spent_on) == expected


@pytest.mark.parametrize(
    ("spent_on", "expected"),
    [
        (SpentOn(2026, 3, 17), True),
        (SpentOn(2025, 12, 31), False),
        (SpentOn(2026, 7, 1), False),
        # 달 단위 집행일은 그 달의 구간이 대상 기간과 겹치면 대상이다.
        (SpentOn(2026, 3), True),
        (SpentOn(2026, 6), True),
        (SpentOn(2025, 12), False),
        (SpentOn(2026, 7), False),
    ],
)
def test_target_period_holds_a_month_whose_span_overlaps_it(
    spent_on: SpentOn, expected: bool
) -> None:
    assert contains(spent_on) is expected


def test_months_are_the_reporting_period_not_the_whole_year() -> None:
    # 사용월로 거르는 게시판은 대상 기간의 달만 받는다. 해 단위인 `collects`와 다른 자리다.
    assert months() == tuple((2026, month) for month in range(1, 7))
    assert months()[0] == (START.year, START.month)
    assert months()[-1] == (END.year, END.month)
