"""부산시와 16개 구·군의 업무추진비 게시판 수집기.

부산은 구·군 열이 같은 rfc3 게시판을 쓴다(`/board/list.<사이트키>` + `startPage`). 그 한 벌을
`Rfc3Board`에 두고, 사이트키·조회 조건처럼 기관마다 다른 값은 레지스트리가 선언한 주소에서 읽는다.
같은 계열을 쓰지 않는 기관만 따로 둔다.
"""

import re
import urllib.parse
from collections.abc import Iterator
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
# 강서구 첨부. `atchFileId`는 64자, `fileSn`은 32자 토큰이라 값을 지어내지 못한다. 본문에는
# 내려받기(`download`)와 전용뷰어(`preview`)가 쌍으로 붙으므로 내려받기 호출만 고른다.
YHLIB_DOWN = re.compile(r"yhLib\.file\.download\(\s*'(?P<file>[^']+)'\s*,\s*'(?P<serial>[^']+)'")
# 강서구 목록이 게시글 번호를 싣는 자리. 주소는 `#`, `onclick`은 `yhLib.inline.post(this)`라
# 번호가 없고, `data-req-get-p-idx` 속성에만 있다.
YHLIB_INDEX = "req-get-p-idx"
# 연제구 첨부 이름 뒤에 붙는 크기 표기. 이름과 가르는 자리다.
SIZE = re.compile(r"\s*\[[^\]]*\]\s*$")
# 목록이 제목에 붙이는 아이콘 글자. 제목의 일부가 아니라 화면 표시다.
BADGES = ("새글",)


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


def named_first(links: list[listing.Link]) -> list[listing.Link]:
    """같은 첨부를 가리키는 링크가 여럿일 때 이름을 밝힌 것을 앞에 둔다.

    부산 게시판은 한 첨부에 링크를 둘 붙이는 일이 잦고(해운대구·동래구·시청 실측), 이름이
    어느 쪽에 붙는지는 게시판마다 다르다. 뒤에서 파일 번호로 하나만 남길 때 이름 없는 쪽이
    이기지 않도록 여기서 차례를 정한다.
    """
    return sorted(links, key=lambda link: not suffix_of(link))


def suffix_of(link: listing.Link) -> str:
    """링크가 밝힌 형식. 확장자 모양이 아니면 밝히지 않은 것으로 둔다.

    이름이 `…(2026.5.)`나 `…(문화관광과)....`처럼 끝나면 마지막 점 뒤가 확장자가 아니다.
    그것을 형식이라 우기면 실제 원본이 실측하지 않은 형식으로 밀린다. 밝히지 않은 것으로
    두면 수집이 실측 선언과 대조해 그 첨부만 사람이 볼 목록에 남긴다.
    """
    return boards.suffix_of(filename_of(link))


def rfc3_endpoint(url: str) -> tuple[str, dict[str, str], str]:
    """rfc3 게시판 주소를 기준 주소·조회 조건·사이트키로 나눈다.

    사이트키는 목록 경로에서 읽는다. 도메인과 다를 수 있어(해운대구 `do`, 남구 `namgu`)
    레지스트리가 주소와 따로 선언하면 두 값이 갈릴 자리가 생긴다.
    """
    list_url, params = boards.endpoint(url)
    if not boards.is_identifier(params.get("boardId", "").replace("_", "")):
        raise ValueError("board url must declare boardId")
    found = SITE_KEY.fullmatch(urllib.parse.urlsplit(list_url).path.rsplit("/", 1)[-1])
    if found is None:
        raise ValueError("board url must name an rfc3 listing")
    return list_url, params, found.group(1)


def listed_pages(parser: listing.TableParser, endpoint: str, parameter: str) -> Iterator[int]:
    """목록 주소를 가리키는 링크가 싣고 다니는 쪽 번호.

    게시글 링크도 지금 보고 있는 쪽 번호를 달고 다닌다. 아무 링크나 세면 쪽 넘김이 사라진
    목록을 "한 쪽짜리 게시판"으로 읽으므로, 링크가 가리키는 곳으로 쪽 넘김과 게시글을 가른다.
    """
    for link in parser.links:
        split = urllib.parse.urlsplit(link.href)
        if not split.path.endswith(endpoint):
            continue
        for value in urllib.parse.parse_qs(split.query).get(parameter, []):
            if value.isdigit():
                yield int(value)


class Rfc3Board:
    """부산 구·군 열이 함께 쓰는 rfc3 게시판. 목록에서 게시글을, 본문에서 첨부를 읽는다.

    목록은 첨부를 밝히지 않는다(실측 2026-09-14, 서구). 그래서 이번 수집이 받을 게시글만
    본문을 열고, 넘길 게시글은 목록에 실린 값만 담아 낸다.
    """

    published_suffixes = PUBLISHED_SUFFIXES
    # 섞인 게시판에서 업무추진비 게시글만 고르는 제목 조건. 비어 있으면 모두 받는다.
    title_filter: re.Pattern[str] | None = None

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params, self.site_key = rfc3_endpoint(board.url)
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
        """목록이 밝힌 마지막 쪽.

        실측(2026-09-14): 열한 게시판이 모두 마지막 쪽 단추에 진짜 마지막 쪽을 싣는다.
        묶는 태그는 기관마다 다르다(`div.paging-wrap2`, `div.page`).
        """
        return listing.last_page(listed_pages(parser, f"list.{self.site_key}", "startPage"))

    def _collects(self, title: str) -> bool:
        """섞인 게시판에서 이 게시글의 원본을 받을지. 조건이 없으면 게시판 전체가 대상이다."""
        return self.title_filter is None or self.title_filter.search(title) is not None

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(page_url)))
        found: list[boards.Attachment] = []
        # 같은 첨부에 내려받기 링크가 둘 붙는 게시판이 있다(동래구·해운대구 실측). 링크가
        # 아니라 파일이 몇 개인지를 센다. 이름은 그중 이름을 밝힌 링크에서 읽는다.
        seen: set[str] = set()
        for link in named_first(parser.links):
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
    """기장군 게시판. 첨부가 없고 목록의 표 자체가 집행내역이다([ADR-0008](
    ../../../docs/adr/0008-declare-html-table-mappings.md)).

    한 줄이 집행 한 건이라 게시글도 첨부도 없다. 공개된 행 수 조건으로 표 전량을 한 응답에
    받고, 그 응답 전체를 `.html` 원본 하나로 둔다. 새 줄이 위에 쌓여 둘째 쪽부터 내용이
    밀리므로, 한 쪽에 담기지 않으면 쪽을 짐작해 나누지 않고 읽지 못한 게시판으로 알린다 —
    울산 중구 회계연도 목록과 같은 규칙.

    게시글 번호는 게시판 하나를 가리키는 고정 값이다. 줄 위치로 매기면 새 줄이 쌓일 때마다
    같은 번호가 다른 줄을 가리킨다. 한 번 받은 원본은 다시 받지 않으므로, 그 뒤에 붙은 줄은
    그 원본을 치우고 다시 수집해야 들어온다(ADR-0008).
    """

    published_suffixes = frozenset({boards.HTML_SUFFIX})
    # 이 게시판 하나를 가리키는 게시글 번호. 표의 줄에는 번호가 없고, 원본도 하나다.
    post_id = "expenses"
    # 한 쪽에 실을 줄 수. 실측 2026-09-17: 표 전량이 3,297줄이라 그보다 넉넉히 잡는다.
    page_size = "4000"

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params, self.site_key = rfc3_endpoint(board.url)
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        # 부서(`categoryCode1`)·연도(`categoryCode2`)·월(`categoryCode3`) 조건은 붙이지 않는다.
        # 부서 조건은 3,297줄 중 530줄만 남기고, 연도·월은 사람이 적은 분류라 3,215건 중
        # 64건이 사용일자와 어긋난다(실측 2026-09-14). 기간은 받은 뒤 사용일자 열로 가른다.
        # `listRow`만 보내면 게시판이 무시하고 열 줄을 준다. `listCel=1`을 함께 보내야 행 수
        # 조건이 열린다(실측 2026-09-17).
        params = {**self.params, "listCel": "1", "listRow": self.page_size, "startPage": "1"}
        parser = listing.parse(boards.request(self.transport, self.list_url, params))
        if listing.page_count(parser, link_keys=("startPage",)) != 1:
            raise boards.UnreadableBoard("expense listing no longer fits one page")
        url = boards.address(self.list_url, params)
        yield boards.Posting(
            self.post_id, boards.html_original(self.post_id, url, skipped(self.post_id, None))
        )


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
            if page >= _script_page_count(parser):
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


class YhLibBoard:
    """강서구 yhLib portal 게시판. 게시글 번호는 링크의 data 속성에, 첨부는 본문의
    `yhLib.file.download` 호출에 있다. 목록·본문·첨부 모두 GET으로 열린다(실측 2026-09-17).

    `bcIdx`(게시판)·`mid`(메뉴) 없이 부르면 목록이 열리지 않는다. 그래서 레지스트리가
    선언한 두 조건을 쪽마다 그대로 싣고, 빠져 있으면 훑기 전에 거절한다.
    """

    published_suffixes = frozenset({".xlsx", ".xls", ".hwpx", ".hwp", ".pdf"})

    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not all(boards.is_identifier(self.params.get(name, "")) for name in ("bcIdx", "mid")):
            raise ValueError("board url must declare bcIdx and mid")
        self.view_url = urllib.parse.urljoin(self.list_url, "view.do")
        self.download_url = urllib.parse.urljoin(self.list_url, "/common/file/download.do")
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = listing.parse(
                boards.request(self.transport, self.list_url, {**self.params, "page": str(page)})
            )
            for row in parser.rows:
                post_id = _yhlib_index(row)
                if post_id is None or not boards.is_identifier(post_id):
                    continue
                posted = listing.posted(_cell(row, "list_date"))
                page_url = boards.address(self.view_url, {**self.params, "idx": post_id})
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
            if page >= _script_page_count(parser):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(page_url)))
        found: list[boards.Attachment] = []
        for link in parser.links:
            call = YHLIB_DOWN.search(link.onclick)
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
        # 한 첨부에 링크가 둘 붙고 이름은 한쪽에만 있다(21660 실측). 파일 번호로 하나만 남긴다.
        seen: set[str] = set()
        for link in named_first(parser.links):
            split = urllib.parse.urlsplit(link.href)
            if not split.path.endswith("/comm/getFile"):
                continue
            query = urllib.parse.parse_qs(split.query)
            file_no = query.get("fileNo", [""])[0]
            upper_no = query.get("upperNo", [""])[0]
            if not (boards.is_identifier(file_no) and boards.is_identifier(upper_no)):
                raise boards.UnreadableBoard("board supplied an unusable attachment identifier")
            if file_no in seen:
                continue
            seen.add(file_no)
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
    """쪽 넘김이 밝힌 마지막 쪽. 시청의 쪽 넘김 주소는 경로가 비어 있어 게시글 번호로 가른다."""

    def pages() -> Iterator[int]:
        for link in parser.links:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(link.href).query)
            if "schIndx" in query:
                continue
            yield from (int(value) for value in query.get("curPage", []) if value.isdigit())

    return listing.last_page(pages())


def _cell(row: listing.Row, name: str) -> str:
    for cell in row.cells:
        if name in cell.classes:
            return cell.text
    return ""


def _yhlib_index(row: listing.Row) -> str | None:
    """강서구 목록 행이 밝힌 게시글 번호. 값은 게시글 링크의 `data-req-get-p-idx`에 있다."""
    for link in row.links:
        value = dict(link.data).get(YHLIB_INDEX)
        if value:
            return value
    return None


def _title(row: listing.Row) -> str:
    """게시글 제목. 목록이 붙인 아이콘 글자는 제목이 아니므로 뗀다."""
    title = _cell(row, "list_tit")
    for badge in BADGES:
        title = title.removesuffix(badge).strip()
    return title


def _script_page_count(parser: listing.TableParser) -> int:
    """연제구의 마지막 쪽. 쪽 넘김 주소가 `#`이라 쪽 수는 `goPage` 호출에만 있다."""
    return listing.last_page(
        int(found) for link in parser.links for found in PAGE_CALL.findall(link.onclick)
    )


__all__ = [
    "PUBLISHED_SUFFIXES",
    "CityBoard",
    "EgovPortalBoard",
    "GijangBoard",
    "MixedRfc3Board",
    "Rfc3Board",
    "YhLibBoard",
]
