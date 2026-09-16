"""대전 5개 자치구의 업무추진비 게시판 수집기.

게시판 계열은 셋이다. 중구·서구·유성구는 eGov `/bbs/<BBSMSTR>/list.do`, 동구는 자체 article
CMS, 대덕구는 자체 dpt CMS다. 시청은 원본 경로가 robots에 막혀 수집 보류다(레지스트리).
실측 근거는 `docs/validation/issue-172.md`에 있다.
"""

import re
import urllib.parse
from collections.abc import Iterator
from html.parser import HTMLParser
from typing import TYPE_CHECKING

from deliciousmap import boards
from deliciousmap.scrapers import listing
from deliciousmap.transport import Transport

if TYPE_CHECKING:
    from deliciousmap.registry.models import Board

# 2026-09-17 실측한 첨부 확장자. 수집이 이 선언과 대조한다.
PUBLISHED_SUFFIXES = frozenset({".xls", ".xlsx", ".hwp", ".hwpx", ".pdf"})
# eGov 목록 주소. 게시판 번호는 경로에 있고 조회 조건은 없다.
BBS_LIST = re.compile(r"^/bbs/BBSMSTR_\d+/list\.do$")
# eGov 목록이 게시글을 여는 호출. 주소는 `#view`이고 값은 이 호출에만 있다.
DETAIL_CALL = re.compile(r"fn_search_detail\(\s*'(?P<id>[^']+)'")
# eGov 본문의 내려받기 호출. 서구·중구·유성구 모두 `href="javascript:…"`에 싣는다.
DOWN_CALL = re.compile(r"fn_egov_downFile\(\s*'(?P<file>[^']+)'\s*,\s*'(?P<serial>[^']+)'")
# 첨부 이름 뒤에 붙는 크기·단추 글자(`… .pdf [197.4 KB] 다운로드`). 이름과 가르는 자리다.
# 마지막 `[…]`만 본다 — 이름 앞의 `[붙임]`에서 자르면 확장자를 잃는다.
BBS_SIZE = re.compile(r"\s*\[[^\[\]]*\][^\[\]]*$")
# 동구 목록 주소와 게시글을 여는 호출.
ARTICLE_LIST = re.compile(r"^/dg/kor/article/[A-Za-z]+$")
ARTICLE_VIEW = re.compile(r"article\.view\(\s*'(?P<id>\d+)'")
# 동구 첨부. 미리보기(`/dg/attach/preview/…`)는 같은 파일이라 세지 않는다.
ARTICLE_ATTACH = re.compile(r"^/dg/attach/[0-9a-f]+/(?P<id>[0-9a-f]+)$")
# 동구 쪽 넘김. 마지막 쪽 단추도 `?pageIndex=N` 주소를 싣는다.
ARTICLE_PAGE = re.compile(r"^\?pageIndex=(\d+)$")
# 대덕구 목록 주소. 메뉴 번호마다 목록·본문 주소가 따로 있다.
DPT_LIST = re.compile(r"^/dpt/dpt02/(?P<menu>DPT\d+)_cmmBoardList\.do$")
# 대덕구 쪽 넘김. 주소가 `#url`이라 쪽 수는 onclick 호출에만 있다.
DPT_PAGE = re.compile(r"fn_link_page\(\s*(\d+)\s*\)")
# 대덕구 첨부. 본문에 파일 주소가 그대로 박혀 있다.
DPT_BINARY = re.compile(r"^/board/binary/DPT_\d+/(?P<id>\d+)(?P<suffix>\.[A-Za-z0-9]{1,8})$")


# 구의회 글을 가르는 글자. 구청 게시판에 의회 사무국 집행내역이 섞이고(동구·서구 실측), 작성자는
# `의회사무국`·`동구 의회사무국`·`대전 동구의회`로, 옛 글은 사람 이름과 제목의 `(의회사무국)`으로만
# 밝힌다. 의회는 구청 집행기관이 아니라서 걸러 내고 센다(`boards.FiltersRows`).
COUNCIL = "의회"


def _is_council(*texts: str) -> bool:
    return any(COUNCIL in text for text in texts)


def _cell(row: listing.Row, *names: str) -> str:
    for cell in row.cells:
        if cell.classes.intersection(names):
            return cell.text
    return ""


class _ButtonTable(listing.TableParser):
    """서구 목록은 게시글을 `<a>`가 아니라 `<button onclick>`으로 연다. 둘을 같은 링크로 읽는다."""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag("a" if tag == "button" else tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag("a" if tag == "button" else tag)


class BbsBoard:
    """중구·유성구 eGov 게시판. 목록에서 게시글을, 본문에서 첨부를 읽는다.

    목록 첨부 칸은 게시글당 링크 하나만 보이고 여러 파일이면 묶음 단추로 바뀐다(서구 실측).
    파일 수를 온전히 세기 위해 본문을 연다. 본문은 `view.do?nttId=`를 GET으로 받아도 열린다.
    """

    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not BBS_LIST.fullmatch(urllib.parse.urlsplit(self.list_url).path):
            raise ValueError("board url must name an eGov bbs listing")
        self.view_url = urllib.parse.urljoin(self.list_url, "view.do")
        self.transport = transport
        # 걸러 낸 구의회 글 수. 서구 부서별 게시판에서 실측했고 같은 계열이라 함께 센다.
        self.filtered = 0

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = listing.parse(
                boards.request(
                    self.transport, self.list_url, {**self.params, "pageIndex": str(page)}
                ),
                parser=_ButtonTable(),
            )
            for row in parser.rows:
                found = next(
                    (DETAIL_CALL.search(link.onclick) for link in row.links if link.onclick), None
                )
                if found is None or not boards.is_identifier(found.group("id").replace("_", "")):
                    continue
                ntt_id = found.group("id")
                # 옮겨 온 옛 글은 번호에 밑줄이 있다(유성구 `ODYS_MYR_1_164`). 저장 이름에 쓰는
                # 게시글 번호에서만 바꾸고, 본문 주소에는 게시판이 준 값을 그대로 쓴다.
                post_id = ntt_id.replace("_", "x")
                title = _cell(row, "subject")
                department = _cell(row, "writer", "deptName")
                if _is_council(title, department):
                    self.filtered += 1
                    continue
                posted = listing.posted(_cell(row, "regDate"))
                page_url = boards.address(self.view_url, {"nttId": ntt_id})
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url)
                )
                yield boards.Posting(post_id, attachments, posted, title, department)
            if page >= listing.page_count(parser):
                return
            page += 1

    def _calls(self, page_url: str) -> list[tuple[str, str, str]]:
        """본문의 내려받기 호출. 사이트 공통 메뉴의 `FileDown.do` 링크는 첨부가 아니다(중구)."""
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(page_url)))
        found: list[tuple[str, str, str]] = []
        for link in parser.links:
            call = DOWN_CALL.search(link.href) or DOWN_CALL.search(link.onclick)
            if call is None:
                continue
            file_id, serial = call.group("file"), call.group("serial")
            if not (boards.is_identifier(file_id.replace("_", "")) and serial.isdigit()):
                raise boards.UnreadableBoard("board supplied an unusable attachment identifier")
            item = (file_id, serial, BBS_SIZE.sub("", link.text))
            if all(item[:2] != seen[:2] for seen in found):
                found.append(item)
        return found

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        download = urllib.parse.urljoin(self.list_url, "/cmm/fms/FileDown.do")
        return tuple(
            boards.Attachment(
                post_id,
                str(index),
                boards.suffix_of(name),
                boards.address(download, {"atchFileId": file_id, "fileSn": serial}),
                page_url,
            )
            for index, (file_id, serial, name) in enumerate(self._calls(page_url), start=1)
        )


class ZipBbsBoard(BbsBoard):
    """서구 eGov 게시판. 파일 하나하나가 아니라 게시글의 첨부 묶음 하나를 받는다.

    실측 2026-09-17: `FileDown.do`는 첨부마다 우리 요청에 404를 준다. 쿠키를 이어 들고 본문을
    먼저 열어도, Referer를 붙여도 같았다. 목록이 여러 파일 게시글에 내주는 묶음 내려받기
    (`zipDownload.do`)는 파일이 하나인 게시글에도 200으로 원본을 담은 ZIP을 준다.
    """

    published_suffixes = frozenset({".zip"})

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        download = urllib.parse.urljoin(self.list_url, "/cmm/fms/zipDownload.do")
        groups = list(dict.fromkeys(file_id for file_id, _, _ in self._calls(page_url)))
        return tuple(
            boards.Attachment(
                post_id,
                str(index),
                ".zip",
                boards.address(
                    download, {"atchFileIdStr": file_id, "zipFileName": "zipDownload.zip"}
                ),
                page_url,
            )
            for index, file_id in enumerate(groups, start=1)
        )


class _ArticleList(HTMLParser):
    """동구 목록의 `div.notice_list` 안 `<li>` 항목. 칸 이름은 `<p>`의 첫 class다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._depth = 0
        self._item: dict[str, str] | None = None
        self._field: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "div" and (self._depth or "notice_list" in classes):
            self._depth += 1
        elif not self._depth:
            return
        elif tag == "li" and "thead" not in classes:
            self._item = {}
        elif tag == "p" and self._item is not None and classes:
            self._field, self._parts = classes[0], []
        elif tag == "a" and self._item is not None:
            found = ARTICLE_VIEW.search(values.get("onclick") or "")
            if found is not None:
                self._item["id"] = found.group("id")

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._depth:
            self._depth -= 1
        elif tag == "p" and self._field is not None and self._item is not None:
            self._item[self._field] = " ".join("".join(self._parts).split())
            self._field = None
        elif tag == "li" and self._item is not None:
            self.items.append(self._item)
            self._item = None

    def handle_data(self, data: str) -> None:
        if self._field is not None:
            self._parts.append(data)


class ArticleBoard:
    """동구 article 게시판. 목록은 표가 아니라 `<li>`이고 본문 주소는 `<목록>/<번호>`다.

    5급 이상 게시판에 구의회 사무국 글이 섞인다(실측 2026-09-17 1쪽 10건 중 2건).
    """

    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not ARTICLE_LIST.fullmatch(urllib.parse.urlsplit(self.list_url).path):
            raise ValueError("board url must name an article listing")
        self.transport = transport
        self.filtered = 0

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            body = boards.request(
                self.transport, self.list_url, {**self.params, "pageIndex": str(page)}
            )
            parser = _ArticleList()
            try:
                parser.feed(body.decode(listing.ENCODING))
                parser.close()
            except UnicodeDecodeError:
                raise boards.UnreadableBoard(
                    "board response is not in the measured encoding"
                ) from None
            for item in parser.items:
                post_id = item.get("id", "")
                if not boards.is_identifier(post_id):
                    continue
                if _is_council(item.get("subject", ""), item.get("writer", "")):
                    self.filtered += 1
                    continue
                posted = listing.posted(item.get("date", ""))
                page_url = f"{self.list_url}/{post_id}"
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url)
                )
                yield boards.Posting(
                    post_id, attachments, posted, item.get("subject", ""), item.get("writer", "")
                )
            if page >= _article_page_count(body):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        document = boards.read(boards.request(self.transport, page_url, {}), listing.ENCODING)
        found: dict[str, boards.Attachment] = {}
        for href, text in document.links:
            match = ARTICLE_ATTACH.fullmatch(href)
            if match is None or match.group("id") in found:
                continue
            found[match.group("id")] = boards.Attachment(
                post_id,
                match.group("id"),
                boards.suffix_of(text),
                urllib.parse.urljoin(self.list_url, href),
                page_url,
            )
        return tuple(found.values())


def _article_page_count(body: bytes) -> int:
    """동구의 마지막 쪽. 쪽 넘김 주소가 `?pageIndex=N`만 싣는다."""
    return listing.last_page(
        int(found.group(1))
        for href, _ in boards.read(body, listing.ENCODING).links
        if (found := ARTICLE_PAGE.fullmatch(href)) is not None
    )


class _DptTable(listing.TableParser):
    """대덕구 목록. 제목 링크 안의 모바일용 줄(`게시일 | 작성자 | 제목`)은 읽지 않는다.

    그 줄을 제목으로 읽으면 제목이 두 번 나오고 작성자 개인 이름이 제목에 섞인다.
    """

    def __init__(self) -> None:
        super().__init__()
        self._hidden: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        if tag == "p":
            hidden = "mobile_con" in (dict(attrs).get("class") or "").split()
            self._hidden.append(hidden)
            self._mute += hidden

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._hidden:
            self._mute -= self._hidden.pop()
        super().handle_endtag(tag)


class DptBoard:
    """대덕구 dpt 게시판. 목록에서 게시글을, 본문에 박힌 파일 주소에서 첨부를 읽는다.

    작성자 칸은 부서가 아니라 담당자 이름이라 게시글 부서로 옮기지 않는다.
    """

    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        found = DPT_LIST.fullmatch(urllib.parse.urlsplit(self.list_url).path)
        if found is None:
            raise ValueError("board url must name a dpt board listing")
        self.view_path = f"{found.group('menu')}_cmmBoardView.do"
        self.view_url = urllib.parse.urljoin(self.list_url, self.view_path)
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = listing.parse(
                boards.request(
                    self.transport, self.list_url, {**self.params, "pageIndex": str(page)}
                ),
                parser=_DptTable(),
            )
            for row in parser.rows:
                article = listing.article_link(row, self.view_path, "ntatcSeq")
                if article is None:
                    continue
                post_id, href = article
                board_id = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get(
                    "boardId", [""]
                )[0]
                if not boards.is_identifier(board_id.replace("_", "")):
                    raise boards.UnreadableBoard("board listing row does not declare its board")
                posted = listing.posted_of(row)
                page_url = boards.address(self.view_url, {"boardId": board_id, "ntatcSeq": post_id})
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url)
                )
                yield boards.Posting(post_id, attachments, posted, listing.title_of(row, href))
            last = listing.last_page(
                int(value) for link in parser.links for value in DPT_PAGE.findall(link.onclick)
            )
            if page >= last:
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        document = boards.read(
            boards.request(self.transport, *boards.endpoint(page_url)), listing.ENCODING
        )
        found: dict[str, boards.Attachment] = {}
        for href, _ in document.links:
            match = DPT_BINARY.fullmatch(href)
            if match is None or match.group("id") in found:
                continue
            found[match.group("id")] = boards.Attachment(
                post_id,
                match.group("id"),
                match.group("suffix").lower(),
                urllib.parse.urljoin(self.list_url, href),
                page_url,
            )
        return tuple(found.values())


__all__ = ["PUBLISHED_SUFFIXES", "ArticleBoard", "BbsBoard", "DptBoard", "ZipBbsBoard"]
