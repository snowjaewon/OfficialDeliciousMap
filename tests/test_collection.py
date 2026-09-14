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


class _RefererScraper(_Scraper):
    """중랑처럼 첨부에 Referer를 요구하는 게시판. 목록 주소를 그대로 실어 보낸다."""

    published_suffixes = frozenset({".pdf"})

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        yield boards.Posting(
            "1",
            (
                boards.Attachment(
                    "1", "1", ".pdf", self.board.url, self.board.url, referer=self.board.url
                ),
            ),
            None,
            "2026년 1월 업무추진비",
        )


class _RefererTransport:
    """Referer가 없으면 200과 함께 오류 화면을 주는 제공자. 실측한 중랑의 동작이다."""

    def __init__(self) -> None:
        self.referers: list[str | None] = []

    def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
        self.referers.append(headers.get("Referer"))
        return b"%PDF-1.4 body" if headers.get("Referer") else PAGE


def test_attachment_referer_reaches_the_request(tmp_path: Path) -> None:
    transport = _RefererTransport()
    output = collect(_target(_RefererScraper), _paths(tmp_path), transport)
    assert transport.referers == ["https://example.invalid/list"]
    assert [item.container for item in output.sources] == ["pdf"]


class _MixedScraper(_Scraper):
    """업무추진비 집행기관이 아닌 줄을 섞어 싣는 게시판. 거른 수를 스스로 센다."""

    published_suffixes = frozenset({".html"})
    excluded = 2

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        yield from super().postings(skipped)


def test_filtered_rows_are_counted_in_the_ledger(tmp_path: Path) -> None:
    output = collect(_target(_MixedScraper), _paths(tmp_path), _Transport())
    assert output.filtered_postings == 2


class _BrokenScraper(_Scraper):
    """긴 순회 중 연결이 끊기는 게시판. 이미 받아 둔 원본은 장부에 그대로 남아야 한다."""

    published_suffixes = frozenset({".pdf"})

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        raise boards.BoardUnavailable("board request failed")
        yield  # pragma: no cover - 계약을 제너레이터로 유지한다


def _two_board_target(scrapers: tuple[type, ...], slug: str = "seoul") -> Target:
    city = City(
        slug,
        "시험",
        MapBounds(37.0, 126.0, 38.0, 127.0),
        (
            Organization(
                "test-org",
                "시험 기관",
                tuple(
                    Board(f"expenses-{index}", "https://example.invalid/list", scraper)
                    for index, scraper in enumerate(scrapers)
                ),
            ),
        ),
    )
    return Target(city, None)


class _Pdf:
    def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
        return b"%PDF-1.4 body"


def test_a_board_failure_is_recorded_instead_of_losing_the_organization(tmp_path: Path) -> None:
    target = _two_board_target((_BrokenScraper, _PdfScraper))
    output = collect(target, _paths(tmp_path), _Pdf())  # type: ignore[arg-type]
    assert [item.container for item in output.sources] == ["pdf"]
    assert output.empty_reason is not None
    assert "test-org/expenses-0=service-unavailable" in output.empty_reason


def test_a_city_without_that_decision_still_stops_on_a_board_failure(tmp_path: Path) -> None:
    # 광주는 이 완화를 받지 않는다. 어느 도시가 받는지는 한 자리에서만 갈린다.
    target = _two_board_target((_BrokenScraper, _PdfScraper), slug="gwangju")
    with pytest.raises(AdapterFailure):
        collect(target, _paths(tmp_path), _Pdf())  # type: ignore[arg-type]


def test_an_unmeasured_format_still_stops_the_collection(tmp_path: Path) -> None:
    # 게시판 실패를 기록한다고 해서 실측하지 않은 형식까지 통과시키지는 않는다.
    class Unknown:
        def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
            return b"\x00\x01\x02 not a measured container"

    with pytest.raises(AdapterFailure):
        collect(_target(_PdfScraper), _paths(tmp_path), Unknown())  # type: ignore[arg-type]
