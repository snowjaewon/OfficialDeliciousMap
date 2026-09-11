"""게시판 해석의 공통 경계. 기관별 스크래퍼가 여기의 계약만 지키면 수집 규칙을 공유한다."""

import urllib.parse
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Protocol

from deliciousmap.transport import HttpTransport, Transport, query

if TYPE_CHECKING:  # 레지스트리가 스크래퍼를 선언하므로 실행 시점에 되짚어 부르지 않는다.
    from deliciousmap.registry.models import Board

# 한 번에 통째로 읽어 둘 수 있는 응답의 상한. 업무추진비 첨부는 실측 표본에서 수십~수백 KB였고
# 이 값은 그보다 두 자리 여유가 있다. 넘는 응답은 잘라 쓰지 않고 받지 못한 것으로 알린다.
# 정제 산출물의 20MB 상한(ADR-0001)과는 다른 이유로 정한 별개의 값이다.
MAX_RESPONSE_BYTES = 20_000_000
# 한 기관에 연달아 요청할 때 두는 간격(초). 게시판 전량 수집이 몰아치지 않게 한다.
REQUEST_INTERVAL = 0.5
# 원본으로 받아들이는 컨테이너의 매직 바이트와 그 컨테이너를 쓰는 확장자.
# 게시판이 밝힌 확장자는 근거가 아니라 대조 대상이다.
CONTAINERS: tuple[tuple[bytes, frozenset[str]], ...] = (
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", frozenset({".xls", ".hwp"})),
    (b"PK\x03\x04", frozenset({".xlsx", ".hwpx"})),
    (b"%PDF-", frozenset({".pdf"})),
)
# 수집 주체를 밝힌다. 브라우저를 가장하지 않는다.
USER_AGENT = "OfficialDeliciousMap/0.1 (+https://github.com/snowjaewon/OfficialDeliciousMap)"
HEADERS = {"User-Agent": USER_AGENT}


class UnsupportedOriginal(Exception):
    """게시판이 원본 대신 다른 것을 주었거나, 그 기관에서 실측하지 않은 형식이다."""


class BoardUnavailable(Exception):
    """게시판에 닿지 못했다. 서비스 응답·오류 원문은 남기지 않는다."""


class UnreadableBoard(Exception):
    """응답이 실측한 구조와 다르거나 온전히 받지 못했다. 형식 문제와 구별한다."""


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

    @property
    def name(self) -> str:
        """저장 이름. 게시판이 준 파일명은 경로로 쓰지 않는다."""
        return f"{self.post_id}-{self.file_id}{self.suffix}"


class BoardScraper(Protocol):
    """게시판 하나를 훑어 원본 첨부의 참조만 낸다. 저장과 형식 판정은 하지 않는다."""

    def __init__(self, board: "Board", transport: Transport) -> None: ...

    def attachments(self) -> Iterator[Attachment]: ...


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
    return HttpTransport(limit=MAX_RESPONSE_BYTES, interval=REQUEST_INTERVAL)


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
    except Exception:
        raise BoardUnavailable("board request failed") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise UnreadableBoard("board response exceeds the size that can be read whole")
    return body


def suffix_of(filename: str, published: frozenset[str]) -> str:
    """게시판이 밝힌 형식. 그 기관에서 실측한 형식만 원본으로 받는다."""
    suffix = PurePosixPath(filename.strip()).suffix.lower()
    if suffix in published:
        return suffix
    raise UnsupportedOriginal("attachment format was not measured for this board")


def require_original(body: bytes, suffix: str) -> None:
    """매직 바이트로 컨테이너를 판정하고 게시판이 밝힌 확장자와 대조한다."""
    for signature, suffixes in CONTAINERS:
        if body.startswith(signature):
            if suffix in suffixes:
                return
            raise UnsupportedOriginal("attachment contradicts its declared format")
    raise UnsupportedOriginal("response is not an original container")
