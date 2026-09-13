"""광주 서구청 업무추진비 공개 해석. 2026-09-13 실측한 구조만 따른다.

실측(`docs/validation/issue-97.md`): 이 구는 일반 게시판이 아니라 `openInfoCostList.es`라는
전용 화면을 쓴다. 게시글 본문이 없고 목록 한 줄이 곧바로 `openInfoDataFileDownload.es`로
이어진다. 쪽 넘김도 없어 한 응답에 그 게시판 전부가 실린다(부서장 탭 실측 약 16.8MB).
줄은 `<tr><td>` 표이고 칸 차례는 번호·제목·내려받기·비고·게시일이며 게시일은 `YYYY-MM-DD`다.
첨부 이름과 형식은 목록에도 링크에도 없어, 받은 내용의 매직 바이트로만 형식을 가린다.
응답은 UTF-8이고 브라우저 위장 없이 200을 준다.
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
CATEGORY_PARAMETER = "oi_seq"
MENU_PARAMETER = "mid"
DOWNLOAD_PATH = "openInfoDataFileDownload.es"
POST_PARAMETER = "oid_seq"
FILE_PARAMETER = "file_seq"
# 이 게시판은 첨부 이름을 어디에도 밝히지 않는다. 빈 문자열은 "게시판이 형식을 말하지 않았다"는
# 뜻이며, 받아들일지는 내려받은 내용의 매직 바이트가 정한다(`boards.container_of`).
PUBLISHED_SUFFIXES = frozenset({""})
POSTED = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
ROW_TAG = "tr"
CELL_TAG = "td"


class SeoguExpenseBoard:
    """서구 업무추진비 공개 화면 하나. 탭(`oi_seq`)마다 따로 선언해 쓴다."""

    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        for name in (CATEGORY_PARAMETER, MENU_PARAMETER):
            if not boards.is_identifier(self.params.get(name, "")):
                raise ValueError("board url must declare mid and oi_seq")
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        # 쪽 넘김이 없다. 한 번 받은 목록이 그 게시판 전부이고 첨부 주소까지 담고 있다.
        page_url = boards.address(self.list_url, self.params)
        body = boards.request(self.transport, self.list_url, self.params)
        listing = boards.parse(body, ENCODING, _Listing())
        for row in _rows(listing):
            if skipped(row.post_id, row.posted):
                # 넘기기로 한 게시글도 목록에서 읽은 값은 낸다. 여기에는 더 열 본문이 없다.
                yield row.posting(())
                continue
            attachments = tuple(
                boards.Attachment(
                    post_id=row.post_id,
                    file_id=file_id,
                    suffix="",
                    url=urllib.parse.urljoin(self.list_url, href),
                    page_url=page_url,
                )
                for file_id, href in row.files
            )
            yield row.posting(attachments)


@dataclass(frozen=True)
class _Row:
    """목록 한 줄. 본문이 없으므로 첨부 주소까지 이 줄에서 다 읽는다."""

    post_id: str
    posted: date
    title: str
    files: tuple[tuple[str, str], ...]

    def posting(self, attachments: tuple[boards.Attachment, ...]) -> boards.Posting:
        # 이 게시판은 작성 부서를 밝히지 않는다. 부서는 원본 표에서 읽는다.
        return boards.Posting(self.post_id, attachments, self.posted, self.title)


class _Listing(boards.Document):
    """목록 한 쪽. 줄마다 칸의 글자와 그 줄에 실린 내려받기 주소를 모은다."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[_Row] = []
        self._cells: list[list[str]] = []
        self._hrefs: list[tuple[int, str]] = []
        self._cell: list[str] | None = None
        self._row = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        if tag == ROW_TAG:
            self._cells, self._hrefs, self._cell, self._row = [], [], None, True
        elif tag == CELL_TAG and self._row:
            self._cell = []
            self._cells.append(self._cell)

    def handle_endtag(self, tag: str) -> None:
        closed = len(self.links)
        super().handle_endtag(tag)
        if self._row and len(self.links) > closed:
            self._hrefs.append((len(self._cells) - 1, self.links[-1][0]))
        if tag == CELL_TAG and self._row:
            self._cell = None
        elif tag == ROW_TAG and self._row:
            self._row = False
            self._close([" ".join("".join(cell).split()) for cell in self._cells])

    def handle_data(self, data: str) -> None:
        super().handle_data(data)
        if self._cell is not None:
            self._cell.append(data)

    def _close(self, cells: list[str]) -> None:
        files = tuple(
            (file_id, href)
            for _, href in self._hrefs
            if (file_id := _download_parameter(href, FILE_PARAMETER)) is not None
        )
        posts = {
            post
            for _, href in self._hrefs
            if (post := _download_parameter(href, POST_PARAMETER)) is not None
        }
        if not files:
            # 내려받을 것이 없는 줄(머리글·첨부 없는 항목)은 게시글로 세지 않는다.
            return
        if len(posts) != 1:
            raise boards.UnreadableBoard("board listing row does not name exactly one post")
        dated = next((index for index, cell in enumerate(cells) if POSTED.search(cell)), None)
        if dated is None:
            raise boards.UnreadableBoard("board listing row does not declare its posting date")
        # 칸 차례는 번호·제목·내려받기·비고·게시일이다. 제목은 번호 바로 다음 칸이다.
        title = cells[1] if len(cells) > 1 else ""
        self.rows.append(_Row(posts.pop(), _posted_on(cells[dated]), title, files))


def _posted_on(cell: str) -> date:
    """줄이 밝힌 게시일. 모양만 날짜인 값은 날짜로 받아들이지 않는다."""
    day = POSTED.search(cell)
    if day is None:
        raise boards.UnreadableBoard("board listing row does not declare its posting date")
    try:
        return date(*(int(part) for part in day.groups()))
    except ValueError:
        raise boards.UnreadableBoard(
            "board listing row declares an impossible posting date"
        ) from None


def _rows(listing: "_Listing") -> tuple[_Row, ...]:
    """목록이 낸 게시글. 같은 게시글이 두 줄에 걸쳐 나오면 먼저 나온 줄을 쓴다."""
    if not listing.rows and any(
        _download_parameter(href, FILE_PARAMETER) is not None for href, _ in listing.links
    ):
        # 내려받기 링크가 있는데 줄을 나누지 못했다. 게시글 없음과 구별해 알린다.
        raise boards.UnreadableBoard("board listing rows no longer follow the measured structure")
    seen: dict[str, _Row] = {}
    for row in listing.rows:
        seen.setdefault(row.post_id, row)
    return tuple(seen.values())


def _download_parameter(href: str, name: str) -> str | None:
    parts = urllib.parse.urlsplit(href)
    if not parts.path.endswith(DOWNLOAD_PATH):
        return None
    value = dict(urllib.parse.parse_qsl(parts.query)).get(name, "")
    return value if boards.is_identifier(value) else None
