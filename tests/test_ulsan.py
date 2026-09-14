from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

import pytest

from deliciousmap import boards
from deliciousmap.collection import collect
from deliciousmap.paths import Paths
from deliciousmap.registry import CITIES, Board, select_target
from deliciousmap.scrapers.ulsan import (
    BukguBoard,
    CityMarketBoard,
    CityTransferBoard,
    DongguMayorBoard,
    EgovBoard,
    JungguBoard,
    NamguBoard,
    UljuBoard,
)


class FakeTransport:
    def __init__(self, responses: dict[tuple[str, frozenset[tuple[str, str]]], bytes]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
        self.calls.append((url, dict(params)))
        key = (url, frozenset(params.items()))
        if key not in self.responses:
            raise AssertionError(f"unexpected request: {url} {params}")
        return self.responses[key]


def response(
    url: str, params: dict[str, str], body: str
) -> tuple[tuple[str, frozenset[tuple[str, str]]], bytes]:
    return (url, frozenset(params.items())), body.encode()


def board(url: str, scraper: type) -> Board:
    return Board("expenses", url, scraper)


def all_rows(*rows: str, pages: str = "1/1") -> str:
    return (
        f"<html><body><p>총게시물 : 2 / 페이지 : {pages}</p>"
        f"<table>{''.join(rows)}</table></body></html>"
    )


def test_ulsan_registry_declares_six_nonempty_organizations() -> None:
    target = select_target(CITIES, "ulsan", None)
    assert [item.slug for item in target.organizations] == [
        "ulsan-city",
        "ulsan-junggu",
        "ulsan-namgu",
        "ulsan-donggu",
        "ulsan-bukgu",
        "ulsan-ulju",
    ]
    assert all(item.boards for item in target.organizations)
    assert select_target(CITIES, "ulsan", "ulsan-ulju").organizations[0].slug == "ulsan-ulju"


def test_ulsan_registers_every_html_table_board_with_a_declared_mapping() -> None:
    # 시청 메뉴 진입점(`contents.ulsan?mId=…`)이 넘겨주는 주소(2026-09-14 실측). 내용은
    # 경로와 `se`가 정하고 `mId`는 화면 제목만 정한다.
    city, junggu, donggu = (
        select_target(CITIES, "ulsan", slug).organizations[0]
        for slug in ("ulsan-city", "ulsan-junggu", "ulsan-donggu")
    )
    found = {
        item.slug: (urlsplit(item.url).path.split("/")[-2], parse_qs(urlsplit(item.url).query))
        for item in city.boards
        if item.table is not None
    }
    assert found == {
        "expenses-deputy": ("ecnmy", {"se": ["2"], "mId": ["001003002001000000"]}),
        "expenses-economic": ("ecnmy", {"se": ["3"], "mId": ["001003002002000000"]}),
        "expenses-fez": ("ecnmy", {"se": ["6"], "mId": ["001003002006000000"]}),
        "expenses-director": ("director", {"mId": ["001003002003000000"]}),
        "expenses-department": ("chief", {"mId": ["001003002005000000"]}),
    }
    assert [item.slug for item in city.boards if item.table is None] == ["expenses-market"]
    assert [item.slug for item in junggu.boards if item.table is not None] == ["expenses-mayor"]
    assert [item.slug for item in donggu.boards if item.table is not None] == ["expenses-mayor"]


def test_ulsan_collection_keeps_board_failures_and_continues(tmp_path: Path) -> None:
    class Unavailable:
        def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
            raise OSError("connection reset")

    target = select_target(CITIES, "ulsan", "ulsan-city")
    output = collect(
        target,
        Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "output"),
        Unavailable(),  # type: ignore[arg-type]
    )
    assert output.sources == ()
    assert output.empty_reason is not None
    assert "ulsan-city/expenses-market=service-unavailable" in output.empty_reason
    assert "ulsan-city/expenses-economic=service-unavailable" in output.empty_reason


def test_egov_board_walks_pages_and_preserves_direct_attachment() -> None:
    url = "https://example.invalid/cop/bbs/selectBoardList.do?bbsId=PrmtFee"
    list_url = "https://example.invalid/cop/bbs/selectBoardList.do"
    row = (
        '<tr><td>1</td><td><a href="/cop/bbs/selectBoardArticle.do?bbsId=PrmtFee&nttId=530915">'
        "2026년 7월 부구청장</a></td><td class=problem_name>총무과</td>"
        "<td class=date>2026-08-17</td>"
        '<td><a href="/cmm/fms/FileDown.do?atchFileId=FILE_1&fileSn=0" '
        'title="지출내역.pdf 다운로드">pdf</a></td></tr>'
    )
    page2 = (
        '<tr><td>2</td><td><a href="/cop/bbs/selectBoardArticle.do?bbsId=PrmtFee&nttId=530914">'
        "2026년 6월 부구청장</a></td><td class=problem_name>총무과</td>"
        "<td class=date>2026-07-17</td>"
        "<td></td></tr>"
    )
    transport = FakeTransport(
        dict(
            [
                response(
                    list_url, {"bbsId": "PrmtFee", "pageIndex": "1"}, all_rows(row, pages="1/2")
                ),
                response(
                    list_url, {"bbsId": "PrmtFee", "pageIndex": "2"}, all_rows(page2, pages="2/2")
                ),
            ]
        )
    )
    postings = list(EgovBoard(board(url, EgovBoard), transport).postings(lambda *_: False))
    assert [item.post_id for item in postings] == ["530915", "530914"]
    assert postings[0].department == "총무과"
    assert postings[0].attachments[0].suffix == ".pdf"
    assert postings[0].attachments[0].url.endswith("atchFileId=FILE_1&fileSn=0")
    assert postings[1].attachments == ()


def test_egov_board_reads_the_title_past_a_row_number_that_links_to_the_article() -> None:
    # 동구 목록은 번호 칸도 게시글로 링크한다(2026-09-14 실측). 번호를 제목으로 읽으면
    # 제목이 밝힌 지출 기간이 사라져 원본이 대상에서 빠진다.
    url = "https://example.invalid/cop/bbs/selectBoardList.do?bbsId=BBSMSTR_1"
    list_url = "https://example.invalid/cop/bbs/selectBoardList.do"
    article = "/cop/bbs/selectBoardArticle.do?bbsId=BBSMSTR_1&amp;nttId=211232"
    row = (
        f'<tr><td class="atchFileId"><a href="{article}">46</a></td>'
        f'<td class="subject"><a href="{article}"> 2026년 2분기 업무추진비 집행내역(합성과) </a>'
        "</td>"
        '<td class="writer txtEl">총무과</td><td class="regDate">2026-07-09</td>'
        '<td class="atchFileI"><a href="/cmm/fms/FileDown.do?atchFileId=FILE_1&amp;fileSn=0">'
        '<img alt="pdf파일"/></a></td><td>12</td></tr>'
    )
    transport = FakeTransport(
        dict([response(list_url, {"bbsId": "BBSMSTR_1", "pageIndex": "1"}, all_rows(row))])
    )
    postings = list(EgovBoard(board(url, EgovBoard), transport).postings(lambda *_: False))
    assert [item.post_id for item in postings] == ["211232"]
    assert postings[0].title == "2026년 2분기 업무추진비 집행내역(합성과)"
    assert postings[0].department == "총무과"
    assert postings[0].attachments[0].url.endswith("atchFileId=FILE_1&fileSn=0")


def test_egov_board_keeps_the_title_when_only_the_title_cell_links() -> None:
    # 번호 칸에 링크가 없는 목록은 전과 같이 읽는다. 부서는 제목 칸 다음의 일반 칸이다.
    url = "https://example.invalid/cop/bbs/selectBoardList.do?bbsId=PrmtFee"
    list_url = "https://example.invalid/cop/bbs/selectBoardList.do"
    row = (
        '<tr><td>7</td><td><a href="/cop/bbs/selectBoardArticle.do?bbsId=PrmtFee&nttId=530915">'
        "2026년 3월 부구청장 업무추진비 사용내역</a></td><td>총무과</td>"
        "<td class=date>2026-04-13</td></tr>"
    )
    transport = FakeTransport(
        dict([response(list_url, {"bbsId": "PrmtFee", "pageIndex": "1"}, all_rows(row))])
    )
    postings = list(EgovBoard(board(url, EgovBoard), transport).postings(lambda *_: False))
    assert postings[0].title == "2026년 3월 부구청장 업무추진비 사용내역"
    assert postings[0].department == "총무과"


def test_namgu_board_uses_the_measured_page_size() -> None:
    url = "https://example.invalid/cop/bbs/selectBoardList.do?bbsId=PrmtFee"
    list_url = "https://example.invalid/cop/bbs/selectBoardList.do"
    row = (
        '<tr><td><a href="/cop/bbs/selectBoardArticle.do?bbsId=PrmtFee&nttId=530915">'
        "2026년 7월 부구청장</a></td><td class=date>2026-08-17</td></tr>"
    )
    transport = FakeTransport(
        dict(
            [
                response(
                    list_url,
                    {"bbsId": "PrmtFee", "pageIndex": "1", "recordCountPerPage": "30"},
                    all_rows(row),
                )
            ]
        )
    )
    postings = list(NamguBoard(board(url, NamguBoard), transport).postings(lambda *_: False))
    assert [item.post_id for item in postings] == ["530915"]


def test_junggu_board_declares_zip_attachment() -> None:
    url = "https://example.invalid/board/list.ulsan?boardId=BBS_0000116"
    list_url = "https://example.invalid/board/list.ulsan"
    row = (
        "<tr><td>1</td><td class=list-title><a "
        'href="/board/view.ulsan?boardId=BBS_0000116&dataSid=725604">'
        "2026년 8월 도시과</a></td><td>도시과</td><td>2026-09-02</td>"
        '<td><a href="/board/download.ulsan?boardId=BBS_0000116&dataSid=725604&fileSid=279491">'
        "zip 파일 다운로드</a></td></tr>"
    )
    transport = FakeTransport(
        dict([response(list_url, {"boardId": "BBS_0000116", "startPage": "1"}, all_rows(row))])
    )
    posting = next(JungguBoard(board(url, JungguBoard), transport).postings(lambda *_: False))
    assert posting.post_id == "725604"
    assert posting.attachments[0].suffix == ".zip"


def test_city_market_reads_encoded_attachment_from_detail() -> None:
    url = "https://example.invalid/u/rep/bbs/list.ulsan?bbsId=BBS_1&mId=M1"
    list_url = "https://example.invalid/u/rep/bbs/list.ulsan"
    view_url = "https://example.invalid/u/rep/bbs/view.do"
    row = (
        '<tr><td><a href="/u/rep/bbs/view.do?bbsId=BBS_1&mId=M1&dataId=182571">시장 6월</a></td>'
        '<td>2026-07-23</td><td><img alt="시장 내역.pdf" /></td></tr>'
    )
    detail = (
        "<a href=\"#\" onclick=\"HHBbs.EncDownFile('/u','BBS_1','file+id=','1');\">"
        '<img alt="시장 내역.pdf (64.7KByte)" /></a>'
    )
    transport = FakeTransport(
        dict(
            [
                response(
                    list_url,
                    {"bbsId": "BBS_1", "mId": "M1", "page": "1"},
                    "<p>총 게시물 : 1 건</p><table>"
                    + row
                    + "</table><ul class='pagination'><li class='active'>"
                    "<a href='#none' title='현재페이지'>1</a></li></ul>",
                ),
                response(view_url, {"bbsId": "BBS_1", "mId": "M1", "dataId": "182571"}, detail),
            ]
        )
    )
    posting = next(
        CityMarketBoard(board(url, CityMarketBoard), transport).postings(lambda *_: False)
    )
    assert posting.attachments[0].suffix == ".pdf"
    assert "bbsFileDown.do" in posting.attachments[0].url
    assert "file%2Bid%3D" in posting.attachments[0].url


def test_bukgu_and_ulju_open_details_only_when_not_skipped() -> None:
    buk_url = "https://example.invalid/lay1/bbs/S1T136C1896/A/348/list.do"
    buk_list = "https://example.invalid/lay1/bbs/S1T136C1896/A/348/list.do"
    buk_view = "https://example.invalid/lay1/bbs/S1T136C1896/A/348/view.do"
    buk_row = (
        '<tr><td class=title><a href="view.do?article_seq=314936">2026년 8월</a></td>'
        "<td>2026-09-08</td></tr>"
    )
    buk_detail = '<a href="/download.do?uuid=abc123.pdf">2026년 집행현황.pdf</a>'
    ulju_url = "https://example.invalid/ulju/bbs/list.do?ptIdx=117&mId=0216040100"
    ulju_list = "https://example.invalid/ulju/bbs/list.do"
    ulju_view = "https://example.invalid/ulju/bbs/view.do"
    ulju_row = (
        '<tr><td class=list_tit><a href="#" '
        "onclick=\"goTo.view('list','68059','117','0216040100');\" "
        'title="2026년 7월">제목</a></td><td class=list_date>2026-08-09</td></tr>'
    )
    ulju_detail = (
        '<a href="#" onclick="fn_egov_downFile(\'abc123\',\'0\');"><img alt="내역.pdf" /></a>'
    )
    transport = FakeTransport(
        dict(
            [
                response(buk_list, {"cpage": "1", "rows": "30"}, all_rows(buk_row)),
                response(buk_view, {"article_seq": "314936"}, buk_detail),
                response(
                    ulju_list,
                    {"ptIdx": "117", "mId": "0216040100", "page": "1"},
                    "<p>전체 페이지 1</p>" + ulju_row,
                ),
                response(
                    ulju_view, {"mId": "0216040100", "bIdx": "68059", "ptIdx": "117"}, ulju_detail
                ),
            ]
        )
    )
    buk = next(BukguBoard(board(buk_url, BukguBoard), transport).postings(lambda *_: False))
    assert buk.attachments[0].suffix == ".pdf"
    assert urlsplit(buk.attachments[0].url).path.endswith("/download.do")
    ulju = next(UljuBoard(board(ulju_url, UljuBoard), transport).postings(lambda *_: False))
    assert ulju.attachments[0].file_id == "abc123"
    assert ulju.attachments[0].suffix == ".pdf"


def test_transfer_board_offers_each_day_as_an_html_original_keyed_by_the_day() -> None:
    url = "https://example.invalid/u/rep/transfer/director/list.ulsan?mId=M1"
    list_url = "https://example.invalid/u/rep/transfer/director/list.ulsan"
    rows = (
        "<tr><td>2</td><td>2026-09-11</td><td>"
        '<a href="#" onclick="f_detail(\'2026-09-11\');">국장 내역(2건)</a></td></tr>'
        "<tr><td>1</td><td>2025-12-30</td><td>"
        '<a href="#" onclick="f_detail(\'2025-12-30\');">국장 내역(1건)</a></td></tr>'
    )
    transport = FakeTransport(
        dict([response(list_url, {"mId": "M1", "curPage": "1"}, all_rows(rows))])
    )
    postings = list(
        CityTransferBoard(board(url, CityTransferBoard), transport).postings(
            lambda _, posted: posted is not None and posted.year < 2026
        )
    )
    assert [(item.post_id, item.posted, item.spent_on) for item in postings] == [
        ("20260911", date(2026, 9, 11), date(2026, 9, 11)),
        ("20251230", date(2025, 12, 30), date(2025, 12, 30)),
    ]
    (detail,) = postings[0].attachments
    assert detail.suffix == ".html"
    assert detail.url == f"{list_url}?mId=M1&useDe=2026-09-11"
    # 건너뛴 게시글은 상세 쪽을 원본으로 내지 않는다.
    assert postings[1].attachments == ()


def test_transfer_board_dates_a_day_by_the_detail_key_it_opens() -> None:
    # 받는 원본은 `useDe=<키>`로 연 쪽이다. 목록 칸이 다른 날을 적어도 집행일은 그 키의 날이다.
    url = "https://example.invalid/u/rep/transfer/director/list.ulsan?mId=M1"
    list_url = "https://example.invalid/u/rep/transfer/director/list.ulsan"
    row = (
        "<tr><td>2026-03-04 이관</td><td>2026-03-05</td><td>"
        '<a href="#" onclick="f_detail(\'2026-03-05\');">국장 내역(1건)</a></td></tr>'
    )
    transport = FakeTransport(
        dict([response(list_url, {"mId": "M1", "curPage": "1"}, all_rows(row))])
    )
    posting = next(
        CityTransferBoard(board(url, CityTransferBoard), transport).postings(lambda *_: False)
    )
    assert (posting.post_id, posting.spent_on) == ("20260305", date(2026, 3, 5))
    assert posting.attachments[0].url == f"{list_url}?mId=M1&useDe=2026-03-05"


def test_transfer_board_reads_two_digit_legacy_dates() -> None:
    url = "https://example.invalid/u/rep/transfer/director/list.ulsan?mId=M1"
    list_url = "https://example.invalid/u/rep/transfer/director/list.ulsan"
    row = (
        "<tr><td>9</td><td>20. 11. 5</td><td>"
        '<a href="#" onclick="f_detail(\'20. 11. 5\');">국장 내역</a></td></tr>'
    )
    transport = FakeTransport(
        dict([response(list_url, {"mId": "M1", "curPage": "1"}, all_rows(row))])
    )
    posting = next(
        CityTransferBoard(board(url, CityTransferBoard), transport).postings(lambda *_: False)
    )
    assert posting.posted == date(2020, 11, 5)


def test_donggu_mayor_uses_the_public_month_search() -> None:
    url = "https://example.invalid/mayor/expense/list.do"
    list_url = url
    row = (
        "<tr><td>1</td><td>2026-02-10</td><td>13:05</td><td>"
        '<a href="./view.do?ymd2=20260210">부서 회의</a></td></tr>'
    )
    responses = [
        response(
            list_url,
            {"searchWrd": f"2026{month:02}", "pageIndex": "1"},
            all_rows(row if month == 2 else ""),
        )
        for month in range(1, 13)
    ]
    transport = FakeTransport(dict(responses))
    postings = list(
        DongguMayorBoard(board(url, DongguMayorBoard), transport).postings(lambda *_: False)
    )
    assert [item.posted for item in postings] == [date(2026, 2, 10)]
    # 집행일이 게시글을 가르는 키이자 상세 쪽을 여는 키다.
    assert postings[0].post_id == "20260210"
    assert postings[0].spent_on == date(2026, 2, 10)
    (detail,) = postings[0].attachments
    assert (detail.suffix, detail.url) == (
        ".html",
        "https://example.invalid/mayor/expense/view.do?ymd2=20260210",
    )
    assert [params["searchWrd"] for _, params in transport.calls] == [
        f"2026{month:02}" for month in range(1, 13)
    ]


def test_listing_without_page_count_is_rejected() -> None:
    url = "https://example.invalid/cop/bbs/selectBoardList.do?bbsId=PrmtFee"
    transport = FakeTransport(
        dict(
            [
                response(
                    "https://example.invalid/cop/bbs/selectBoardList.do",
                    {"bbsId": "PrmtFee", "pageIndex": "1"},
                    "<tr><td><a "
                    'href="/cop/bbs/selectBoardArticle.do?bbsId=PrmtFee&nttId=1">x</a></td>'
                    "<td>2026-01-01</td></tr>",
                )
            ]
        )
    )
    with pytest.raises(boards.UnreadableBoard):
        list(EgovBoard(board(url, EgovBoard), transport).postings(lambda *_: False))


def test_valid_generic_zip_is_not_mislabelled_as_ooxml() -> None:
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("expense.txt", "fixture")
    assert boards.container_of(stream.getvalue()) == "zip"


@pytest.mark.parametrize("total", [1, 11])
def test_city_market_does_not_guess_paging_for_an_unmeasured_listing(total: int) -> None:
    url = "https://example.invalid/u/rep/bbs/list.ulsan?bbsId=BBS_1&mId=M1"
    transport = FakeTransport(
        dict(
            [
                response(
                    "https://example.invalid/u/rep/bbs/list.ulsan",
                    {"bbsId": "BBS_1", "mId": "M1", "page": "1"},
                    f"<p>총 게시물 : {total} 건</p>",
                )
            ]
        )
    )
    with pytest.raises(boards.UnreadableBoard):
        list(CityMarketBoard(board(url, CityMarketBoard), transport).postings(lambda *_: False))


def test_city_market_detail_failure_is_not_silently_recorded() -> None:
    url = "https://example.invalid/u/rep/bbs/list.ulsan?bbsId=BBS_1&mId=M1"
    list_url = "https://example.invalid/u/rep/bbs/list.ulsan"
    view_url = "https://example.invalid/u/rep/bbs/view.do"
    row = (
        '<tr><td><a href="/u/rep/bbs/view.do?bbsId=BBS_1&mId=M1&dataId=1">시장 6월</a></td>'
        "<td>2026-06-30</td></tr>"
    )

    class FailingDetailTransport(FakeTransport):
        def fetch(self, request_url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
            if request_url == view_url:
                raise boards.BoardUnavailable("fixture detail failure")
            return super().fetch(request_url, params, headers)

    transport = FailingDetailTransport(
        dict(
            [
                response(
                    list_url,
                    {"bbsId": "BBS_1", "mId": "M1", "page": "1"},
                    "<p>총 게시물 : 1 건</p><table>"
                    + row
                    + "</table><ul class='pagination'><li class='active'>"
                    "<a href='#none' title='현재페이지'>1</a></li></ul>",
                )
            ]
        )
    )
    with pytest.raises(boards.BoardUnavailable):
        list(CityMarketBoard(board(url, CityMarketBoard), transport).postings(lambda *_: False))


def test_an_html_page_is_an_original_only_where_the_board_publishes_html() -> None:
    # 첨부를 요청했는데 오류 쪽이 HTML로 오는 일이 흔하다. 그것을 원본으로 받지 않는다.
    page = b"\xef\xbb\xbf\r\n  <!DOCTYPE html><html><body><table></table></body></html>"
    assert boards.container_of(page, html=True) == "html"
    with pytest.raises(boards.UnsupportedOriginal):
        boards.container_of(page)
