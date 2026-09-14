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
from datetime import date
from typing import TYPE_CHECKING

from deliciousmap import boards
from deliciousmap.scrapers import listing
from deliciousmap.scrapers.listing import Row as _Row
from deliciousmap.transport import Transport

if TYPE_CHECKING:
    from deliciousmap.registry.models import Board

ENCODING = listing.ENCODING
PUBLISHED_SUFFIXES = frozenset({".xls", ".xlsx", ".xlsm", ".hwp", ".hwpx", ".pdf", ".zip"})
PDF_SUFFIXES = frozenset({".pdf"})
ZIP_SUFFIXES = frozenset({".zip"})


def _compact_date(value: str) -> date:
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except (TypeError, ValueError):
        raise boards.UnreadableBoard(
            "board listing row declares an impossible posting date"
        ) from None


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
        if candidate and not listing.has_date(candidate):
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
            parser = listing.parse(boards.request(self.transport, self.list_url, params))
            rows = [
                (row, listing.article_link(row, "selectBoardArticle.do", "nttId"))
                for row in parser.rows
            ]
            rows = [(row, article) for row, article in rows if article is not None]
            for row, article in rows:
                assert article is not None
                post_id, href = article
                posted = listing.posted(row.text)
                page_url = urllib.parse.urljoin(self.list_url, href)
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(row, post_id, page_url)
                )
                yield boards.Posting(
                    post_id, attachments, posted, listing.title_of(row, href), _department(row)
                )
            total = listing.page_count(parser, link_keys=("pageIndex",))
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
                        listing.suffix(link, PUBLISHED_SUFFIXES),
                        urllib.parse.urljoin(self.list_url, link.href),
                        page_url,
                    )
                )
        return tuple(found)


class NamguBoard(EgovBoard):
    """남구 eGov 게시판. 실측된 30건 보기 옵션을 사용한다."""

    page_size_parameter = "recordCountPerPage"
    page_size = "30"


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
            parser = listing.parse(
                boards.request(
                    self.transport, self.list_url, {**self.params, "startPage": str(page)}
                )
            )
            rows = [
                (row, listing.article_link(row, "view.ulsan", "dataSid")) for row in parser.rows
            ]
            rows = [(row, article) for row, article in rows if article is not None]
            for row, article in rows:
                assert article is not None
                post_id, href = article
                posted = listing.posted(row.text)
                page_url = urllib.parse.urljoin(self.list_url, href)
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(row, post_id, page_url)
                )
                yield boards.Posting(
                    post_id, attachments, posted, listing.title_of(row, href), _department(row)
                )
            if page >= listing.page_count(parser, link_keys=("startPage",)):
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
                        listing.suffix(link, PUBLISHED_SUFFIXES),
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
        for search_value in self.search_values():
            yield from self._postings_for_search(search_value, skipped)

    def search_values(self) -> tuple[str | None, ...]:
        """검색 조건 없이 게시판이 제공하는 전체 목록을 읽는다."""
        return (None,)

    def _postings_for_search(
        self, search_value: str | None, skipped: boards.Skipped
    ) -> Iterator[boards.Posting]:
        page = 1
        while True:
            params = {**self.params, self.page_parameter: str(page)}
            if search_value is not None:
                params["searchWrd"] = search_value
            parser = listing.parse(boards.request(self.transport, self.list_url, params))
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
                    title = listing.title_of(
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
                        (
                            index
                            for index, cell in enumerate(row.cells)
                            if listing.has_date(cell.text)
                        ),
                        None,
                    )
                    if posted_index is None:
                        ordinal -= 1
                        continue
                    posted = listing.posted(row.cells[posted_index].text)
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
            if page >= listing.page_count(parser, link_keys=(self.page_parameter,)):
                return
            page += 1


class DongguMayorBoard(JungguMayorBoard):
    """동구 구청장 원자료 표. 공개된 월 검색으로 대상 연도 목록을 읽는다."""

    page_parameter = "pageIndex"

    def search_values(self) -> tuple[str, ...]:
        from deliciousmap import period

        return tuple(f"{period.START.year}{month:02d}" for month in range(1, 13))


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
            parser = listing.parse(
                boards.request(self.transport, self.list_url, {**self.params, "page": str(page)})
            )
            rows = [(row, listing.article_link(row, "view.do", "dataId")) for row in parser.rows]
            rows = [(row, article) for row, article in rows if article is not None]
            for row, article in rows:
                assert article is not None
                post_id, href = article
                posted = listing.posted(row.text)
                page_url = urllib.parse.urljoin(self.list_url, href)
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url, href)
                )
                yield boards.Posting(post_id, attachments, posted, listing.title_of(row, href), "")
            if page >= listing.page_count(parser):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str, href: str) -> tuple[boards.Attachment, ...]:
        view_url = urllib.parse.urljoin(self.list_url, href)
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(view_url)))
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
                    listing.suffix(link, PUBLISHED_SUFFIXES),
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
            parser = listing.parse(
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
                posted = listing.posted(row.text)
                post_id = f"{posted:%Y%m%d}{page:03d}{ordinal:02d}"
                skipped(post_id, posted)
                yield boards.Posting(post_id, (), posted, detail.text, "")
            if page >= listing.page_count(parser, link_keys=("curPage",)):
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
            parser = listing.parse(
                boards.request(
                    self.transport,
                    self.list_url,
                    {**self.params, "cpage": str(page), "rows": self.page_size},
                )
            )
            rows = [
                (row, listing.article_link(row, "view.do", "article_seq")) for row in parser.rows
            ]
            rows = [(row, article) for row, article in rows if article is not None]
            for row, article in rows:
                assert article is not None
                post_id, href = article
                posted = listing.posted(row.text)
                page_url = urllib.parse.urljoin(self.list_url, href)
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url, href)
                )
                yield boards.Posting(
                    post_id, attachments, posted, listing.title_of(row, href), _department(row)
                )
            if page >= listing.page_count(parser, link_keys=("cpage",)):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str, href: str) -> tuple[boards.Attachment, ...]:
        view_url = urllib.parse.urljoin(self.list_url, href)
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(view_url)))
        result: list[boards.Attachment] = []
        for link in parser.links:
            if "download.do" not in urllib.parse.urlsplit(link.href).path:
                continue
            result.append(
                boards.Attachment(
                    post_id,
                    str(len(result) + 1),
                    listing.suffix(link, PUBLISHED_SUFFIXES),
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
            parser = listing.parse(
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
                posted = listing.posted(row.text)
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
            if page >= listing.page_count(parser):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        view_url, params = boards.endpoint(page_url)
        parser = listing.parse(boards.request(self.transport, view_url, params))
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
                    listing.suffix(link, PUBLISHED_SUFFIXES),
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
