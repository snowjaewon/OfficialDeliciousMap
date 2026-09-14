"""수집이 원본으로 받아들이는 범위. 화면이 원본인 게시판에서만 HTML을 받는다."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from deliciousmap import boards
from deliciousmap.collection import collect
from deliciousmap.paths import Paths
from deliciousmap.pipeline import AdapterFailure
from deliciousmap.registry import Board, City, MapBounds, Organization, Target

PAGE = b"<!DOCTYPE html><html><body><table><tr><td>2026-01-02</td></tr></table></body></html>"


class _Scraper:
    """게시글 하나에 원본 하나. 선언한 확장자만 바꿔 가며 같은 수집 경로를 지나간다."""

    published_suffixes = frozenset({".html"})

    def __init__(self, board: Board, transport: object) -> None:
        self.board = board

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        yield boards.Posting(
            "1",
            (
                boards.Attachment(
                    "1", "1", next(iter(self.published_suffixes)), self.board.url, self.board.url
                ),
            ),
            None,
            "2026년 1월 업무추진비",
        )


class _PdfScraper(_Scraper):
    published_suffixes = frozenset({".pdf"})


class _Transport:
    def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
        return PAGE


def _target(scraper: type) -> Target:
    city = City(
        "testcity",
        "시험",
        MapBounds(37.0, 126.0, 38.0, 127.0),
        (
            Organization(
                "test-org",
                "시험 기관",
                (Board("expenses", "https://example.invalid/list", scraper),),
            ),
        ),
    )
    return Target(city, None)


def _paths(tmp_path: Path) -> Paths:
    return Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "out")


def test_html_board_stores_the_page_it_received_as_the_original(tmp_path: Path) -> None:
    output = collect(_target(_Scraper), _paths(tmp_path), _Transport())
    assert [item.container for item in output.sources] == ["html"]
    assert output.sources[0].path.read_bytes() == PAGE
    assert output.sources[0].source_hash == __import__("hashlib").sha256(PAGE).hexdigest()


def test_attachment_board_does_not_accept_a_page_as_an_original(tmp_path: Path) -> None:
    # Referer 없는 중랑 첨부처럼 200으로 온 화면을 PDF 게시판의 원본으로 받아들이지 않는다.
    with pytest.raises(AdapterFailure):
        collect(_target(_PdfScraper), _paths(tmp_path), _Transport())
