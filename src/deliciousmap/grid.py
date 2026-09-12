"""원본을 표 격자로 읽는다. 형식 판별은 확장자가 아니라 파일 앞 바이트로 한다."""

import io
import warnings
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

import openpyxl
import pdfplumber
import xlrd

# 셀 값. 엑셀의 날짜 셀만 datetime이고 숫자는 float, 나머지는 앞뒤 공백을 둔 문자열이다.
Cell = str | float | datetime
# 형식별 읽기가 내는 표 하나. 이름표(시트 이름 또는 나온 쪽)와 자르기 전의 행들이다.
Block = tuple[str, list[tuple[Cell, ...]]]

OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP = b"PK\x03\x04"
PDF = b"%PDF-"
# 연속 빈 행이 이만큼 이어지면 시트의 끝으로 본다.
MAX_BLANK_RUN = 1_000
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
class Table:
    """표 하나. `name`은 산출물의 위치 표기, `label`은 원본의 시트 이름이나 나온 쪽이다."""

    name: str
    label: str
    rows: tuple[tuple[Cell, ...], ...]

    def cell(self, row: int, column: int) -> Cell:
        """행은 1부터, 열은 0부터 센다. 없는 칸은 빈 문자열이다."""
        cells = self.rows[row - 1] if 0 < row <= len(self.rows) else ()
        return cells[column] if column < len(cells) else ""


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
    for index, (label, rows) in enumerate(blocks, start=1):
        trimmed = _trim(rows)
        if trimmed:
            tables.append(Table(f"{prefix}{index}", label, trimmed))
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
        book = xlrd.open_workbook(file_contents=content)
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
        )
        for sheet in book.sheets()
    ]


def _xlsx(content: bytes) -> list[Block]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        raise UnsupportedFormat("broken ZIP container") from None
    if "xl/workbook.xml" not in names:
        # HWPX·원본 묶음 ZIP 등 엑셀이 아닌 ZIP 컨테이너.
        raise UnsupportedFormat("ZIP container without an Excel workbook")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = openpyxl.load_workbook(
                io.BytesIO(_transitional(content)), read_only=True, data_only=True
            )
    except Exception:
        raise UnreadableOriginal("workbook could not be read") from None
    if not book.worksheets:
        # 시트를 하나도 못 읽은 통합문서를 빈 원본으로 보고하지 않는다.
        raise UnreadableOriginal("workbook has no readable worksheet")
    try:
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
            blocks.append((sheet.title, rows))
        book.close()
    except Exception:
        raise UnreadableOriginal("workbook could not be read") from None
    return blocks


def _pdf(content: bytes) -> list[Block]:
    """괘선으로 칸이 나뉜 표를 격자로 옮긴다. 셀 값은 모두 글자이며 숫자로 바꾸지 않는다.

    글자 층이 없는 스캔본이나 괘선 없는 안내문은 표가 나오지 않는다. 그때는 표 0개로
    돌려 미해결로 남기며, 집행 없음으로 바꾸지 않는다.
    """
    try:
        with pdfplumber.open(io.BytesIO(content)) as document:
            return [
                (
                    f"{page.page_number}쪽",
                    [tuple("" if cell is None else cell for cell in row) for row in rows],
                )
                for page in document.pages
                for rows in page.extract_tables()
            ]
    except Exception:
        # 암호가 걸렸거나 구조가 깨진 PDF. 원본 내용은 사유에 담지 않는다.
        raise UnreadableOriginal("PDF could not be read") from None


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
