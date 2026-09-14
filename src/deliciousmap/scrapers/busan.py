"""부산시와 16개 구·군의 업무추진비 게시판 수집기.

부산은 구·군 열둘이 같은 rfc3 게시판을 쓴다(`/board/list.<사이트키>` + `startPage`). 그 한 벌을
`Rfc3Board`에 두고, 사이트키·조회 조건처럼 기관마다 다른 값은 레지스트리가 선언한 주소에서 읽는다.
같은 계열을 쓰지 않는 기관만 따로 둔다.
"""

import re
import urllib.parse
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from deliciousmap import boards
from deliciousmap.scrapers import listing
from deliciousmap.transport import Transport

if TYPE_CHECKING:
    from deliciousmap.registry.models import Board

# rfc3 게시판에서 실측한 첨부 확장자. 기관마다 다른 것은 게시판 선언이 좁힌다.
PUBLISHED_SUFFIXES = frozenset({".xls", ".xlsx", ".xlsm", ".hwp", ".hwpx", ".pdf", ".zip"})
# `/board/list.bsseogu`의 `bsseogu`. 같은 계열이라도 사이트키는 도메인과 다를 수 있어
# (해운대 `do`, 남구 `namgu`) 주소에서 읽고 따로 선언하지 않는다.
SITE_KEY = re.compile(r"^list\.([A-Za-z0-9]+)$")
# 내려받기 링크가 밝히는 파일 이름. `title`은 `<이름> 다운받기`, 본문 글자는 `<이름> (20 kb)`다.
FILENAME = re.compile(
    r"^\s*(?P<name>.+?)\s*"
    r"(?:(?:첨부파일\s*)?다운(?:받기|로드)|\(\s*[\d.,]+\s*[KMGkmg]?[Bb]?\s*\))\s*$"
)
# 연제구 목록이 게시글 번호를 싣는 자리. 주소는 `#`이고 실제 값은 스크립트 호출에만 있다.
VIEW_CALL = re.compile(r"goTo\.view\(\s*'[^']*'\s*,\s*'(?P<id>[^']+)'")
# 연제구 쪽 넘김. 마지막 쪽도 주소가 아니라 스크립트 호출로만 밝힌다.
PAGE_CALL = re.compile(r"goPage\(\s*(\d+)\s*\)")
# 연제구 첨부. `fileSn`이 정수가 아니라 32자리 토큰이라 값을 지어내지 못한다.
DOWN_CALL = re.compile(r"fn_egov_downFile\(\s*'(?P<file>[^']+)'\s*,\s*'(?P<serial>[^']+)'")
# 연제구 첨부 이름 뒤에 붙는 크기 표기. 이름과 가르는 자리다.
SIZE = re.compile(r"\s*\[[^\]]*\]\s*$")
# 목록이 제목에 붙이는 아이콘 글자. 제목의 일부가 아니라 화면 표시다.
BADGES = ("새글",)
# 기장군 사용일자의 구분자 없는 표기. 실측 3,283줄 가운데 131줄이 이 모양이다.
COMPACT_DATE = re.compile(r"(\d{4})(\d{2})(\d{2})")


def names_of(link: listing.Link) -> tuple[str, ...]:
    """링크가 밝힌 파일 이름 후보. 게시판마다 이름을 적는 자리가 다르다.

    `title`이 `<이름> 다운받기`인 곳, 보이는 글자가 `<이름> (20 kb)`인 곳, 이름만 적는 곳
    (동래구), 그리고 보이는 글자는 `…(문화관광과).... (14 kb)`로 자르고 온전한 이름은 옆
    링크의 `title`에 두는 곳(해운대구)이 모두 있다. 어느 자리가 맞는지는 확장자가 정한다.
    """
    found: list[str] = []
    for value in (link.title, link.text):
        match = FILENAME.match(value)
        if match is not None:
            found.append(match.group("name"))
        found.append(value.strip())
    return tuple(found)


def filename_of(link: listing.Link) -> str:
    """내려받기 링크가 밝힌 파일 이름. 밝히지 않으면 빈 이름이다.

    이름 안에 기간이 들어가 `업무추진비집행내역(개금2동-2026.8.).xlsx`처럼 적히는 일이 잦다
    (부산진구 3977223 실측). 앞에서부터 확장자처럼 보이는 것을 줍지 않고 이름을 통째로 읽는다.
    """
    for name in names_of(link):
        if boards.SUFFIX.fullmatch(boards.suffix_of(name)):
            return name
    return ""


def suffix_of(link: listing.Link) -> str:
    """링크가 밝힌 형식. 확장자 모양이 아니면 밝히지 않은 것으로 둔다.

    이름이 `…(2026.5.)`나 `…(문화관광과)....`처럼 끝나면 마지막 점 뒤가 확장자가 아니다.
    그것을 형식이라 우기면 실제 원본이 실측하지 않은 형식으로 밀린다. 밝히지 않은 것으로
    두면 수집이 실측 선언과 대조해 그 첨부만 사람이 볼 목록에 남긴다.
    """
    return boards.suffix_of(filename_of(link))


class Rfc3Board:
    """부산 구·군 열둘이 함께 쓰는 rfc3 게시판. 목록에서 게시글을, 본문에서 첨부를 읽는다.

    목록은 첨부를 밝히지 않는다(실측 2026-09-14, 서구). 그래서 이번 수집이 받을 게시글만
    본문을 열고, 넘길 게시글은 목록에 실린 값만 담아 낸다.
    """

    published_suffixes = PUBLISHED_SUFFIXES
    # 섞인 게시판에서 업무추진비 게시글만 고르는 제목 조건. 비어 있으면 모두 받는다.
    title_filter: re.Pattern[str] | None = None

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not boards.is_identifier(self.params.get("boardId", "").replace("_", "")):
            raise ValueError("board url must declare boardId")
        name = urllib.parse.urlsplit(self.list_url).path.rsplit("/", 1)[-1]
        found = SITE_KEY.fullmatch(name)
        if found is None:
            raise ValueError("board url must name an rfc3 listing")
        self.site_key = found.group(1)
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = listing.parse(
                boards.request(
                    self.transport, self.list_url, {**self.params, "startPage": str(page)}
                )
            )
            for row in parser.rows:
                article = listing.article_link(row, f"view.{self.site_key}", "dataSid")
                if article is None:
                    continue
                post_id, href = article
                posted = listing.posted_of(row)
                title = listing.title_of(row, href)
                page_url = boards.address(
                    urllib.parse.urljoin(self.list_url, f"view.{self.site_key}"),
                    {"boardId": self.params["boardId"], "dataSid": post_id},
                )
                if skipped(post_id, posted) or not self._collects(title):
                    yield boards.Posting(post_id, (), posted, title)
                    continue
                yield boards.Posting(post_id, self._attachments(post_id, page_url), posted, title)
            if page >= self._page_count(parser):
                return
            page += 1

    def _page_count(self, parser: listing.TableParser) -> int:
        """목록이 밝힌 마지막 쪽. 쪽 넘김 링크만 본다.

        게시글 링크도 `startPage`를 달고 다니므로(지금 보고 있는 쪽) 아무 링크나 세면 쪽
        넘김이 사라진 목록을 "한 쪽짜리 게시판"으로 읽는다. 쪽 넘김은 언제나 목록 주소를
        가리키고 게시글은 본문 주소를 가리켜, 가리키는 곳으로 둘을 가른다.

        실측(2026-09-14): 열한 게시판이 모두 마지막 쪽 단추에 진짜 마지막 쪽을 싣는다.
        묶는 태그는 기관마다 다르다(`div.paging-wrap2`, `div.page`).
        """
        pages = [
            int(value)
            for link in parser.links
            if urllib.parse.urlsplit(link.href).path.endswith(f"list.{self.site_key}")
            for value in urllib.parse.parse_qs(urllib.parse.urlsplit(link.href).query).get(
                "startPage", []
            )
            if value.isdigit()
        ]
        if not pages:
            raise boards.UnreadableBoard("board listing does not declare its page count")
        return max(pages)

    def _collects(self, title: str) -> bool:
        """섞인 게시판에서 이 게시글의 원본을 받을지. 조건이 없으면 게시판 전체가 대상이다."""
        return self.title_filter is None or self.title_filter.search(title) is not None

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(page_url)))
        found: list[boards.Attachment] = []
        # 같은 첨부에 내려받기 링크가 둘 붙는 게시판이 있다(동래구·해운대구 실측). 링크가
        # 아니라 파일이 몇 개인지를 센다. 이름은 그중 이름을 밝힌 링크에서 읽는다.
        seen: set[str] = set()
        for link in sorted(parser.links, key=lambda item: not suffix_of(item)):
            path = urllib.parse.urlsplit(link.href).path
            if not path.endswith(f"download.{self.site_key}"):
                continue
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(link.href).query)
            file_sid = query.get("fileSid", [""])[0]
            if not boards.is_identifier(file_sid):
                raise boards.UnreadableBoard("board supplied an unusable attachment identifier")
            if file_sid in seen:
                continue
            seen.add(file_sid)
            found.append(
                boards.Attachment(
                    post_id,
                    file_sid,
                    suffix_of(link),
                    boards.address(
                        urllib.parse.urljoin(self.list_url, f"download.{self.site_key}"),
                        {
                            "boardId": self.params["boardId"],
                            "dataSid": post_id,
                            "fileSid": file_sid,
                        },
                    ),
                    page_url,
                )
            )
        return tuple(found)


class MixedRfc3Board(Rfc3Board):
    """정보공개 통합 게시판(중구·수영구). 업무추진비 아닌 글이 섞여 있어 제목으로 고른다.

    실측 2026-09-14 1쪽: 중구 10건 중 9건, 수영구 10건 중 6건만 업무추진비다. 거르지 않으면
    점검 결과·현황 공개 같은 다른 글의 첨부까지 받는다. 표기는 `시책추진업무추진비`·
    `업무추진비사용내역`처럼 붙여 쓰기도 해서 낱말이 들어 있는지만 본다.

    `업무추진비`가 아니라 `추진비`를 찾는다. 중구에 `…과장급이상무추진비사용내역(2026.8.)`
    처럼 `업`이 빠진 제목이 2건 있어(실측) 온전한 낱말로 찾으면 그 글이 빠진다. 같은 게시판의
    업무추진비 아닌 제목(이륜자동차 등록현황, 외국인 현황, 석면해체 공개 등)에는 `추진비`가
    들어가지 않아 이 조건으로도 갈린다.
    """

    title_filter = re.compile("추진비")


class GijangBoard:
    """기장군 게시판. 첨부가 없고 목록의 표 자체가 집행내역이다.

    한 줄이 집행 한 건이라 게시글·첨부가 없다. 이 이슈는 표에서 집행내역을 뽑지 않으므로
    (#140 제외 범위) 받은 원본이 0건인 것이 맞다. 그 사실을 조용한 0건으로 두지 않도록
    줄은 그대로 게시글로 내고, 첨부가 없다는 것을 선언으로 밝힌다.
    """

    published_suffixes: frozenset[str] = frozenset()
    # 실측한 열 차례: 부서·사용자·사용일자·사용장소·사용목적·사용금액·대상인원·사용방법·연도·월.
    COLUMNS = 10
    DEPARTMENT, SPENT_ON, PURPOSE = 0, 2, 4

    def __init__(self, board: "Board", transport: Transport) -> None:
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
            ordinal = 0
            for row in parser.rows:
                if row.header or len(row.cells) != self.COLUMNS:
                    # 머리글 줄이거나 열 수가 다른 줄. 집행 줄만 센다.
                    continue
                ordinal += 1
                posted = _spent_on(row.cells[self.SPENT_ON].text)
                post_id = f"{page:04d}{ordinal:02d}"
                skipped(post_id, posted)
                # 집행 한 줄에는 제목이 없다. 목적 칸을 제목 자리에 그대로 옮긴다.
                yield boards.Posting(
                    post_id,
                    (),
                    posted,
                    row.cells[self.PURPOSE].text,
                    row.cells[self.DEPARTMENT].text,
                )
            if page >= _gijang_page_count(parser, self.list_url):
                return
            page += 1


def _spent_on(text: str) -> date | None:
    """집행 줄이 밝힌 사용일자. 읽지 못하면 밝히지 않은 것으로 둔다.

    이 칸은 자유 입력이라 실측에서 97가지 모양이 나왔다(`2026. 8. 20.`, `2026.06.28.`,
    `20260628`, `26.6.11.`, `6.27.(금)`, 빈 칸). 읽히는 모양만 읽고 나머지는 짐작하지 않는다.
    옆 칸의 연도·월은 사람이 적은 분류라 3,215건 중 64건이 사용일자와 어긋나 대신 쓰지 않는다.
    """
    compact = COMPACT_DATE.fullmatch(text.strip())
    if compact is not None:
        try:
            return date(*(int(part) for part in compact.groups()))
        except ValueError:
            return None
    try:
        return listing.posted(text)
    except boards.UnreadableBoard:
        return None


def _gijang_page_count(parser: listing.TableParser, list_url: str) -> int:
    name = urllib.parse.urlsplit(list_url).path.rsplit("/", 1)[-1]
    pages = [
        int(value)
        for link in parser.links
        if urllib.parse.urlsplit(link.href).path.endswith(name)
        for value in urllib.parse.parse_qs(urllib.parse.urlsplit(link.href).query).get(
            "startPage", []
        )
        if value.isdigit()
    ]
    if not pages:
        raise boards.UnreadableBoard("board listing does not declare its page count")
    return max(pages)


class EgovPortalBoard:
    """연제구 egov portal 게시판. 게시글 번호도 쪽 수도 주소가 아니라 스크립트 호출에 있다.

    `mId` 없이 부르면 목록이 400, 본문이 500이다(실측 2026-09-14). 그래서 레지스트리가
    선언한 조회 조건을 쪽마다 그대로 싣고, 빠져 있으면 훑기 전에 거절한다.
    """

    published_suffixes = frozenset({".xlsx", ".xls", ".hwpx", ".hwp", ".pdf"})

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not all(boards.is_identifier(self.params.get(name, "")) for name in ("ptIdx", "mId")):
            raise ValueError("board url must declare ptIdx and mId")
        self.view_url = urllib.parse.urljoin(self.list_url, "view.do")
        self.download_url = urllib.parse.urljoin(self.list_url, "/cmm/fms/FileDown.do")
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = listing.parse(
                boards.request(self.transport, self.list_url, {**self.params, "page": str(page)})
            )
            for row in parser.rows:
                found = next(
                    (VIEW_CALL.search(link.onclick) for link in row.links if link.onclick), None
                )
                if found is None or not boards.is_identifier(found.group("id")):
                    continue
                post_id = found.group("id")
                posted = listing.posted(_cell(row, "list_date"))
                page_url = boards.address(self.view_url, {**self.params, "bIdx": post_id})
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url)
                )
                yield boards.Posting(
                    post_id,
                    attachments,
                    posted,
                    _title(row),
                    _cell(row, "list_write"),
                )
            if page >= _page_count(parser):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(page_url)))
        found: list[boards.Attachment] = []
        for link in parser.links:
            call = DOWN_CALL.search(link.onclick)
            if call is None:
                continue
            file_id, serial = call.group("file"), call.group("serial")
            if not (boards.is_identifier(file_id) and boards.is_identifier(serial)):
                raise boards.UnreadableBoard("board supplied an unusable attachment identifier")
            found.append(
                boards.Attachment(
                    post_id,
                    str(len(found) + 1),
                    boards.suffix_of(SIZE.sub("", link.text)),
                    boards.address(self.download_url, {"atchFileId": file_id, "fileSn": serial}),
                    page_url,
                )
            )
        return tuple(found)


class CityBoard:
    """부산시청 `ghopen12` 게시판. 본문에서 첨부를 읽고 잠긴 첨부는 수집이 따로 센다.

    이 게시판의 첨부에는 이름이 `.xlsx`인데 내용이 Fasoo DRM인 파일이 섞여 있다(실측
    2026-09-14, 표본 8건 중 3건). 여기서는 가르지 않는다 — 무엇이 들어 있었는지는 받아 본
    뒤에야 알 수 있고, 그 판정과 계수는 수집 경계가 한다.
    """

    published_suffixes = frozenset({".xlsx", ".xls", ".hwp", ".hwpx", ".pdf"})

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not boards.is_identifier(self.params.get("schBizNo", "")):
            raise ValueError("board url must declare schBizNo")
        self.view_url = urllib.parse.urljoin(self.list_url, "view")
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = listing.parse(
                boards.request(self.transport, self.list_url, {**self.params, "curPage": str(page)})
            )
            for row in parser.rows:
                article = listing.article_link(row, "view", "schIndx")
                if article is None:
                    continue
                post_id, href = article
                posted = listing.posted_of(row)
                page_url = boards.address(
                    self.view_url, {"schCommand": "Expense", "schIndx": post_id}
                )
                attachments = (
                    () if skipped(post_id, posted) else self._attachments(post_id, page_url)
                )
                yield boards.Posting(
                    post_id,
                    attachments,
                    posted,
                    listing.title_of(row, href),
                    _cell(row, "txtLeft"),
                )
            if page >= _city_page_count(parser):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(page_url)))
        found: list[boards.Attachment] = []
        for link in parser.links:
            split = urllib.parse.urlsplit(link.href)
            if not split.path.endswith("/comm/getFile"):
                continue
            query = urllib.parse.parse_qs(split.query)
            file_no = query.get("fileNo", [""])[0]
            upper_no = query.get("upperNo", [""])[0]
            if not (boards.is_identifier(file_no) and boards.is_identifier(upper_no)):
                raise boards.UnreadableBoard("board supplied an unusable attachment identifier")
            found.append(
                boards.Attachment(
                    post_id,
                    file_no,
                    suffix_of(link),
                    boards.address(
                        urllib.parse.urljoin(self.list_url, "/comm/getFile"),
                        {
                            "srvcId": query.get("srvcId", ["OPENGOV"])[0],
                            "upperNo": upper_no,
                            "fileTy": query.get("fileTy", ["ATTACH"])[0],
                            "fileNo": file_no,
                        },
                    ),
                    page_url,
                )
            )
        return tuple(found)


def _city_page_count(parser: listing.TableParser) -> int:
    """쪽 넘김이 밝힌 마지막 쪽. 게시글 주소도 `curPage`를 달고 다니므로 그것은 세지 않는다."""
    pages: list[int] = []
    for link in parser.links:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(link.href).query)
        if "schIndx" in query:
            continue
        pages.extend(int(value) for value in query.get("curPage", []) if value.isdigit())
    if not pages:
        raise boards.UnreadableBoard("board listing does not declare its page count")
    return max(pages)


def _cell(row: listing.Row, name: str) -> str:
    for cell in row.cells:
        if name in cell.classes:
            return cell.text
    return ""


def _title(row: listing.Row) -> str:
    """게시글 제목. 목록이 붙인 아이콘 글자는 제목이 아니므로 뗀다."""
    title = _cell(row, "list_tit")
    for badge in BADGES:
        title = title.removesuffix(badge).strip()
    return title


def _page_count(parser: listing.TableParser) -> int:
    pages = [int(found) for link in parser.links for found in PAGE_CALL.findall(link.onclick)]
    if not pages:
        raise boards.UnreadableBoard("board listing does not declare its page count")
    return max(pages)


__all__ = ["PUBLISHED_SUFFIXES", "CityBoard", "EgovPortalBoard", "Rfc3Board"]
