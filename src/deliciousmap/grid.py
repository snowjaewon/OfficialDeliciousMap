"""원본을 표 격자로 읽는다. 형식 판별은 확장자가 아니라 파일 앞 바이트로 한다."""

import io
import re
import warnings
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from xml.etree import ElementTree

import openpyxl
import pdfplumber
import xlrd
from pdfplumber.table import Table as RuledTable

# 셀 값. 엑셀의 날짜 셀만 datetime이고 숫자는 float, 나머지는 앞뒤 공백을 둔 문자열이다.
Cell = str | float | datetime
# 형식별 읽기가 내는 표 하나. 이름표(시트 이름 또는 나온 쪽), 자르기 전의 행들, 세로 병합이다.
Block = tuple[str, list[tuple[Cell, ...]], tuple["Span", ...]]

OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP = b"PK\x03\x04"
PDF = b"%PDF-"
# 연속 빈 행이 이만큼 이어지면 시트의 끝으로 본다.
MAX_BLANK_RUN = 1_000
# 통합문서 XML의 이름공간. `_transitional`이 Strict를 이 이름공간으로 바꾼 뒤에 읽는다.
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
DOCUMENT = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
WORKBOOK_RELS = "xl/_rels/workbook.xml.rels"
# 괘선 좌표가 소수점 아래에서 어긋나는 것을 견디는 폭(포인트).
RULE_TOLERANCE = 1.0
# ISO/IEC 29500 Strict 이름공간과 같은 뜻의 Transitional 이름공간. 관계 유형은 접두어로 바뀐다.
STRICT_MAIN = b"http://purl.oclc.org/ooxml/spreadsheetml/main"
STRICT_NAMESPACES = (
    (STRICT_MAIN, b"http://schemas.openxmlformats.org/spreadsheetml/2006/main"),
    (
        b"http://purl.oclc.org/ooxml/officeDocument/relationships",
        b"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    ),
    (
        b"http://purl.oclc.org/ooxml/officeDocument/sharedTypes",
        b"http://schemas.openxmlformats.org/officeDocument/2006/sharedTypes",
    ),
    (
        b"http://purl.oclc.org/ooxml/drawingml/main",
        b"http://schemas.openxmlformats.org/drawingml/2006/main",
    ),
)


class UnsupportedFormat(Exception):
    """이번 구현이 읽지 않는 형식(HWP·HWPX·ZIP 묶음 등). 자동으로 LLM에 넘기지 않는다."""


class UnreadableOriginal(Exception):
    """형식은 맞지만 내용을 격자로 옮기지 못했다."""


@dataclass(frozen=True)
class Span:
    """세로 병합이 덮은 이어짐 칸 하나. 값은 `holder` 행의 같은 열에 있다.

    행은 1부터, 열은 0부터 센다. 병합을 읽지 못한 원본은 병합 없이 읽으며, 그때의 결과는
    병합을 몰랐을 때와 같다.
    """

    row: int
    column: int
    holder: int


@dataclass(frozen=True)
class Table:
    """표 하나. `name`은 산출물의 위치 표기, `label`은 원본의 시트 이름이나 나온 쪽이다."""

    name: str
    label: str
    rows: tuple[tuple[Cell, ...], ...]
    # 세로 병합. `rows`에는 이어짐 칸이 빈 값 그대로 들어 있어 헤더 서명이 원본과 같다.
    spans: tuple[Span, ...] = ()

    def cell(self, row: int, column: int) -> Cell:
        """격자에 적힌 그대로. 행은 1부터, 열은 0부터 센다. 없는 칸은 빈 문자열이다."""
        cells = self.rows[row - 1] if 0 < row <= len(self.rows) else ()
        return cells[column] if column < len(cells) else ""

    def value(self, row: int, column: int) -> Cell:
        """원본에 보이는 값. 세로 병합의 이어짐 칸은 병합이 담은 값이고 나머지는 `cell`과 같다."""
        for span in self.spans:
            if span.row == row and span.column == column:
                return self.cell(span.holder, column)
        return self.cell(row, column)


def text(value: Cell) -> str:
    """셀을 사람이 읽는 한 줄 문자열로 옮긴다. 줄바꿈·연속 공백은 공백 하나로 모은다."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return " ".join(value.split())


def read_tables(path: Path) -> tuple[Table, ...]:
    """통합문서는 시트마다, PDF는 괘선으로 나뉜 표마다 표 하나다.

    내용이 없는 시트·표는 표가 아니며 뒤쪽의 빈 칸·빈 행은 잘라 낸다. 위치 표기는
    통합문서가 `sheet1`, PDF가 `table1`이고 `label`이 시트 이름 또는 나온 쪽을 남긴다.
    """
    content = path.read_bytes()
    if content.startswith(OLE2):
        prefix, blocks = "sheet", _legacy(content)
    elif content.startswith(ZIP):
        prefix, blocks = "sheet", _xlsx(content)
    elif content.startswith(PDF):
        prefix, blocks = "table", _pdf(content)
    else:
        raise UnsupportedFormat("not a workbook or PDF")
    tables = []
    for index, (label, rows, spans) in enumerate(blocks, start=1):
        trimmed = _trim(rows)
        if trimmed:
            tables.append(Table(f"{prefix}{index}", label, trimmed, spans))
    return tuple(tables)


def _trim(rows: list[tuple[Cell, ...]]) -> tuple[tuple[Cell, ...], ...]:
    """행 번호가 원본과 같도록 앞쪽 빈 행은 두고 뒤쪽만 자른다."""
    cut = [cells[: max((i + 1 for i, value in enumerate(cells) if text(value)), default=0)]
           for cells in rows]  # fmt: skip
    while cut and not cut[-1]:
        cut.pop()
    return tuple(cut)


def _legacy(content: bytes) -> list[Block]:
    try:
        # 병합은 서식 기록에 들어 있어 그것까지 읽어야 이어짐 칸을 알 수 있다.
        book = xlrd.open_workbook(file_contents=content, formatting_info=True)
    except xlrd.XLRDError:
        # HWP 5.0도 같은 OLE2 컨테이너를 쓴다. 엑셀 통합문서가 없으면 지원하지 않는 형식이다.
        raise UnsupportedFormat("OLE2 container without an Excel workbook") from None
    except Exception:
        raise UnreadableOriginal("workbook could not be read") from None
    return [
        (
            sheet.name,
            [
                tuple(_cell(sheet, row, column, book.datemode) for column in range(sheet.ncols))
                for row in range(sheet.nrows)
            ],
            _legacy_spans(sheet),
        )
        for sheet in book.sheets()
    ]


def _legacy_spans(sheet: xlrd.sheet.Sheet) -> tuple[Span, ...]:
    """병합 범위는 반쯤 열린 구간이다. `(16, 18, 1, 2)`는 17~18행의 둘째 열 하나를 덮는다."""
    return tuple(
        Span(row + 1, column, top + 1)
        for top, bottom, left, right in sheet.merged_cells
        for row in range(top + 1, bottom)
        for column in range(left, right)
    )


def _xlsx(content: bytes) -> list[Block]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        raise UnsupportedFormat("broken ZIP container") from None
    if "xl/workbook.xml" not in names:
        # HWPX·원본 묶음 ZIP 등 엑셀이 아닌 ZIP 컨테이너.
        raise UnsupportedFormat("ZIP container without an Excel workbook")
    data = _transitional(content)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise UnreadableOriginal("workbook could not be read") from None
    if not book.worksheets:
        # 시트를 하나도 못 읽은 통합문서를 빈 원본으로 보고하지 않는다.
        raise UnreadableOriginal("workbook has no readable worksheet")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            spans = _xlsx_spans(archive)
        blocks: list[Block] = []
        for sheet in book.worksheets:
            rows: list[tuple[Cell, ...]] = []
            blank_run = 0
            for values in sheet.iter_rows(values_only=True):
                cells = tuple(_xlsx_cell(value) for value in values)
                blank_run = 0 if any(text(value) for value in cells) else blank_run + 1
                # 서식만 남은 거대한 범위를 끝까지 따라가지 않는다.
                if blank_run > MAX_BLANK_RUN:
                    break
                rows.append(cells)
            blocks.append((sheet.title, rows, spans.get(sheet.title, ())))
        book.close()
    except Exception:
        raise UnreadableOriginal("workbook could not be read") from None
    return blocks


def _xlsx_spans(archive: zipfile.ZipFile) -> dict[str, tuple[Span, ...]]:
    """시트 이름마다 세로 병합. openpyxl은 읽기 전용으로 열면 병합을 싣지 않는다.

    openpyxl이 이미 연 통합문서만 여기로 온다. 관계 기록과 `xl/workbook.xml`은 openpyxl도
    같은 것을 읽으므로 둘이 없거나 깨진 통합문서는 여기 오기 전에 읽기 실패다(2026-09-13 실측).
    시트가 아닌 부분을 가리키는 관계만 병합 없이 지나간다.
    """
    names = set(archive.namelist())
    targets = {
        item.get("Id"): item.get("Target", "")
        for item in ElementTree.fromstring(archive.read(WORKBOOK_RELS))
    }
    book = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    spans = {}
    for sheet in book.iterfind(f"{MAIN}sheets/{MAIN}sheet"):
        target = targets.get(sheet.get(f"{DOCUMENT}id", ""), "")
        part = target[1:] if target.startswith("/") else f"xl/{target}"
        spans[sheet.get("name", "")] = _sheet_spans(archive, part) if part in names else ()
    return spans


def _sheet_spans(archive: zipfile.ZipFile, part: str) -> tuple[Span, ...]:
    """시트 XML의 `mergeCell`만 훑는다. 칸 값은 openpyxl이 읽으므로 여기서는 버린다."""
    spans: list[Span] = []
    with archive.open(part) as stream:
        for _, element in ElementTree.iterparse(stream):
            if element.tag == f"{MAIN}mergeCell":
                spans.extend(_merged(element.get("ref", "")))
            element.clear()
    return tuple(spans)


def _merged(reference: str) -> Iterator[Span]:
    """`B17:B18`처럼 적힌 병합 범위. 두 행 이상을 덮을 때만 이어짐 칸이 생긴다."""
    found = re.fullmatch(r"([A-Z]+)([0-9]+):([A-Z]+)([0-9]+)", reference)
    if found is None:
        return
    first, top, last, bottom = found.groups()
    for row in range(int(top) + 1, int(bottom) + 1):
        for column in range(_column(first), _column(last) + 1):
            yield Span(row, column, int(top))


def _column(letters: str) -> int:
    """`A`가 0인 열 번호."""
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - ord("A") + 1
    return index - 1


def _pdf(content: bytes) -> list[Block]:
    """괘선으로 칸이 나뉜 표를 격자로 옮긴다. 셀 값은 모두 글자이며 숫자로 바꾸지 않는다.

    글자 층이 없는 스캔본이나 괘선 없는 안내문은 표가 나오지 않는다. 그때는 표 0개로
    돌려 미해결로 남기며, 집행 없음으로 바꾸지 않는다.
    """
    try:
        with pdfplumber.open(io.BytesIO(content)) as document:
            return [
                (f"{page.page_number}쪽", _pdf_rows(table), _pdf_spans(table))
                for page in document.pages
                for table in page.find_tables()
            ]
    except Exception:
        # 암호가 걸렸거나 구조가 깨진 PDF. 원본 내용은 사유에 담지 않는다.
        raise UnreadableOriginal("PDF could not be read") from None


def _pdf_rows(table: RuledTable) -> list[tuple[Cell, ...]]:
    """칸이 없는 자리는 빈 글자로 둔다. 병합 여부는 `_pdf_spans`가 따로 싣는다."""
    return [tuple("" if cell is None else cell for cell in row) for row in table.extract()]


def _pdf_spans(table: RuledTable) -> tuple[Span, ...]:
    """칸이 없는 자리 가운데 위 칸이 그 행 끝까지 내려온 것만 세로 병합이다.

    통합문서와 달리 PDF는 병합된 자리에 칸 자체가 없다. 위 칸이 거기까지 내려오지 않았다면
    그냥 칸이 없는 자리이며 병합으로 보지 않는다.
    """
    spans: list[Span] = []
    # 열마다 값을 담은 마지막 칸의 행과 그 칸의 아랫변. 칸도 행도 (왼쪽, 위, 오른쪽, 아래)다.
    holders: dict[int, tuple[int, float]] = {}
    for row, line in enumerate(table.rows, start=1):
        bottom = line.bbox[3]
        for column, cell in enumerate(line.cells):
            if cell is not None:
                holders[column] = (row, cell[3])
                continue
            holder = holders.get(column)
            if holder is None:
                continue
            holder_row, holder_bottom = holder
            if holder_bottom < bottom - RULE_TOLERANCE:
                # 위 칸이 이 행 끝까지 내려오지 않았다. 병합이 아니라 그냥 칸이 없는 자리다.
                holders.pop(column, None)
                continue
            spans.append(Span(row, column, holder_row))
    return tuple(spans)


def _transitional(content: bytes) -> bytes:
    """ISO Strict 이름공간을 Transitional로 바꾼다. openpyxl은 Strict 시트를 조용히 건너뛴다."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if STRICT_MAIN not in archive.read("xl/workbook.xml"):
            return content
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as target:
            for item in archive.infolist():
                data = archive.read(item)
                if item.filename.endswith((".xml", ".rels")):
                    for strict, transitional in STRICT_NAMESPACES:
                        data = data.replace(strict, transitional)
                target.writestr(item, data)
    return stream.getvalue()


def _xlsx_cell(value: object) -> Cell:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int | float):
        return float(value)
    return str(value).strip()


def _cell(sheet: xlrd.sheet.Sheet, row: int, column: int, datemode: int) -> Cell:
    kind = sheet.cell_type(row, column)
    value = sheet.cell_value(row, column)
    if kind == xlrd.XL_CELL_DATE:
        try:
            return _as_datetime(xlrd.xldate_as_datetime(value, datemode))
        except (ValueError, OverflowError, xlrd.xldate.XLDateError):
            raise UnreadableOriginal("invalid date cell") from None
    if kind == xlrd.XL_CELL_NUMBER:
        return float(value)
    if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    return str(value).strip()


def _as_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise UnreadableOriginal("invalid date cell")
    return value
