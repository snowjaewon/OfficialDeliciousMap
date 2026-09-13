"""광주 자치구 `.es` 게시판 해석. 2026-09-13 실측한 북구·남구·동구 구조만 따른다.

실측(`docs/validation/issue-97.md`): 목록은 `board.es?mid=&bid=`의 `nPage`로 넘기고 쪽 수는
`현재 페이지 N/P`에 있다. 게시글은 같은 주소에 `act=view&list_no=`를 붙이고, 첨부는 구마다
`boardDownload.es`(북구)나 `download.es`(남구·동구)로 갈리되 둘 다 `list_no`와 `seq`를 싣는다.
목록 한 줄은 북구·동구가 `<ul><li>`, 남구가 `<tr><td>`지만 칸 차례는 셋 다
번호·제목·부서·게시일·첨부·조회수로 같다. 응답은 UTF-8이고 브라우저 위장 없이 200을 준다.
"""

import re
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from deliciousmap import boards
from deliciousmap.transport import Transport

if TYPE_CHECKING:  # 레지스트리가 이 스크래퍼를 선언한다. 실행 시점에 되짚어 부르지 않는다.
    from deliciousmap.registry.models import Board

ENCODING = "utf-8"
LIST_PATH = "board.es"
BOARD_PARAMETER = "bid"
MENU_PARAMETER = "mid"
PAGE_PARAMETER = "nPage"
POST_PARAMETER = "list_no"
FILE_PARAMETER = "seq"
ACTION_PARAMETER = "act"
VIEW_ACTION = "view"
# 첨부 주소의 경로. 같은 게시판 계열인데 구마다 이름이 다르다(실측).
DOWNLOAD_PATHS = ("boardDownload.es", "download.es")
# 이 계열에서 실측한 첨부 형식. 2026년치 379건을 모두 내려받아 매직 바이트까지 확인했다.
# 그 밖의 형식이 올라오면 조용히 넘기지 않고 알린다.
PUBLISHED_SUFFIXES = frozenset({".xls", ".xlsx", ".xlsm", ".hwp", ".hwpx", ".pdf"})
# 목록이 밝히는 현재 쪽과 전체 쪽. 이 값이 없으면 게시판 구조가 바뀐 것이므로 짐작하지 않는다.
PAGE_INFO = re.compile(r"현재\s*페이지\s*(\d+)\s*/\s*([\d,]+)")
# 이 계열의 게시일 표기. 시청의 `YYYY-MM-DD`와 달라 따로 읽는다.
POSTED = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
# 첨부가 달린 줄임을 알리는 그림의 대체 문구. 확장자는 붙기도 하고 비기도 한다(동구 실측).
ATTACHED = "첨부파일"
# 첨부 이름에서 형식을 읽는다. 북구는 링크의 `title`에, 남구·동구는 링크 글자와 `filename`에 있다.
NAMED_SUFFIX = re.compile(r"\.([A-Za-z0-9]{1,8})(?=[\s,\](]|$)")
FILENAME_PARAMETER = "filename"
# 목록 한 줄을 이루는 요소. 구마다 표와 목록으로 갈려 둘 다 받는다.
ROW_TAGS = frozenset({"ul", "tr"})
CELL_TAGS = frozenset({"li", "td"})


class GwangjuDistrictBoard:
    """`.es` 게시판 하나. 게시판 주소가 밝힌 `mid`·`bid`만 쓰고 구를 구별하지 않는다."""

    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        for name in (BOARD_PARAMETER, MENU_PARAMETER):
            if not boards.is_identifier(self.params.get(name, "")):
                raise ValueError("board url must declare mid and bid")
        self.transport = transport

    def postings(self, collected: boards.Collected) -> Iterator[boards.Posting]:
        page = 1
        while True:
            listing = self._listing(page)
            for row in _with_attachments(listing):
                # 이미 끝낸 게시글은 본문을 열지 않고 목록에서 읽은 값만 낸다.
                yield row.posting(()) if collected(row.post_id) else self._posting(row)
            if page >= _total_pages(listing):
                return
            page += 1

    def _posting(self, row: "_Row") -> boards.Posting:
        params = {**self.params, ACTION_PARAMETER: VIEW_ACTION, POST_PARAMETER: row.post_id}
        page_url = boards.address(self.list_url, params)
        body = boards.request(self.transport, self.list_url, params)
        attachments = []
        for href, text, title in boards.parse(body, ENCODING, _View()).files:
            file_id = _download_parameter(href, FILE_PARAMETER)
            if file_id is None or _download_parameter(href, POST_PARAMETER) != row.post_id:
                continue
            attachments.append(
                boards.Attachment(
                    post_id=row.post_id,
                    file_id=file_id,
                    suffix=_suffix(href, text, title),
                    url=urllib.parse.urljoin(self.list_url, href),
                    page_url=page_url,
                )
            )
        return row.posting(tuple(attachments))

    def _listing(self, page: int) -> "_Listing":
        params = {**self.params, PAGE_PARAMETER: str(page)}
        body = boards.request(self.transport, self.list_url, params)
        return boards.parse(body, ENCODING, _Listing())


@dataclass(frozen=True)
class _Row:
    """목록 한 줄. 게시글 번호·게시일·제목·부서와 첨부 표시가 있었는지만 남긴다."""

    post_id: str
    posted: date
    title: str
    department: str
    filed: bool

    def posting(self, attachments: tuple[boards.Attachment, ...]) -> boards.Posting:
        return boards.Posting(self.post_id, attachments, self.posted, self.title, self.department)


class _View(boards.Document):
    """게시글 본문. 앵커의 주소와 함께 `title`까지 남긴다. 첨부 형식이 거기에만 있는 구가 있다."""

    def __init__(self) -> None:
        super().__init__()
        self.files: list[tuple[str, str, str]] = []
        self._titles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        if tag == "a":
            self._titles.append(dict(attrs).get("title") or "")

    def handle_endtag(self, tag: str) -> None:
        closed = len(self.links)
        super().handle_endtag(tag)
        if tag == "a" and self._titles and len(self.links) > closed:
            href, text = self.links[-1]
            self.files.append((href, text, self._titles.pop()))


class _Listing(boards.Document):
    """목록 한 쪽. 줄은 요소 이름이 아니라 칸의 차례로 읽는다. 구마다 표와 목록으로 갈린다."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[_Row] = []
        # 지금 열려 있는 줄들. 메뉴처럼 겹친 목록이 있어 쌓아 둔다.
        self._cells: list[list[list[str]]] = []
        # 줄마다 링크를 그 링크가 들어 있던 칸 번호와 함께 둔다. 제목 칸을 그 값으로 가린다.
        self._hrefs: list[list[tuple[int, str]]] = []
        self._filed: list[bool] = []
        self._cell: list[list[str] | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        if tag == "img" and self._cells and ATTACHED in (dict(attrs).get("alt") or ""):
            self._filed[-1] = True
        if tag in ROW_TAGS:
            self._cells.append([])
            self._hrefs.append([])
            self._filed.append(False)
            self._cell.append(None)
        elif tag in CELL_TAGS and self._cells:
            cell: list[str] = []
            self._cells[-1].append(cell)
            self._cell[-1] = cell

    def handle_endtag(self, tag: str) -> None:
        closed = len(self.links)
        super().handle_endtag(tag)
        if self._cells and len(self.links) > closed:
            self._hrefs[-1].append((len(self._cells[-1]) - 1, self.links[-1][0]))
        if tag in CELL_TAGS and self._cells:
            self._cell[-1] = None
        elif tag in ROW_TAGS and self._cells:
            cells = [" ".join("".join(cell).split()) for cell in self._cells.pop()]
            self._cell.pop()
            self._close(cells, self._hrefs.pop(), self._filed.pop())

    def handle_data(self, data: str) -> None:
        super().handle_data(data)
        if self._cells and self._cell[-1] is not None:
            self._cell[-1].append(data)

    def _close(self, cells: list[str], hrefs: list[tuple[int, str]], filed: bool) -> None:
        linked = [(index, _post_of(href)) for index, href in hrefs]
        found = next(((index, post) for index, post in linked if post is not None), None)
        if found is None:
            # 게시글로 이어지지 않는 줄(머리글·메뉴)은 게시글로 세지 않는다.
            return
        titled, post_id = found
        if not 0 <= titled < len(cells):
            raise boards.UnreadableBoard("board listing row places its post link outside a cell")
        dated = next(
            (index for index, cell in enumerate(cells) if index > titled and POSTED.search(cell)),
            None,
        )
        if dated is None:
            raise boards.UnreadableBoard("board listing row does not declare its posting date")
        # 칸 차례는 번호·제목·부서·게시일이다. 제목 바로 다음 칸이 게시일이면 부서 칸이 없다.
        department = cells[titled + 1] if dated > titled + 1 else ""
        self.rows.append(_Row(post_id, _posted_on(cells[dated]), cells[titled], department, filed))


def _posted_on(cell: str) -> date:
    """줄이 밝힌 게시일. 모양만 날짜인 값은 날짜로 받아들이지 않는다."""
    day = POSTED.search(cell)
    if day is None:
        raise boards.UnreadableBoard("board listing row does not declare its posting date")
    year, month, item = (int(part) for part in day.groups())
    try:
        return date(year, month, item)
    except ValueError:
        raise boards.UnreadableBoard(
            "board listing row declares an impossible posting date"
        ) from None


def _with_attachments(listing: "_Listing") -> tuple[_Row, ...]:
    """목록에 첨부 표시가 함께 실린 게시글만 고른다. 본문을 열어 보지 않는다."""
    if not listing.rows and any(_post_of(href) is not None for href, _ in listing.links):
        # 게시글로 이어지는 링크가 있는데 줄을 나누지 못했다. 게시글 없음과 구별해 알린다.
        raise boards.UnreadableBoard("board listing rows no longer follow the measured structure")
    seen: dict[str, _Row] = {}
    for row in listing.rows:
        seen.setdefault(row.post_id, row)
    return tuple(row for row in seen.values() if row.filed)


def _total_pages(listing: "_Listing") -> int:
    found = PAGE_INFO.search(listing.text)
    if found is None:
        raise boards.UnreadableBoard("board listing does not declare its page count")
    return int(found.group(2).replace(",", ""))


def _post_of(href: str) -> str | None:
    """게시글로 이어지는 링크인지. 같은 주소가 목록·본문을 겸해 `act=view`까지 본다."""
    parts = urllib.parse.urlsplit(href)
    if not parts.path.endswith(LIST_PATH):
        return None
    params = dict(urllib.parse.parse_qsl(parts.query))
    if params.get(ACTION_PARAMETER) != VIEW_ACTION:
        return None
    value = params.get(POST_PARAMETER, "")
    return value if boards.is_identifier(value) else None


def _download_parameter(href: str, name: str) -> str | None:
    parts = urllib.parse.urlsplit(href)
    if not any(parts.path.endswith(path) for path in DOWNLOAD_PATHS):
        return None
    value = dict(urllib.parse.parse_qsl(parts.query)).get(name, "")
    return value if boards.is_identifier(value) else None


def _suffix(href: str, text: str, title: str) -> str:
    """게시판이 밝힌 첨부 형식. 구마다 링크 글자·`title`·`filename` 중 하나에만 있다."""
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(href).query))
    for name in (text, title, query.get(FILENAME_PARAMETER, "")):
        found = NAMED_SUFFIX.search(name)
        if found is not None:
            return f".{found.group(1).lower()}"
    return ""
