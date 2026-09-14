"""화면 자체가 집행 표인 서울 게시판.

서울시청·은평·관악·서대문은 첨부를 내려받지 않는다. 집행 내역이 게시판 화면 안의
표나 줄로 있고, 기관이 주는 공식 내려받기는 관악의 `.xls` 이름 HTML(2026-09-14 실측
695KB·1,855행)과 서대문의 0바이트 응답뿐이다. 그래서 받은 화면을 원본으로 남긴다
(`boards.container_of(..., html=True)`).

세 게시판은 사용월을 직접 고를 수 있어 대상 기간의 달만 받는다(`period.months`).
서울시청은 사용월로 목록을 거르되 게시글마다 상세 화면이 따로 있어 그 상세가 원본이다.
"""

from __future__ import annotations

import calendar
import re
import urllib.parse
from collections.abc import Iterator
from datetime import date
from html.parser import HTMLParser
from typing import TYPE_CHECKING

from deliciousmap import boards
from deliciousmap.transport import Transport

if TYPE_CHECKING:
    from deliciousmap.registry.models import Board

HTML_SUFFIXES = frozenset({".html"})
DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
# 서울시청 목록 제목은 `<해>년 <달>월 <기관 축> <부서…> 업무추진비 - <종류>` 모양이다.
# 축은 2026 상반기 전수 실측(2026-09-14)에서 네 가지만 나왔다: 사업소 1,167, 서울시본청
# 1,074, 소방재난본부(소방서) 247, 의회사무처 117.
CITY_AXIS = re.compile(r"^\d{4}년\s*\d{1,2}월\s*(\S+)")


def _months() -> tuple[tuple[int, int], ...]:
    """대상 기간의 달. 레지스트리가 스크래퍼를 선언하므로 기간 모듈은 실행 시점에 부른다."""
    from deliciousmap import period

    return period.months()


def _page_id(year: int, month: int, page: int) -> str:
    """화면 하나의 식별자. 사용월과 쪽만으로 정해져 다시 실행해도 같은 원본을 가리킨다."""
    return f"{year}{month:02d}{page:04d}"


def _screen(url: str, params: dict[str, str], post_id: str) -> boards.Posting:
    """받을 화면 하나를 게시글로 싣는다. 게시일·제목을 밝히지 않는 게시판이라 비워 둔다."""
    address = boards.address(url, params)
    return boards.Posting(
        post_id, (boards.Attachment(post_id, "1", ".html", address, address),), None, ""
    )


class MonthlyScreenBoard:
    """사용월을 고를 수 있고 화면이 곧 원본인 게시판의 공통 경계.

    쪽 수는 그 달의 첫 화면에서만 읽는다. 나머지 쪽은 수집이 내려받으므로 여기서 다시
    부르지 않는다 — 같은 화면을 두 번 요청하지 않기 위해서다.
    """

    published_suffixes = HTML_SUFFIXES
    encoding = "utf-8"

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        for year, month in _months():
            for page in range(1, self.pages(year, month) + 1):
                post_id = _page_id(year, month, page)
                skipped(post_id, None)
                yield _screen(self.list_url, self.page_params(year, month, page), post_id)

    def pages(self, year: int, month: int) -> int:
        """그 달의 화면 수. 기관이 그 달에 공개한 것이 없으면 0이고 원본도 남기지 않는다."""
        body = boards.request(self.transport, self.list_url, self.page_params(year, month, 1))
        return self.page_count(self.text(body))

    def text(self, body: bytes) -> str:
        try:
            return body.decode(self.encoding)
        except UnicodeDecodeError:
            raise boards.UnreadableBoard("board response is not in the measured encoding") from None

    def page_params(self, year: int, month: int, page: int) -> dict[str, str]:
        raise NotImplementedError

    def page_count(self, text: str) -> int:
        raise NotImplementedError


class EunpyeongBoard(MonthlyScreenBoard):
    """은평구 집행 내역 화면. 집행 한 건이 한 줄이고 `searchDeDtMonth`로 사용월을 고른다.

    2026-09-14 실측: `searchDeDtMonth=2026-06`이 그 달만 남기고, `pageUnit`은 화면이
    그대로 받아들인다(10·50·1000 실측). 거르지 않은 전체는 176,448줄·17,645쪽이다.
    """

    # 화면 하나에 담을 줄 수. 실측한 값 중 가장 큰 것을 써서 한 달이 두 화면에 담긴다.
    page_size = "1000"

    def page_params(self, year: int, month: int, page: int) -> dict[str, str]:
        return {
            **self.params,
            "pageIndex": str(page),
            "pageUnit": self.page_size,
            "searchDeDtMonth": f"{year}-{month:02d}",
        }

    def page_count(self, text: str) -> int:
        if not _has_rows(text):
            return 0
        pages = [int(found) for found in re.findall(r"pageIndex=(\d+)", text)]
        return max(pages) if pages else 1


class SeodaemunBoard(MonthlyScreenBoard):
    """서대문구 집행 내역 화면. EUC-KR이고 쪽 넘김은 `cp`다.

    2026-09-14 실측: 검색 필드를 빈 값이라도 함께 보내야 쪽이 바뀐다. 그 조건을 GET
    조회 조건에 그대로 실으면 POST 없이도 쪽이 바뀐다(`cp=1`과 `cp=2`가 다른 화면).
    2026-06은 724건·181쪽이고 화면 하나에 집행 네 건이 담긴다. 금액은 천원 단위다.
    """

    encoding = "euc-kr"

    def page_params(self, year: int, month: int, page: int) -> dict[str, str]:
        return {
            **self.params,
            "cp": str(page),
            "searchGUBUN": "",
            "searchDept": "",
            "searchYear": str(year),
            "searchMonth": f"{month:02d}",
        }

    def page_count(self, text: str) -> int:
        found = re.search(r"집행건수.{0,200}?([\d,]+)\s*건", text, re.S)
        if found is not None and int(found.group(1).replace(",", "")) == 0:
            return 0
        pages = [int(value) for value in re.findall(r"goPage\((\d+)\)", text)]
        return max(pages) if pages else 1


class GwanakBoard(MonthlyScreenBoard):
    """관악구 월별 내려받기. 기관이 주는 공식 산출이지만 내용은 HTML 표다.

    2026-09-14 실측: `.xls` 이름에 `Content-Type: text/html`이고 매직 바이트가 없다.
    시작일·종료일이 31일 이내여야 하므로 달 하나가 요청 하나다. 2026-06은 1,855행이었다.
    """

    def page_params(self, year: int, month: int, page: int) -> dict[str, str]:
        last = calendar.monthrange(year, month)[1]
        return {
            **self.params,
            "searchCondition3": f"{year}-{month:02d}-01",
            "searchCondition4": f"{year}-{month:02d}-{last:02d}",
        }

    def pages(self, year: int, month: int) -> int:
        # 달 하나가 화면 하나다. 쪽 수를 묻자고 같은 산출을 두 번 받지 않는다.
        return 1

    def page_count(self, text: str) -> int:
        return 1


class CityExpenseBoard:
    """서울시청 정보소통광장 업무추진비. 목록은 사용월로 거르고 상세 화면이 원본이다.

    2026-09-14 실측: `ym[year]`·`ym[month]`가 사용월을 거르고 `items_per_page=50`,
    `page`로 넘긴다. 쪽 넘김 막대는 창만 보여 주므로 빈 쪽이 나올 때까지 넘긴다.
    상세 안에 HWPX 내려받기가 있지만 그 경로(`/og/com/`)는 이 호스트의 robots.txt가
    막는 유일한 경로이고, 집행 표는 상세 화면 안에 그대로 있어 열 이유가 없다.

    이 게시판은 기관 축 일곱 갈래가 한 곳에 섞여 있다. 목록 제목이 축을 밝히므로
    업무추진비 집행기관이 아닌 축(의회사무처)을 제목으로 거르고 그 수를 남긴다.
    """

    published_suffixes = HTML_SUFFIXES
    # 거르는 기관 축. 서울특별시가 아니라 별개 기관의 집행이다.
    excluded_axes = frozenset({"의회사무처"})
    page_size = "50"

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        self.transport = transport
        # 제목 축이 걸러 낸 게시글 수. 수집 장부가 아니라 실행 기록으로만 쓴다.
        self.excluded = 0

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        for year, month in _months():
            page = 1
            while True:
                listing = _Listing.of(
                    boards.request(self.transport, self.list_url, self._params(year, month, page))
                )
                if not listing.rows:
                    break
                for post_id, title, posted in listing.rows:
                    if self._excluded(title):
                        self.excluded += 1
                        continue
                    page_url = urllib.parse.urljoin(self.list_url, f"/expense/{post_id}")
                    attachments = (
                        ()
                        if skipped(post_id, posted)
                        else (boards.Attachment(post_id, "1", ".html", page_url, page_url),)
                    )
                    yield boards.Posting(post_id, attachments, posted, title)
                page += 1

    def _excluded(self, title: str) -> bool:
        found = CITY_AXIS.match(title)
        return found is not None and found.group(1) in self.excluded_axes

    def _params(self, year: int, month: int, page: int) -> dict[str, str]:
        return {
            **self.params,
            "ym[year]": str(year),
            "ym[month]": str(month),
            "items_per_page": self.page_size,
            "page": str(page),
        }


class _Listing(HTMLParser):
    """서울시청 목록의 게시글 번호·제목·공개일만 읽는다.

    제목 칸이 닫히지 않은 채 다음 칸이 열리는 화면이라(실측) 새 칸이 열릴 때 앞 칸을
    닫는다. 담당자 실명은 목록에 없고 상세에만 있으므로 여기서 읽지 않는다.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str, date | None]] = []
        self._post_id = ""
        self._title: list[str] = []
        self._cell: str = ""
        self._parts: list[str] = []
        self._in_title = False

    @staticmethod
    def of(body: bytes) -> _Listing:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            raise boards.UnreadableBoard("board response is not in the measured encoding") from None
        listing = _Listing()
        listing.feed(text)
        listing.close()
        return listing

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raw = dict(attrs)
        if tag in {"td", "th"}:
            self._close_cell()
            self._cell = " ".join((raw.get("class") or "").split())
            self._parts = []
        elif tag == "a" and self._cell.startswith("data-title"):
            found = re.fullmatch(r"/expense/(\d+)", raw.get("href") or "")
            if found is not None:
                self._post_id = found.group(1)
                self._in_title = True
                self._title = []
        elif tag == "tr":
            self._close_cell()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._in_title = False
        elif tag in {"td", "th", "tr"}:
            self._close_cell()

    def handle_data(self, data: str) -> None:
        self._parts.append(data)
        if self._in_title:
            self._title.append(data)

    def _close_cell(self) -> None:
        if self._cell.startswith("data-date") and self._post_id:
            found = DATE.search("".join(self._parts))
            posted = _posted(found)
            self.rows.append((self._post_id, " ".join("".join(self._title).split()), posted))
            self._post_id = ""
        self._cell = ""
        self._parts = []


def _posted(found: re.Match[str] | None) -> date | None:
    if found is None:
        return None
    try:
        return date(*(int(part) for part in found.groups()))
    except ValueError:
        raise boards.UnreadableBoard("board listing declares an impossible posting date") from None


def _has_rows(text: str) -> bool:
    """화면이 집행 줄을 담고 있는지. 머리글만 있는 화면은 원본으로 남기지 않는다."""
    return len(re.findall(r"<tr[\s>]", text, re.I)) > 1


__all__ = [
    "CityExpenseBoard",
    "EunpyeongBoard",
    "GwanakBoard",
    "MonthlyScreenBoard",
    "SeodaemunBoard",
]
