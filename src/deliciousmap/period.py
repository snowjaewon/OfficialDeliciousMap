"""이번 제출의 대상 기간. 수집·추출·화면이 같은 기간을 쓴다.

원본 안의 날짜는 그 표가 실제로 담은 지출을 말하고, 제목은 그 게시글이 무엇을 공개한 것인지를
말한다. 대상 원본은 원본을 열기 전에 골라야 하므로 제목의 표기를 읽는다. 실측하지 않은 표기는
짐작하지 않는다. 고른 원본을 어디에 쓰는지는 README의 CLI 절에 있다.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from deliciousmap.contracts import SpentOn

START = date(2026, 1, 1)
END = date(2026, 6, 30)
LABEL = "2026년 상반기"

# 두 자리 연도의 기준 세기. 이 게시판의 게시글은 2004~2026년이고 `04년`~`26년`으로 적는다.
CENTURY = 2000
# 범위를 잇는 글자. 물결·하이픈·붙임표·쉼표를 모두 실측했고 분기와 달에 같이 쓰인다.
RANGE = r"\s*[~\-–∼,]\s*"
# 달 하나 또는 달의 범위. 해 뒤에 오는 달 표기는 모두 이 모양이다.
MONTHS = (
    rf"(?P<first_month>1[0-2]|[1-9])\s*월?{RANGE}(?P<last_month>1[0-2]|[1-9])\s*월"
    r"|(?P<month>1[0-2]|[1-9])\s*월"
)
# 제목 끝 괄호에 둔 달. 서울 구로(해 있음)와 성북(해 없음) 게시판이 이 자리에 달을 둔다.
BRACKETED_MONTH = r"\(\s*(?P<bracketed_month>1[0-2]|[1-9])\s*월\s*\)\s*$"
# 게시글 제목이 밝히는 지출 기간 표기. 2026-09-12 광주시청 게시판 제목 10,476건을 전수로 보고
# 실제로 쓰인 모양만 읽는다. 연도 뒤에 바로 붙은 표기만 보므로 제목 뒤쪽의 다른 숫자(부서의
# `5·18`, 분기 뒤 괄호의 달)는 기간으로 읽지 않는다. 연도만 있으면 그 해 전체다.
DECLARATION = re.compile(
    r"(?<!\d)(?P<year>\d{4}|\d{2})\s*(?:년도|년|\.)\s*"
    r"(?:"
    # `1/4분기`처럼 분모를 적는 분수형. 실측은 분모가 모두 4다.
    r"(?P<fraction>[1-4])\s*/\s*4\s*분기"
    rf"|(?P<first_quarter>[1-4]){RANGE}(?P<last_quarter>[1-4])\s*분기"
    # `제2분기`처럼 차례를 밝히는 표기. 2026-09-14 부산시청 게시판에서 실측했다.
    r"|제?\s*(?P<quarter>[1-4])\s*분기"
    rf"|{MONTHS}"
    r"|(?P<half>[상하])\s*반기"
    r")?"
)

# `년` 없이 제목 맨 앞에 적은 네 자리 해. 서울 구로 게시판(2026-09-14 실측 28건)의
# `2026 3월 …`(3건)과 `2026 …집행내역(4월)`(25건)이고, 광주 게시판에도 앞 모양이 8종 11건
# (`2015 5~6월 …` 같은 범위 5종 포함) 있으나 모두 2020년까지의 게시라 판정이 바뀌지 않는다.
# 해에 붙은 표기가 아니므로 `DECLARATION`이 기간을 못 읽은 제목에만 쓰고, 달은 실측한 두
# 자리 — 띄어 쓴 해 바로 뒤와 제목 끝 괄호 — 에서만 읽는다. 달이 없으면 그 해 전체로 넓히지
# 않고, 달 뒤에 붙은 글자(`3월분`)와 분기 뒤 괄호의 달은 읽지 않는다.
BARE_YEAR = re.compile(rf"^\s*(?P<year>\d{{4}})\s+(?:(?:{MONTHS})\s|[^\d\s].*{BRACKETED_MONTH})")


# 연도 없이 달 하나만 적은 제목. 달을 제목 맨 앞이나 가운데에 띄어 쓰거나 제목 끝 괄호에 둔다.
# 맨 앞은 울산시청 시장 게시판의 `6월 업무추진비 사용 내역`(2026-09-14)이고, 광주 게시판에도
# 같은 모양 38건(`6월 업무추진비 집행내역(의정담당관실)`)이 있으나 모두 2026년 이전 게시라 판정이
# 바뀌지 않는다. 가운데(`민원여권과 1월 …`)와 끝 괄호(`…집행내역 공개(8월)`)는 서울 성북
# 게시판(2026-09-14)에서 실측했고, 광주에도 8건 있으나 모두 2012~2015년 게시다.
# `DECLARATION`은 연도에 붙은 표기만 읽으므로 따로 두고, `DECLARATION`·`BARE_YEAR`가 기간을
# 못 읽은 제목에만 쓴다. 실측하지 않은 모양 — 범위(`6~7월`), 달 뒤에 붙은 글자(`5월분`·`8월중`)
# — 은 읽지 않는다.
YEARLESS_MONTH = re.compile(rf"(?:^|\s)(?P<month>1[0-2]|[1-9])\s*월\s|{BRACKETED_MONTH}")
# 해 자리에 쓴 세 자리 이상의 숫자. 이런 제목은 해 없는 제목이 아니라 해를 잘못 적은 제목이다
# (서울 성동 `2026월 1월 …`, 성북 `…(206.4월)`, 부산 `2026월 3월 …`·`…(202년 2월)`). 오기는
# 네 건이 세 모양이라 규칙이 되지 않으므로 짐작하지 않고 기간 미선언으로 둔다.
MISWRITTEN_YEAR = re.compile(r"(?<!\d)\d{3,}\s*[년월.]")
# 달의 범위. 해 없는 제목에서는 범위를 달 하나로 잘라 읽지 않도록 범위가 있으면 읽지 않는다.
MONTH_RANGE = re.compile(rf"{RANGE}(?:1[0-2]|[1-9])\s*월")


def collects(posted: date | None) -> bool:
    """이번 수집이 받을 게시글인지. 게시일의 해가 대상 기간의 해와 같아야 한다.

    게시판은 20년치를 한 곳에 쌓아 두고, 이번 제출이 다루는 것은 그중 대상 기간뿐이다.
    대상 기간의 지출을 실은 게시글은 같은 해에 올라오므로 해 단위로 자른다. 달로 자르지
    않는 것은 분기 정산이 분기가 끝난 뒤에 올라오기 때문이다. 게시일을 밝히지 않는 게시판은
    가를 근거가 없어 받는다 — 근거 없음을 0건으로 바꾸지 않는다.

    받지 않은 게시글은 수집 장부에 수로 남는다(`FetchOutput.uncollected_postings`).
    이미 받아 둔 원본은 이 규칙과 무관하게 장부에 그대로 남는다.
    """
    return posted is None or START.year <= posted.year <= END.year


@dataclass(frozen=True)
class Span:
    """지출이 걸쳐 있는 구간. 게시글 제목이 밝힌 기간과 집행일 하나가 같은 어휘를 쓴다."""

    start: date
    end: date

    def overlaps(self, other: "Span") -> bool:
        return self.start <= other.end and other.start <= self.end


REPORTING = Span(START, END)


def months() -> tuple[tuple[int, int], ...]:
    """대상 기간이 걸친 달. 사용월로 거르는 게시판이 무엇을 받을지 여기서만 정한다.

    게시일로만 가를 수 있는 게시판은 해 단위인 `collects`를 따른다. 사용월을 직접
    고를 수 있는 게시판(서울 은평·관악·서대문 실측)은 그 달을 기관에 물어보므로
    대상 기간 밖의 달까지 받을 이유가 없다.
    """
    first = 12 * START.year + START.month - 1
    last = 12 * END.year + END.month - 1
    return tuple((value // 12, value % 12 + 1) for value in range(first, last + 1))


def span(spent_on: SpentOn) -> Span:
    """집행일 하나가 가리키는 구간. 일이 있으면 그 하루이고, 일이 비었으면 그 달 전체다.

    일이 빈 집행일을 그 달 1일·말일 어느 쪽으로도 좁히지 않는다. 아는 것은 달까지뿐이다.
    """
    if spent_on.day is not None:
        day = date(spent_on.year, spent_on.month, spent_on.day)
        return Span(day, day)
    last = calendar.monthrange(spent_on.year, spent_on.month)[1]
    return Span(date(spent_on.year, spent_on.month, 1), date(spent_on.year, spent_on.month, last))


def contains(spent_on: SpentOn) -> bool:
    """이번 제출이 다룰 집행일인가. 그 집행일의 구간이 대상 기간과 겹쳐야 한다.

    일이 있는 집행일의 구간은 하루라 판정이 `START <= day <= END`와 같다 — 바뀌는 것은
    달까지만 적힌 집행일뿐이다.
    """
    return span(spent_on).overlaps(REPORTING)


# 대상에서 빠진 사유. 게시일을 읽지 못한 게시글은 `posted_out_of_range`로 센다.
ExclusionReason = Literal["posted_out_of_range", "declared_out_of_range", "undeclared_in_year"]


def declared(title: str | None) -> Span | None:
    """게시글 제목이 밝힌 지출 기간. 실측한 표기가 아니면 밝히지 않은 것으로 둔다."""
    text = title or ""
    found = DECLARATION.search(text) or BARE_YEAR.search(text)
    if found is None:
        return None
    year = int(found["year"])
    year += CENTURY if year < 100 else 0
    first, last = _months(found)
    if first > last:
        # 거꾸로 적힌 범위는 뒤집어 고치지 않는다. 무엇을 뜻하는지 알 수 없다.
        return None
    return Span(date(year, first, 1), date(year, last, calendar.monthrange(year, last)[1]))


def exclusion(
    posted: date | None, title: str | None, spent_on: date | None = None
) -> ExclusionReason | None:
    """대상이 아니면 그 사유. 대상이면 `None`.

    `undeclared_in_year`는 감시 지점이다. 게시일이 대상 연도인데 제목이 기간을 밝히지 않으면
    그 게시글은 조용히 빠진다. 0이 아니게 되면 그 표기를 실측해 규칙에 더해야 한다. 광주
    (2026-09-12)는 0건이었고, 울산(2026-09-14)의 147건은 동구 제목 칸 오류와 연도 없는 달
    표기(`YEARLESS_MONTH`)였다(#146). 서울(2026-09-14)의 37건 중 32건은 `년` 없는 해
    (`BARE_YEAR`)와 가운데·끝 괄호의 달이었고, 남은 5건은 기간을 적지 않았거나 해를 잘못
    적은 제목이다(#155).

    상세 키로 집행일을 밝힌 하루치 게시글(`spent_on`)은 제목이 기간을 적지 않는다. 그 게시글이
    밝힌 지출 기간은 그 하루이므로 제목 대신 그 날로 가른다(ADR-0008).
    """
    if posted is None and title is None and spent_on is None:
        return None
    if posted is None or not collects(posted):
        return "posted_out_of_range"
    if spent_on is not None:
        return None if Span(spent_on, spent_on).overlaps(REPORTING) else "declared_out_of_range"
    span = declared(title) or _yearless_month(title, posted)
    if span is None:
        return "undeclared_in_year"
    return None if span.overlaps(REPORTING) else "declared_out_of_range"


def _yearless_month(title: str | None, posted: date) -> Span | None:
    """연도 없이 달만 적은 제목의 기간. 게시월을 포함해 게시일까지의 가장 가까운 그 달이다.

    지출은 게시보다 먼저 있으므로 게시월보다 뒤인 달은 지난해다. 게시월과 같은 달은 올해다.
    연도 없는 분기·반기·범위는 실측하지 않아 읽지 않는다.
    """
    text = title or ""
    found = YEARLESS_MONTH.search(text)
    if found is None or MISWRITTEN_YEAR.search(text) or MONTH_RANGE.search(text):
        return None
    month = int(found["month"] or found["bracketed_month"])
    year = posted.year if month <= posted.month else posted.year - 1
    return Span(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]))


def targets(posted: date | None, title: str | None, spent_on: date | None = None) -> bool:
    """이번 제출의 대상 게시글인지. 게시일의 해와 제목이 밝힌 지출 기간이 모두 맞아야 한다.

    게시일도 제목도 없으면 목록 구조를 읽지 않는 게시판이라 기간으로 가를 수 없다. 그때는
    가르지 않고 대상으로 둔다. 가를 근거가 없다는 것을 0건으로 바꾸지 않기 위해서다.
    """
    return exclusion(posted, title, spent_on) is None


def _months(found: re.Match[str]) -> tuple[int, int]:
    """표기가 가리키는 첫 달과 끝 달. 분기는 달 셋씩이고, 밝히지 않았으면 그 해 전체다."""
    groups = found.groupdict()
    if groups.get("fraction"):
        return _quarter(int(groups["fraction"]), int(groups["fraction"]))
    if groups.get("first_quarter"):
        return _quarter(int(groups["first_quarter"]), int(groups["last_quarter"]))
    if groups.get("quarter"):
        return _quarter(int(groups["quarter"]), int(groups["quarter"]))
    if groups.get("first_month"):
        return int(groups["first_month"]), int(groups["last_month"])
    month = groups.get("month") or groups.get("bracketed_month")
    if month:
        return int(month), int(month)
    if groups.get("half"):
        return (1, 6) if groups["half"] == "상" else (7, 12)
    return 1, 12


def _quarter(first: int, last: int) -> tuple[int, int]:
    return 3 * first - 2, 3 * last
