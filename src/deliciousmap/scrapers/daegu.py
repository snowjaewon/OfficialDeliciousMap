"""대구시와 구·군의 업무추진비 게시판 수집기.

게시판 계열은 넷이다. 시청·남구·달성군은 ICMS(`index.do?menu_id=` 목록 + `fn_egov_downFile`),
동구·서구는 yhLib portal(`scrapers.busan.YhLibBoard`에 의회 글 거르기를 더함), 수성구는 해마다
대상자별 월 집행표를 여는 화면, 군위군은 자체 CMS(`page.do?mnu_uid=`)다. 중구·북구·달서구는
수집 보류다(레지스트리). 실측 근거는 `docs/validation/issue-173.md`에 있다.
"""

import re
import urllib.parse
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from deliciousmap import boards
from deliciousmap.scrapers import listing
from deliciousmap.scrapers.busan import YhLibBoard
from deliciousmap.transport import Transport

if TYPE_CHECKING:
    from deliciousmap.registry.models import Board

# 2026-09-17 실측한 첨부 확장자. 수집이 이 선언과 대조한다. 시청·남구·달성군·수성구·군위군의
# 2026년 원본 1,496개가 모두 이 셋이었다(한글 문서는 없었다).
PUBLISHED_SUFFIXES = frozenset({".xls", ".xlsx", ".pdf"})
# ICMS 목록이 게시글을 여는 호출. 주소는 `javascript:;`이고 번호는 이 호출에만 있다.
ICMS_VIEW = re.compile(r"fn_icms_navi_common\(\s*'view'\s*,\s*'(?P<id>\d+)'")
# ICMS의 내려받기 호출. 미리보기(`filePreview`)는 같은 파일을 변환해 보여 주므로 세지 않는다.
DOWN_CALL = re.compile(r"fn_egov_downFile\(\s*'(?P<file>[^']+)'\s*,\s*'(?P<serial>[^']+)'")
# ICMS 목록 폼의 게시판 번호. 본문 주소에 함께 실어야 본문이 열린다.
BBS_ID = re.compile(rb'name="bbsId"\s+value="(?P<id>[A-Za-z0-9_]+)"')
# ICMS 본문 주소. 사이트 스크립트(`getActionUrl`)가 폼을 보내는 주소와 같고 GET으로도 열린다.
ICMS_ARTICLE = "/icms/bbs/selectBoardArticle.do"
ICMS_DOWNLOAD = "/icms/cmm/fms/FileDown.do"
# 부서 열의 이름. 시청·달성군은 `부서명`, 남구는 `담당부서`다.
DEPARTMENT_HEADERS = frozenset({"부서명", "담당부서"})
# 첨부 이름 뒤의 크기 표기(`… .xlsx [16934 byte]`). 이름과 가르는 자리다. 남구는 그 뒤에
# 아이콘(`alt="첨부파일"`)을 같은 링크 안에 두므로 마지막 `[…]` 뒤의 글자까지 뗀다.
SIZE = re.compile(r"\s*\[[^\[\]]*\][^\[\]]*$")
# 수성구 집행표 화면. 대상자를 고르면 사이트가 이 주소로 폼을 보낸다(`fn_searchBoe`).
OFFICIAL_LINK = "/front/businessOperatingExpense/icmsOperatingExpenseFront.do"
# 수성구 대상자 목록의 구분선(`------------------`). 사람이 아니다.
SEPARATOR = re.compile(r"-+")
# 군위군 목록의 게시글 주소와 본문 첨부.
GUNWI_ARTICLE = "bod_uid"
GUNWI_FILE = re.compile(r"^/board_download\.do\?file_uid=(?P<id>\d+)$")
# 군위군 작성자 열의 이름. 부서가 적힌다.
WRITER_HEADER = "작성자"

# 구의회 글을 가르는 글자. 구청 게시판에 의회 사무국 집행내역이 섞이고(대전 동구·서구 선례),
# 수성구는 대상자 목록에 `의회사무국장`을 둔다. 의회는 집행기관이 아니라서 걸러 내고 센다.
COUNCIL = "의회"


def _is_council(*texts: str) -> bool:
    return any(COUNCIL in text for text in texts)


def _column(rows: list[listing.Row], names: frozenset[str]) -> int | None:
    """머리글 줄에서 이름이 맞는 열의 차례. 열 차례는 기관마다 달라 이름으로 찾는다."""
    for row in rows:
        if not row.header:
            continue
        for index, cell in enumerate(row.cells):
            if cell.text in names:
                return index
    return None


def _text_at(row: listing.Row, index: int | None) -> str:
    return row.cells[index].text if index is not None and index < len(row.cells) else ""


def _downloads(links: list[listing.Link]) -> list[tuple[str, str, str]]:
    """내려받기 호출의 (파일 묶음, 순번, 이름). 같은 호출은 한 번만 센다."""
    found: list[tuple[str, str, str]] = []
    for link in links:
        call = DOWN_CALL.search(link.href)
        if call is None:
            continue
        file_id, serial = call.group("file"), call.group("serial")
        if not (boards.is_identifier(file_id.replace("_", "")) and boards.is_identifier(serial)):
            raise boards.UnreadableBoard("board supplied an unusable attachment identifier")
        if all((file_id, serial) != seen[:2] for seen in found):
            found.append((file_id, serial, SIZE.sub("", link.text)))
    return found


class IcmsBoard:
    """시청·남구·달성군 ICMS 게시판. 목록에서 게시글을, 본문에서 첨부를 읽는다.

    목록 첨부 칸은 시청에서 게시글당 첫 파일만 보여 준다(실측 2026-09-17, 50줄 중 `fileSn=1`만
    보이는 줄이 있음). 파일 수를 온전히 세기 위해 본문을 연다.
    """

    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not self.params.get("menu_id", "").isdigit():
            raise ValueError("board url must declare an ICMS menu_id")
        self.download_url = urllib.parse.urljoin(self.list_url, ICMS_DOWNLOAD)
        self.transport = transport
        self.filtered = 0

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            body = boards.request(
                self.transport, self.list_url, {**self.params, "pageIndex": str(page)}
            )
            found = BBS_ID.search(body)
            if found is None:
                raise boards.UnreadableBoard("board listing does not declare its board")
            bbs_id = found.group("id").decode()
            parser = listing.parse(body)
            department_at = _column(parser.rows, DEPARTMENT_HEADERS)
            for row in parser.rows:
                calls = ((link, ICMS_VIEW.search(link.onclick)) for link in row.links)
                opener = next(((link, call) for link, call in calls if call is not None), None)
                if opener is None:
                    continue
                post_id = opener[1].group("id")
                title, department = opener[0].text, _text_at(row, department_at)
                if _is_council(title, department):
                    self.filtered += 1
                    continue
                posted = listing.posted_of(row)
                page_url = boards.address(
                    self.list_url,
                    {
                        "menu_id": self.params["menu_id"],
                        "menu_link": ICMS_ARTICLE,
                        "bbsId": bbs_id,
                        "nttId": post_id,
                    },
                )
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url)
                )
                yield boards.Posting(post_id, attachments, posted, title, department)
            if page >= listing.page_count(parser, link_keys=("pageIndex",)):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(page_url)))
        return tuple(
            boards.Attachment(
                post_id,
                str(index),
                boards.suffix_of(name),
                boards.address(self.download_url, {"atchFileId": file_id, "fileSn": serial}),
                page_url,
            )
            for index, (file_id, serial, name) in enumerate(_downloads(parser.links), start=1)
        )


class CouncilFilteredYhLibBoard(YhLibBoard):
    """동구·서구 yhLib 게시판. 구청 게시판에 의회사무국장 집행내역이 섞여 걸러 내고 센다.

    실측 2026-09-17: 동구는 `…집행내역(의회사무국장)`(2025년 게시), 서구는 `2026년 8월
    의회사무국장 업무추진비 집행내역`처럼 제목에 밝힌다. 서구 목록은 작성 부서 칸도 있다.
    """

    def __init__(self, board: "Board", transport: Transport) -> None:
        super().__init__(board, transport)
        self.filtered = 0

    def keeps(self, title: str, department: str) -> bool:
        if _is_council(title, department):
            self.filtered += 1
            return False
        return True


class _Officials(boards.Document):
    """수성구 화면의 대상자 선택 상자. 고른 사람은 `selected`로 밝힌다."""

    def __init__(self) -> None:
        super().__init__()
        self.names: list[str] = []
        self.selected: str | None = None
        self._in_select = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        values = dict(attrs)
        if tag == "select":
            self._in_select = values.get("name") == "search_target"
        elif tag == "option" and self._in_select:
            name = (values.get("value") or "").strip()
            self.names.append(name)
            if "selected" in values:
                self.selected = name

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        if tag == "select":
            self._in_select = False


class OfficialTableBoard:
    """수성구 업무추진비 화면. 게시판이 아니라 해마다 한 화면이고, 대상자를 고르면 그 사람의
    월별 집행 건수·금액과 달마다 첨부 하나를 보여 준다(실측 2026-09-17, 2026년 67명).

    달 하나의 첨부 묶음을 게시글 하나로 본다. 화면에 게시일이 없어 `posted`는 비우고, 제목은
    첨부 이름(`2026년 1월 업무추진비공개(구청장)`)이 밝힌 기간을 쓴다. 대상자를 고르는 폼은
    POST지만 같은 조건을 GET으로 보내도 같은 화면이 온다.
    """

    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not self.params.get("menu_id", "").isdigit():
            raise ValueError("board url must declare the year's menu_id")
        self.download_url = urllib.parse.urljoin(self.list_url, ICMS_DOWNLOAD)
        self.transport = transport
        self.filtered = 0

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        officials = self._officials(boards.request(self.transport, self.list_url, self.params))
        if not officials.names:
            raise boards.UnreadableBoard("board page does not list its officials")
        for name in officials.names:
            if not name or SEPARATOR.fullmatch(name):
                continue
            query = {**self.params, "menu_link": OFFICIAL_LINK, "search_target": name}
            page_url = boards.address(self.list_url, query)
            body = boards.request(self.transport, self.list_url, query)
            if self._officials(body).selected != name:
                raise boards.UnreadableBoard("board page does not show the official asked for")
            yield from self._months(name, body, page_url, skipped)

    def _officials(self, body: bytes) -> _Officials:
        return boards.parse(body, listing.ENCODING, _Officials())

    def _months(
        self, name: str, body: bytes, page_url: str, skipped: boards.Skipped
    ) -> Iterator[boards.Posting]:
        groups: dict[str, list[tuple[str, str]]] = {}
        for file_id, serial, filename in _downloads(listing.parse(body).links):
            groups.setdefault(file_id, []).append((serial, filename))
        for file_id, files in groups.items():
            post_id = file_id.replace("_", "")
            if _is_council(name):
                self.filtered += 1
                continue
            title = PurePosixPath(files[0][1]).stem.strip()
            attachments = (
                ()
                if skipped(post_id, None)
                else tuple(
                    boards.Attachment(
                        post_id,
                        str(index),
                        boards.suffix_of(filename),
                        boards.address(
                            self.download_url, {"atchFileId": file_id, "fileSn": serial}
                        ),
                        page_url,
                    )
                    for index, (serial, filename) in enumerate(files, start=1)
                )
            )
            yield boards.Posting(post_id, attachments, None, title, name)


class GunwiBoard:
    """군위군 게시판. 목록 주소(`cmd=2`)는 조회수를 올린 뒤 스크립트로 `cmd=258` 본문에 넘긴다.

    본문은 `cmd=258`로 곧바로 열린다(실측 2026-09-17). 첨부는 `/board_download.do?file_uid=`가
    원본을 바로 준다 — robots가 막는 `/upload/`로 넘기지 않는다.
    """

    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not self.params.get("mnu_uid", "").isdigit():
            raise ValueError("board url must declare mnu_uid")
        self.transport = transport
        self.filtered = 0

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = listing.parse(
                boards.request(self.transport, self.list_url, {**self.params, "pageNo": str(page)})
            )
            writer_at = _column(parser.rows, frozenset({WRITER_HEADER}))
            for row in parser.rows:
                article = listing.article_link(row, "", GUNWI_ARTICLE)
                if article is None:
                    continue
                post_id, href = article
                title, department = listing.title_of(row, href), _text_at(row, writer_at)
                if _is_council(title, department):
                    self.filtered += 1
                    continue
                posted = listing.posted_of(row)
                page_url = boards.address(
                    self.list_url, {**self.params, "bod_uid": post_id, "cmd": "258"}
                )
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url)
                )
                yield boards.Posting(post_id, attachments, posted, title, department)
            if page >= listing.page_count(parser):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        document = boards.read(
            boards.request(self.transport, *boards.endpoint(page_url)), listing.ENCODING
        )
        found: dict[str, boards.Attachment] = {}
        for href, text in document.links:
            match = GUNWI_FILE.fullmatch(href)
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


__all__ = [
    "PUBLISHED_SUFFIXES",
    "CouncilFilteredYhLibBoard",
    "GunwiBoard",
    "IcmsBoard",
    "OfficialTableBoard",
]
