from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
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
    EgovBoard,
    JungguBoard,
    JungguMayorBoard,
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


def test_transfer_board_keeps_no_attachment_postings() -> None:
    url = "https://example.invalid/u/rep/transfer/director/list.ulsan?mId=M1"
    list_url = "https://example.invalid/u/rep/transfer/director/list.ulsan"
    row = (
        "<tr><td>1</td><td>2026-09-11</td><td>"
        '<a href="#" onclick="f_detail(\'2026-09-11\');">국장 내역</a></td></tr>'
    )
    transport = FakeTransport(
        dict([response(list_url, {"mId": "M1", "curPage": "1"}, all_rows(row))])
    )
    posting = next(
        CityTransferBoard(board(url, CityTransferBoard), transport).postings(lambda *_: False)
    )
    assert posting.posted == date(2026, 9, 11)
    assert posting.attachments == ()


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


def test_junggu_mayor_table_without_links_is_preserved() -> None:
    url = "https://example.invalid/mayor/board/list.ulsan?boardId=BBS_0000006"
    row = (
        "<tr><td>8046</td><td>2026-06-30</td><td>20:14</td><td>등대갈비</td>"
        "<td>안전감찰 준비 노고 격려</td><td>7</td></tr>"
    )
    transport = FakeTransport(
        dict(
            [
                response(
                    "https://example.invalid/mayor/board/list.ulsan",
                    {"boardId": "BBS_0000006", "startPage": "1"},
                    "<p>총게시물 1 / 페이지 : 1/1</p><table>" + row + "</table>",
                )
            ]
        )
    )
    posting = next(
        JungguMayorBoard(board(url, JungguMayorBoard), transport).postings(lambda *_: False)
    )
    assert posting.posted == date(2026, 6, 30)
    assert posting.title == "안전감찰 준비 노고 격려"
    assert posting.attachments == ()


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
