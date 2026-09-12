"""광주광역시청 업무추진비 게시판 해석. 2026-09-11 실측한 구조만 따른다.

실측(`docs/validation/issue-51.md`): 목록은 `boardList.do`의 `movePage`로 넘기고 페이지 수는
`전체페이지 : N`에 있다. 게시글은 `boardView.do?boardId=&seq=`(축약형으로 200 확인),
첨부는 `fileDownload.do?...fileSn=`이다. 두 주소 모두 `seq`를 실어 목록에서 첨부가 달린
게시글을 가려낼 수 있다. 응답은 UTF-8이고
Referer·브라우저 위장 없이 200을 준다. 폐기된 `pageId` 파라미터는 붙이지 않는다.
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
VIEW_PATH = "boardView.do"
FILE_PATH = "fileDownload.do"
BOARD_PARAMETER = "boardId"
PAGE_PARAMETER = "movePage"
POST_PARAMETER = "seq"
FILE_PARAMETER = "fileSn"
# 이 게시판에서 실측한 첨부 형식. 2026-09-11 표본 80건과 첫 운영 수집에서 만난 건을 모두
# 내려받아 매직 바이트까지 확인했다. 그 밖의 형식이 올라오면 조용히 넘기지 않고 알린다.
PUBLISHED_SUFFIXES = frozenset({".xls", ".xlsx", ".xlsm", ".hwp", ".hwpx", ".pdf"})
# 목록이 밝히는 전체 페이지 수. 이 값이 없으면 게시판 구조가 바뀐 것이므로 짐작하지 않는다.
TOTAL_PAGES = re.compile(r"전체페이지\s*:\s*([\d,]+)")
# 목록 한 줄의 실측 구조. 게시일과 제목은 본문이 아니라 이 줄에만 있고, 지출 기간은 제목에만
# 있다. 대상 원본은 본문을 열기 전에 골라야 하므로 여기까지는 요소 구조를 읽는다.
ROW_CLASS = "body_row"
DATE_CLASS = "date"
# 게시글을 올린 부서. 원본 표에 부서 열이 없을 때 이 값이 부서가 된다.
WRITER_CLASS = "writer"
# 화면에 읽히지 않는 딱지(`작성일`·`작성자`). 값이 아니므로 줄의 글자에서 뺀다.
BLIND_CLASS = "blind"
POSTED = re.compile(r"\d{4}-\d{2}-\d{2}")


class GwangjuCityBoard:
    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not boards.is_identifier(self.params.get(BOARD_PARAMETER, "").replace("_", "")):
            raise ValueError("board url must declare boardId")
        self.view_url = urllib.parse.urljoin(self.list_url, VIEW_PATH)
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
        params = {BOARD_PARAMETER: self.params[BOARD_PARAMETER], POST_PARAMETER: row.post_id}
        page_url = boards.address(self.view_url, params)
        attachments = []
        for href, filename in self._read(self.view_url, params).links:
            file_id = _parameter(href, FILE_PATH, FILE_PARAMETER)
            if file_id is None:
                continue
            attachments.append(
                boards.Attachment(
                    post_id=row.post_id,
                    file_id=file_id,
                    suffix=boards.suffix_of(filename),
                    url=urllib.parse.urljoin(self.list_url, href),
                    page_url=page_url,
                )
            )
        return row.posting(tuple(attachments))

    def _listing(self, page: int) -> "_Listing":
        params = {**self.params, PAGE_PARAMETER: str(page)}
        body = boards.request(self.transport, self.list_url, params)
        return boards.parse(body, ENCODING, _Listing())

    def _read(self, url: str, params: dict[str, str]) -> boards.Document:
        return boards.read(boards.request(self.transport, url, params), ENCODING)


@dataclass(frozen=True)
class _Row:
    """목록 한 줄. 게시글 번호·게시일·제목과 그 줄에 첨부 링크가 있었는지만 남긴다."""

    post_id: str
    posted: date
    title: str
    department: str
    filed: bool

    def posting(self, attachments: tuple[boards.Attachment, ...]) -> boards.Posting:
        return boards.Posting(self.post_id, attachments, self.posted, self.title, self.department)


class _Listing(boards.Document):
    """목록 한 쪽. 공통 해석에 더해 실측한 `body_row` 구조로 줄을 나눈다."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[_Row] = []
        # `body_row` 안쪽 div의 깊이. 0이면 줄 밖이다.
        self._depth = 0
        self._posted_depth = 0
        self._writer_depth = 0
        # 지금 열려 있는 `blind` 요소의 태그. `span` 말고 `label`에도 붙는다(실측).
        self._blind: list[str] = []
        self._links: list[str] = []
        self._titles: list[str] = []
        self._posted: list[str] = []
        self._writer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        classes = (dict(attrs).get("class") or "").split()
        if BLIND_CLASS in classes:
            self._blind.append(tag)
        if tag != "div":
            return
        if self._depth:
            if ROW_CLASS in classes:
                # 앞 줄이 닫히기 전에 다음 줄이 시작했다. 그대로 두면 남은 줄이 갇힌다.
                raise boards.UnreadableBoard("board listing row started before the previous closed")
            self._depth += 1
            if DATE_CLASS in classes:
                self._posted_depth = self._depth
            if WRITER_CLASS in classes:
                self._writer_depth = self._depth
        elif ROW_CLASS in classes:
            self._depth, self._posted_depth, self._writer_depth = 1, 0, 0
            self._links, self._titles = [], []
            self._posted, self._writer = [], []
            # 줄 밖 markup의 짝이 맞지 않아도 줄 읽기는 그대로 되게 한다.
            self._blind = [tag] if BLIND_CLASS in classes else []

    def handle_endtag(self, tag: str) -> None:
        closed = len(self.links)
        super().handle_endtag(tag)
        if self._depth and len(self.links) > closed:
            href, text = self.links[-1]
            self._links.append(href)
            if _parameter(href, VIEW_PATH, POST_PARAMETER) is not None:
                self._titles.append(text)
        if self._blind and self._blind[-1] == tag:
            self._blind.pop()
        if tag != "div" or not self._depth:
            return
        if self._posted_depth == self._depth:
            self._posted_depth = 0
        if self._writer_depth == self._depth:
            self._writer_depth = 0
        self._depth -= 1
        if not self._depth:
            self._close()

    def handle_data(self, data: str) -> None:
        super().handle_data(data)
        if self._blind:
            return
        if self._posted_depth:
            self._posted.append(data)
        if self._writer_depth:
            self._writer.append(data)

    def close(self) -> None:
        """쪽을 다 읽었는데 줄이 닫히지 않았으면 그 줄에 나머지 게시글이 갇힌 것이다."""
        super().close()
        if self._depth:
            raise boards.UnreadableBoard("board listing row never closed")

    def _close(self) -> None:
        posts = [_parameter(href, VIEW_PATH, POST_PARAMETER) for href in self._links]
        post_id = next((post for post in posts if post is not None), None)
        if post_id is None:
            # 게시글로 이어지지 않는 줄(머리글 등)은 게시글로 세지 않는다.
            return
        filed = any(_parameter(href, FILE_PATH, POST_PARAMETER) == post_id for href in self._links)
        title = self._titles[0] if self._titles else ""
        department = " ".join("".join(self._writer).split())
        self.rows.append(_Row(post_id, _posted_on(self._posted), title, department, filed))


def _posted_on(parts: list[str]) -> date:
    """줄이 밝힌 게시일. 모양만 날짜인 값은 날짜로 받아들이지 않는다."""
    day = POSTED.search(" ".join("".join(parts).split()))
    if day is None:
        raise boards.UnreadableBoard("board listing row does not declare its posting date")
    try:
        return date.fromisoformat(day.group(0))
    except ValueError:
        raise boards.UnreadableBoard(
            "board listing row declares an impossible posting date"
        ) from None


def _with_attachments(listing: "_Listing") -> tuple[_Row, ...]:
    """목록에 첨부 링크가 함께 실린 게시글만 고른다. 본문을 열어 보지 않는다."""
    if not listing.rows and any(
        _parameter(href, VIEW_PATH, POST_PARAMETER) is not None for href, _ in listing.links
    ):
        # 게시글로 이어지는 링크가 있는데 줄을 나누지 못했다. 게시글 없음과 구별해 알린다.
        raise boards.UnreadableBoard("board listing rows no longer follow the measured structure")
    seen: dict[str, _Row] = {}
    for row in listing.rows:
        seen.setdefault(row.post_id, row)
    return tuple(row for row in seen.values() if row.filed)


def _total_pages(listing: boards.Document) -> int:
    found = TOTAL_PAGES.search(listing.text)
    if found is None:
        raise boards.UnreadableBoard("board listing does not declare its page count")
    return int(found.group(1).replace(",", ""))


def _parameter(href: str, path: str, name: str) -> str | None:
    parts = urllib.parse.urlsplit(href)
    if not parts.path.endswith(path):
        return None
    value = dict(urllib.parse.parse_qsl(parts.query)).get(name, "")
    return value if boards.is_identifier(value) else None
