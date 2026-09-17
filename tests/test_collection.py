"""수집이 원본으로 받아들이는 범위. 화면이 원본인 게시판에서만 HTML을 받는다."""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from deliciousmap import boards
from deliciousmap.collection import collect
from deliciousmap.contracts import FetchOutput
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
    paths = _paths(tmp_path)
    output = collect(_target(_Scraper), paths, _Transport())
    assert [item.container for item in output.sources] == ["html"]
    # 산출물이 적는 자리는 raw-root 기준 상대 경로다(#202).
    assert output.sources[0].path == Path("testcity/test-org/expenses/1-1.html")
    assert (paths.raw_root / output.sources[0].path).read_bytes() == PAGE
    assert output.sources[0].source_hash == hashlib.sha256(PAGE).hexdigest()


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
    filtered = 2

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


def test_every_city_records_a_board_failure_the_same_way(tmp_path: Path) -> None:
    """#140의 결정: 끊긴 게시판을 이어 가는 규칙에서 도시 이름을 뺀다.

    도시 이름은 게시판이 끊겼는지와 무관하다. 광주도 서울·울산과 같이 사유를 장부 경고에
    남기고 다음 게시판으로 간다.
    """
    target = _two_board_target((_BrokenScraper, _PdfScraper), slug="gwangju")
    output = collect(target, _paths(tmp_path), _Pdf())  # type: ignore[arg-type]
    assert [item.container for item in output.sources] == ["pdf"]
    assert output.empty_reason is not None
    assert "test-org/expenses-0=service-unavailable" in output.empty_reason


def test_a_board_failure_that_collects_nothing_is_still_a_failure(tmp_path: Path) -> None:
    """다 훑고도 한 건이 없고 원인이 장애라면 실패다. 그것까지 경고로 남기면 장애가
    "첨부가 없는 기관"과 같은 모양이 된다."""
    target = _two_board_target((_BrokenScraper, _BrokenScraper), slug="gwangju")
    with pytest.raises(AdapterFailure):
        collect(target, _paths(tmp_path), _Pdf())  # type: ignore[arg-type]


def test_an_unmeasured_format_still_stops_the_collection(tmp_path: Path) -> None:
    # 게시판 실패를 기록한다고 해서 실측하지 않은 형식까지 통과시키지는 않는다.
    class Unknown:
        def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
            return b"\x00\x01\x02 not a measured container"

    with pytest.raises(AdapterFailure):
        collect(_target(_PdfScraper), _paths(tmp_path), Unknown())  # type: ignore[arg-type]


class _Big:
    """상한을 넘는 원본을 주는 제공자. 인천시청 실측(33,016,108바이트)의 축소판이다."""

    def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
        return b"%PDF-1.4 " + b"0" * 64


def test_an_oversize_original_is_a_ledger_entry_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """한 번에 읽어 둘 수 없는 원본 하나가 기관 전체 수집을 실패로 만들지 않는다.

    실측(2026-09-17 인천시청 3087017): `.xlsx` 하나가 33MB라 상한을 넘고, 그 하나 때문에
    시청 다섯 게시판이 통째로 실패했다. 잘라 쓰지 않되 사유는 장부에 남긴다.
    상한을 낮춰 같은 자리를 지나간다 — 테스트가 33MB를 만들지 않기 위해서다.
    """
    monkeypatch.setattr(boards, "MAX_RESPONSE_BYTES", 8)
    output = collect(_target(_PdfScraper), _paths(tmp_path), _Big())  # type: ignore[arg-type]
    assert output.sources == ()
    assert [item.reason for item in output.missing] == ["too_large"]
    assert output.missing[0].filename == "1-1.pdf"


class _CountingTransport:
    """요청한 주소를 세는 제공자. 본문을 다시 열었는지 그 수로 가른다."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
        self.urls.append(url)
        return PAGE


class _PartlyAttachedScraper:
    """게시글 둘 중 하나에만 첨부가 달린 게시판. 넘기지 않은 게시글만 본문을 연다.

    인천 부평 실측(#174)의 축소판이다 — 집행이 없었다는 알림은 본문에 내려받기 링크가 없다.
    """

    published_suffixes = frozenset({".html"})

    def __init__(self, board: Board, transport: object) -> None:
        self.board = board
        self.transport = transport

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        for post_id, attached in (("1", True), ("2", False)):
            page_url = f"{self.board.url}/{post_id}"
            if skipped(post_id, None):
                # 넘기기로 한 게시글은 본문을 열지 않으므로 주소를 싣지 않는다.
                yield boards.Posting(post_id, (), None, "2026년 1월 업무추진비")
                continue
            boards.request(self.transport, page_url, {})  # type: ignore[arg-type]
            attachments = (
                (boards.Attachment(post_id, "1", ".html", page_url, page_url),) if attached else ()
            )
            yield boards.Posting(post_id, attachments, None, "2026년 1월 업무추진비", url=page_url)


def _ledger_entries(paths: Paths, target: Target) -> dict[str, dict[str, object]]:
    path = paths.board_dir(target, "test-org", "expenses") / "collected.jsonl"
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return {str(entry["post_id"]): entry for entry in entries}


def test_a_posting_without_any_attachment_is_counted_in_the_collection(tmp_path: Path) -> None:
    """첨부가 하나도 없는 게시글을 수로 싣는다. 받지 못한 원본과 같은 자리에 두지 않는다."""
    output = collect(_target(_PartlyAttachedScraper), _paths(tmp_path), _CountingTransport())
    assert output.unattached_postings == 1
    assert [item.container for item in output.sources] == ["html"]
    assert output.missing == ()
    assert output.uncollected_postings == 0
    assert output.filtered_postings == 0


def test_a_posting_without_any_attachment_keeps_its_address_in_the_ledger(tmp_path: Path) -> None:
    target, paths = _target(_PartlyAttachedScraper), _paths(tmp_path)
    collect(target, paths, _CountingTransport())
    entry = _ledger_entries(paths, target)["2"]
    assert entry["url"] == "https://example.invalid/list/2"
    assert entry["files"] == []


def test_a_posting_without_any_attachment_is_not_opened_again(tmp_path: Path) -> None:
    """장부에 남았으므로 다시 실행해도 본문을 열지 않는다(인천 기준 매 실행 569번)."""
    target, paths = _target(_PartlyAttachedScraper), _paths(tmp_path)
    first = _CountingTransport()
    collect(target, paths, first)
    assert first.urls.count("https://example.invalid/list/2") == 1
    second = _CountingTransport()
    output = collect(target, paths, second)
    assert second.urls == []
    assert output.unattached_postings == 1


class _SkippingScraper(_PartlyAttachedScraper):
    """업무추진비 글이 아니라 본문을 열지 않은 게시글만 내는 게시판(부산 중구·수영구)."""

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        yield boards.Posting("3", (), None, "이륜자동차 등록현황")


def test_a_posting_the_scraper_passed_over_is_not_counted_as_unattached(tmp_path: Path) -> None:
    """본문을 열지 않고 넘긴 게시글은 첨부가 없다고 확인한 것이 아니다. 장부에도 남기지 않는다."""
    target, paths = _target(_SkippingScraper), _paths(tmp_path)
    output = collect(target, paths, _CountingTransport())
    assert output.unattached_postings == 0
    assert not (paths.board_dir(target, "test-org", "expenses") / "collected.jsonl").exists()


def test_a_collection_written_before_the_column_existed_still_reads() -> None:
    """새 칸이 없던 시절의 산출물을 읽어도 실패하지 않는다. 그 값은 0이다."""
    payload = {"sources": [], "missing": [], "uncollected_postings": 3, "filtered_postings": 1}
    assert FetchOutput.model_validate(payload).unattached_postings == 0
