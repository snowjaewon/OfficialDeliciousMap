"""인천시와 9구 2군의 업무추진비 게시판 수집기.

인천의 기초자치단체 여덟 곳은 `bbsMsgList.do` 한 계열을 쓴다. 그 한 벌을 `BbsBoard`에 두고,
게시판 코드(`bcd`)와 분류(`cate1`)처럼 기관마다 다른 값은 레지스트리가 선언한 주소에서 읽는다.
같은 계열이라도 목록을 표로 그리는 기관(서해·계양·강화·옹진·검단·제물포)과 목록으로 그리는
기관(남동·부평)이 있어, 게시글 하나를 `<tr>`·`<li>` 어느 쪽으로도 읽는다.

나머지 넷은 계열이 달라 따로 둔다. 시청은 `CityBoard`, 미추홀·영종은 한 계열이라 `KeyedBoard`
한 벌을 나눠 쓰고, 연수는 `YeonsuBoard`다. 목록 구조가 다를 뿐 계약은 같다 — 목록에서 게시글을,
본문에서 첨부를 읽고 저장과 형식 판정은 하지 않는다.
"""

import re
import urllib.parse
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import TYPE_CHECKING

from deliciousmap import boards
from deliciousmap.grid import is_html
from deliciousmap.scrapers import listing
from deliciousmap.transport import Transport

if TYPE_CHECKING:
    from deliciousmap.registry.models import Board

# 인천 게시판에서 실측한 첨부 확장자(2026-09-17). 기관마다 다른 것은 게시판 선언이 좁힌다.
PUBLISHED_SUFFIXES = frozenset({".xlsx", ".xls", ".xlsm", ".hwp", ".hwpx", ".pdf", ".zip"})
# 한 목록 쪽에 실을 줄 수. 계열마다 조건 이름이 다르고, 보내지 않으면 열 줄씩 준다.
PAGE_SIZE = "100"
# 미추홀구·영종구의 쪽 넘김. 주소는 `javascript:;`이고 쪽 번호는 스크립트 호출에만 있다.
PAGE_CALL = re.compile(r"fnList\(\s*\{\s*'page'\s*:\s*'(\d+)'\s*\}")
# 링크가 이름 뒤에 붙이는 화면 글자. 이름의 일부가 아니라 단추·크기 표시다.
NOISE = re.compile(
    r"\s*(?:\(\s*[\d.,]+\s*[KMGkmg]?[Bb]?(?:yte)?\s*\)|\[[^\]]*\]"
    r"|다운로드|다운받기|내려받기|미리보기|새창)\s*$"
)
# 목록이 제목에 붙이는 아이콘 글자. 제목의 일부가 아니라 화면 표시다.
BADGES = ("NEW", "새글")
# 구·군의회 글을 가르는 글자. 구청·군청 게시판에 의회 사무국·사무과의 집행내역이 섞이고
# (2026-09-17 실측: 남동 9건·연수 9건·강화 8건·옹진 8건·영종 실과장급 2건이 2026년 게시글에
# 들어 있다), 의회는 그 기관의 집행기관이 아니라서 걸러 내고 센다(`boards.FiltersRows`).
# 제목이 `…의회사무과 업무추진비…`·`…(의회사무국)`으로, 목록 칸이 부서·작성자로 밝힌다.
COUNCIL = "의회"


def is_council(*texts: str) -> bool:
    """의회가 쓴 줄인지. 제목과 목록이 밝힌 부서·작성자 가운데 하나라도 밝히면 참이다."""
    return any(COUNCIL in text for text in texts)


def _path(href: str) -> str:
    """주소의 경로. 세션을 경로에 다는 게시판이 있어(강화군 실측) 경로 매개변수를 뗀다."""
    return urllib.parse.urlsplit(href).path.split(";", 1)[0]


def _query(href: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)


def filename_of(text: str) -> str:
    """링크가 밝힌 파일 이름. 이름 뒤에 붙은 화면 글자는 이름이 아니므로 뗀다."""
    name = " ".join(text.split())
    while True:
        shorter = NOISE.sub("", name)
        if shorter == name:
            return name
        name = shorter


def suffix_of(text: str) -> str:
    """링크가 밝힌 형식. 확장자 모양이 아니면 밝히지 않은 것으로 둔다.

    이름 가운데에 점이 든 첨부가 잦아(`2026.08월_업무추진비(오류왕길동).xlsx`, 검단구 실측)
    앞에서부터 줍지 않고 이름의 마지막 확장자만 읽는다.
    """
    found = boards.suffix_of(filename_of(text))
    return found if boards.SUFFIX.fullmatch(found) else ""


def posted_in(text: str) -> date | None:
    """덩이가 밝힌 게시일. 제목 뒤에 처음 적힌 날짜가 작성일이다(표·목록 두 모양 모두).

    제목에도 날짜가 적히므로(`2026.08.01. 업무추진비…`) 덩이의 글자에서 제목은 뺀다.
    오늘 올라온 글은 날짜 대신 시각만 적는 게시판이 있어(검단구 실측) 읽을 날짜가 없으면
    짐작하지 않고 비운다 — 게시일을 밝히지 않은 게시글은 수집이 대상으로 받는다.
    """
    found = listing.DATE_RE.search(text)
    if found is None:
        return None
    year, month, day = found.groups()
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def department_of(row: listing.Row) -> str:
    """행이 밝힌 담당부서. 네 게시판 모두 작성일 칸 바로 앞이 담당부서다(2026-09-17 실측)."""
    for index, cell in enumerate(row.cells):
        if index and listing.DATE_RE.fullmatch(cell.text):
            return row.cells[index - 1].text
    return ""


def title_of(text: str) -> str:
    """게시글 제목. 목록이 붙인 아이콘 글자는 제목이 아니므로 뗀다."""
    title = " ".join(text.split())
    for badge in BADGES:
        title = title.removesuffix(badge).strip()
    return title


def pages_of(hrefs: Iterable[str], base: str, endpoint: str, parameter: str) -> Iterator[int]:
    """목록 주소를 가리키는 링크가 싣고 다니는 쪽 번호.

    게시글 링크도 지금 보고 있는 쪽 번호를 달고 다닌다. 아무 링크나 세면 쪽 넘김이 사라진
    목록을 "한 쪽짜리 게시판"으로 읽으므로, 링크가 가리키는 곳으로 쪽 넘김과 게시글을 가른다.
    가리키는 곳은 목록 주소에 붙여 본다 — 쪽 넘김을 조회 조건만으로 적는 게시판이 있어
    (시청 실측: `?curPage=2&cntPerPage=100`) 주소만 보면 경로가 비어 있다.
    """
    for href in hrefs:
        target = urllib.parse.urljoin(base, href)
        if not _path(target).endswith(endpoint):
            continue
        for value in _query(target).get(parameter, []):
            if value.isdigit():
                yield int(value)


def script_pages(links: Iterable[listing.Link]) -> Iterator[int]:
    """쪽 넘김 주소가 `javascript:;`인 목록의 쪽 번호. 값은 스크립트 호출에만 있다."""
    for link in links:
        for found in PAGE_CALL.findall(link.onclick):
            yield int(found)


@dataclass(frozen=True)
class Item:
    """목록의 게시글 한 덩이. 표로 그리든 목록으로 그리든 같은 모양으로 읽는다.

    `text`에는 제목을 넣지 않는다. 제목에도 날짜가 적혀(`2026.08.01. 업무추진비…`, 검단구 실측)
    섞으면 그것을 게시일로 읽는다.
    """

    title: str
    text: str
    links: tuple[tuple[str, str], ...]


class Items(HTMLParser):
    """목록을 게시글 덩이로 가른다. 덩이는 게시글 링크에서 시작해 다음 게시글 링크 앞에서 끝난다.

    같은 계열이 기관마다 표(`<tr>`)와 목록(`<li>`)으로 갈려 그려지고, 목록 쪽은 닫는 태그를
    하나 빠뜨린다(2026-09-17 실측: 남동 `<li>` 1,925개에 닫는 태그 1,924개, 부평 1,638개에
    1,637개). 하나만 빠져도 요소 경계로는 그 뒤의 게시글을 한 덩이도 끊어 낼 수 없다. 요소
    구조에 기대지 않고 게시글 링크로 가르면 두 모양을 한 규칙으로 읽는다.
    """

    def __init__(self, starts: Callable[[str], bool]) -> None:
        super().__init__(convert_charrefs=True)
        self.starts = starts
        self.items: list[Item] = []
        # 쪽 넘김을 세는 자리. 덩이 안팎을 가리지 않고 본 주소를 그대로 담는다.
        self.hrefs: list[str] = []
        self._open = False
        self._title = ""
        self._text: list[str] = []
        self._links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._label = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        href, label = self._href, " ".join("".join(self._label).split())
        self._href, self._label = None, []
        self.hrefs.append(href)
        if self.starts(href):
            self._settle()
            self._open, self._title = True, label
            self._text, self._links = [], [(href, label)]
        elif self._open:
            self._links.append((href, label))

    def handle_data(self, data: str) -> None:
        # 링크 안의 글자는 제목과 파일 이름이라 덩이의 글자로 세지 않는다.
        if self._href is not None:
            self._label.append(data)
        elif self._open:
            self._text.append(data)

    def close(self) -> None:
        super().close()
        self._settle()

    def _settle(self) -> None:
        if not self._open:
            return
        self.items.append(
            Item(self._title, " ".join("".join(self._text).split()), tuple(self._links))
        )
        self._open = False


class CityFiles(HTMLParser):
    """시청 본문의 첨부. 이름은 링크가 아니라 바로 앞 `file-name` 칸에 있다(실측)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.files: list[tuple[str, str]] = []
        self._name = ""
        self._span: list[str] | None = None
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raw = dict(attrs)
        if tag == "span" and "file-name" in (raw.get("class") or "").split():
            self._span = []
        elif tag == "a":
            self._href = raw.get("href") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._span is not None:
            self._name = " ".join("".join(self._span).split())
            self._span = None
        elif tag == "a" and self._href is not None:
            if _path(self._href).endswith("/comm/getFile"):
                self.files.append((self._name, self._href))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._span is not None:
            self._span.append(data)


def _opens_posting(href: str) -> bool:
    """덩이를 여는 링크인지. `bbsMsgList.do` 계열은 게시글 링크가 덩이의 첫 줄이다."""
    return _path(href).endswith("bbsMsgDetail.do") and boards.is_identifier(
        _query(href).get("msg_seq", [""])[0]
    )


def _by_posting(items: Iterable[Item]) -> dict[str, Item]:
    """게시글 번호별 덩이. 한 게시글에 게시글 링크가 둘이면 그 둘을 한 덩이로 합친다.

    둘로 남기면 앞 덩이에는 게시일이 없어 같은 게시글이 기간 판정을 두 번, 서로 다르게 받는다.
    사전에 담기는 차례는 목록에 실린 차례 그대로다.
    """
    found: dict[str, Item] = {}
    for item in items:
        post_id = _query(item.links[0][0])["msg_seq"][0]
        seen = found.get(post_id)
        found[post_id] = (
            item
            if seen is None
            else Item(seen.title or item.title, f"{seen.text} {item.text}", seen.links + item.links)
        )
    return found


def read[T: HTMLParser](body: bytes, parser: T) -> T:
    """응답을 해석기 하나로 읽는다. 인코딩 계약은 목록 해석기와 같다."""
    try:
        parser.feed(body.decode(listing.ENCODING))
        parser.close()
    except UnicodeDecodeError:
        raise boards.UnreadableBoard("board response is not in the measured encoding") from None
    return parser


def identifier(value: str) -> str:
    """게시판이 준 식별자. 주소에 그대로 실을 수 있는 값이 아니면 읽지 못한 목록이다."""
    if not boards.is_identifier(value):
        raise boards.UnreadableBoard("board supplied an unusable identifier")
    return value


class CityBoard:
    """인천시청 정보공개포털 게시판. 게시글 번호가 조회 조건이 아니라 경로에 있다.

    한 쪽에 실을 줄 수를 `cntPerPage`로 물을 수 있어(실측 2026-09-17: 11,053건이 1,106쪽에서
    111쪽으로 준다) 목록 요청을 그만큼 줄인다. 첨부 이름은 링크에 없고 그 앞 칸에 있다.
    """

    # 이 게시판만 집행내역을 스캔본으로도 공개한다(2026-09-17 실측: 2026년 첨부 가운데 본청
    # 실국과장 5건·소방 14건이 `.jpg`·`.png`이고, 받은 내용도 JPEG·PNG였다). 서울 용산과 같은
    # 모양이라 컨테이너는 이미 실측 목록에 있다. 표를 읽는 일은 이 이슈 밖이고, 여기서는 받은
    # 형식을 그대로 센다. 다른 인천 게시판에서는 이 확장자를 실측하지 않았다.
    published_suffixes = PUBLISHED_SUFFIXES | {".jpg", ".jpeg", ".png"}

    def __init__(self, board: "Board", transport: Transport) -> None:
        # 의회가 쓴 줄. 시청 게시판에서는 2026년 게시글에 없었지만, 도시 안의 다른 게시판이
        # 섞어 싣고 있어 같은 규칙을 둔다. 섞이지 않은 게시판에서는 0으로 남는다.
        self.filtered = 0
        self.list_url, self.params = boards.endpoint(board.url)
        self.board_path = _path(self.list_url)
        if not boards.is_identifier(self.board_path.rsplit("/", 1)[-1]):
            raise ValueError("board url must name an open information section")
        self.download_url = urllib.parse.urljoin(self.list_url, "/comm/getFile")
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = listing.parse(
                boards.request(
                    self.transport,
                    self.list_url,
                    {**self.params, "curPage": str(page), "cntPerPage": PAGE_SIZE},
                )
            )
            for row in parser.rows:
                article = self._article(row)
                if article is None:
                    continue
                post_id, href = article
                title, department = listing.title_of(row, href), department_of(row)
                if is_council(title, department):
                    self.filtered += 1
                    continue
                posted = listing.posted_of(row)
                page_url = f"{self.list_url}/{post_id}"
                opened = not skipped(post_id, posted)
                attachments = self._attachments(post_id, page_url) if opened else ()
                yield boards.Posting(
                    post_id, attachments, posted, title, department, url=page_url if opened else ""
                )
            hrefs = (link.href for link in parser.links)
            if page >= listing.last_page(
                pages_of(hrefs, self.list_url, self.board_path, "curPage")
            ):
                return
            page += 1

    def _article(self, row: listing.Row) -> tuple[str, str] | None:
        """행이 가리키는 게시글. 게시글 번호는 목록 경로 아래의 마지막 조각이다."""
        for link in row.links:
            parent, _, last = _path(link.href).rpartition("/")
            if parent.endswith(self.board_path) and boards.is_identifier(last):
                return last, link.href
        return None

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        parser = read(boards.request(self.transport, page_url, {}), CityFiles())
        found: list[boards.Attachment] = []
        for name, href in parser.files:
            query = _query(href)
            file_no = identifier(query.get("fileNo", [""])[0])
            upper_no = identifier(query.get("upperNo", [""])[0])
            found.append(
                boards.Attachment(
                    post_id,
                    file_no,
                    suffix_of(name),
                    boards.address(
                        self.download_url,
                        {
                            "srvcId": identifier(query.get("srvcId", [""])[0]),
                            "upperNo": upper_no,
                            "fileTy": identifier(query.get("fileTy", [""])[0]),
                            "fileNo": file_no,
                        },
                    ),
                    page_url,
                )
            )
        return tuple(found)


class BbsBoard:
    """인천 기초자치단체 여덟 곳이 함께 쓰는 `bbsMsgList.do` 게시판.

    목록도 첨부 링크를 싣지만(서해구 표본 10건에서 본문과 같았다) 본문을 열어 읽는다. 목록이
    첨부를 모두 싣는지는 한 쪽 표본으로 확인할 수 없고, 빠뜨린 첨부는 0건과 같은 모양이 된다.
    본문을 여는 것은 이번 수집이 받을 게시글뿐이다.

    한 쪽에 실을 줄 수를 `listsz`로 물을 수 있다(실측 2026-09-17: 일곱 호스트 모두 100줄).
    """

    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: Transport) -> None:
        # 의회가 쓴 줄(남동·강화·옹진 실측). 섞이지 않은 게시판에서는 0으로 남는다.
        self.filtered = 0
        self.list_url, self.params = boards.endpoint(board.url)
        if not boards.is_identifier(self.params.get("bcd", "").replace("_", "")):
            raise ValueError("board url must declare bcd")
        self.detail_url = urllib.parse.urljoin(self.list_url, "bbsMsgDetail.do")
        self.download_url = urllib.parse.urljoin(self.list_url, "bbsMsgFileDown.do")
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = read(
                boards.request(
                    self.transport,
                    self.list_url,
                    {**self.params, "listsz": PAGE_SIZE, "pgno": str(page)},
                ),
                Items(_opens_posting),
            )
            for post_id, item in _by_posting(parser.items).items():
                # 부서·작성자는 칸 차례가 기관마다 달라 따로 읽지 않는다. 덩이의 글자에 그
                # 값이 모두 들어 있어 제목과 함께 본다(남동 목록의 `남동구의회` 실측).
                if is_council(item.title, item.text):
                    self.filtered += 1
                    continue
                posted = posted_in(item.text)
                page_url = boards.address(self.detail_url, {**self.params, "msg_seq": post_id})
                opened = not skipped(post_id, posted)
                attachments = self._attachments(post_id, page_url) if opened else ()
                yield boards.Posting(
                    post_id,
                    attachments,
                    posted,
                    title_of(item.title),
                    url=page_url if opened else "",
                )
            pages = pages_of(parser.hrefs, self.list_url, "bbsMsgList.do", "pgno")
            if page >= listing.last_page(pages):
                return
            page += 1

    def verify(self, body: bytes) -> None:
        """받은 것이 원본인지. 원본이 없는 게시글에는 파일 대신 이 게시판의 화면을 준다.

        옹진군 실측 2026-09-17: `msg_seq` 2211·2212의 첨부는 목록·본문이 `11KByte`짜리
        `.xlsx`라고 밝히지만, 내려받기 주소가 302로 본문 화면으로 보내고 그 화면이 115KB로
        온다. 이웃 게시글(2210·2213)은 같은 요청에 200과 OOXML을 준다. 쿠키를 이어 들고
        본문을 먼저 열어도, Referer를 붙여도, 여러 첨부를 묶어 주는 주소로 물어도 같다
        (묶음 주소는 항목이 없는 22바이트 빈 ZIP을 준다). 이 게시판은 화면을 원본으로 내지
        않으므로, 받을 원본이 기관 쪽에 없다는 뜻이고 다시 요청해도 달라지지 않는다.

        아무 HTML이나 그렇게 읽지는 않는다. **이 게시판의 화면일 때만** 유실로 가른다 —
        그 화면은 자기 게시판 코드를 달고 온다(실측: 받은 115KB 안에 `bcd=opendata1`이 다섯
        번, `bbsMsgDetail.do`가 두 번 있다). 점검·차단 화면처럼 그 표식이 없는 HTML은 유실이
        아니라 실측하지 않은 형식으로 남아 사람이 본다. 제물포구가 한때 모든 요청에 404를
        준 것처럼 일시적 장애는 실제로 일어나고, 추가형 장부에 박힌 유실은 다시 받지 않는다.

        첨부가 없는 게시글은 본문에 내려받기 링크가 없어 여기까지 오지 않는다 — 그 게시글을
        유실로 세지 않는다.
        """
        marker = f"bcd={self.params['bcd']}".encode()
        if is_html(body) and marker in body and b"bbsMsgDetail.do" in body:
            raise boards.OriginalGone("board served its own page instead of the original")

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(page_url)))
        found: list[boards.Attachment] = []
        for link in parser.links:
            if not _path(link.href).endswith("bbsMsgFileDown.do"):
                continue
            file_no = identifier(_query(link.href).get("fileno", [""])[0])
            found.append(
                boards.Attachment(
                    post_id,
                    file_no,
                    suffix_of(link.text),
                    boards.address(
                        self.download_url,
                        {
                            "bcd": self.params["bcd"],
                            "msg_seq": post_id,
                            "fileno": file_no,
                        },
                    ),
                    page_url,
                )
            )
        return tuple(found)


class KeyedBoard:
    """미추홀구·영종구가 함께 쓰는 계열. 같은 틀을 쓰고 조회 조건 이름과 첨부 경로만 다르다.

    쪽 넘김 주소가 `javascript:;`이고 쪽 번호는 `fnList` 호출에만 있다. 첨부 주소에는 지어낼 수
    없는 열쇠가 붙어 본문에서 그대로 읽는다. 기관마다 다른 값은 아래 네 칸이 정한다.
    """

    published_suffixes = PUBLISHED_SUFFIXES
    # 레지스트리가 선언해야 하는 조회 조건(게시판을 가르는 값).
    board_key = ""
    # 게시글 번호를 싣는 조회 조건.
    article_key = ""
    # 첨부를 내려받는 경로.
    download_path = ""
    # 첨부를 가리키는 조회 조건(파일 번호).
    file_key = ""

    def __init__(self, board: "Board", transport: Transport) -> None:
        # 의회가 쓴 줄. 영종구 실·과장급 게시판에서 2026년 게시글 2건을 실측했다.
        self.filtered = 0
        self.list_url, self.params = boards.endpoint(board.url)
        if not boards.is_identifier(self.params.get(self.board_key, "").replace("_", "")):
            raise ValueError(f"board url must declare {self.board_key}")
        self.view_url = urllib.parse.urljoin(self.list_url, "view.do")
        self.download_url = urllib.parse.urljoin(self.list_url, self.download_path)
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = listing.parse(
                boards.request(self.transport, self.list_url, {**self.params, "page": str(page)})
            )
            for row in parser.rows:
                article = listing.article_link(row, "view.do", self.article_key)
                if article is None:
                    continue
                post_id, href = article
                title, department = listing.title_of(row, href), department_of(row)
                if is_council(title, department):
                    self.filtered += 1
                    continue
                posted = listing.posted_of(row)
                page_url = boards.address(self.view_url, {**self.params, self.article_key: post_id})
                opened = not skipped(post_id, posted)
                attachments = self._attachments(post_id, page_url) if opened else ()
                yield boards.Posting(
                    post_id, attachments, posted, title, department, url=page_url if opened else ""
                )
            if page >= listing.last_page(script_pages(parser.links)):
                return
            page += 1

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(page_url)))
        found: list[boards.Attachment] = []
        for link in parser.links:
            if not _path(link.href).endswith(self.download_path):
                continue
            query = _query(link.href)
            file_id = identifier(query.get(self.file_key, [""])[0])
            found.append(
                boards.Attachment(
                    post_id,
                    file_id,
                    suffix_of(link.text),
                    boards.address(self.download_url, self._download(file_id, query)),
                    page_url,
                )
            )
        return tuple(found)

    def _download(self, file_id: str, query: dict[str, list[str]]) -> dict[str, str]:
        """첨부를 부르는 조회 조건. 열쇠는 게시판이 준 값을 그대로 싣는다."""
        return {self.file_key: file_id, "key": identifier(query.get("key", [""])[0])}


class MichuholBoard(KeyedBoard):
    """미추홀구 게시판. 게시글 713쪽을 한 게시판에 쌓아 둔다(2020-12-01까지, 실측)."""

    board_key = "board_code"
    article_key = "sq"
    download_path = "/other/file_down.do"
    file_key = "sq"


class YeongjongBoard(KeyedBoard):
    """영종구 게시판. 직급별로 다섯이고, 2026년 상반기 집행내역은 옛 중구청장 이름으로 실린다.

    첨부 주소가 파일 번호와 함께 내려받기인지(`TP=dn`)를 묻는다. 그 값도 본문이 밝힌 것을
    그대로 싣는다 — 보내지 않으면 기관이 무엇을 줄지 실측하지 않았다.
    """

    board_key = "pst_id"
    article_key = "pst_sn"
    download_path = "/other/attach/process.file.do"
    file_key = "sn"

    def _download(self, file_id: str, query: dict[str, list[str]]) -> dict[str, str]:
        return {"TP": identifier(query.get("TP", [""])[0]), **super()._download(file_id, query)}


class YeonsuBoard:
    """연수구 게시판. 목록·본문이 같은 주소이고 첨부는 파일 이름이 열쇠다.

    첨부에는 번호가 없어 본문에 실린 차례를 파일 번호로 쓴다. Referer 없이 부르면 200과 함께
    "정상적인 접근이 아닙니다" 화면이 오므로(실측 2026-09-17) 본문 주소를 함께 보낸다 —
    브라우저가 보내는 헤더를 그대로 붙이는 것이라 차단 우회가 아니다.
    """

    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: Transport) -> None:
        # 의회가 쓴 줄(`의회사무국`, 2026년 게시글 9건 실측).
        self.filtered = 0
        self.list_url, self.params = boards.endpoint(board.url)
        if not _path(self.list_url).endswith(".asp"):
            raise ValueError("board url must name the expense listing")
        self.download_url = urllib.parse.urljoin(self.list_url, "/shareEtc/download_utf.asp")
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            parser = listing.parse(
                boards.request(
                    self.transport, self.list_url, {**self.params, "gotopage": str(page)}
                )
            )
            for row in parser.rows:
                article = listing.article_link(row, ".asp", "idx")
                if article is None:
                    continue
                post_id, href = article
                title, department = listing.title_of(row, href), department_of(row)
                if is_council(title, department):
                    self.filtered += 1
                    continue
                posted = listing.posted_of(row)
                page_url = boards.address(self.list_url, {"page": "v", "idx": post_id})
                opened = not skipped(post_id, posted)
                attachments = self._attachments(post_id, page_url) if opened else ()
                yield boards.Posting(
                    post_id, attachments, posted, title, department, url=page_url if opened else ""
                )
            if page >= listing.last_page(self._pages(parser)):
                return
            page += 1

    def _pages(self, parser: listing.TableParser) -> Iterator[int]:
        """쪽 넘김이 밝힌 쪽 번호. 게시글 링크도 `gotopage`를 달고 다녀 게시글 번호로 가른다."""
        for link in parser.links:
            if "idx" in _query(link.href):
                continue
            yield from pages_of([link.href], self.list_url, ".asp", "gotopage")

    def _attachments(self, post_id: str, page_url: str) -> tuple[boards.Attachment, ...]:
        parser = listing.parse(boards.request(self.transport, *boards.endpoint(page_url)))
        found: list[boards.Attachment] = []
        for link in parser.links:
            if not _path(link.href).endswith("/shareEtc/download_utf.asp"):
                continue
            target = urllib.parse.urljoin(self.list_url, link.href)
            found.append(
                boards.Attachment(
                    post_id,
                    str(len(found) + 1),
                    suffix_of(link.text),
                    boards.address(*boards.endpoint(target)),
                    page_url,
                    page_url,
                )
            )
        return tuple(found)


__all__ = [
    "PUBLISHED_SUFFIXES",
    "BbsBoard",
    "CityBoard",
    "KeyedBoard",
    "MichuholBoard",
    "YeongjongBoard",
    "YeonsuBoard",
]
