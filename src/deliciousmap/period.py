"""이번 제출의 대상 기간. 수집·추출·화면이 같은 기간을 쓴다.

원본 안의 날짜는 그 표가 실제로 담은 지출을 말하고, 제목은 그 게시글이 무엇을 공개한 것인지를
말한다. 대상 원본은 원본을 열기 전에 골라야 하므로 제목의 표기를 읽는다. 실측하지 않은 표기는
짐작하지 않는다. 고른 원본을 어디에 쓰는지는 README의 CLI 절에 있다.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date

START = date(2026, 1, 1)
END = date(2026, 6, 30)
LABEL = "2026년 상반기"

# 두 자리 연도의 기준 세기. 이 게시판의 게시글은 2004~2026년이고 `04년`~`26년`으로 적는다.
CENTURY = 2000
# 범위를 잇는 글자. 물결·하이픈·붙임표·쉼표를 모두 실측했고 분기와 달에 같이 쓰인다.
RANGE = r"\s*[~\-–∼,]\s*"
# 게시글 제목이 밝히는 지출 기간 표기. 2026-09-12 광주시청 게시판 제목 10,476건을 전수로 보고
# 실제로 쓰인 모양만 읽는다. 연도 뒤에 바로 붙은 표기만 보므로 제목 뒤쪽의 다른 숫자(부서의
# `5·18`, 분기 뒤 괄호의 달)는 기간으로 읽지 않는다. 연도만 있으면 그 해 전체다.
DECLARATION = re.compile(
    r"(?<!\d)(?P<year>\d{4}|\d{2})\s*(?:년도|년|\.)\s*"
    r"(?:"
    # `1/4분기`처럼 분모를 적는 분수형. 실측은 분모가 모두 4다.
    r"(?P<fraction>[1-4])\s*/\s*4\s*분기"
    rf"|(?P<first_quarter>[1-4]){RANGE}(?P<last_quarter>[1-4])\s*분기"
    r"|(?P<quarter>[1-4])\s*분기"
    rf"|(?P<first_month>1[0-2]|[1-9])\s*월?{RANGE}(?P<last_month>1[0-2]|[1-9])\s*월"
    r"|(?P<month>1[0-2]|[1-9])\s*월"
    r"|(?P<half>[상하])\s*반기"
    r")?"
)


def contains(day: date) -> bool:
    return START <= day <= END


@dataclass(frozen=True)
class Span:
    """게시글 제목이 밝힌 지출 기간. 하루가 아니라 달 단위의 구간이다."""

    start: date
    end: date

    def overlaps(self, other: "Span") -> bool:
        return self.start <= other.end and other.start <= self.end


REPORTING = Span(START, END)


def declared(title: str | None) -> Span | None:
    """게시글 제목이 밝힌 지출 기간. 실측한 표기가 아니면 밝히지 않은 것으로 둔다."""
    found = DECLARATION.search(title or "")
    if found is None:
        return None
    year = int(found["year"])
    year += CENTURY if year < 100 else 0
    first, last = _months(found)
    if first > last:
        # 거꾸로 적힌 범위는 뒤집어 고치지 않는다. 무엇을 뜻하는지 알 수 없다.
        return None
    return Span(date(year, first, 1), date(year, last, calendar.monthrange(year, last)[1]))


def targets(posted: date | None, title: str | None) -> bool:
    """이번 제출의 대상 게시글인지. 게시일의 해와 제목이 밝힌 지출 기간이 모두 맞아야 한다.

    게시일도 제목도 없으면 목록 구조를 읽지 않는 게시판이라 기간으로 가를 수 없다. 그때는
    가르지 않고 대상으로 둔다. 가를 근거가 없다는 것을 0건으로 바꾸지 않기 위해서다.
    """
    if posted is None and title is None:
        return True
    if posted is None or not (START.year <= posted.year <= END.year):
        return False
    span = declared(title)
    return span is not None and span.overlaps(REPORTING)


def _months(found: re.Match[str]) -> tuple[int, int]:
    """표기가 가리키는 첫 달과 끝 달. 분기는 달 셋씩이고, 밝히지 않았으면 그 해 전체다."""
    if found["fraction"]:
        return _quarter(int(found["fraction"]), int(found["fraction"]))
    if found["first_quarter"]:
        return _quarter(int(found["first_quarter"]), int(found["last_quarter"]))
    if found["quarter"]:
        return _quarter(int(found["quarter"]), int(found["quarter"]))
    if found["first_month"]:
        return int(found["first_month"]), int(found["last_month"])
    if found["month"]:
        return int(found["month"]), int(found["month"])
    if found["half"]:
        return (1, 6) if found["half"] == "상" else (7, 12)
    return 1, 12


def _quarter(first: int, last: int) -> tuple[int, int]:
    return 3 * first - 2, 3 * last
