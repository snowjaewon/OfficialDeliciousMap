"""여러 도시가 함께 쓰는 게시판 목록 해석. 표·쪽 넘김·게시일처럼 계열을 가리지 않는 것만 둔다.

기관마다 프레임워크가 달라도 목록은 거의 언제나 `<tr>`과 `<a>`다. 그 둘을 읽는 방법을
한 자리에 두어, 도시 스크래퍼는 그 도시에서 실측한 차이만 적는다. 무엇을 첨부로 볼지,
어떤 조회 조건을 붙일지처럼 기관마다 다른 것은 여기 두지 않는다.
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

    @property
    def text(self) -> str:
        return " ".join(" ".join(self._text).split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "ul" and "pagination" in (dict(attrs).get("class") or "").split():
            self._pagination = True
        elif tag == "tr" and not self._tr:
            self._tr = True
            self._cells = [[]]
        elif tag in {"td", "th"} and self._tr and self._cell is None:
            self._cell = []
            self._cell_classes = frozenset((dict(attrs).get("class") or "").split())
            self._cell_links = []
            self._cells[-1].append(("", self._cell_classes, self._cell_links, self._cell))
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
        if tag == "a" and self._link_attrs is not None:
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
            for _, classes, links, parts in self._cells[-1]:
                cells.append(Cell(" ".join(" ".join(parts).split()), classes, tuple(links)))
            self.rows.append(Row(tuple(cells)))
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
        self._text.append(data)
        if self._cell is not None:
            self._cell.append(data)
        if self._link_attrs is not None:
            self._link_text.append(data)

    def close(self) -> None:
        super().close()
        if self._tr:
            raise boards.UnreadableBoard("board listing row never closed")


def parse(body: bytes, encoding: str = ENCODING) -> TableParser:
    parser = TableParser()
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


def title_of(row: Row, href: str) -> str:
    for link in row.links:
        if link.href == href:
            return link.text
    return ""
