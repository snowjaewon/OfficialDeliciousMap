"""화면이 원본인 서울 게시판의 계약. 합성 화면으로 고정한다."""

from pathlib import Path

import pytest

from deliciousmap import boards
from deliciousmap.collection import collect
from deliciousmap.paths import Paths
from deliciousmap.registry import CITIES, Board, select_target
from deliciousmap.scrapers.seoul_html import (
    CityExpenseBoard,
    EunpyeongBoard,
    GwanakBoard,
    SeodaemunBoard,
)

CITY_LIST = "https://opengov.seoul.go.kr/expense/list"
EUNPYEONG = "https://www.ep.go.kr/www/selectJobPrtnCtWebList.do"
SEODAEMUN = "https://www.sdm.go.kr/admininfo/budget/openmoney.do"
GWANAK = "https://www.gwanak.go.kr/site/gwanak/estimate/estimateListExcel.do"


class FakeTransport:
    def __init__(self, responses: dict[frozenset[tuple[str, str]], bytes]) -> None:
        self.responses = responses
        self.calls: list[dict[str, str]] = []

    def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
        self.calls.append(dict(params))
        key = frozenset(params.items())
        if key not in self.responses:
            raise AssertionError(f"unexpected request: {url} {params}")
        return self.responses[key]


def never(post_id: str, posted: object) -> bool:
    return False


def board(url: str, scraper: type) -> Board:
    return Board("expenses", url, scraper)


def city_page(*rows: tuple[str, str, str]) -> bytes:
    """서울시청 목록 한 쪽. 실측대로 제목 칸을 닫지 않은 채 공개일 칸을 연다."""
    body = "".join(
        f'<tr><td class="data-num">1</td>'
        f'<td class="data-title aLeft"><a href="/expense/{post_id}">{title}</a>'
        f'<td class="data-date">{posted}</td>'
        f'<td class="date-hit">3</td></tr>'
        for post_id, title, posted in rows
    )
    return f"<html><body><table><tbody>{body}</tbody></table></body></html>".encode()


def month_params(month: int, page: int) -> dict[str, str]:
    return {
        "ym[year]": "2026",
        "ym[month]": str(month),
        "items_per_page": "50",
        "page": str(page),
    }


def test_city_board_walks_every_reporting_month_until_a_page_is_empty() -> None:
    responses = {}
    for month in range(1, 7):
        responses[frozenset(month_params(month, 1).items())] = city_page(
            (
                f"1000{month}",
                f"2026년 {month}월 서울시본청 재무과 업무추진비 - 기관운영",
                "2026-07-01",
            )
        )
        responses[frozenset(month_params(month, 2).items())] = city_page()
    scraper = CityExpenseBoard(board(CITY_LIST, CityExpenseBoard), FakeTransport(responses))
    found = list(scraper.postings(never))
    assert [item.post_id for item in found] == [f"1000{month}" for month in range(1, 7)]
    assert found[0].attachments[0].url == "https://opengov.seoul.go.kr/expense/10001"
    assert found[0].attachments[0].suffix == ".html"
    assert found[0].posted is not None and found[0].posted.isoformat() == "2026-07-01"
    assert found[0].title.startswith("2026년 1월 서울시본청")


def test_city_board_filters_the_council_axis_and_counts_it() -> None:
    responses = {}
    for month in range(1, 7):
        responses[frozenset(month_params(month, 1).items())] = city_page(
            (
                f"200{month}",
                f"2026년 {month}월 의회사무처 총무담당관 업무추진비 - 기관운영",
                "2026-07-01",
            ),
            (
                f"300{month}",
                f"2026년 {month}월 사업소 서울역사박물관 업무추진비 - 부서운영",
                "2026-07-02",
            ),
        )
        responses[frozenset(month_params(month, 2).items())] = city_page()
    scraper = CityExpenseBoard(board(CITY_LIST, CityExpenseBoard), FakeTransport(responses))
    found = list(scraper.postings(never))
    assert [item.post_id for item in found] == [f"300{month}" for month in range(1, 7)]
    assert scraper.filtered == 6


def test_city_board_reports_an_impossible_posting_date() -> None:
    responses = {
        frozenset(month_params(1, 1).items()): city_page(
            ("1", "2026년 1월 사업소 가", "2026-02-31")
        )
    }
    scraper = CityExpenseBoard(board(CITY_LIST, CityExpenseBoard), FakeTransport(responses))
    with pytest.raises(boards.UnreadableBoard):
        list(scraper.postings(never))


def eunpyeong_params(month: int, page: int) -> dict[str, str]:
    return {
        "pageIndex": str(page),
        "pageUnit": "1000",
        "searchDeDtMonth": f"2026-{month:02d}",
    }


def test_eunpyeong_reads_its_page_count_once_and_yields_every_screen() -> None:
    first = (
        b"<html><table><tr><th>a</th></tr><tr><td>1</td></tr></table>"
        b"<a href='?pageIndex=3'>3</a></html>"
    )
    responses = {frozenset(eunpyeong_params(month, 1).items()): first for month in range(1, 7)}
    transport = FakeTransport(responses)
    scraper = EunpyeongBoard(board(EUNPYEONG, EunpyeongBoard), transport)
    found = list(scraper.postings(never))
    assert len(found) == 18
    assert [item.post_id for item in found[:3]] == ["2026010001", "2026010002", "2026010003"]
    # 쪽 수는 달마다 한 번만 묻는다. 나머지 화면은 수집이 내려받는다.
    assert len(transport.calls) == 6
    assert "searchDeDtMonth=2026-01" in found[0].attachments[0].url


def test_eunpyeong_leaves_a_month_without_rows_uncollected() -> None:
    empty = b"<html><table><tr><th>a</th></tr></table></html>"
    responses = {frozenset(eunpyeong_params(month, 1).items()): empty for month in range(1, 7)}
    scraper = EunpyeongBoard(board(EUNPYEONG, EunpyeongBoard), FakeTransport(responses))
    assert list(scraper.postings(never)) == []


def seodaemun_params(month: int, page: int) -> dict[str, str]:
    return {
        "cp": str(page),
        "searchGUBUN": "",
        "searchDept": "",
        "searchYear": "2026",
        "searchMonth": f"{month:02d}",
    }


def test_seodaemun_reads_euckr_and_pages_by_goPage() -> None:
    body = '<html><td>집행건수</td><td>724 건</td><a href="javascript:goPage(2)">2</a>\
<a href="javascript:goPage(181)">181</a></html>'.encode("euc-kr")
    responses = {frozenset(seodaemun_params(month, 1).items()): body for month in range(1, 7)}
    scraper = SeodaemunBoard(board(SEODAEMUN, SeodaemunBoard), FakeTransport(responses))
    found = list(scraper.postings(never))
    assert len(found) == 181 * 6
    assert found[180].post_id == "2026010181"
    assert "searchMonth=01" in found[0].attachments[0].url


def test_seodaemun_leaves_an_empty_month_uncollected() -> None:
    body = '<html><td>집행건수</td><td>0 건</td><a href="javascript:goPage(1)">1</a></html>'.encode(
        "euc-kr"
    )
    responses = {frozenset(seodaemun_params(month, 1).items()): body for month in range(1, 7)}
    scraper = SeodaemunBoard(board(SEODAEMUN, SeodaemunBoard), FakeTransport(responses))
    assert list(scraper.postings(never)) == []


def test_gwanak_requests_one_export_per_month_without_probing() -> None:
    transport = FakeTransport({})
    scraper = GwanakBoard(board(GWANAK, GwanakBoard), transport)
    found = list(scraper.postings(never))
    assert [item.post_id for item in found] == [f"2026{month:02d}0001" for month in range(1, 7)]
    # 31일 달과 28일 달의 끝날을 그 달의 실제 말일로 보낸다(31일 이내 제한).
    assert "searchCondition4=2026-01-31" in found[0].attachments[0].url
    assert "searchCondition4=2026-02-28" in found[1].attachments[0].url
    assert transport.calls == []


def test_html_screens_are_stored_as_originals(tmp_path: Path) -> None:
    page = (
        "<html><body><table><tr><th>집행부서</th></tr>"
        "<tr><td>2026-06-30</td></tr></table></body></html>"
    ).encode()

    class Screen:
        def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
            return page

    target = select_target(CITIES, "seoul", "seoul-gwanak")
    paths = Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "out")
    output = collect(target, paths, Screen())  # type: ignore[arg-type]
    assert len(output.sources) == 6
    assert {item.container for item in output.sources} == {"html"}
    assert all((paths.raw_root / item.path).read_bytes() == page for item in output.sources)


def test_seoul_registry_declares_the_measured_html_organizations() -> None:
    target = select_target(CITIES, "seoul", None)
    slugs = [item.slug for item in target.organizations]
    assert {"seoul-city", "seoul-eunpyeong", "seoul-gwanak", "seoul-seodaemun"} <= set(slugs)
    assert select_target(CITIES, "seoul", "seoul-city").organizations[0].slug == "seoul-city"
    assert all(
        board.scraper.published_suffixes == frozenset({".html"})
        for slug in ("seoul-city", "seoul-eunpyeong", "seoul-gwanak", "seoul-seodaemun")
        for board in select_target(CITIES, "seoul", slug).organizations[0].boards
    )


def test_a_screen_without_the_measured_marker_is_not_an_original() -> None:
    """제공자 오류 화면이 200으로 와도 원본으로 저장하지 않는다.

    화면이 곧 원본인 게시판은 매직 바이트가 없어 내용으로만 가릴 수 있다. 그 게시판에서
    실측한 표식이 없으면 받은 것이 집행 표가 아니라고 본다.
    """
    error = "<html><body><h1>일시적인 오류가 발생했습니다</h1></body></html>".encode()
    scraper = EunpyeongBoard(board(EUNPYEONG, EunpyeongBoard), FakeTransport({}))
    with pytest.raises(boards.UnsupportedOriginal):
        scraper.verify(error)


def test_a_screen_with_the_measured_marker_passes() -> None:
    page = (
        "<html><table><tr><th>사용일자(일시)</th></tr><tr><td>1</td></tr></table></html>".encode()
    )
    scraper = EunpyeongBoard(board(EUNPYEONG, EunpyeongBoard), FakeTransport({}))
    scraper.verify(page)
