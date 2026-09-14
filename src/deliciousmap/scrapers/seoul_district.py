"""계열을 이루지 않는 서울 자치구 게시판.

중구·도봉·노원·마포·강서·강남·강동은 각자 다른 틀을 쓴다. 2026-09-14에 프로젝트 UA로
목록·상세·첨부 경계를 하나씩 실측했고, 공통 훑기는 `scrapers.seoul.ListingBoard`를
그대로 따른다.

강북구는 여기에 없다. 첫 응답이 쿠키 서명을 돌려보내라는 433바이트 스크립트라
레지스트리에서 `bot_blocked`로 수집을 보류한다(이슈 #141).
"""

from __future__ import annotations

import re
import urllib.parse

from deliciousmap import boards
from deliciousmap.scrapers.seoul import (
    NAMED_SUFFIX,
    POSTED,
    Entry,
    Link,
    Listing,
    ListingBoard,
    Row,
    parameter_of,
    posted_on,
)

# 원본이 아닌 것이 분명한 형식. 중구 상세의 첫 파일 링크는 사이트 그림이다(1.7MB PNG).
# 실측하지 않은 형식을 여기서 걸러 내지는 않는다 — 그것은 수집 장부가 사람에게 알린다.
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"})

# 게시글 주소가 경로 끝의 번호로 끝나는 게시판(마포·강서·강동 실측).
PATH_POST = re.compile(r"/(\d+)(?:[?#]|$)")


def _path_entry(
    board: ListingBoard, row: Row, prefix: str, department_cell: int | None = None
) -> Entry | None:
    """경로 끝 번호로 게시글을 가리키는 목록 한 줄.

    부서 칸을 못 박아야 하는 게시판이 있다. 강서는 제목과 작성자 사이에 첨부 칸이 있고
    그 칸이 비어 있지 않아("첨부파일") 제목 뒤 첫 칸을 부서로 읽으면 어긋난다.
    """
    for link in row.links:
        path = urllib.parse.urlsplit(link.href).path
        if not path.startswith(prefix):
            continue
        found = PATH_POST.search(path)
        if found is None:
            continue
        department = (
            row.cell(department_cell) if department_cell is not None else _next_cell(row, link.cell)
        )
        return Entry(
            found.group(1),
            posted_on(row.text),
            link.text,
            department,
            urllib.parse.urljoin(board.list_url, link.href),
        )
    return None


def _next_cell(row: Row, index: int) -> str:
    """제목 뒤 첫 부서 칸. 빈 칸과 번호 칸은 건너뛰고 게시일 칸에서 멈춘다.

    칸 차례가 게시판마다 달라(강서는 제목과 부서 사이에 빈 첨부 칸이 있다) 자리를
    고정하지 않는다. 게시일을 만나면 부서 칸이 없는 줄이므로 빈 값으로 둔다.
    """
    for position in range(index + 1, len(row.cells)):
        candidate = row.cells[position]
        if _dated(candidate):
            return ""
        if candidate and not candidate.replace(",", "").isdigit():
            return candidate
    return ""


def _dated(cell: str) -> bool:
    return POSTED.search(cell) is not None


class JungguBoard(ListingBoard):
    """중구 cwsboard. 게시글은 `mode=view&cid=`, 쪽 넘김은 `page2`다.

    2026-09-14 실측: 상세의 첫 파일 링크는 사이트 그림(1.7MB PNG)이라 `filename=`의
    확장자로 걸러야 한다. 의회사무과 줄이 같은 게시판에 섞여 있어 공표부서로 거른다.
    """

    page_parameter = "page2"
    attachments_in_listing = False
    download_path = "/cwsboard/board.do"
    filtered_departments = frozenset({"의회"})

    def entry(self, row: Row) -> Entry | None:
        for link in row.links:
            if "mode=view" not in link.href:
                continue
            post_id = parameter_of(link.href, "cid")
            if post_id is None or not boards.is_identifier(post_id):
                continue
            return Entry(
                post_id,
                posted_on(row.text),
                link.text,
                _next_cell(row, link.cell),
                urllib.parse.urljoin(self.list_url, link.href),
            )
        return None

    def is_download(self, link: Link) -> bool:
        if self.download_path not in urllib.parse.urlsplit(link.href).path:
            return False
        if parameter_of(link.href, "mode") != "download":
            return False
        # 사이트 그림만 걸러 낸다. 실측하지 않은 형식은 여기서 조용히 버리지 않고
        # 수집 장부(`unmeasured.jsonl`)가 사람에게 알리도록 그대로 넘긴다.
        found = NAMED_SUFFIX.search(parameter_of(link.href, "filename") or "")
        return found is None or f".{found.group(1).lower()}" not in IMAGE_SUFFIXES


class DobongBoard(ListingBoard):
    """도봉구 ASP 게시판. 쪽 넘김 `intPage`는 `bbs.asp`에만 붙는다.

    2026-09-14 실측: 진입 주소 `Contents.asp`에 `intPage`를 붙이면 리다이렉트에서
    떨어져 1쪽만 돌아온다. 그래서 레지스트리가 `bbs.asp`를 직접 가리킨다.
    응답은 UTF-8이고 게시글은 `bbs.asp?bmode=D&pcode=`, 첨부는 `download.asp`다.
    """

    page_parameter = "intPage"
    attachments_in_listing = False
    download_path = "download.asp"

    def entry(self, row: Row) -> Entry | None:
        for link in row.links:
            if parameter_of(link.href, "bmode") != "D":
                continue
            post_id = parameter_of(link.href, "pcode")
            if post_id is None or not boards.is_identifier(post_id):
                continue
            return Entry(
                post_id,
                posted_on(row.text),
                link.text,
                _next_cell(row, link.cell + 1),
                urllib.parse.urljoin(self.list_url, link.href),
            )
        return None

    def is_download(self, link: Link) -> bool:
        return self.download_path in urllib.parse.urlsplit(link.href).path


class NowonBoard(ListingBoard):
    """노원구 BD 게시판. 첨부가 목록에 있고 쪽 넘김은 `q_currPage`다.

    2026-09-14 실측: 게시글 번호는 `fnRecntCnt(this,'1012','20260910161420785')`의
    셋째 인자이고 전체 쪽 수는 화면의 `lastPageNum = "1017"`이 밝힌다. 형식은 같은
    게시판 안에서 섞인다(목업은 XLSX·HWPX, 이번 실측은 PDF).
    """

    page_parameter = "q_currPage"
    download_path = "/component/file/ND_fileDownload.do"
    post_call = re.compile(r"fnRecntCnt\([^,]+,\s*'[^']*'\s*,\s*'(\d+)'\s*\)")
    last_page = re.compile(r"lastPageNum\s*=\s*\"(\d+)\"")

    def entry(self, row: Row) -> Entry | None:
        for link in row.links:
            found = self.post_call.search(link.onclick)
            if found is None:
                continue
            return Entry(
                found.group(1),
                posted_on(row.text),
                link.text,
                _next_cell(row, link.cell),
                boards.address(self.list_url, {**self.params, "q_bbscttSn": found.group(1)}),
            )
        return None

    def page_count(self, listing: Listing, text: str) -> int:
        found = self.last_page.search(text)
        if found is None:
            raise boards.UnreadableBoard("board listing does not declare its page count")
        return int(found.group(1))

    def is_download(self, link: Link) -> bool:
        return self.download_path in urllib.parse.urlsplit(link.href).path


class MapoBoard(ListingBoard):
    """마포구 REST 게시판. 목록이 게시글 주소와 첨부를 함께 준다. 쪽 넘김은 `cp`다."""

    page_parameter = "cp"
    download_path = "/site/main/file/download/uu/"
    post_prefix = "/site/main/board/expense/"

    def entry(self, row: Row) -> Entry | None:
        return _path_entry(self, row, self.post_prefix)

    def is_download(self, link: Link) -> bool:
        return self.download_path in urllib.parse.urlsplit(link.href).path


class GangseoBoard(ListingBoard):
    """강서구 게시판. 첨부는 본문의 `/comm/getFile`이고 쪽 넘김은 `curPage`다."""

    page_parameter = "curPage"
    attachments_in_listing = False
    download_path = "/comm/getFile"
    post_prefix = "/gs030325/"
    # 칸 차례는 순번·제목·첨부파일·작성자·작성일·조회수다(2026-09-14 실측).
    department_cell = 3

    def entry(self, row: Row) -> Entry | None:
        return _path_entry(self, row, self.post_prefix, self.department_cell)

    def is_download(self, link: Link) -> bool:
        return urllib.parse.urlsplit(link.href).path == self.download_path


class GangnamBoard(ListingBoard):
    """강남구 게시판. 상세가 없고 목록 줄이 곧 첨부다. 쪽 넘김은 `pgno`다.

    2026-09-14 실측: 쪽 넘김 막대는 `selectPage_func(n)`으로 그리고 마지막 쪽 단추가
    937을 담는다. 첨부는 `/file/1/get/<uuid>/download.do`이고 같은 uuid의
    `preview.do`는 미리보기라 원본이 아니다. 의회 줄이 섞여 담당부서로 거른다.
    """

    page_parameter = "pgno"
    download = re.compile(r"^/file/\d+/get/([0-9a-f-]{8,40})/download\.do$")
    page_call = re.compile(r"selectPage_func\((\d+)\)")
    filtered_departments = frozenset({"의회"})
    # 게시글 번호 칸. 상세가 없어 목록의 번호를 게시글 식별자로 쓴다.
    number_cell = 0

    def entry(self, row: Row) -> Entry | None:
        post_id = row.cell(self.number_cell).replace(",", "")
        if not post_id.isdigit() or not any(self.download.match(_path(item)) for item in row.links):
            return None
        return Entry(
            post_id,
            posted_on(row.text),
            row.cell(self.number_cell + 1),
            _department(row),
            boards.address(self.list_url, {**self.params, self.page_parameter: str(self.page)}),
        )

    def page_count(self, listing: Listing, text: str) -> int:
        pages = [int(value) for value in self.page_call.findall(text)]
        if not pages:
            raise boards.UnreadableBoard("board listing does not declare its page count")
        return max(pages)

    def is_download(self, link: Link) -> bool:
        return self.download.match(_path(link)) is not None


class GangdongBoard(ListingBoard):
    """강동구 REST 게시판. 첨부는 본문에 있고 쪽 넘김은 `cp`다.

    2026-09-14 실측: 목업이 남긴 "요청 간격 0.3초에 400"은 다시 나타나지 않았다.
    0.2초 간격으로 열두 쪽을 연달아 받아 모두 200이었으므로 공통 간격을 그대로 둔다.
    """

    page_parameter = "cp"
    attachments_in_listing = False
    download_path = "/web/newportal/file/download/uu/"
    post_prefix = "/web/newportal/bbs/"

    def entry(self, row: Row) -> Entry | None:
        return _path_entry(self, row, self.post_prefix)

    def is_download(self, link: Link) -> bool:
        return self.download_path in urllib.parse.urlsplit(link.href).path


def _path(link: Link) -> str:
    return urllib.parse.urlsplit(link.href).path


def _department(row: Row) -> str:
    """게시일 바로 앞 칸의 부서. 강남은 번호·제목·첨부·담당부서·작성일 차례다(실측)."""
    for index, cell in enumerate(row.cells):
        if _dated(cell) and index:
            return row.cell(index - 1)
    return ""


__all__ = [
    "DobongBoard",
    "GangdongBoard",
    "GangnamBoard",
    "GangseoBoard",
    "JungguBoard",
    "MapoBoard",
    "NowonBoard",
]
