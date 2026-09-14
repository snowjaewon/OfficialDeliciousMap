"""첨부를 내려받는 서울 자치구 게시판의 계열 스크래퍼.

2026-09-14에 프로젝트 UA로 실측한 네 계열을 담는다. 기관마다 다른 값(게시판 번호·
메뉴 키·첨부 경로)은 레지스트리의 게시판 주소에서 오고, 계열 안에서 갈리는 것은
목록에 첨부가 있는지(`attachments_in_listing`) 하나다.

- bbsNo: `selectBbsNttList.do?bbsNo=&key=` + `pageIndex` — 성동·동대문·성북·구로·
  금천·영등포·송파
- portal-bbs: `/portal/bbs/<게시판>/list.do?menuNo=` + `pageIndex` — 용산·광진·동작,
  그리고 경로가 다른 중랑
- cbIdx: `ex/bbs/List.do?cbIdx=` + `pageIndex` → `View.do` → `Download.do` — 양천·서초
- 종로: egov `selectBoardList.do`. 목록에서 바로 첨부를 주고 제목 칸이 없다.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from deliciousmap import boards
from deliciousmap.transport import Transport

if TYPE_CHECKING:
    from deliciousmap.registry.models import Board

ENCODING = "utf-8"
# 서울 자치구 게시판에서 실측한 첨부 형식. 같은 게시판 안에서도 섞여 올라온다
# (구로 pdf·hwp, 양천 hwpx·xlsx). 무엇으로 받아들일지는 매직 바이트가 정한다.
# 빈 값은 게시판이 형식을 밝히지 않은 첨부다(종로·동작 실측: 링크에 그림과 "다운로드"만
# 있고 파일 이름이 없다). 무엇으로 받아들일지는 어차피 매직 바이트가 정하므로, 밝히지
# 않은 것을 실측하지 않은 형식으로 바꿔 세지 않는다.
# `.jpg`·`.png`는 용산이 집행내역을 스캔본으로 올린 2026년 게시글 10건에서 실측했다.
PUBLISHED_SUFFIXES = frozenset(
    {"", ".pdf", ".hwp", ".hwpx", ".xls", ".xlsx", ".xlsm", ".zip", ".jpg", ".jpeg", ".png"}
)
# 게시글 하나를 담는 요소. 게시판마다 다르므로 계열 스크래퍼가 고른다. 표로 그린
# 게시판은 `tr`, 광진은 `li` 하나가 게시글, 종로는 `ul` 하나가 게시글이다(실측).
ROW_TAGS = frozenset({"tr", "ul", "li"})
CELL_TAGS = frozenset({"td", "th", "li"})
# 이 계열들의 게시일 표기. `2026.09.14`·`2026-09-14`·`2026년 09월 10일`을 실측했다.
POSTED = re.compile(
    r"(?:(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})|(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일)"
)
# 파일 이름에서 읽는 형식. 앞뒤가 글자·숫자가 아닌 자리의 확장자만 본다.
NAMED_SUFFIX = re.compile(r"\.([A-Za-z0-9]{1,8})(?![A-Za-z0-9])")
# 화면 글자로만 형식을 밝히는 목록. 성동·구로 실측의 `pdf파일첨부` 모양이다.
SPELLED_SUFFIX = re.compile(r"\b(pdf|hwpx|hwp|xlsx|xlsm|xls|zip)\s*(?:파일|문서)", re.I)
# 목록이 전체 쪽 수를 글자로 밝히는 자리. `[ 1 / 762 페이지 ]`와 `[ 1 / 571 pages ]`를
# 모두 실측했다(용산·광진).
PAGE_INFO = re.compile(r"\[\s*[\d,]+\s*/\s*([\d,]+)\s*(?:페이지|pages?)\s*\]", re.I)


def suffix_from(*values: str) -> str:
    """게시판이 밝힌 형식. 읽지 못하면 빈 값이고, 그 첨부는 실측 대상으로 남는다."""
    for value in values:
        for found in NAMED_SUFFIX.finditer(value):
            suffix = f".{found.group(1).lower()}"
            if suffix in PUBLISHED_SUFFIXES:
                return suffix
        spelled = SPELLED_SUFFIX.search(value)
        if spelled is not None:
            return f".{spelled.group(1).lower()}"
    return ""


def posted_on(cell: str) -> date | None:
    """줄이 밝힌 게시일. 모양만 날짜인 값은 날짜로 받아들이지 않는다.

    읽지 못한 줄은 게시일 없음으로 둔다. 게시판이 그 칸을 비워 두거나(동작 실측의 2017년
    줄) 달력에 없는 날을 적는(중구 실측의 `2021-05-70`) 일이 있고, 기관이 잘못 적은 한 줄
    때문에 그 기관의 2026년 원본까지 0건이 되게 하지 않기 위해서다. 읽지 못했다는 사실은
    빈 게시일로 남고, 이번 제출의 대상인지는 제목이 밝힌 기간이 정한다(`period.exclusion`).

    구조가 바뀐 게시판은 이 함수가 아니라 쪽 단위로 가른다 — 한 쪽의 어느 줄에도 날짜
    모양이 없으면 `ListingBoard.postings`가 멈춘다.
    """
    found = POSTED.search(cell)
    if found is None:
        return None
    parts = [value for value in found.groups() if value is not None]
    try:
        return date(*(int(part) for part in parts))
    except ValueError:
        return None


@dataclass(frozen=True)
class Link:
    """줄 안의 앵커 하나. 어느 칸에 있었는지까지 남겨 제목 칸과 첨부 칸을 가른다.

    `title`을 따로 든다. 용산·광진은 첨부 링크에 그림만 넣고 파일 이름을 `title`에만
    싣기 때문에(2026-09-14 실측) 링크 글자만으로는 형식을 읽을 수 없다.
    """

    cell: int
    href: str
    text: str
    onclick: str
    title: str = ""


@dataclass(frozen=True)
class Row:
    """목록 한 줄. 칸의 글자와 앵커만 남기고 요소 구조에는 기대지 않는다."""

    cells: tuple[str, ...]
    links: tuple[Link, ...]

    @property
    def text(self) -> str:
        return " ".join(self.cells)

    def cell(self, index: int) -> str:
        return self.cells[index] if 0 <= index < len(self.cells) else ""


@dataclass
class _Open:
    """해석 중인 줄 하나. 표와 목록이 서로 안에 겹쳐 나오므로 쌓아 두고 안쪽부터 닫는다."""

    tag: str
    cells: list[str]
    links: list[Link]
    parts: list[str] | None = None
    # 줄 전체의 글자. 칸을 따로 그리지 않는 게시판(광진 실측)은 이 값이 유일한 칸이 된다.
    text: list[str] = field(default_factory=list)


class Listing(boards.Document):
    """목록 한 쪽. 표와 목록을 같은 방식으로 읽는다.

    줄을 쌓아 두고 안쪽부터 닫는다. 메뉴 목록 안에 표가 들어 있거나 칸 안에 목록이
    들어 있는 화면이 있어(광진·구로·서초 실측), 겹친 줄을 하나로 뭉치면 게시일 칸이
    줄에서 떨어져 나간다. 게시글로 이어지지 않는 줄은 계열 스크래퍼가 걸러 낸다.
    """

    def __init__(self, row_tags: frozenset[str] = frozenset({"tr"})) -> None:
        super().__init__()
        self.rows: list[Row] = []
        self.row_tags = row_tags
        # 줄을 이루는 요소는 칸이 될 수 없다. 종로는 `ul`이 줄이고 `li`가 칸,
        # 광진은 `li`가 줄이라 그 안의 `li`를 칸으로 읽지 않는다.
        self.cell_tags = CELL_TAGS - row_tags
        self._open_rows: list[_Open] = []
        self._anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        raw = dict(attrs)
        if tag == "a":
            self._anchors.append((raw.get("onclick") or "", raw.get("title") or ""))
        elif tag == "img":
            self._append(raw.get("alt") or "")
        if tag in self.row_tags:
            self._open_rows.append(_Open(tag, [], []))
        elif tag in self.cell_tags and self._open_rows:
            row = self._open_rows[-1]
            self._close_cell(row)
            row.parts = []

    def handle_endtag(self, tag: str) -> None:
        closed = len(self.links)
        super().handle_endtag(tag)
        if tag == "a":
            onclick, title = self._anchors.pop() if self._anchors else ("", "")
            if len(self.links) > closed and self._open_rows:
                row = self._open_rows[-1]
                href, text = self.links[-1]
                index = len(row.cells) if row.parts is not None else max(len(row.cells) - 1, 0)
                row.links.append(Link(index, href, text, onclick, title))
        elif tag in self.cell_tags and self._open_rows:
            self._close_cell(self._open_rows[-1])
        elif tag in self.row_tags:
            self._close_row(tag)

    def handle_data(self, data: str) -> None:
        super().handle_data(data)
        self._append(data)

    def close(self) -> None:
        super().close()
        while self._open_rows:
            self._close_row(self._open_rows[-1].tag)

    def _append(self, data: str) -> None:
        for row in self._open_rows:
            row.text.append(data)
        if self._open_rows and self._open_rows[-1].parts is not None:
            row = self._open_rows[-1]
            assert row.parts is not None
            row.parts.append(data)

    @staticmethod
    def _close_cell(row: _Open) -> None:
        if row.parts is not None:
            row.cells.append(" ".join("".join(row.parts).split()))
            row.parts = None

    def _close_row(self, tag: str) -> None:
        found = next(
            (
                index
                for index in reversed(range(len(self._open_rows)))
                if self._open_rows[index].tag == tag
            ),
            None,
        )
        if found is None:
            return
        for row in self._open_rows[found:]:
            self._close_cell(row)
            # 칸을 따로 그리지 않는 게시판은 줄 전체를 칸 하나로 둔다(광진 실측).
            cells = row.cells or [" ".join("".join(row.text).split())]
            if any(cells):
                self.rows.append(Row(tuple(cells), tuple(row.links)))
        del self._open_rows[found:]


def listing_of(
    body: bytes, encoding: str = ENCODING, row_tags: frozenset[str] = frozenset({"tr"})
) -> Listing:
    return boards.parse(body, encoding, Listing(row_tags))


def total_pages(listing: Listing, parameter: str) -> int:
    """목록이 밝힌 전체 쪽 수. 밝히지 않으면 짐작하지 않고 알린다.

    쪽 넘김 막대가 창만 보여 주는 게시판이라도 마지막 쪽 단추가 전체 쪽 수를 담는다
    (실측: 성동 357·송파 1,251·구로 1,090). 광진처럼 `[ 1 / 571 pages ]`로 밝히는
    게시판은 그 글자를 먼저 읽는다.
    """
    declared = PAGE_INFO.search(listing.text)
    if declared is not None:
        return int(declared.group(1).replace(",", ""))
    pages = [
        int(value)
        for link in listing.links
        for value in urllib.parse.parse_qs(urllib.parse.urlsplit(link[0]).query).get(parameter, ())
        if value.isdigit()
    ]
    if not pages:
        raise boards.UnreadableBoard("board listing does not declare its page count")
    return max(pages)


def decode(body: bytes, encoding: str) -> str:
    try:
        return body.decode(encoding)
    except UnicodeDecodeError:
        raise boards.UnreadableBoard("board response is not in the measured encoding") from None


def parameter_of(href: str, name: str) -> str | None:
    value = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get(name, [""])[0]
    return value or None


class ListingBoard:
    """목록을 쪽마다 훑는 게시판의 공통 경계. 계열마다 줄 해석과 첨부 자리만 다르다."""

    published_suffixes = PUBLISHED_SUFFIXES
    encoding = ENCODING
    page_parameter = "pageIndex"
    # 게시글 하나를 담는 요소. 게시판마다 실측해서 고른다.
    row_tags = frozenset({"tr"})
    # 첨부 링크가 목록 줄에 있는지. 아니면 게시글 본문을 열어 읽는다(실측으로 갈린다).
    attachments_in_listing = True
    # 이 게시판이 업무추진비 집행기관이 아닌 줄을 섞어 싣는다면 그 부서 이름 조각.
    excluded_departments: frozenset[str] = frozenset()

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        self.transport = transport
        # 섞인 게시판에서 걸러 낸 줄 수. 실행 기록으로만 쓴다.
        self.excluded = 0
        # 지금 읽고 있는 목록 쪽. 상세가 없는 게시판이 출처 주소에 쓴다.
        self.page = 1

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            body = self._request(page)
            listing = listing_of(body, self.encoding, self.row_tags)
            # 상세가 없는 게시판은 지금 읽는 쪽이 게시글의 출처다(강남 실측).
            self.page = page
            rows = [(entry, row) for row in listing.rows if (entry := self.entry(row)) is not None]
            if rows and not any(POSTED.search(row.text) for _, row in rows):
                # 그 쪽의 어느 줄에도 날짜 모양이 없으면 게시판 구조가 바뀐 것이다. 칸을
                # 비워 둔 줄이나 달력에 없는 날을 적은 줄 하나와 달리 조용히 넘기지 않는다.
                raise boards.UnreadableBoard("board listing page declares no posting date")
            for entry, row in rows:
                if self._excluded(entry):
                    self.excluded += 1
                    continue
                if skipped(entry.post_id, entry.posted):
                    yield entry.posting(())
                    continue
                yield entry.posting(self.attachments(entry, row))
            if page >= self.page_count(listing, decode(body, self.encoding)):
                return
            page += 1

    def _request(self, page: int) -> bytes:
        return boards.request(self.transport, self.list_url, self.page_params(page))

    def page_count(self, listing: Listing, text: str) -> int:
        """전체 쪽 수. 쪽 넘김을 주소가 아니라 스크립트로 그리는 게시판이 덮어쓴다."""
        return total_pages(listing, self.page_parameter)

    def page_params(self, page: int) -> dict[str, str]:
        return {**self.params, self.page_parameter: str(page)}

    def _excluded(self, entry: Entry) -> bool:
        return any(name in entry.department for name in self.excluded_departments)

    def entry(self, row: Row) -> Entry | None:
        raise NotImplementedError

    def attachments(self, entry: Entry, row: Row) -> tuple[boards.Attachment, ...]:
        links = row.links if self.attachments_in_listing else self.detail_links(entry)
        found: list[boards.Attachment] = []
        seen: set[str] = set()
        for link in links:
            if not self.is_download(link) or link.href in seen:
                # 같은 원본을 파일 이름 링크와 그림 링크로 두 번 싣는 게시판이 있다(노원 실측).
                continue
            seen.add(link.href)
            found.append(
                boards.Attachment(
                    entry.post_id,
                    str(len(found) + 1),
                    suffix_from(link.title, link.text, link.href, row.text),
                    urllib.parse.urljoin(self.list_url, link.href),
                    entry.page_url,
                    self.referer,
                )
            )
        return tuple(found)

    def detail_links(self, entry: Entry) -> tuple[Link, ...]:
        url, params = boards.endpoint(entry.page_url)
        body = boards.request(self.transport, url, params)
        view = boards.parse(body, self.encoding, _View())
        # 본문은 줄 구조가 아니므로 앵커를 그대로 쓴다. 파일 이름이 `title`에만 있는
        # 게시판이 있어 그 값까지 함께 든다.
        return tuple(Link(0, href, text, "", title) for href, text, title in view.files)

    def is_download(self, link: Link) -> bool:
        raise NotImplementedError

    @property
    def referer(self) -> str:
        return ""


@dataclass(frozen=True)
class Entry:
    """목록이 밝힌 게시글 하나. 본문을 열지 결정하는 데 필요한 값만 담는다."""

    post_id: str
    # 게시판이 읽을 수 있는 게시일을 적지 않은 줄은 빈 값이다(`posted_on`).
    posted: date | None
    title: str
    department: str
    page_url: str

    def posting(self, attachments: tuple[boards.Attachment, ...]) -> boards.Posting:
        return boards.Posting(self.post_id, attachments, self.posted, self.title, self.department)


class BbsNoBoard(ListingBoard):
    """`selectBbsNttList.do` 계열. 성동·동대문·성북·구로·금천·영등포·송파가 같은 모양이다.

    2026-09-14 실측: 제목 링크는 `selectBbsNttView.do?...nttNo=`이고 첨부는
    `downloadBbsFile.do?atchmnflNo=`나 `downloadBbsFileStr.do?atchmnflStr=`다.
    첨부를 목록에 싣는 구(성동·구로·영등포·송파)와 본문에만 싣는 구(동대문·성북·금천)가
    갈린다. 쪽 수는 마지막 쪽 단추의 `pageIndex`가 밝힌다.
    """

    view_path = "selectBbsNttView.do"
    post_parameter = "nttNo"
    board_parameter = "bbsNo"
    download_paths = ("downloadBbsFile.do", "downloadBbsFileStr.do")

    def entry(self, row: Row) -> Entry | None:
        link = next((item for item in row.links if self._view(item)), None)
        if link is None:
            return None
        post_id = parameter_of(link.href, self.post_parameter) or ""
        if not boards.is_identifier(post_id):
            raise boards.UnreadableBoard("board listing row declares an unusable post identifier")
        return Entry(
            post_id,
            posted_on(row.text),
            link.text,
            _department(row, link.cell),
            urllib.parse.urljoin(self.list_url, link.href),
        )

    def _view(self, link: Link) -> bool:
        """이 게시판의 게시글 링크인지. 메뉴에 실린 다른 게시판의 링크를 줄로 읽지 않는다."""
        if self.view_path not in link.href or not parameter_of(link.href, self.post_parameter):
            return False
        declared = self.params.get(self.board_parameter)
        found = parameter_of(link.href, self.board_parameter)
        return declared is None or found is None or found == declared

    def is_download(self, link: Link) -> bool:
        path = urllib.parse.urlsplit(link.href).path
        return any(name in path for name in self.download_paths)


class BbsNoDetailBoard(BbsNoBoard):
    """첨부를 본문에만 싣는 `selectBbsNttList.do` 게시판(동대문·성북·금천 실측)."""

    attachments_in_listing = False


class PortalBoard(ListingBoard):
    """`/portal/bbs/<게시판>/list.do` 계열. 용산·광진·동작이 같은 모양이다.

    2026-09-14 실측: 제목 링크는 `view.do?nttId=`이고 첨부는
    `/portal/cmmn/file/fileDown.do?atchFileId=&fileSn=`다. 광진은 줄을 표가 아니라
    목록으로 그리고 전체 쪽 수를 `[ 1 / 571 pages ]`로 밝힌다.
    """

    view_path = "view.do"
    post_parameter = "nttId"
    download_path = "file/fileDown.do"

    @property
    def board_path(self) -> str:
        """이 게시판의 경로. 메뉴에 실린 다른 게시판의 게시글 링크를 줄로 읽지 않는다."""
        return urllib.parse.urlsplit(self.list_url).path.rsplit("/", 1)[0] + "/"

    def entry(self, row: Row) -> Entry | None:
        link = next(
            (
                item
                for item in row.links
                if self.view_path in item.href
                and parameter_of(item.href, self.post_parameter)
                and urllib.parse.urlsplit(item.href).path.startswith(self.board_path)
            ),
            None,
        )
        if link is None:
            return None
        post_id = parameter_of(link.href, self.post_parameter) or ""
        if not boards.is_identifier(post_id):
            raise boards.UnreadableBoard("board listing row declares an unusable post identifier")
        return Entry(
            post_id,
            posted_on(row.text),
            link.text,
            _department(row, link.cell),
            urllib.parse.urljoin(self.list_url, link.href),
        )

    def is_download(self, link: Link) -> bool:
        href = link.href
        if href.startswith("javascript:"):
            # 미리보기·읽어 주기 단추가 같은 주소를 인자로 물고 있다. 원본 링크만 받는다.
            return False
        return self.download_path in urllib.parse.urlsplit(href).path


class GwangjinBoard(PortalBoard):
    """광진구 portal-bbs. 줄을 표가 아니라 목록으로 그려 `li` 하나가 게시글이다.

    2026-09-14 실측: `<li>` 안에 번호·제목·첨부·부서·게시일이 `span`으로 들어 있고
    칸을 따로 그리지 않는다. 전체 쪽 수는 `[ 1 / 571 페이지 ]`로 밝힌다.
    """

    row_tags = frozenset({"li"})


class PortalDetailBoard(PortalBoard):
    """첨부를 본문에만 싣는 portal-bbs 게시판(동작 실측)."""

    attachments_in_listing = False


class JungnangBoard(PortalBoard):
    """중랑구 portal-bbs 변형. 목록·본문 경로가 다르고 첨부가 Referer를 요구한다.

    2026-09-14 실측: 목록은 `/portal/bbs/list/B0000143.do`, 게시글은
    `/portal/bbs/view/B0000143/<번호>.do`, 첨부는 `/portal/cmm/fms/FileDown.do`다.
    첨부를 Referer 없이 부르면 200과 함께 1,052바이트 오류 화면이 오고, 목록 주소를
    Referer로 실으면 106KB PDF가 온다. 브라우저가 보내는 헤더를 그대로 붙인 것이다.
    """

    download_path = "cmm/fms/FileDown.do"

    def entry(self, row: Row) -> Entry | None:
        link = next((item for item in row.links if "/portal/bbs/view/" in item.href), None)
        if link is None:
            return None
        found = re.search(r"/portal/bbs/view/[^/]+/(\d+)\.do", link.href)
        if found is None:
            return None
        return Entry(
            found.group(1),
            posted_on(row.text),
            link.text,
            _department(row, link.cell),
            urllib.parse.urljoin(self.list_url, link.href),
        )

    @property
    def referer(self) -> str:
        return boards.address(self.list_url, self.params)


class CbIdxBoard(ListingBoard):
    """`ex/bbs/List.do?cbIdx=` 계열. 서초가 목록에서 본문 주소를 그대로 준다.

    2026-09-14 실측: 본문은 `View.do?cbIdx=&bcIdx=`, 첨부는
    `/common/board/Download.do?bcIdx=&cbIdx=&streFileNm=<이름>`이고 이름에 형식이 있다.
    """

    attachments_in_listing = False
    view_path = "/View.do"
    post_parameter = "bcIdx"
    board_parameter = "cbIdx"
    download_path = "/common/board/Download.do"

    def __init__(self, board: Board, transport: Transport) -> None:
        super().__init__(board, transport)
        if not boards.is_identifier(self.params.get(self.board_parameter, "")):
            raise ValueError("board url must declare cbIdx")

    def entry(self, row: Row) -> Entry | None:
        post_id = self.post_of(row)
        if post_id is None:
            return None
        page_url = boards.address(
            self.list_url.rsplit("/", 1)[0] + self.view_path,
            {
                self.board_parameter: self.params[self.board_parameter],
                self.post_parameter: post_id,
            },
        )
        return Entry(
            post_id, posted_on(row.text), self.title_of(row), _department(row, 1), page_url
        )

    def post_of(self, row: Row) -> str | None:
        for link in row.links:
            value = parameter_of(link.href, self.post_parameter)
            if value is not None and boards.is_identifier(value):
                return value
        return None

    def title_of(self, row: Row) -> str:
        return next((link.text for link in row.links if link.text), "")

    def is_download(self, link: Link) -> bool:
        if self.download_path not in urllib.parse.urlsplit(link.href).path:
            # 목록 위 배너는 `DownloadViewFile.do?cfIdx=`라 게시글 첨부가 아니다(양천 실측).
            return False
        return parameter_of(link.href, self.board_parameter) == self.params[self.board_parameter]


class YangcheonBoard(CbIdxBoard):
    """양천구 cbIdx 게시판. 제목이 JS로 렌더되고 본문 주소도 `doBbsFView`로 열린다.

    2026-09-14 실측: 목록 줄의 `doBbsFView('397','314286',…)`가 게시판·게시글 번호를
    밝히고 `View.do?cbIdx=397&bcIdx=314286`이 같은 본문을 준다. 제목 칸은
    `document.write(wdigm_title('…'))`라 그 인자를 읽는다.
    """

    view_call = re.compile(r"doBbsFView\(\s*'(\d+)'\s*,\s*'(\d+)'")
    rendered_title = re.compile(r"wdigm_title\(\s*'(.*?)'\s*\)", re.S)

    def post_of(self, row: Row) -> str | None:
        for link in row.links:
            found = self.view_call.search(link.onclick)
            if found is not None and found.group(1) == self.params[self.board_parameter]:
                return found.group(2)
        return super().post_of(row)

    def title_of(self, row: Row) -> str:
        for cell in row.cells:
            found = self.rendered_title.search(cell)
            if found is not None:
                return " ".join(found.group(1).split())
        return super().title_of(row)


class JongnoBoard(ListingBoard):
    """종로구 egov 게시판. 목록에서 바로 첨부를 주고 제목 칸이 없다.

    2026-09-14 실측: 줄은 `<ul class="respon-td">`이고 칸마다 이름표와 값이 함께 있다
    (`<span>년도</span><em>2026</em>`). 칸 차례는 번호·년도·해당 월·작성부서·구분·
    담당자·파일·작성일이고, 게시글 번호는 `viewMove('257188')`에, 첨부는
    `/cmm/fms/FileDown.do?atchFileId=FILE_…&fileSn=1`에 있다.

    담당자 실명이 목록에 실려 있으므로 그 칸은 읽지 않는다. 제목 칸이 없어 게시판이
    밝힌 년도·해당 월 두 칸을 기간 표기로 옮겨 싣는다 — 지어내는 값이 아니라 그 두 칸이다.
    """

    row_tags = frozenset({"ul"})
    view_call = re.compile(r"viewMove\(\s*'(\d+)'\s*\)")
    download_path = "/cmm/fms/FileDown.do"
    # `viewMove`가 넘겨보내는 본문 주소(2026-09-14 실측).
    view_path = "/portal/bbs/selectBoardArticle.do"
    # 쪽 넘김을 주소가 아니라 `pageMove(n)`으로 그린다. 맨끝 단추가 전체 쪽 수를 담는다.
    page_call = re.compile(r"pageMove\((\d+)\)")
    # 칸 이름표. 칸 차례가 아니라 이름표로 찾는다. 담당자 칸은 일부러 읽지 않는다.
    labels = {"year": "년도", "month": "해당 월", "department": "작성부서", "posted": "작성일"}

    def entry(self, row: Row) -> Entry | None:
        post_id = next(
            (
                found.group(1)
                for link in row.links
                if (found := self.view_call.search(link.href or link.onclick)) is not None
            ),
            None,
        )
        if post_id is None:
            return None
        values = {name: _labelled(row, label) for name, label in self.labels.items()}
        year, month = values["year"], values["month"]
        if not (year.isdigit() and month.isdigit()):
            raise boards.UnreadableBoard("board listing row does not declare its spending month")
        page_url = boards.address(
            urllib.parse.urljoin(self.list_url, self.view_path),
            {**self.params, "menuNo": self.params.get("menuId", ""), "nttId": post_id},
        )
        return Entry(
            post_id,
            posted_on(values["posted"] or row.text),
            f"{int(year)}년 {int(month)}월 업무추진비",
            values["department"],
            page_url,
        )

    def page_count(self, listing: Listing, text: str) -> int:
        pages = [int(value) for value in self.page_call.findall(text)]
        if not pages:
            raise boards.UnreadableBoard("board listing does not declare its page count")
        return max(pages)

    def is_download(self, link: Link) -> bool:
        return self.download_path in urllib.parse.urlsplit(link.href).path


def _labelled(row: Row, label: str) -> str:
    """이름표가 앞에 붙은 칸의 값. 이름표만 걷어내고 남은 글자를 돌려준다."""
    for cell in row.cells:
        if cell.startswith(label):
            return cell[len(label) :].strip()
    return ""


def _department(row: Row, title_cell: int) -> str:
    """제목 바로 다음 칸의 부서. 그 자리가 게시일이면 부서 칸이 없는 게시판이다."""
    index = title_cell + 1
    if not 0 <= index < len(row.cells):
        return ""
    candidate = row.cells[index]
    return "" if POSTED.search(candidate) or candidate.isdigit() else candidate


__all__ = [
    "BbsNoBoard",
    "BbsNoDetailBoard",
    "CbIdxBoard",
    "GwangjinBoard",
    "JongnoBoard",
    "JungnangBoard",
    "Entry",
    "Link",
    "ListingBoard",
    "PUBLISHED_SUFFIXES",
    "Row",
    "PortalBoard",
    "PortalDetailBoard",
    "YangcheonBoard",
    "decode",
    "parameter_of",
    "posted_on",
    "suffix_from",
    "total_pages",
]


class _View(boards.Document):
    """게시글 본문. 앵커의 주소·글자와 함께 `title`까지 남긴다. 파일 이름이 거기에만 있다."""

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
        if tag == "a" and self._titles:
            title = self._titles.pop()
            if len(self.links) > closed:
                href, text = self.links[-1]
                self.files.append((href, text, title))
