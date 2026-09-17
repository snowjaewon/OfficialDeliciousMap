"""게시판 해석의 공통 경계. 기관별 스크래퍼가 여기의 계약만 지키면 수집 규칙을 공유한다."""

import re
import urllib.parse
import zipfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from io import BytesIO
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from deliciousmap.grid import is_html
from deliciousmap.transport import HttpTransport, ResourceGone, Transport, query

if TYPE_CHECKING:  # 레지스트리가 스크래퍼를 선언하므로 실행 시점에 되짚어 부르지 않는다.
    from deliciousmap.registry.models import Board

# 한 번에 통째로 읽어 둘 수 있는 응답의 상한. 업무추진비 첨부는 실측 표본에서 수십~수백 KB였고
# 이 값은 그보다 두 자리 여유가 있다. 넘는 응답은 잘라 쓰지 않고 받지 못한 것으로 알린다.
# 정제 산출물의 20MB 상한(ADR-0001)과는 다른 이유로 정한 별개의 값이다.
MAX_RESPONSE_BYTES = 20_000_000
# 전량 수집은 요청이 수만 번이라 일시적 실패를 만난다. 실측: 2,584번째 게시글에서 한 번 끊겼고
# 그 주소는 곧바로 다시 200을 주었다. 그런 실패만 이만큼 다시 시도한다.
REQUEST_ATTEMPTS = 4
REQUEST_BACKOFF = 2.0
# 첨부는 목록·본문보다 크고 느릴 수 있어 넉넉히 기다린다.
REQUEST_TIMEOUT = 30.0
# 한 기관에 연달아 요청할 때 두는 간격(초). 게시판 전량 수집이 몰아치지 않게 한다.
# 광주 게시판 실측(2026-09-11): 게시글 하나에 본문·첨부 두 번을 요청하고 왕복이 합쳐 0.78초다.
# 0.5초일 때 건당 1.78초로 대기가 56%를 차지해 0.2초로 낮췄다. 합산 약 2.1 req/s이고 여전히
# 순차 요청이다. 기관이 어디까지 견디는지는 측정하지 않았으므로 더 줄이지 않는다.
REQUEST_INTERVAL = 0.2
# 공통 간격으로는 견디지 못한다고 실측한 호스트만 둔다. 지금은 비어 있다.
# 2026-09-14 실측: 강동은 목업 기록("간격 0.3초에 400")과 달리 0.2초로 열두 쪽을 연달아
# 받아 모두 200이었다. 중랑은 간격을 1.0초로 넓혀도 853쪽 순회가 끝나지 않아(≈190쪽에서
# 끊김) 느리게 하는 것이 답이 아니었다. 재지 않은 값을 효과가 있는 것처럼 두지 않는다.
HOST_INTERVALS: dict[str, float] = {}
# 공통 기다림 안에 응답을 주지 못한다고 실측한 호스트만 둔다. 기장군은 게시판 전량(3,297줄,
# 2.96MB)을 한 응답으로 만들어 주느라 2026-09-17 실측에서 116초가 걸렸다. 쪽을 나누면 새 줄이
# 위에 쌓여 내용이 밀리므로(ADR-0008) 나누는 대신 그 게시판에서만 넉넉히 기다린다.
HOST_TIMEOUTS: dict[str, float] = {"www.gijang.go.kr": 300.0}
# 서명만으로 갈리지 않는 형식이 있어 앞부분에서 표식을 함께 찾는다. 이만큼만 본다.
MARKER_WINDOW = 4096
# 수집 주체를 밝힌다. 브라우저를 가장하지 않는다.
USER_AGENT = "OfficialDeliciousMap/0.1 (+https://github.com/snowjaewon/OfficialDeliciousMap)"
HEADERS = {"User-Agent": USER_AGENT}


class UnsupportedOriginal(Exception):
    """게시판이 원본 대신 다른 것을 주었거나, 그 기관에서 실측하지 않은 형식이다."""


class BoardUnavailable(Exception):
    """게시판에 닿지 못했다. 서비스 응답·오류 원문은 남기지 않는다."""


class UnreadableBoard(Exception):
    """응답이 실측한 구조와 다르거나 온전히 받지 못했다. 형식 문제와 구별한다."""


class OversizeOriginal(UnreadableBoard):
    """한 번에 읽어 둘 수 있는 크기를 넘는 응답. 잘라 쓰면 원본이 아니므로 받지 못한 것으로 둔다.

    목록·본문이 이만큼 크면 그 게시판을 읽지 못한 것이라 `UnreadableBoard`를 그대로 물려받고,
    첨부일 때만 수집이 이 이름으로 가려 장부에 남긴다(인천시청 실측: 본청실국과장 게시글
    3087017의 `.xlsx` 하나가 상한을 넘는다).
    """


class OriginalGone(Exception):
    """게시판이 링크한 원본이 기관 쪽에 없다. 다시 요청해도 달라지지 않는다."""


class EmptyOriginal(Exception):
    """게시판이 내용 없는 첨부를 200으로 주었다. 받을 것이 없다는 점에서 유실과 같다."""


class ProtectedOriginal(Exception):
    """기관이 DRM으로 잠근 첨부다. 200으로 오지만 읽을 수 있는 원본이 들어 있지 않다."""


class NotAnOriginal(Exception):
    """게시판이 원본 대신 편집 도구가 만든 부속 파일을 올렸다. 다시 받아도 같다."""


@dataclass(frozen=True)
class Container:
    """원본으로 받아들이는 형식 하나. 게시판이 밝힌 확장자는 근거가 아니라 대조 대상이다."""

    name: str
    signature: bytes
    suffixes: frozenset[str]
    # 서명이 같은 다른 형식과 가르는 표식. 비어 있으면 서명만으로 판정한다.
    marker: bytes = b""

    def matches(self, body: bytes) -> bool:
        if not body.startswith(self.signature):
            return False
        return not self.marker or self.marker in body[:MARKER_WINDOW]


# 실측으로 확인한 컨테이너만 둔다. `.xls`는 OLE2와 SpreadsheetML 둘 다로 올라온다.
CONTAINERS: tuple[Container, ...] = (
    Container("ole2", bytes.fromhex("d0cf11e0a1b11ae1"), frozenset({".xls", ".hwp"})),
    Container("ooxml", bytes.fromhex("504b0304"), frozenset({".xlsx", ".xlsm", ".hwpx"})),
    Container("pdf", b"%PDF-", frozenset({".pdf"})),
    Container(
        "spreadsheetml",
        b"<?xml",
        frozenset({".xls", ".xlsx"}),
        b"urn:schemas-microsoft-com:office:spreadsheet",
    ),
    # 한글 XML. 실측(2026-09-14 부산 동구): `.hwp`·`.hwpx` 이름으로 올라오지만 내용은
    # BOM 뒤에 `<HWPML`로 시작하는 XML이다. 이름이 밝힌 확장자와 다르다고 버리지 않는다.
    Container("hwpml", b"<?xml", frozenset({".hwp", ".hwpx"}), b"<HWPML"),
    Container("zip", bytes.fromhex("504b0304"), frozenset({".zip"})),
    # 집행내역을 표가 아니라 스캔본으로 공개하는 게시판이 있다. 용산 실측(2026-09-14):
    # 2026년 게시글 10건이 `…집행내역001.jpg` 모양의 이미지였다(JPEG 7·PNG 3).
    # 표를 읽는 일은 이 이슈의 범위 밖이고, 여기서는 받은 형식을 그대로 센다.
    Container("jpeg", bytes.fromhex("ffd8ff"), frozenset({".jpg", ".jpeg"})),
    Container("png", bytes.fromhex("89504e470d0a1a0a"), frozenset({".png"})),
)
# UTF-8 바이트 순서 표시. 내용의 일부가 아니라 인코딩 표시다.
BOM = b"\xef\xbb\xbf"
# 한글 문서 묶음이 스스로 밝히는 매체 유형. 압축 안의 `mimetype` 항목에 있다.
HWPX_MEDIA_TYPE = b"application/hwp+zip"
# 저장 이름에 쓸 수 있는 확장자의 모양. 게시판이 준 이름을 경로로 그대로 쓰지 않는다.
SUFFIX = re.compile(r"\.[a-z0-9]{1,8}")
# 집행내역을 첨부 대신 HTML 표로 내는 게시판의 원본 이름. 받은 응답 전체를 그대로 둔다.
HTML_SUFFIX = ".html"


def is_identifier(value: str) -> bool:
    """주소와 경로에 그대로 쓸 수 있는 식별자인지. 게시판이 준 값을 그대로 믿지 않는다."""
    return bool(value) and value.isascii() and value.isalnum()


@dataclass(frozen=True)
class Attachment:
    """게시글 하나에 달린 원본 첨부. 아직 내려받기 전의 참조다."""

    post_id: str
    file_id: str
    # 게시판이 밝힌 형식. 저장 전에 매직 바이트와 대조한다.
    suffix: str
    url: str
    # 원본의 출처로 남길 게시글 주소.
    page_url: str
    # 이 첨부를 받을 때 함께 보낼 Referer. 비어 있으면 보내지 않는다.
    # 중랑 실측(2026-09-14): Referer 없이 부르면 200과 함께 1,052바이트 오류 화면이 온다.
    # 일반 브라우저가 보내는 헤더를 그대로 붙이는 것이므로 차단 우회가 아니다.
    referer: str = ""

    def __post_init__(self) -> None:
        if not (is_identifier(self.post_id) and is_identifier(self.file_id)):
            raise UnreadableBoard("board supplied an unusable attachment identifier")
        if self.suffix and not SUFFIX.fullmatch(self.suffix):
            raise UnreadableBoard("board supplied an unusable attachment extension")

    @property
    def name(self) -> str:
        """저장 이름. 게시판이 준 파일명은 경로로 쓰지 않는다."""
        return f"{self.post_id}-{self.file_id}{self.suffix}"


def html_original(post_id: str, url: str, skipped: bool) -> tuple[Attachment, ...]:
    """HTML 표 게시글의 원본 참조 하나. 받은 쪽 주소가 곧 출처다. 넘길 게시글이면 없다.

    집행내역을 HTML 표로 내는 게시판이 모두 같은 참조를 만든다(ADR-0008). 도시마다 따로
    두면 저장 이름과 출처 주소가 도시별로 갈릴 수 있어 여기 한 자리에 둔다.
    """
    return () if skipped else (Attachment(post_id, "1", HTML_SUFFIX, url, url),)


@dataclass(frozen=True)
class Posting:
    """게시글 하나와 거기 달린 원본 첨부 전부. 수집 기록의 단위다.

    이미 수집을 마친 게시글도 목록에 실린 값만 담아 나온다. 그때 `attachments`는 비어 있고
    스크래퍼는 본문을 열지 않는다. 무엇을 다시 받을지는 수집이 자기 기록으로 정한다.
    """

    post_id: str
    attachments: tuple[Attachment, ...]
    # 목록이 밝힌 게시일·제목·작성 부서. 지출 기간은 제목에만 있어 대상 선별이 이 값을 쓰고,
    # 부서는 원본 표에 부서 열이 없을 때 쓴다. 목록 구조를 읽지 않는 스크래퍼는 채우지 않는다.
    posted: date | None = None
    title: str = ""
    department: str = ""
    # 하루치 집행내역을 날짜로 여는 게시판(울산 시청·동구)이 상세 키로 밝힌 집행일. 그 원본의
    # 표에는 집행일 열이 없어 레코드의 집행일과 대상 기간이 이 값을 쓴다([ADR-0008](
    # ../../docs/adr/0008-declare-html-table-mappings.md)).
    spent_on: date | None = None


# 본문을 열지 않고 넘길 게시글인지 묻는다. 이미 수집을 마쳤거나 이번 수집의 기간 밖이면 참이다.
# 게시일을 함께 묻는 것은 기간 밖 게시글의 본문까지 여는 일을 막기 위해서다.
Skipped = Callable[[str, date | None], bool]


class BoardScraper(Protocol):
    """게시판 하나를 훑어 게시글과 원본 첨부의 참조만 낸다. 저장과 형식 판정은 하지 않는다."""

    # 그 게시판에서 실측한 첨부 확장자. 수집이 이 선언과 대조한다.
    published_suffixes: frozenset[str]

    def __init__(self, board: "Board", transport: Transport) -> None: ...

    def postings(self, skipped: Skipped) -> Iterator[Posting]: ...


@runtime_checkable
class VerifiesOriginal(Protocol):
    """받은 것이 원본이 맞는지 내용으로 가리는 게시판.

    화면 자체가 원본인 게시판은 매직 바이트가 없어 `container_of`만으로는 제공자
    오류 화면과 집행 표를 가르지 못한다. 그런 게시판이 실측한 표식을 여기서 대조한다.
    """

    def verify(self, body: bytes) -> None: ...


@runtime_checkable
class FiltersRows(Protocol):
    """업무추진비 집행기관이 아닌 줄을 섞어 싣는 게시판.

    그런 게시판만 이 칸을 가진다(서울 시청·중구·강남 실측). 무엇을 뺐는지 수집이
    장부에 싣도록 스크래퍼가 스스로 센다.
    """

    filtered: int


@runtime_checkable
class ResumesListing(Protocol):
    """목록을 쪽 단위로 이어 훑을 수 있는 게시판(#154).

    중랑 목록 853쪽은 원본을 함께 받는 실행에서 한 번도 끝까지 가지 못했다. 끊길 때마다
    1쪽부터 다시 훑지 않도록 수집이 앞선 실행이 끝낸 쪽을 알려 준다. 게시판은 한 쪽의 게시글을
    호출자가 모두 처리한 뒤, 다음 쪽을 묻기 전에 `settle`로 그 다음 쪽 번호를 알린다. 기록은
    수집이 한다 — 스크래퍼는 저장하지 않는다.
    """

    def resume(self, page: int, filtered: int, settle: Callable[[int], None]) -> None: ...


class Document(HTMLParser):
    """앵커의 주소·표시 문자열과 본문 텍스트만 남긴다. 요소 구조에는 기대지 않는다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._text: list[str] = []
        self._open: list[tuple[str, list[str]]] = []

    @property
    def text(self) -> str:
        return " ".join("".join(self._text).split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._open.append((dict(attrs).get("href") or "", []))

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._open:
            href, parts = self._open.pop()
            self.links.append((href, " ".join("".join(parts).split())))

    def handle_data(self, data: str) -> None:
        self._text.append(data)
        for _, parts in self._open:
            parts.append(data)


def default_transport() -> HttpTransport:
    """게시판 요청 경계. 원본 첨부의 상한과 기관에 두는 요청 간격을 여기서만 정한다.

    쿠키를 이어 든다. 진입 화면이 세션을 내준 뒤에야 목록을 주는 게시판이 있어(광산구 실측)
    그 게시판이 쿠키 없이는 훑히지 않는다. 다른 게시판은 쿠키를 요구하지 않으므로 영향이 없다.
    """
    return HttpTransport(
        timeout=REQUEST_TIMEOUT,
        limit=MAX_RESPONSE_BYTES,
        interval=REQUEST_INTERVAL,
        attempts=REQUEST_ATTEMPTS,
        backoff=REQUEST_BACKOFF,
        session=True,
        host_intervals=HOST_INTERVALS,
        host_timeouts=HOST_TIMEOUTS,
    )


def read(body: bytes, encoding: str) -> Document:
    return parse(body, encoding, Document())


def parse[T: Document](body: bytes, encoding: str, document: T) -> T:
    """게시판별 해석기로 응답을 읽는다. 인코딩 계약은 `read`와 같다."""
    try:
        text = body.decode(encoding)
    except UnicodeDecodeError:
        raise UnreadableBoard("board response is not in the measured encoding") from None
    document.feed(text)
    document.close()
    return document


def endpoint(url: str) -> tuple[str, dict[str, str]]:
    """주소를 요청 경계가 쓰는 기준 주소와 조회 조건으로 나눈다."""
    parts = urllib.parse.urlsplit(url)
    return (
        urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
        dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True)),
    )


def address(url: str, params: Mapping[str, str]) -> str:
    """요청 경계가 실제로 보낼 주소. 기록에 남기는 주소도 이 함수로 만든다."""
    return f"{url}?{query(params)}"


def request(transport: Transport, url: str, params: Mapping[str, str], referer: str = "") -> bytes:
    """게시판 응답 하나를 받는다. 제공자 오류는 안전한 예외로만 알린다."""
    headers = {**HEADERS, "Referer": referer} if referer else HEADERS
    try:
        body = transport.fetch(url, params, headers)
    except ResourceGone:
        raise OriginalGone("board links a file the organization no longer serves") from None
    except Exception:
        raise BoardUnavailable("board request failed") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise OversizeOriginal("board response exceeds the size that can be read whole")
    return body


def suffix_of(filename: str) -> str:
    """게시판이 밝힌 형식. 받아들일지는 수집이 스크래퍼의 선언과 대조해 정한다."""
    return PurePosixPath(filename.strip()).suffix.lower()


# 기관이 DRM으로 잠근 파일의 머리. 이름은 `.xlsx`·`.hwpx`인데 내용이 다르다. 실측 2026-09-14:
# 부산시청은 Fasoo(`\x9b DRMONE  This Document is encrypted and protected by Fasoo DRM`),
# 부산 북구는 Softcamp(`SCDSA004`)를 쓴다.
# 잠긴 파일과 실측하지 않은 형식은 다르다. 형식은 선언하면 읽히고, 이것은 풀어야 읽힌다.
DRM_SIGNATURES = (b"\x9b DRMONE", b"SCDSA")
# 편집 도구가 문서 옆에 만드는 부속 파일. 실측(2026-09-14 부산진구 3966536): 668바이트이고
# UTF-16LE로 `HCellShareFileInfo`로 시작한다. 한셀이 공동 편집에 쓰는 잠금 정보이며 집행 표가
# 아니다. 형식을 선언해도 표가 생기지 않으므로 실측하지 않은 형식과 같은 자리에 두지 않는다.
SHARE_INFO = "ShareFileInfo"
# 문서 묶음임을 알리는 항목. OOXML은 `[Content_Types].xml`이나 부문 폴더로, HWPX는
# `Contents/`의 본문으로 자신을 밝힌다(양천 `.hwpx` 실측: mimetype·version.xml·
# Contents/header.xml·META-INF/container.xml). 이것이 없는 묶음만 일반 ZIP이다.
PACKAGE_FOLDERS = ("word/", "xl/", "ppt/", "Contents/")
PACKAGE_ENTRY = "[Content_Types].xml"


def is_placeholder(body: bytes) -> bool:
    """원본 대신 올라온 편집 도구의 부속 파일인지. 이름이 아니라 내용으로 가른다."""
    return SHARE_INFO in body[:64].decode("utf-16-le", errors="ignore")


def is_protected(body: bytes) -> bool:
    """기관이 DRM으로 잠근 첨부인지. 이름이 아니라 내용으로 가른다."""
    return body.startswith(DRM_SIGNATURES)


def _is_document_package(names: set[str]) -> bool:
    return PACKAGE_ENTRY in names or any(name.startswith(PACKAGE_FOLDERS) for name in names)


def container_of(body: bytes, *, html: bool = False) -> str:
    """매직 바이트로 컨테이너를 판정한다. 게시판이 밝힌 확장자는 믿지 않는다.

    실측(2026-09-11): 이 게시판은 OOXML 파일에 `.xls` 이름을 붙여 올리기도 한다(seq 963·857).
    이름이 어긋난다고 버리면 실제 원본을 잃으므로, 판정한 컨테이너를 출처에 기록해 넘긴다.

    `html`은 화면 자체가 원본인 게시판에서만 켠다(`.html`을 실측 확장자로 선언한 게시판).
    첨부를 내려받는 게시판에서 켜면 Referer 없는 중랑 첨부처럼 200으로 오는 오류 화면을
    원본으로 받아들이게 되므로, 기본값은 끈 상태다. HTML 판정 자체는 표를 읽는 쪽과 같은
    `grid.is_html` 하나다(서울 화면 게시판, 울산 HTML 표 게시판 — ADR-0008).
    """
    if not body:
        raise EmptyOriginal("board served an empty attachment")
    if is_protected(body):
        raise ProtectedOriginal("organization serves this original under DRM")
    if is_placeholder(body):
        raise NotAnOriginal("board published an editor side file instead of an original")
    # BOM은 형식이 아니라 인코딩 표시다. XML 계열 원본이 그것 때문에 안 걸리지 않게 뗀다.
    body = body.removeprefix(BOM)
    # A ZIP archive shares the OOXML magic bytes.  Distinguish Office archives
    # by their package entries while retaining the historical fallback for
    # short synthetic OOXML signatures used by older adapters.
    if body.startswith(bytes.fromhex("504b0304")):
        try:
            with zipfile.ZipFile(BytesIO(body)) as archive:
                names = set(archive.namelist())
                # 한글 문서(HWPX)는 ODF·EPUB과 같이 `mimetype`을 맨 앞에 둔다. 묶음인 것은
                # OOXML과 같지만 안을 여는 방법이 달라, 묶음이 스스로 밝힌 매체 유형으로
                # 가른다(부산 북구 실측). 밝히지 않는 묶음은 아래의 부문 폴더로 갈린다.
                declared = archive.read("mimetype") if "mimetype" in names else b""
        except (OSError, zipfile.BadZipFile, KeyError):
            names, declared = set(), b""
        if declared.strip() == HWPX_MEDIA_TYPE:
            return "hwpx"
        if names and not _is_document_package(names):
            return "zip"
    for container in CONTAINERS:
        if container.matches(body):
            return container.name
    if html and is_html(body):
        return "html"
    raise UnsupportedOriginal("response is not an original container")
