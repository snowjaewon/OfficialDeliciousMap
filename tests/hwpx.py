"""합성 HWPX. 실제 원본처럼 표준 ZIP 안에 OWPML 본문을 담고 표를 `<hp:tbl>`로 적는다.

실제 원본은 `Contents/section0.xml` 하나에 본문을 두고, 한 칸의 글을 `<hp:p>` 여러 개로
쪼개며, 병합한 칸은 `<hp:cellSpan>`을 두고 덮인 자리의 `<hp:tc>`를 아예 적지 않는다(남구
게시분 6개 실측). 여기서는 그 구조만 흉내 내며 원본 내용은 쓰지 않는다.
"""

import io
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

MIMETYPE = "application/hwp+zip"
NAMESPACES = (
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
    ' xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
)


@dataclass(frozen=True)
class Cell:
    """칸 하나. `lines`가 둘 이상이면 실제 원본처럼 칸 안에서 문단이 나뉜다."""

    lines: tuple[str, ...]
    columns: int = 1
    rows: int = 1


def cell(*lines: str, columns: int = 1, rows: int = 1) -> Cell:
    return Cell(tuple(lines), columns, rows)


Value = str | Cell
Rows = Sequence[Sequence[Value]]
# 본문에 적는 것. 글자는 표 밖 문단 하나이고 행 묶음은 표 하나다.
Part = str | Rows


def document(*parts: Part, body: str | None = None) -> bytes:
    """본문 하나에 문단과 표를 적은 순서대로 담은 합성 HWPX. `body`는 본문 XML을 통째로 바꾼다."""
    return archive(("Contents/section0.xml", section(*parts) if body is None else body))


def archive(*files: tuple[str, str]) -> bytes:
    """실제 원본의 앞자리 파일을 그대로 두고 넘겨받은 파일만 더한 ZIP."""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as target:
        # 실제 원본은 `mimetype`을 압축하지 않고 맨 앞에 둔다.
        target.writestr("mimetype", MIMETYPE, zipfile.ZIP_STORED)
        target.writestr("version.xml", '<?xml version="1.0" encoding="UTF-8"?><hv:HCFVersion/>')
        target.writestr("Contents/header.xml", '<?xml version="1.0" encoding="UTF-8"?><hh:head/>')
        for name, text in files:
            target.writestr(name, text)
    return stream.getvalue()


def section(*parts: Part) -> str:
    """본문 하나의 OWPML. 구역이 여럿인 원본을 만들 때 `archive`와 함께 쓴다."""
    written = [
        f"<hp:p><hp:run><hp:t>{escape(part)}</hp:t></hp:run></hp:p>"
        if isinstance(part, str)
        else f"<hp:p><hp:run>{_table(part)}</hp:run></hp:p>"
        for part in parts
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f"<hs:sec {NAMESPACES}>{''.join(written)}</hs:sec>"
    )


def _table(rows: Rows) -> str:
    """병합으로 덮인 자리는 `<hp:tc>`를 적지 않고, 남은 칸의 `colAddr`가 그만큼 건너뛴다."""
    taken: set[tuple[int, int]] = set()
    written = []
    for row, values in enumerate(rows):
        column = 0
        cells = []
        for value in values:
            item = value if isinstance(value, Cell) else Cell((value,))
            while (row, column) in taken:
                column += 1
            taken.update(
                (row + r, column + c) for r in range(item.rows) for c in range(item.columns)
            )
            cells.append(_cell(item, row, column))
            column += item.columns
        written.append(f"<hp:tr>{''.join(cells)}</hp:tr>")
    columns = max((column for _, column in taken), default=-1) + 1
    return f'<hp:tbl rowCnt="{len(rows)}" colCnt="{columns}">{"".join(written)}</hp:tbl>'


def _cell(item: Cell, row: int, column: int) -> str:
    paragraphs = "".join(
        f"<hp:p><hp:run><hp:t>{escape(line)}</hp:t></hp:run></hp:p>" for line in item.lines
    )
    return (
        f"<hp:tc><hp:subList>{paragraphs}</hp:subList>"
        f'<hp:cellAddr colAddr="{column}" rowAddr="{row}"/>'
        f'<hp:cellSpan colSpan="{item.columns}" rowSpan="{item.rows}"/></hp:tc>'
    )
