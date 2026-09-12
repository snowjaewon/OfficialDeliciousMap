"""원본 형식 판별과 격자 읽기. 합성 통합문서로만 확인한다."""

import io
import re
import zipfile
from datetime import datetime, time
from pathlib import Path

import openpyxl
import pytest

from deliciousmap.grid import UnreadableOriginal, UnsupportedFormat, read_tables
from tests import pdf
from tests.gwangju import workbook


def test_legacy_workbook_keeps_date_cells_and_skips_empty_sheets(tmp_path: Path) -> None:
    path = tmp_path / "원본.bin"
    path.write_bytes(
        workbook([("제목",), ("일시", "금액"), (datetime(2026, 1, 5, 12, 7), 62000.0)], [])
    )
    (table,) = read_tables(path)
    assert (table.name, table.label) == ("sheet1", "시트1")
    assert table.rows[2] == (datetime(2026, 1, 5, 12, 7), 62000.0)


def test_xlsx_is_read_by_content_and_trims_formatted_empty_ranges(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "기관운영"
    sheet.append(["□ 합성과 업무추진비"])
    sheet.append(["사용자", "사용일시", "시각", "금액"])
    sheet.append(["합성과장", datetime(2026, 2, 3), time(12, 4), 93000])
    # 서식만 있는 먼 칸은 격자에 넣지 않는다.
    sheet.cell(row=5000, column=60).number_format = "0"
    book.create_sheet("빈 시트")
    path = tmp_path / "집행내역.xls"
    book.save(path)
    (table,) = read_tables(path)
    assert table.label == "기관운영"
    assert table.rows == (
        ("□ 합성과 업무추진비",),
        ("사용자", "사용일시", "시각", "금액"),
        ("합성과장", datetime(2026, 2, 3), "12:04", 93000.0),
    )


def strict(path: Path) -> bytes:
    """openpyxl이 쓴 통합문서를 ISO Strict 이름공간으로 바꾼다. 실제 원본 두 개가 이 형식이다."""
    source = zipfile.ZipFile(path)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            for transitional, iso in (
                (b"http://schemas.openxmlformats.org/spreadsheetml/2006/main",
                 b"http://purl.oclc.org/ooxml/spreadsheetml/main"),
                (b"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
                 b"http://purl.oclc.org/ooxml/officeDocument/relationships"),
            ):  # fmt: skip
                data = data.replace(transitional, iso)
            target.writestr(name, data)
    return stream.getvalue()


def test_strict_ooxml_workbook_is_read_like_a_transitional_one(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    book.active.append(["사용일시", "금액"])
    book.active.append(["2026-01-05", 62000])
    book.save(tmp_path / "보통.xlsx")
    path = tmp_path / "엄격.xlsx"
    path.write_bytes(strict(tmp_path / "보통.xlsx"))
    (table,) = read_tables(path)
    assert table.rows == (("사용일시", "금액"), ("2026-01-05", 62000.0))


def test_workbook_without_readable_sheets_is_not_reported_as_empty(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    book.save(tmp_path / "보통.xlsx")
    source = zipfile.ZipFile(tmp_path / "보통.xlsx")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "xl/workbook.xml":
                data = re.sub(rb"<sheets>.*</sheets>", b"<sheets/>", data)
            target.writestr(name, data)
    path = tmp_path / "시트 없음.xlsx"
    path.write_bytes(stream.getvalue())
    with pytest.raises(UnreadableOriginal):
        read_tables(path)


@pytest.mark.parametrize(
    "content",
    [b"HWP Document File", b"PK\x03\x04not-a-workbook"],
)
def test_other_formats_are_unsupported(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "원본.xls"
    path.write_bytes(content)
    with pytest.raises(UnsupportedFormat):
        read_tables(path)


def test_pdf_table_is_read_with_the_page_as_the_label(tmp_path: Path) -> None:
    path = tmp_path / "집행내역.pdf"
    path.write_bytes(
        pdf.document(
            [
                ("사용자", "사용일시", "사용장소", "사용금액"),
                ("", "계", "", "155,000"),
                ("합성과", "2026-01-07 12:22", "합성식당", "93,000"),
                ("합성과", "2026-01-08 12:22", "합성찻집", "62,000"),
            ]
        )
    )
    (table,) = read_tables(path)
    assert (table.name, table.label) == ("table1", "1쪽")
    assert table.rows[0] == ("사용자", "사용일시", "사용장소", "사용금액")
    assert table.rows[2] == ("합성과", "2026-01-07 12:22", "합성식당", "93,000")


def test_pdf_numbers_the_tables_and_names_the_page_each_came_from(tmp_path: Path) -> None:
    path = tmp_path / "집행내역.pdf"
    path.write_bytes(
        pdf.document(
            [("사용일시", "사용장소"), ("2026-01-07", "합성식당")],
            [("사용일시", "사용장소"), ("2026-02-09", "합성찻집")],
        )
    )
    first, second = read_tables(path)
    assert [(table.name, table.label) for table in (first, second)] == [
        ("table1", "1쪽"),
        ("table2", "2쪽"),
    ]
    assert second.rows[1] == ("2026-02-09", "합성찻집")


def test_pdf_without_a_readable_table_is_not_reported_as_empty(tmp_path: Path) -> None:
    """괘선이 없어 칸을 가를 수 없는 PDF. 표 0개를 집행 없음으로 바꾸지 않는다."""
    path = tmp_path / "안내문.pdf"
    path.write_bytes(pdf.document([("붙임과 같이 게시합니다.",)], ruled=False))
    assert read_tables(path) == ()


def test_broken_pdf_is_unreadable_rather_than_an_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "깨진.pdf"
    path.write_bytes(b"%PDF-1.7 synthetic")
    with pytest.raises(UnreadableOriginal):
        read_tables(path)
