"""게시판 목록 해석. 표·쪽 넘김·게시일처럼 계열을 가리지 않는 것만 둔다.

기관마다 프레임워크가 달라도 목록은 거의 언제나 `<tr>`과 `<a>`다. 그 둘을 읽는 방법을
한 자리에 두어, 도시 스크래퍼는 그 도시에서 실측한 차이만 적는다. 무엇을 첨부로 볼지,
어떤 조회 조건을 붙일지처럼 기관마다 다른 것은 여기 두지 않는다.

지금 이것을 쓰는 것은 부산의 다섯 스크래퍼다. 울산은 같은 모양의 해석기를 자기 모듈에
그대로 두고 있다 — #145가 그 구조 위에 HTML 표 수집을 얹은 직후라, 여기로 옮기면 이미
산출물을 낸 도시의 해석이 조용히 달라질 수 있다(이 모듈은 `<script>` 글자를 빼고 머리글
줄을 표시하는 점이 다르다). 울산 원본으로 그 차이를 확인할 수 있는 쪽에서 옮긴다.
"""

import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser

from deliciousmap import boards

ENCODING = "utf-8"
# 게시일 표기. 실측한 구분자는 `-`·`.`·`/`이고 구분자 둘레의 공백은 기관마다 다르다
# (울산 `2026-09-02`, 부산 rfc3 `2026. 09. 02`). 공백은 표기 차이일 뿐이라 여기서 함께 읽는다.
DATE_RE = re.compile(r"(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})")
# 울산시청의 옛 행은 두 자리 연도로 적는다(`20. 11. 5`). 그 게시판이 2000년대 기록이라
# 세기를 상수로 둔다. 네 자리가 언제나 먼저 이기도록 DATE_RE와 나누어 둔다 — `2020`의
# 뒤 두 자리를 `20`으로 읽지 않기 위해서다.
SHORT_DATE_RE = re.compile(r"(?<!\d)(\d{2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})(?!\d)")
PAGE_RE = re.compile(r"(?:페이지|page)\s*[:：]?\s*\d+\s*/\s*([\d,]+)", re.I)
EXTENSION_RE = re.compile(r"\.([A-Za-z0-9]{1,8})(?![A-Za-z0-9])")
NAMED_FORMAT_RE = re.compile(r"\b(zip|pdf|xlsx?|xlsm|hwp|hwpx)\s*(?:파일|다운로드)", re.I)
PAGINATION_KEYS = frozenset({"cpage", "curPage", "page", "pageIndex", "startPage"})


@dataclass(frozen=True)
class Link:
    href: str
    text: str
    title: str
    onclick: str


@dataclass(frozen=True)
class Cell:
    text: str
    classes: frozenset[str]
    links: tuple[Link, ...]


@dataclass(frozen=True)
class Row:
    cells: tuple[Cell, ...]
    # 머리글 줄인지. `<th>`만으로 이루어진 줄은 값이 아니라 열 이름이다. 표 자체가 자료인
    # 게시판(기장군)은 게시글 링크로 걸러 낼 수가 없어 이 표시로 가른다.
    header: bool = False

    @property
    def text(self) -> str:
        return " ".join(cell.text for cell in self.cells)

    @property
    def links(self) -> tuple[Link, ...]:
        return tuple(link for cell in self.cells for link in cell.links)


class TableParser(HTMLParser):
    """표의 칸과 앵커만 남긴다. 외부 DOM 없이 목록 구조를 읽기 위한 최소한의 해석기다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[Row] = []
        self.links: list[Link] = []
        self._cells: list[list[tuple[str, frozenset[str], list[Link], list[str]]]] = []
        self._cell: list[str] | None = None
        self._cell_classes: frozenset[str] = frozenset()
        self._cell_links: list[Link] = []
        self._link_attrs: dict[str, str] | None = None
        self._link_text: list[str] = []
        self._pagination = False
        self.pagination_pages: list[int] = []
        self._tr = False
        self._text: list[str] = []
        # `<script>`·`<style>` 안의 글자는 화면에 나오지 않는다. 칸 글자로 세면 제목이 두 번
        # 나오거나(동래구 `console.log('제목')`) 없는 값이 생긴다.
        self._mute = 0

    @property
    def text(self) -> str:
        return " ".join(" ".join(self._text).split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._mute += 1
        elif tag == "ul" and "pagination" in (dict(attrs).get("class") or "").split():
            self._pagination = True
        elif tag == "tr" and not self._tr:
            self._tr = True
            self._cells = [[]]
        elif tag in {"td", "th"} and self._tr and self._cell is None:
            self._cell = []
            self._cell_classes = frozenset((dict(attrs).get("class") or "").split())
            self._cell_links = []
            self._cells[-1].append((tag, self._cell_classes, self._cell_links, self._cell))
        elif tag == "a":
            raw = dict(attrs)
            self._link_attrs = {
                "href": raw.get("href") or "",
                "title": raw.get("title") or "",
                "onclick": raw.get("onclick") or "",
            }
            self._link_text = []
        elif tag == "img":
            alt = dict(attrs).get("alt") or ""
            if alt and self._cell is not None:
                self._cell.append(alt)
            if alt and self._link_attrs is not None:
                self._link_text.append(alt)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._mute = max(0, self._mute - 1)
        elif tag == "a" and self._link_attrs is not None:
            link = Link(
                self._link_attrs["href"],
                " ".join(" ".join(self._link_text).split()),
                self._link_attrs["title"],
                self._link_attrs["onclick"],
            )
            self.links.append(link)
            if self._pagination:
                self._remember_page(link)
            if self._cell is not None:
                self._cell_links.append(link)
            self._link_attrs = None
            self._link_text = []
        elif tag in {"td", "th"} and self._cell is not None:
            self._cell = None
            self._cell_links = []
        elif tag == "tr" and self._tr:
            cells: list[Cell] = []
            tags: list[str] = []
            for name, classes, links, parts in self._cells[-1]:
                cells.append(Cell(" ".join(" ".join(parts).split()), classes, tuple(links)))
                tags.append(name)
            self.rows.append(Row(tuple(cells), bool(tags) and set(tags) == {"th"}))
            self._cells = []
            self._tr = False
        elif tag == "ul" and self._pagination:
            self._pagination = False

    def _remember_page(self, link: Link) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(link.href).query)
        for key in PAGINATION_KEYS:
            value = query.get(key, [""])[0]
            if value.isdigit():
                self.pagination_pages.append(int(value))
        if not query and "현재페이지" in link.title and link.text.strip().isdigit():
            self.pagination_pages.append(int(link.text.strip()))

    def handle_data(self, data: str) -> None:
        if self._mute:
            return
        self._text.append(data)
        if self._cell is not None:
            self._cell.append(data)
        if self._link_attrs is not None:
            self._link_text.append(data)

    def close(self) -> None:
        super().close()
        if self._tr:
            raise boards.UnreadableBoard("board listing row never closed")


def parse(body: bytes, encoding: str = ENCODING, parser: TableParser | None = None) -> TableParser:
    """목록을 읽는다. 표시 방식만 다른 게시판은 해석기를 넘겨 같은 계약으로 읽는다."""
    parser = TableParser() if parser is None else parser
    try:
        parser.feed(body.decode(encoding))
        parser.close()
    except UnicodeDecodeError:
        raise boards.UnreadableBoard("board response is not in the measured encoding") from None
    return parser


def posted(text: str) -> date:
    """행이 밝힌 게시일. 읽지 못하면 짐작하지 않고 읽을 수 없는 목록으로 알린다."""
    found = DATE_RE.search(text)
    if found is not None:
        values = found.groups()
    else:
        short = SHORT_DATE_RE.search(text)
        if short is None:
            raise boards.UnreadableBoard("board listing row does not declare its posting date")
        values = (str(2000 + int(short.group(1))), short.group(2), short.group(3))
    try:
        return date(*(int(part) for part in values))
    except ValueError:
        raise boards.UnreadableBoard(
            "board listing row declares an impossible posting date"
        ) from None


def posted_of(row: Row) -> date:
    """행이 밝힌 게시일. 날짜만 담긴 칸을 먼저 보고, 그런 칸이 없을 때만 줄 전체를 본다.

    rfc3 계열은 열 차례가 기관마다 다르고(실측 2026-09-14, 아홉 게시판에 일곱 가지) 제목 칸이
    게시일 칸보다 앞에 온다. 줄 전체를 훑으면 제목에 적힌 날짜를 게시일로 읽는다.
    """
    for cell in row.cells:
        if DATE_RE.fullmatch(cell.text) or SHORT_DATE_RE.fullmatch(cell.text):
            return posted(cell.text)
    return posted(row.text)


def has_date(text: str) -> bool:
    return DATE_RE.search(text) is not None or SHORT_DATE_RE.search(text) is not None


def page_count(parser: TableParser, *, link_keys: Iterable[str] = ()) -> int:
    """목록이 밝힌 마지막 쪽. 밝히지 않으면 쪽 수를 지어내지 않고 읽을 수 없다고 알린다."""
    found = PAGE_RE.search(parser.text)
    if found is not None:
        return int(found.group(1).replace(",", ""))
    found = re.search(r"전체\s*페이지\s+(\d+)", parser.text, re.I)
    if found is not None:
        return int(found.group(1))
    candidates: list[int] = []
    for link in parser.links:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(link.href).query)
        for key in link_keys:
            value = query.get(key, [""])[0]
            if value.isdigit():
                candidates.append(int(value))
    candidates.extend(parser.pagination_pages)
    if not candidates:
        raise boards.UnreadableBoard("board listing does not declare its page count")
    return max(candidates)


def suffix(link: Link, published: frozenset[str]) -> str:
    """링크가 밝힌 첨부 형식. 주소에서 주운 확장자는 실측한 것일 때만 받아들인다."""
    for value in (link.text, link.title, link.onclick):
        match = EXTENSION_RE.search(value)
        if match is not None:
            return f".{match.group(1).lower()}"
        named = NAMED_FORMAT_RE.search(value)
        if named is not None:
            return f".{named.group(1).lower()}"
    found = re.search(r"\.([A-Za-z0-9]{1,8})(?:$|[?&#])", link.href)
    found_suffix = f".{found.group(1).lower()}" if found else ""
    return found_suffix if found_suffix in published else ""


def article_link(row: Row, needle: str, parameter: str) -> tuple[str, str] | None:
    """행이 가리키는 게시글. 주소 경로에 `needle`이 있고 `parameter`가 식별자여야 한다."""
    for link in row.links:
        if needle not in urllib.parse.urlsplit(link.href).path:
            continue
        value = urllib.parse.parse_qs(urllib.parse.urlsplit(link.href).query).get(parameter, [""])[
            0
        ]
        if boards.is_identifier(value):
            return value, link.href
    return None


def is_row_number(text: str) -> bool:
    """번호 칸의 글자인지. 번호 칸까지 게시글로 링크하는 목록이 있어 제목과 가른다."""
    return text.strip().isdigit()


def title_of(row: Row, href: str) -> str:
    """행이 가리키는 게시글의 제목.

    같은 게시글 주소를 가진 링크가 여럿이면 행 번호가 아닌 쪽이 제목이다(울산 동구 목록,
    2026-09-14 실측). 번호 칸까지 같은 주소로 걸어 두는 게시판이 있어서다.
    """
    texts = [link.text for link in row.links if link.href == href]
    return next(
        (text for text in texts if not is_row_number(text)),
        texts[0] if texts else "",
    )
