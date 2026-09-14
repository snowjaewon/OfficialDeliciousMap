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
    linked = [
        index
        for index, cell in enumerate(row.cells)
        if any(
            parameter in link.href
            for link in cell.links
            for parameter in ("nttId=", "dataSid=", "article_seq=")
        )
    ]
    # 번호 칸도 게시글로 링크하는 목록(동구)이 있다. 부서는 번호가 아니라 제목 칸 다음이다.
    title_index = next(
        (index for index in linked if not _is_row_number(row.cells[index].text)),
        linked[0] if linked else 0,
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
    texts = [link.text for cell in row.cells for link in cell.links if link.href == href]
    # 같은 게시글 링크가 여럿이면 행 번호가 아닌 쪽이 제목이다(동구 목록, 2026-09-14 실측).
    return next((text for text in texts if not _is_row_number(text)), texts[0] if texts else "")


def _is_row_number(text: str) -> bool:
    return text.strip().isdigit()


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
    """중구 구청장 원자료 표. 목록 표가 곧 집행내역이다(행 하나가 지출 하나, 날짜 열이 있다).

    공개된 회계연도 검색(`searchType=TMP_FIELD1`, `keyword=<연도>`)과 실측한 `listRow=1000`으로
    대상 연도의 행을 한 쪽에 받고, 그 쪽 응답 전체를 원본으로 둔다(2026-09-14 실측: 2025년
    482행, 2026년 198행이 한 쪽). 해 목록은 새 행이 위에 쌓여 둘째 쪽부터 내용이 밀리므로, 한 쪽에
    담기지 않으면 쪽을 짐작해 나누지 않고 읽지 못한 게시판으로 알린다.

    게시글 번호가 연도라 한 번 받은 해 목록은 다시 받지 않는다. 그 뒤에 붙은 행은 그 원본을 치우고
    다시 수집해야 들어온다(ADR-0008).
    """

    published_suffixes = frozenset({boards.HTML_SUFFIX})
    page_size = "1000"

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        from deliciousmap import period

        for year in range(period.START.year, period.END.year + 1):
            params = {
                **self.params,
                "listRow": self.page_size,
                "searchType": "TMP_FIELD1",
                "searchOperation": "OR",
                "keyword": str(year),
                "startPage": "1",
            }
            parser = _parse(boards.request(self.transport, self.list_url, params))
            if _page_count(parser, link_keys=("startPage",)) != 1:
                raise boards.UnreadableBoard("fiscal-year listing no longer fits one page")
            post_id = str(year)
            url = boards.address(self.list_url, params)
            yield boards.Posting(post_id, _html_original(post_id, url, skipped(post_id, None)))


class DongguMayorBoard:
    """동구 구청장 원자료 표. 목록 한 행이 집행일 하루치 게시글이고 표는 상세 쪽에 있다.

    공개된 월 검색(`searchWrd=YYYYMM`)으로 대상 연도 목록만 읽고, 행마다 `view.do?ymd2=YYYYMMDD`
    상세 쪽 응답 전체를 원본으로 받는다(2026-09-14 실측). 상세 표에는 집행일 열이 없어 상세 키의
    날을 집행일로 싣는다(ADR-0008). 그 날이 게시글을 가르는 키라 게시글 번호로 쓴다.
    """

    published_suffixes = frozenset({boards.HTML_SUFFIX})

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        self.view_url = urllib.parse.urljoin(self.list_url, "view.do")
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        from deliciousmap import period

        for year in range(period.START.year, period.END.year + 1):
            for month in range(1, 13):
                yield from self._month(f"{year}{month:02d}", skipped)

    def _month(self, search: str, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            params = {**self.params, "searchWrd": search, "pageIndex": str(page)}
            parser = _parse(boards.request(self.transport, self.list_url, params))
            for row in parser.rows:
                found = next(
                    (
                        (link, key)
                        for cell in row.cells
                        for link in cell.links
                        if (key := re.search(r"ymd2=(\d{8})", link.href)) is not None
                    ),
                    None,
                )
                if found is None:
                    continue
                link, key = found
                post_id = key.group(1)
                posted = _compact_date(post_id)
                url = boards.address(self.view_url, {"ymd2": post_id})
                yield boards.Posting(
                    post_id,
                    _html_original(post_id, url, skipped(post_id, posted)),
                    posted,
                    link.text,
                    "",
                    spent_on=posted,
                )
            if page >= _page_count(parser, link_keys=("pageIndex",)):
                return
            page += 1


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
    """울산시 부시장·경제자유구역청장·실·국장·부서장 표.

    목록 한 행이 사용일자 하루치 게시글이고, 집행내역은 첨부가 아니라 `useDe=<사용일자>`로 연
    상세 쪽의 HTML 표다(2026-09-14 실측). 그 쪽 응답 전체를 원본으로 받는다. 상세 표에는
    집행일 열이 없어 사용일자를 상세 키가 밝힌 집행일로 싣는다(ADR-0008). 사용일자가 게시글을
    가르는 키라 게시글 번호로 쓴다 — 목록의 쪽·순번은 새 게시글이 올라오면 밀린다.
    """

    published_suffixes = frozenset({boards.HTML_SUFFIX})

    def __init__(self, board: Board, transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = _parse(
                boards.request(self.transport, self.list_url, {**self.params, "curPage": str(page)})
            )
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
                found = re.search(r"f_detail\(\s*'([^']+)'", detail.onclick)
                if found is None:
                    raise boards.UnreadableBoard(
                        "board listing row does not declare its detail key"
                    )
                key = found.group(1)
                # 받는 쪽은 이 키로 연 쪽이다. 목록 칸이 아니라 키에서 날을 읽어 둘이 어긋나지
                # 않게 한다.
                posted = _posted(key)
                post_id = f"{posted:%Y%m%d}"
                url = boards.address(self.list_url, {**self.params, "useDe": key})
                yield boards.Posting(
                    post_id,
                    _html_original(post_id, url, skipped(post_id, posted)),
                    posted,
                    detail.text,
                    "",
                    spent_on=posted,
                )
            if page >= _page_count(parser, link_keys=("curPage",)):
                return
            page += 1


def _html_original(post_id: str, url: str, skipped: bool) -> tuple[boards.Attachment, ...]:
    """HTML 표 게시글의 원본 참조 하나. 받은 쪽 주소가 곧 출처다. 넘길 게시글이면 없다."""
    return () if skipped else (boards.Attachment(post_id, "1", boards.HTML_SUFFIX, url, url),)


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
