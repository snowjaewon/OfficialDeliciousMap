"""원본 컨테이너 판정의 계약. 게시판이 밝힌 이름이 아니라 바이트가 근거다."""

from io import BytesIO
from zipfile import ZipFile

import pytest

from deliciousmap import boards

# 관악 월별 내려받기 실측(2026-09-14): `.xls` 이름에 `Content-Type: text/html`이고
# 본문은 빈 줄로 시작한다. 서울시청 상세는 `<!DOCTYPE html>`로 시작한다.
GWANAK_EXPORT = b"\r\n" * 8 + (
    '<meta charset="utf-8" /><table summary="업무추진비"><tr><td>1</td></tr></table>'.encode()
)
CITY_DETAIL = (
    b"<!DOCTYPE html>\n<html lang='ko'><body><table><tr><td>1</td></tr></table></body></html>"
)
# 중랑 첨부를 Referer 없이 부르면 200과 함께 오던 오류 화면. 첨부 게시판에서는 원본이 아니다.
ERROR_PAGE = "<html><head><title>오류</title></head><body>오류</body></html>".encode()


def test_html_is_not_an_original_container_by_default() -> None:
    for body in (GWANAK_EXPORT, CITY_DETAIL, ERROR_PAGE):
        with pytest.raises(boards.UnsupportedOriginal):
            boards.container_of(body)


def test_html_boards_receive_their_page_as_the_original() -> None:
    assert boards.container_of(GWANAK_EXPORT, html=True) == "html"
    assert boards.container_of(CITY_DETAIL, html=True) == "html"


def test_html_acceptance_does_not_reach_binary_containers() -> None:
    # `html=True`여도 매직 바이트가 있는 형식은 그 형식으로 판정한다.
    assert boards.container_of(b"%PDF-1.4 body", html=True) == "pdf"
    with pytest.raises(boards.EmptyOriginal):
        boards.container_of(b"", html=True)


def test_bytes_without_markup_are_still_unsupported() -> None:
    with pytest.raises(boards.UnsupportedOriginal):
        boards.container_of(b"\xef\xbb\xbf   plain text, no markup", html=True)


def _archive(*names: str) -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        for name in names:
            archive.writestr(name, "x")
    return stream.getvalue()


def test_hwpx_packages_are_not_read_as_plain_zip_archives() -> None:
    # 양천 실측(2026-09-14): `.hwpx` 첨부는 `[Content_Types].xml`도 `word/`도 없어
    # 일반 ZIP과 갈리지 않았다. 이미 커밋된 장부는 hwpx를 ooxml로 세고 있다.
    hwpx = _archive("mimetype", "version.xml", "Contents/header.xml", "META-INF/container.xml")
    assert boards.container_of(hwpx) == "ooxml"


def test_plain_zip_archives_stay_zip() -> None:
    assert boards.container_of(_archive("a.pdf", "b.pdf")) == "zip"
    assert boards.container_of(_archive("[Content_Types].xml", "xl/workbook.xml")) == "ooxml"


def test_scanned_images_are_measured_containers() -> None:
    # 용산 실측(2026-09-14): 2026년 게시글 10건이 집행내역을 스캔본으로 공개한다
    # (`7월 업무추진비 집행내역001.jpg`). JPEG 7건·PNG 3건이었다.
    assert boards.container_of(bytes.fromhex("ffd8ffe000104a464946")) == "jpeg"
    assert boards.container_of(bytes.fromhex("89504e470d0a1a0a")) == "png"
