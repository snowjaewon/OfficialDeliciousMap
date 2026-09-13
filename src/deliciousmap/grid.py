"""원본을 표 격자로 읽는다. 형식 판별은 확장자가 아니라 파일 앞 바이트로 한다."""

import io
import re
import warnings
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from xml.etree import ElementTree

import openpyxl
import pdfplumber
import xlrd

# 셀 값. 엑셀의 날짜 셀만 datetime이고 숫자는 float, 나머지는 앞뒤 공백을 둔 문자열이다.
Cell = str | float | datetime
# 형식별 읽기가 내는 표 하나. `Table.label`이 될 이름표와 자르기 전의 행들이다.
Block = tuple[str, list[tuple[Cell, ...]]]

OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP = b"PK\x03\x04"
PDF = b"%PDF-"
# 연속 빈 행이 이만큼 이어지면 시트의 끝으로 본다.
MAX_BLANK_RUN = 1_000
# 표 하나를 펼칠 수 있는 칸 수의 상한. 자리·병합 표기가 깨진 HWPX가 격자를 키우지 못하게 한다.
MAX_TABLE_CELLS = 1_000_000
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
# HWPX 본문. 쪽이 아니라 구역마다 파일이 나뉘고 번호는 0부터 이어진다.
SECTION = re.compile(r"Contents/section(\d+)\.xml")
# OWPML 문단 이름공간. 표·행·칸·글자가 모두 여기에 있다.
OWPML = "http://www.hancom.co.kr/hwpml/2011/paragraph"
TABLE = f"{{{OWPML}}}tbl"
ROW = f"{{{OWPML}}}tr"
CELL = f"{{{OWPML}}}tc"
ADDRESS = f"{{{OWPML}}}cellAddr"
SPAN = f"{{{OWPML}}}cellSpan"
PARAGRAPH = f"{{{OWPML}}}p"
TEXT_TAG = f"{{{OWPML}}}t"


class UnsupportedFormat(Exception):
    """이번 구현이 읽지 않는 형식(HWP·ZIP 묶음 등). 자동으로 LLM에 넘기지 않는다."""


class UnreadableOriginal(Exception):
    """형식은 맞지만 내용을 격자로 옮기지 못했다."""


@dataclass(frozen=True)
class Table:
    """표 하나. `name`은 산출물의 위치 표기, `label`은 원본이 이 표를 부르는 이름이다.

    이름표는 형식마다 다른 자리에서 온다 — 통합문서는 시트 이름, PDF는 나온 쪽,
    HWPX는 표 바로 앞의 제목 문단이다.
    """

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
    """통합문서는 시트마다, PDF는 괘선으로 나뉜 표마다, HWPX는 `<hp:tbl>`마다 표 하나다.

    내용이 없는 시트·표는 표가 아니며 뒤쪽의 빈 칸·빈 행은 잘라 낸다. 위치 표기는
    통합문서가 `sheet1`, PDF·HWPX가 `table1`이다.
    """
    content = path.read_bytes()
    if content.startswith(OLE2):
        prefix, blocks = "sheet", _legacy(content)
    elif content.startswith(ZIP):
        prefix, blocks = _zip(content)
    elif content.startswith(PDF):
        prefix, blocks = "table", _pdf(content)
    else:
        raise UnsupportedFormat("not a workbook, HWPX, or PDF")
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


def _zip(content: bytes) -> tuple[str, list[Block]]:
    """ZIP 컨테이너는 엑셀 통합문서이거나 HWPX 본문이다. 둘 다 아니면 읽지 않는다."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile:
        raise UnsupportedFormat("broken ZIP container") from None
    if "xl/workbook.xml" in names:
        return "sheet", _xlsx(content)
    sections = sorted(
        (int(found.group(1)), name)
        for name in names
        if (found := SECTION.fullmatch(name)) is not None
    )
    if not sections:
        # 게시판의 첨부 묶음 등 엑셀도 HWPX도 아닌 ZIP 컨테이너.
        raise UnsupportedFormat("ZIP container without an Excel workbook or an HWPX body")
    return "table", _hwpx(content, [name for _, name in sections])


def _xlsx(content: bytes) -> list[Block]:
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


@dataclass
class _Body:
    """본문 하나를 훑는 동안의 상태. 표 바로 앞의 문단을 그 표의 이름표로 쓴다."""

    # 표 앞에 문단이 없을 때 쓸 본문 이름(`section0`).
    fallback_label: str
    blocks: list[Block] = field(default_factory=list)
    label: str = ""


def _hwpx(content: bytes, sections: list[str]) -> list[Block]:
    """OWPML 본문의 `<hp:tbl>`마다 표 하나다. 표 밖 문단은 표로 만들지 않는다.

    HWPX에는 시트 이름이 없어 표 바로 앞의 비어 있지 않은 문단을 `label`로 남긴다. 실제
    원본에서 그 자리는 `2026. 1분기 업무추진비 집행내역(회계과)` 같은 표 제목이다.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            bodies = [(name, archive.read(name)) for name in sections]
    except (zipfile.BadZipFile, KeyError):
        raise UnreadableOriginal("HWPX body could not be read") from None
    blocks: list[Block] = []
    for name, body in bodies:
        found = _Body(Path(name).stem)
        try:
            _scan(ElementTree.fromstring(body), found)
        except UnreadableOriginal:
            # 자리 표기를 두고 이미 정한 사유가 있다. 뭉뚱그리지 않고 그대로 올린다.
            raise
        except Exception:
            # 구조가 깨진 본문. 원본 내용은 사유에 담지 않는다.
            raise UnreadableOriginal("HWPX body could not be read") from None
        blocks.extend(found.blocks)
    return blocks


def _scan(element: ElementTree.Element, body: _Body) -> None:
    """본문을 적힌 순서대로 훑는다. 칸 안에 든 표도 제 표로 따로 낸다."""
    for child in element:
        if child.tag == TABLE:
            body.blocks.append((body.label or body.fallback_label, _hwpx_rows(child)))
            body.label = ""
            for row in child.findall(ROW):
                for cell in row.findall(CELL):
                    _scan(cell, body)
            # 칸 안의 문단은 이 표의 것이다. 다음 표의 이름표로 새지 않게 다시 비운다.
            body.label = ""
            continue
        if child.tag == PARAGRAPH:
            found = _joined_text(child)
            if found.strip():
                body.label = found.strip()
        _scan(child, body)


def _hwpx_rows(table: ElementTree.Element) -> list[tuple[Cell, ...]]:
    """`<hp:cellAddr>`가 가리키는 자리에 칸을 놓아 행·열 번호를 원본과 같게 둔다.

    병합으로 덮인 자리는 비워 둔다. 통합문서의 병합 칸도 왼쪽 위에만 값이 있고 나머지는
    비어 있으므로 `Table.cell`을 읽는 쪽이 형식마다 다른 규칙을 알 필요가 없다.
    """
    placed: dict[tuple[int, int], Cell] = {}
    taken: set[tuple[int, int]] = set()
    height = 0
    width = 0
    for index, element in enumerate(table.findall(ROW)):
        column = 0
        for cell in element.findall(CELL):
            while (index, column) in taken:
                column += 1
            row, column = _at(cell, index, column)
            rows, columns = _span(cell)
            height = max(height, row + rows)
            width = max(width, column + columns)
            if height * width > MAX_TABLE_CELLS:
                # 실제 원본의 가장 큰 표도 600칸이 되지 않는다. 여기까지 오면 표기가 깨진
                # 것이며, 자리를 짐작해 줄이지 않고 옮기지 못했다고 남긴다.
                raise UnreadableOriginal("HWPX table is too large to lay out")
            if (row, column) in taken:
                # 두 칸이 한 자리를 가리킨다. 나중 칸으로 덮어써 앞 칸을 조용히 버리지 않는다.
                raise UnreadableOriginal("HWPX cells overlap in the same position")
            placed[(row, column)] = _joined_text(cell)
            taken.update((row + r, column + c) for r in range(rows) for c in range(columns))
            column += columns
    return [
        tuple(placed.get((row, column), "") for column in range(width)) for row in range(height)
    ]


def _at(cell: ElementTree.Element, row: int, column: int) -> tuple[int, int]:
    """칸이 놓인 자리. `<hp:cellAddr>`가 없는 표는 적힌 차례대로 왼쪽부터 채운다."""
    address = cell.find(ADDRESS)
    if address is None:
        return row, column
    return _number(address.get("rowAddr"), row), _number(address.get("colAddr"), column)


def _span(cell: ElementTree.Element) -> tuple[int, int]:
    """칸이 덮는 행·열 수. 병합하지 않은 칸은 하나씩이다."""
    span = cell.find(SPAN)
    if span is None:
        return 1, 1
    return _number(span.get("rowSpan"), 1, 1), _number(span.get("colSpan"), 1, 1)


def _number(value: str | None, fallback: int, floor: int = 0) -> int:
    """자리도 크기도 음수일 수 없다. 읽지 못한 값은 적힌 차례에서 얻은 값으로 둔다."""
    try:
        found = int(value) if value is not None else fallback
    except ValueError:
        found = fallback
    return max(found, floor)


def _joined_text(element: ElementTree.Element) -> str:
    """칸·문단의 글자를 잇는다. 한 칸이 `<hp:t>` 여러 개로 쪼개져 있어도 한 값이다.

    실제 원본은 칸 안에서 줄을 나눠 `결제`·`방법`을 따로 적는다. 그 사이에 무엇도 끼우지
    않아야 원본이 보여 주는 `결제방법`이 된다. 칸 안에 든 표는 제 표로 따로 내므로 여기서
    글자를 가져오지 않는다.
    """
    return "".join(
        "".join(child.itertext()) if child.tag == TEXT_TAG else _joined_text(child)
        for child in element
        if child.tag != TABLE
    )


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
