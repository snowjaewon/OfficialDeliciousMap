"""게시글 제목이 밝히는 지출 기간. 2026-09-12 광주시청 게시판 제목 10,476건 전수 실측이다.

제목 표기는 합성 부서명으로 바꿔 실었고, 기간 표기 자체는 실측한 모양 그대로다.
"""

from datetime import date

import pytest

from deliciousmap.period import END, START, Span, declared, targets


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
        # 게시일을 읽지 못한 게시글도 대상에 넣지 않는다.
        (None, "2026년 1분기 업무추진비 집행내역(합성과)", False),
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


def test_a_period_that_ends_before_it_starts_is_not_read() -> None:
    """거꾸로 적힌 범위는 뒤집어 고치지 않는다. 밝히지 않은 것으로 둔다."""
    assert declared("2026년 4~1분기 업무추진비 집행내역(합성과)") is None
