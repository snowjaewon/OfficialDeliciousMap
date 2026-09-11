"""게시판 해석의 공통 경계. 기관별 스크래퍼가 여기의 계약만 지키면 수집 규칙을 공유한다."""

import re
import urllib.parse
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Protocol

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


class OriginalGone(Exception):
    """게시판이 링크한 원본이 기관 쪽에 없다. 다시 요청해도 달라지지 않는다."""


class EmptyOriginal(Exception):
    """게시판이 내용 없는 첨부를 200으로 주었다. 받을 것이 없다는 점에서 유실과 같다."""


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
    Container("ooxml", bytes.fromhex("504b0304"), frozenset({".xlsx", ".hwpx"})),
    Container("pdf", b"%PDF-", frozenset({".pdf"})),
    Container(
        "spreadsheetml",
        b"<?xml",
        frozenset({".xls", ".xlsx"}),
        b"urn:schemas-microsoft-com:office:spreadsheet",
    ),
)
# 저장 이름에 쓸 수 있는 확장자의 모양. 게시판이 준 이름을 경로로 그대로 쓰지 않는다.
SUFFIX = re.compile(r"\.[a-z0-9]{1,8}")


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

    def __post_init__(self) -> None:
        if not (is_identifier(self.post_id) and is_identifier(self.file_id)):
            raise UnreadableBoard("board supplied an unusable attachment identifier")
        if self.suffix and not SUFFIX.fullmatch(self.suffix):
            raise UnreadableBoard("board supplied an unusable attachment extension")

    @property
    def name(self) -> str:
        """저장 이름. 게시판이 준 파일명은 경로로 쓰지 않는다."""
        return f"{self.post_id}-{self.file_id}{self.suffix}"


@dataclass(frozen=True)
class Posting:
    """게시글 하나와 거기 달린 원본 첨부 전부. 수집 기록의 단위다."""

    post_id: str
    attachments: tuple[Attachment, ...]


# 이미 수집을 마친 게시글인지 묻는다. 참이면 스크래퍼는 본문을 열지 않는다.
Collected = Callable[[str], bool]


class BoardScraper(Protocol):
    """게시판 하나를 훑어 게시글과 원본 첨부의 참조만 낸다. 저장과 형식 판정은 하지 않는다."""

    # 그 게시판에서 실측한 첨부 확장자. 수집이 이 선언과 대조한다.
    published_suffixes: frozenset[str]

    def __init__(self, board: "Board", transport: Transport) -> None: ...

    def postings(self, collected: Collected) -> Iterator[Posting]: ...


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


def default_transport() -> Transport:
    """게시판 요청 경계. 원본 첨부의 상한과 기관에 두는 요청 간격을 여기서만 정한다."""
    return HttpTransport(
        timeout=REQUEST_TIMEOUT,
        limit=MAX_RESPONSE_BYTES,
        interval=REQUEST_INTERVAL,
        attempts=REQUEST_ATTEMPTS,
        backoff=REQUEST_BACKOFF,
    )


def read(body: bytes, encoding: str) -> Document:
    try:
        text = body.decode(encoding)
    except UnicodeDecodeError:
        raise UnreadableBoard("board response is not in the measured encoding") from None
    document = Document()
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


def request(transport: Transport, url: str, params: Mapping[str, str]) -> bytes:
    """게시판 응답 하나를 받는다. 제공자 오류는 안전한 예외로만 알린다."""
    try:
        body = transport.fetch(url, params, HEADERS)
    except ResourceGone:
        raise OriginalGone("board links a file the organization no longer serves") from None
    except Exception:
        raise BoardUnavailable("board request failed") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise UnreadableBoard("board response exceeds the size that can be read whole")
    return body


def suffix_of(filename: str) -> str:
    """게시판이 밝힌 형식. 받아들일지는 수집이 스크래퍼의 선언과 대조해 정한다."""
    return PurePosixPath(filename.strip()).suffix.lower()


def require_original(body: bytes, suffix: str) -> None:
    """매직 바이트로 컨테이너를 판정하고 게시판이 밝힌 확장자와 대조한다."""
    if not body:
        raise EmptyOriginal("board served an empty attachment")
    for container in CONTAINERS:
        if container.matches(body):
            if suffix in container.suffixes:
                return
            raise UnsupportedOriginal("attachment contradicts its declared format")
    raise UnsupportedOriginal("response is not an original container")
