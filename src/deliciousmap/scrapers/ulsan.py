"""울산시와 5개 구·군의 업무추진비 게시판 수집기.

각 기관은 같은 이름의 게시판이라도 서로 다른 프레임워크를 사용한다. 이
모듈은 현장에서 확인한 목록/본문/첨부 경계를 그대로 보존하며, 게시판이
본문 안에 첨부를 제공하지 않는 경우에도 목록 게시물을 빈 첨부 튜플로
기록한다.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import TYPE_CHECKING

from deliciousmap import boards
from deliciousmap.transport import Transport

if TYPE_CHECKING:
    from deliciousmap.registry.models import Board

ENCODING = "utf-8"
PUBLISHED_SUFFIXES = frozenset({".xls", ".xlsx", ".xlsm", ".hwp", ".hwpx", ".pdf", ".zip"})
PDF_SUFFIXES = frozenset({".pdf"})
ZIP_SUFFIXES = frozenset({".zip"})
DATE_RE = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")
# The oldest city transfer rows use a two-digit year (`20. 11. 5`).  The
# surrounding board is a 2000s archive, so the century is explicit rather than
# inferred from the current year.  Keep this separate from DATE_RE so a full
# year always wins and a substring of `2020` cannot be read as `20`.
SHORT_DATE_RE = re.compile(r"(?<!\d)(\d{2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})(?!\d)")
PAGE_RE = re.compile(r"(?:페이지|page)\s*[:：]?\s*\d+\s*/\s*([\d,]+)", re.I)
EXTENSION_RE = re.compile(r"\.([A-Za-z0-9]{1,8})(?![A-Za-z0-9])")
PAGINATION_KEYS = frozenset({"cpage", "curPage", "page", "pageIndex", "startPage"})


@dataclass(frozen=True)
class _Link:
    href: str
    text: str
    title: str
    onclick: str


@dataclass(frozen=True)
class _Cell:
    text: str
    classes: frozenset[str]
    links: tuple[_Link, ...]


@dataclass(frozen=True)
class _Row:
    cells: tuple[_Cell, ...]

    @property
    def text(self) -> str:
        return " ".join(cell.text for cell in self.cells)


class _TableParser(HTMLParser):
    """Capture table cells and anchors without depending on a third-party DOM."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_Row] = []
        self.links: list[_Link] = []
        self._cells: list[list[tuple[str, frozenset[str], list[_Link], list[str]]]] = []
        self._cell: list[str] | None = None
        self._cell_classes: frozenset[str] = frozenset()
        self._cell_links: list[_Link] = []
        self._link_attrs: dict[str, str] | None = None
        self._link_text: list[str] = []
        self._pagination = False
        self.pagination_pages: list[int] = []
        self._tr = False
        self._text: list[str] = []

    @property
    def text(self) -> str:
        return " ".join(" ".join(self._text).split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "ul" and "pagination" in (dict(attrs).get("class") or "").split():
            self._pagination = True
        elif tag == "tr" and not self._tr:
            self._tr = True
            self._cells = [[]]
        elif tag in {"td", "th"} and self._tr and self._cell is None:
            self._cell = []
            self._cell_classes = frozenset((dict(attrs).get("class") or "").split())
            self._cell_links = []
            self._cells[-1].append(("", self._cell_classes, self._cell_links, self._cell))
        elif tag == "a":
            raw = dict(attrs)
            self._link_attrs = {
                "href": raw.get("href") or "",
                "title": raw.get("title") or "",
                "onclick": raw.get("onclick") or "",
            }
            self._link_text = []
        elif tag == "img":
            alt = dict(attrs).get("alt") or ""
            if alt and self._cell is not None:
                self._cell.append(alt)
            if alt and self._link_attrs is not None:
                self._link_text.append(alt)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link_attrs is not None:
            link = _Link(
                self._link_attrs["href"],
                " ".join(" ".join(self._link_text).split()),
                self._link_attrs["title"],
                self._link_attrs["onclick"],
            )
            self.links.append(link)
            if self._pagination:
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(link.href).query)
                for key in PAGINATION_KEYS:
                    value = query.get(key, [""])[0]
                    if value.isdigit():
                        self.pagination_pages.append(int(value))
                if not query and "현재페이지" in link.title and link.text.strip().isdigit():
                    self.pagination_pages.append(int(link.text.strip()))
            if self._cell is not None:
                self._cell_links.append(link)
            self._link_attrs = None
            self._link_text = []
        elif tag in {"td", "th"} and self._cell is not None:
            self._cell = None
            self._cell_links = []
        elif tag == "tr" and self._tr:
            cells: list[_Cell] = []
            for _, classes, links, parts in self._cells[-1]:
                cells.append(_Cell(" ".join(" ".join(parts).split()), classes, tuple(links)))
            self.rows.append(_Row(tuple(cells)))
            self._cells = []
            self._tr = False
        elif tag == "ul" and self._pagination:
            self._pagination = False

    def handle_data(self, data: str) -> None:
        self._text.append(data)
        if self._cell is not None:
            self._cell.append(data)
        if self._link_attrs is not None:
            self._link_text.append(data)

    def close(self) -> None:
        super().close()
        if self._tr:
            raise boards.UnreadableBoard("board listing row never closed")


def _parse(body: bytes) -> _TableParser:
    parser = _TableParser()
    try:
        parser.feed(body.decode(ENCODING))
        parser.close()
    except UnicodeDecodeError:
        raise boards.UnreadableBoard("board response is not in the measured encoding") from None
    return parser


def _posted(text: str) -> date:
    found = DATE_RE.search(text)
    if found is not None:
        values = found.groups()
    else:
        short = SHORT_DATE_RE.search(text)
        if short is None:
            raise boards.UnreadableBoard("board listing row does not declare its posting date")
        values = (str(2000 + int(short.group(1))), short.group(2), short.group(3))
    try:
        return date(*(int(part) for part in values))
    except ValueError:
        raise boards.UnreadableBoard(
            "board listing row declares an impossible posting date"
        ) from None


def _has_date(text: str) -> bool:
    return DATE_RE.search(text) is not None or SHORT_DATE_RE.search(text) is not None


def _compact_date(value: str) -> date:
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except (TypeError, ValueError):
        raise boards.UnreadableBoard(
            "board listing row declares an impossible posting date"
        ) from None


def _market_page_count(parser: _TableParser) -> int:
    return _page_count(parser)


def _page_count(
    parser: _TableParser,
    *,
    link_keys: tuple[str, ...] = (),
) -> int:
    found = PAGE_RE.search(parser.text)
    if found is not None:
        return int(found.group(1).replace(",", ""))
    found = re.search(r"전체\s*페이지\s+(\d+)", parser.text, re.I)
    if found is not None:
        return int(found.group(1))
    candidates: list[int] = []
    for link in parser.links:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(link.href).query)
        for key in link_keys:
            value = query.get(key, [""])[0]
            if value.isdigit():
                candidates.append(int(value))
    candidates.extend(parser.pagination_pages)
    if not candidates:
        raise boards.UnreadableBoard("board listing does not declare its page count")
    return max(candidates)


def _suffix(link: _Link) -> str:
    for value in (link.text, link.title, link.onclick):
        match = EXTENSION_RE.search(value)
        if match is not None:
            return f".{match.group(1).lower()}"
        named = re.search(r"\b(zip|pdf|xlsx?|xlsm|hwp|hwpx)\s*(?:파일|다운로드)", value, re.I)
        if named is not None:
            return f".{named.group(1).lower()}"
    found = re.search(r"\.([A-Za-z0-9]{1,8})(?:$|[?&#])", link.href)
    suffix = f".{found.group(1).lower()}" if found else ""
    return suffix if suffix in PUBLISHED_SUFFIXES else ""


def _article_link(row: _Row, needle: str, parameter: str) -> tuple[str, str] | None:
    for cell in row.cells:
        for link in cell.links:
            if needle not in urllib.parse.urlsplit(link.href).path:
                continue
            value = urllib.parse.parse_qs(urllib.parse.urlsplit(link.href).query).get(
                parameter, [""]
            )[0]
            if boards.is_identifier(value):
                return value, link.href
    return None


def _department(row: _Row) -> str:
    for cell in row.cells:
        if "problem_name" in cell.classes:
            return cell.text
    texts = [cell.text for cell in row.cells]
    title_index = next(
        (
            index
            for index, cell in enumerate(row.cells)
            if any(
                parameter in link.href
                for link in cell.links
                for parameter in ("nttId=", "dataSid=", "article_seq=")
            )
        ),
        0,
    )
    if title_index + 1 < len(texts):
        candidate = texts[title_index + 1]
        if candidate and not _has_date(candidate):
            return candidate
    return ""


class EgovBoard:
    """남구·동구의 표준 eGov 목록 게시판."""

    published_suffixes = PDF_SUFFIXES
    page_size_parameter: str | None = None
    page_size: str | None = None

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not boards.is_identifier(self.params.get("bbsId", "").replace("_", "")):
            raise ValueError("board url must declare bbsId")
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            params = {**self.params, "pageIndex": str(page)}
            if self.page_size is not None and self.page_size_parameter is not None:
                params[self.page_size_parameter] = self.page_size
            listing = _parse(boards.request(self.transport, self.list_url, params))
            rows = [
                (row, _article_link(row, "selectBoardArticle.do", "nttId")) for row in listing.rows
            ]
            rows = [(row, article) for row, article in rows if article is not None]
            for row, article in rows:
                assert article is not None
                post_id, href = article
                posted = _posted(row.text)
                page_url = urllib.parse.urljoin(self.list_url, href)
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(row, post_id, page_url)
                )
                yield boards.Posting(
                    post_id, attachments, posted, _title(row, href), _department(row)
                )
            total = _page_count(listing, link_keys=("pageIndex",))
            if page >= total:
                return
            page += 1

    def _attachments(self, row: _Row, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        found: list[boards.Attachment] = []
        index = 0
        for cell in row.cells:
            for link in cell.links:
                if "FileDown.do" not in link.href and "fn_egov_downFile" not in link.onclick:
                    continue
                index += 1
                found.append(
                    boards.Attachment(
                        post_id,
                        str(index),
                        _suffix(link),
                        urllib.parse.urljoin(self.list_url, link.href),
                        page_url,
                    )
                )
        return tuple(found)


class NamguBoard(EgovBoard):
    """남구 eGov 게시판. 실측된 30건 보기 옵션을 사용한다."""

    page_size_parameter = "recordCountPerPage"
    page_size = "30"


def _title(row: _Row, href: str) -> str:
    for cell in row.cells:
        for link in cell.links:
            if link.href == href:
                return link.text
    return ""


class JungguBoard(EgovBoard):
    """중구의 `board/list.ulsan` 게시판(목록에서 ZIP 첨부를 제공)."""

    published_suffixes = ZIP_SUFFIXES

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not boards.is_identifier(self.params.get("boardId", "").replace("_", "")):
            raise ValueError("board url must declare boardId")
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = _parse(
                boards.request(
                    self.transport, self.list_url, {**self.params, "startPage": str(page)}
                )
            )
            rows = [(row, _article_link(row, "view.ulsan", "dataSid")) for row in parser.rows]
            rows = [(row, article) for row, article in rows if article is not None]
            for row, article in rows:
                assert article is not None
                post_id, href = article
                posted = _posted(row.text)
                page_url = urllib.parse.urljoin(self.list_url, href)
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(row, post_id, page_url)
                )
                yield boards.Posting(
                    post_id, attachments, posted, _title(row, href), _department(row)
                )
            if page >= _page_count(parser, link_keys=("startPage",)):
                return
            page += 1

    def _attachments(self, row: _Row, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        found: list[boards.Attachment] = []
        index = 0
        for cell in row.cells:
            for link in cell.links:
                if "download.ulsan" not in link.href:
                    continue
                index += 1
                found.append(
                    boards.Attachment(
                        post_id,
                        str(index),
                        _suffix(link),
                        urllib.parse.urljoin(self.list_url, link.href),
                        page_url,
                    )
                )
        return tuple(found)


class JungguMayorBoard:
    """중구 구청장 원자료 표. 본문에 첨부가 없어 목록만 보존한다."""

    published_suffixes: frozenset[str] = frozenset()
    page_parameter = "startPage"

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = _parse(
                boards.request(
                    self.transport,
                    self.list_url,
                    {**self.params, self.page_parameter: str(page)},
                )
            )
            ordinal = 0
            for row in parser.rows:
                found = next(
                    (
                        re.search(r"ymd2=(\d{8})", link.href)
                        for cell in row.cells
                        for link in cell.links
                    ),
                    None,
                )
                ordinal += 1
                if found is not None:
                    date_id = found.group(1)
                    posted = _compact_date(date_id)
                    post_id = f"{date_id}{page:03d}{ordinal:02d}"
                    title = _title(
                        row,
                        next(
                            (
                                link.href
                                for cell in row.cells
                                for link in cell.links
                                if "ymd2=" in link.href
                            ),
                            "",
                        ),
                    )
                else:
                    posted_index = next(
                        (index for index, cell in enumerate(row.cells) if _has_date(cell.text)),
                        None,
                    )
                    if posted_index is None:
                        ordinal -= 1
                        continue
                    posted = _posted(row.cells[posted_index].text)
                    sequence = next(
                        (cell.text for cell in row.cells[:posted_index] if cell.text.isdigit()),
                        str(ordinal),
                    )
                    post_id = f"{sequence}{page:03d}{ordinal:02d}"
                    title = (
                        row.cells[posted_index + 3].text
                        if posted_index + 3 < len(row.cells)
                        else ""
                    )
                skipped(post_id, posted)
                yield boards.Posting(
                    post_id,
                    (),
                    posted,
                    title,
                    "",
                )
            if page >= _page_count(parser, link_keys=(self.page_parameter,)):
                return
            page += 1


class DongguMayorBoard(JungguMayorBoard):
    """동구 구청장 원자료 표. 중구와 같은 날짜 링크 경계를 사용한다."""

    page_parameter = "pageIndex"


class CityMarketBoard:
    """울산시 시장 게시판. 목록의 `dataId`와 본문의 EncDownFile을 연결한다."""

    published_suffixes = PDF_SUFFIXES

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not all(
            boards.is_identifier(self.params.get(name, "").replace("_", ""))
            for name in ("bbsId", "mId")
        ):
            raise ValueError("board url must declare bbsId and mId")
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = _parse(
                boards.request(self.transport, self.list_url, {**self.params, "page": str(page)})
            )
            rows = [(row, _article_link(row, "view.do", "dataId")) for row in parser.rows]
            rows = [(row, article) for row, article in rows if article is not None]
            for row, article in rows:
                assert article is not None
                post_id, href = article
                posted = _posted(row.text)
                page_url = urllib.parse.urljoin(self.list_url, href)
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url, href)
                )
                yield boards.Posting(post_id, attachments, posted, _title(row, href), "")
            if page >= _market_page_count(parser):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str, href: str) -> tuple[boards.Attachment, ...]:
        view_url = urllib.parse.urljoin(self.list_url, href)
        parser = _parse(boards.request(self.transport, *boards.endpoint(view_url)))
        result: list[boards.Attachment] = []
        for link in parser.links:
            match = re.search(
                r"EncDownFile\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]",
                link.onclick,
            )
            if match is None:
                continue
            _, bbs_id, file_id, file_sn = match.groups()
            download = urllib.parse.urljoin(self.list_url, "/u/enc/media/bbsFileDown.do")
            result.append(
                boards.Attachment(
                    post_id,
                    str(len(result) + 1),
                    _suffix(link),
                    boards.address(
                        download, {"bbsId": bbs_id, "atchFileId": file_id, "fileSn": file_sn}
                    ),
                    page_url,
                )
            )
        return tuple(result)


class CityTransferBoard:
    """울산시 실·국장/경제부시장 표. 거래 내역은 본문에 있고 첨부는 없다."""

    published_suffixes: frozenset[str] = frozenset()

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = _parse(
                boards.request(self.transport, self.list_url, {**self.params, "curPage": str(page)})
            )
            ordinal = 0
            for row in parser.rows:
                detail = next(
                    (
                        link
                        for cell in row.cells
                        for link in cell.links
                        if "f_detail" in link.onclick
                    ),
                    None,
                )
                if detail is None:
                    continue
                ordinal += 1
                posted = _posted(row.text)
                post_id = f"{posted:%Y%m%d}{page:03d}{ordinal:02d}"
                skipped(post_id, posted)
                yield boards.Posting(post_id, (), posted, detail.text, "")
            if page >= _page_count(parser, link_keys=("curPage",)):
                return
            page += 1


class BukguBoard:
    """북구 lay1 게시판. 첨부는 목록 아이콘이 아니라 본문에서 읽는다."""

    published_suffixes = PDF_SUFFIXES
    # The measured board exposes 10, 20, and 30 rows per page.  Use the
    # largest published option so a resumed year-only collection does not
    # needlessly walk the 10-row default archive.
    page_size = "30"

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = _parse(
                boards.request(
                    self.transport,
                    self.list_url,
                    {**self.params, "cpage": str(page), "rows": self.page_size},
                )
            )
            rows = [(row, _article_link(row, "view.do", "article_seq")) for row in parser.rows]
            rows = [(row, article) for row, article in rows if article is not None]
            for row, article in rows:
                assert article is not None
                post_id, href = article
                posted = _posted(row.text)
                page_url = urllib.parse.urljoin(self.list_url, href)
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url, href)
                )
                yield boards.Posting(
                    post_id, attachments, posted, _title(row, href), _department(row)
                )
            if page >= _page_count(parser, link_keys=("cpage",)):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str, href: str) -> tuple[boards.Attachment, ...]:
        view_url = urllib.parse.urljoin(self.list_url, href)
        parser = _parse(boards.request(self.transport, *boards.endpoint(view_url)))
        result: list[boards.Attachment] = []
        for link in parser.links:
            if "download.do" not in urllib.parse.urlsplit(link.href).path:
                continue
            result.append(
                boards.Attachment(
                    post_id,
                    str(len(result) + 1),
                    _suffix(link),
                    urllib.parse.urljoin(self.list_url, link.href),
                    page_url,
                )
            )
        return tuple(result)


class UljuBoard:
    """울주군 게시판. 목록의 `goTo.view`를 본문과 연결한다."""

    published_suffixes = PDF_SUFFIXES

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = _parse(
                boards.request(self.transport, self.list_url, {**self.params, "page": str(page)})
            )
            rows: list[tuple[_Row, str, str]] = []
            for row in parser.rows:
                view = next(
                    (
                        re.search(r"goTo\.view\([^,]+,\s*'([^']+)'", link.onclick)
                        for cell in row.cells
                        for link in cell.links
                    ),
                    None,
                )
                if view is None or not boards.is_identifier(view.group(1)):
                    continue
                rows.append((row, view.group(1), view.group(0)))
            for row, post_id, _ in rows:
                posted = _posted(row.text)
                page_url = boards.address(
                    urllib.parse.urljoin(self.list_url, "/ulju/bbs/view.do"),
                    {
                        "mId": self.params.get("mId", ""),
                        "bIdx": post_id,
                        "ptIdx": self.params.get("ptIdx", "117"),
                    },
                )
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url)
                )
                title = next(
                    (
                        link.title.strip() or link.text
                        for cell in row.cells
                        for link in cell.links
                        if "goTo.view" in link.onclick
                    ),
                    "",
                )
                yield boards.Posting(post_id, attachments, posted, title, "")
            if page >= _page_count(parser):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        view_url, params = boards.endpoint(page_url)
        parser = _parse(boards.request(self.transport, view_url, params))
        result: list[boards.Attachment] = []
        for link in parser.links:
            match = re.search(
                r"fn_egov_downFile\(['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)", link.onclick
            )
            if match is None:
                continue
            file_id, file_sn = match.groups()
            attachment_id = file_id if boards.is_identifier(file_id) else str(len(result) + 1)
            download = urllib.parse.urljoin(self.list_url, "/cmm/fms/FileDown.do")
            result.append(
                boards.Attachment(
                    post_id,
                    attachment_id,
                    _suffix(link),
                    boards.address(download, {"atchFileId": file_id, "fileSn": file_sn}),
                    page_url,
                )
            )
        return tuple(result)


__all__ = [
    "BukguBoard",
    "CityMarketBoard",
    "CityTransferBoard",
    "DongguMayorBoard",
    "EgovBoard",
    "JungguBoard",
    "JungguMayorBoard",
    "NamguBoard",
    "PUBLISHED_SUFFIXES",
    "UljuBoard",
]
