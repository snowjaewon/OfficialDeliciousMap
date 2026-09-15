"""첨부를 내려받는 서울 계열 스크래퍼의 계약. 합성 목록으로 고정한다."""

import json
from datetime import date
from pathlib import Path

import pytest

from deliciousmap import boards
from deliciousmap.collection import collect
from deliciousmap.paths import Paths
from deliciousmap.pipeline import AdapterFailure, FailureCause
from deliciousmap.registry import CITIES, Board, select_target
from deliciousmap.scrapers.seoul import (
    BbsNoBoard,
    BbsNoDetailBoard,
    CbIdxBoard,
    GwangjinBoard,
    JongnoBoard,
    JungnangBoard,
    PortalBoard,
    PortalDetailBoard,
    YangcheonBoard,
)

BBSNO = "https://www.sd.go.kr/main/selectBbsNttList.do?bbsNo=172&key=1330"
PORTAL = "https://www.yongsan.go.kr/portal/bbs/B0000030/list.do?menuNo=200140"
GWANGJIN = "https://www.gwangjin.go.kr/portal/bbs/B0000027/list.do?menuNo=201646"
JUNGNANG = "https://www.jungnang.go.kr/portal/bbs/list/B0000143.do?menuNo=200432"
CBIDX = "https://www.seocho.go.kr/site/seocho/ex/bbs/List.do?cbIdx=33"
YANGCHEON = "https://www.yangcheon.go.kr/site/yangcheon/ex/bbs/List.do?cbIdx=397"
JONGNO = (
    "https://www.jongno.go.kr/portal/bbs/selectBoardList.do"
    "?bbsId=BBSMSTR_000000001167&menuId=110210"
)


class FakeTransport:
    """주소와 조회 조건으로 응답을 고른다. 선언하지 않은 요청은 실패로 알린다."""

    def __init__(self, responses: dict[tuple[str, frozenset[tuple[str, str]]], bytes]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
        self.calls.append((url, dict(params), dict(headers)))
        key = (url, frozenset(params.items()))
        if key not in self.responses:
            raise AssertionError(f"unexpected request: {url} {params}")
        return self.responses[key]


def never(post_id: str, posted: date | None) -> bool:
    return False


def always(post_id: str, posted: date | None) -> bool:
    return True


def board(url: str, scraper: type) -> Board:
    return Board("expenses", url, scraper)


def at(url: str, params: dict[str, str], body: str) -> tuple[tuple[str, frozenset], bytes]:
    return (url, frozenset(params.items())), body.encode()


def page(rows: str, last: int, parameter: str = "pageIndex") -> str:
    """목록 한 쪽. 쪽 넘김 막대는 마지막 쪽 단추만 두고 창은 그리지 않는다."""
    return (
        f'<html><body><table>{rows}</table><a href="?{parameter}={last}">{last}</a></body></html>'
    )


MENU = (
    '<ul class="gnb"><li><a href="/www/selectBbsNttView.do?bbsNo=999&amp;nttNo=1">딴 게시판</a>'
    "</li></ul>"
)


def bbsno_row(post: str, title: str, department: str, posted: str, file_cell: str) -> str:
    return (
        f"<tr><td>1</td>"
        f'<td><a href="./selectBbsNttView.do?bbsNo=172&amp;nttNo={post}">{title}</a></td>'
        f"<td>{department}</td><td>{posted}</td><td>{file_cell}</td></tr>"
    )


def test_bbsno_board_reads_the_listing_row_and_its_attachment() -> None:
    rows = bbsno_row(
        "361382",
        "2026년 8월 소통담당관 시책추진업무추진비",
        "소통담당관",
        "2026.09.14",
        '<a href="downloadBbsFileStr.do?atchmnflStr=A_B">pdf파일첨부</a>',
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.sd.go.kr/main/selectBbsNttList.do",
                    {"bbsNo": "172", "key": "1330", "pageIndex": "1"},
                    MENU + page(rows, 1),
                )
            ]
        )
    )
    found = list(BbsNoBoard(board(BBSNO, BbsNoBoard), transport).postings(never))
    assert len(found) == 1
    posting = found[0]
    assert posting.post_id == "361382"
    assert posting.posted == date(2026, 9, 14)
    assert posting.department == "소통담당관"
    assert [item.suffix for item in posting.attachments] == [".pdf"]
    assert posting.attachments[0].url.endswith("downloadBbsFileStr.do?atchmnflStr=A_B")
    assert posting.attachments[0].name == "361382-1.pdf"


def test_bbsno_board_ignores_post_links_from_another_board() -> None:
    # 메뉴에 다른 게시판의 게시글 링크가 섞여 있어도 줄로 읽지 않는다(구로·서초 실측).
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.sd.go.kr/main/selectBbsNttList.do",
                    {"bbsNo": "172", "key": "1330", "pageIndex": "1"},
                    MENU
                    + page(
                        '<tr><td><a href="./selectBbsNttView.do?bbsNo=999&amp;nttNo=5">딴 글</a>'
                        "</td><td>2026.09.14</td></tr>",
                        1,
                    ),
                )
            ]
        )
    )
    assert list(BbsNoBoard(board(BBSNO, BbsNoBoard), transport).postings(never)) == []


def test_bbsno_board_walks_every_page() -> None:
    rows = [
        bbsno_row(f"{index}", f"2026년 {index}월 업무추진비", "재무과", "2026.09.14", "")
        for index in (1, 2)
    ]
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.sd.go.kr/main/selectBbsNttList.do",
                    {"bbsNo": "172", "key": "1330", "pageIndex": str(number)},
                    page(rows[number - 1], 2),
                )
                for number in (1, 2)
            ]
        )
    )
    found = list(BbsNoBoard(board(BBSNO, BbsNoBoard), transport).postings(never))
    assert [item.post_id for item in found] == ["1", "2"]


def test_bbsno_board_reports_a_listing_without_a_page_count() -> None:
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.sd.go.kr/main/selectBbsNttList.do",
                    {"bbsNo": "172", "key": "1330", "pageIndex": "1"},
                    "<html><table>"
                    + bbsno_row("1", "가", "재무과", "2026.09.14", "")
                    + "</table></html>",
                )
            ]
        )
    )
    with pytest.raises(boards.UnreadableBoard):
        list(BbsNoBoard(board(BBSNO, BbsNoBoard), transport).postings(never))


def test_bbsno_detail_board_opens_the_post_for_its_attachment() -> None:
    listing = page(bbsno_row("194615", "2026년 8월 청소행정과", "청소행정과", "2026-09-11", ""), 1)
    detail = (
        '<html><a href="./downloadBbsFile.do?atchmnflNo=165149">'
        "pdf 문서 시책추진업무추진비 집행내역(26.8.).pdf</a></html>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.sd.go.kr/main/selectBbsNttList.do",
                    {"bbsNo": "172", "key": "1330", "pageIndex": "1"},
                    listing,
                ),
                at(
                    "https://www.sd.go.kr/main/selectBbsNttView.do",
                    {"bbsNo": "172", "nttNo": "194615"},
                    detail,
                ),
            ]
        )
    )
    found = list(BbsNoDetailBoard(board(BBSNO, BbsNoDetailBoard), transport).postings(never))
    assert [item.suffix for item in found[0].attachments] == [".pdf"]


def test_skipped_posts_never_open_the_detail() -> None:
    listing = page(bbsno_row("194615", "2026년 8월 청소행정과", "청소행정과", "2026-09-11", ""), 1)
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.sd.go.kr/main/selectBbsNttList.do",
                    {"bbsNo": "172", "key": "1330", "pageIndex": "1"},
                    listing,
                )
            ]
        )
    )
    found = list(BbsNoDetailBoard(board(BBSNO, BbsNoDetailBoard), transport).postings(always))
    assert found[0].attachments == ()
    assert [call[0] for call in transport.calls] == [
        "https://www.sd.go.kr/main/selectBbsNttList.do"
    ]


def test_a_post_without_an_attachment_is_still_a_posting() -> None:
    listing = page(bbsno_row("1", "2026년 8월 업무추진비", "재무과", "2026.09.14", ""), 1)
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.sd.go.kr/main/selectBbsNttList.do",
                    {"bbsNo": "172", "key": "1330", "pageIndex": "1"},
                    listing,
                )
            ]
        )
    )
    found = list(BbsNoBoard(board(BBSNO, BbsNoBoard), transport).postings(never))
    assert found[0].attachments == ()
    assert found[0].title == "2026년 8월 업무추진비"


def test_portal_board_reads_the_file_name_from_the_link_title() -> None:
    rows = (
        "<tr><td>7612</td>"
        '<td class="title"><a href="/portal/bbs/B0000030/view.do?nttId=768233&amp;menuNo=200140">'
        "2026년 8월 건설관리과 시책추진업무추진비</a></td><td>건설관리과</td>"
        '<td><a href="/portal/cmmn/file/fileDown.do?atchFileId=abc&amp;fileSn=1" '
        'title="시책추진업무추진비 집행내역(2026.8월).pdf"><i></i></a>'
        '<a class="viewer-link" href="/portal/singl/convert/convertToHtml.do?atchFileId=abc">'
        "바로보기</a></td>"
        "<td>2026-09-11</td></tr>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.yongsan.go.kr/portal/bbs/B0000030/list.do",
                    {"menuNo": "200140", "pageIndex": "1"},
                    "<html><body>총 7612 건 [1 / 1 페이지]<table>"
                    + rows
                    + "</table></body></html>",
                )
            ]
        )
    )
    found = list(PortalBoard(board(PORTAL, PortalBoard), transport).postings(never))
    assert [item.suffix for item in found[0].attachments] == [".pdf"]
    assert found[0].department == "건설관리과"


def test_portal_board_ignores_another_boards_post_link() -> None:
    rows = (
        "<tr><td>1</td>"
        '<td><a href="/portal/bbs/B0000075/view.do?nttId=476419&amp;menuNo=200022">딴 글</a></td>'
        "<td>2026-09-11</td></tr>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.yongsan.go.kr/portal/bbs/B0000030/list.do",
                    {"menuNo": "200140", "pageIndex": "1"},
                    "<html>[1 / 1 페이지]<table>" + rows + "</table></html>",
                )
            ]
        )
    )
    assert list(PortalBoard(board(PORTAL, PortalBoard), transport).postings(never)) == []


def test_gwangjin_reads_one_posting_per_list_item() -> None:
    items = "".join(
        f'<li><span class="num">{number}</span><div class="s">'
        f'<a href="/portal/bbs/B0000027/view.do?nttId=662579{number}&amp;menuNo=201646">'
        f'<span class="tit">2026년 8월 교통지도과 업무추진비</span></a>'
        f'<a href="/portal/cmmn/file/fileDown.do?atchFileId=x{number}&amp;fileSn=1" '
        f'title="2026년08월_업무추진비.pdf"><i></i></a></div>'
        f'<span class="dept">교통지도과</span><span class="date">2026-09-1{number}</span></li>'
        for number in (1, 2)
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.gwangjin.go.kr/portal/bbs/B0000027/list.do",
                    {"menuNo": "201646", "pageIndex": "1"},
                    "<html>Total : 5702 건 [ 1 / 1 pages ]"
                    f'<ul class="board-list">{items}</ul></html>',
                )
            ]
        )
    )
    found = list(GwangjinBoard(board(GWANGJIN, GwangjinBoard), transport).postings(never))
    assert [item.post_id for item in found] == ["6625791", "6625792"]
    assert [item.posted for item in found] == [date(2026, 9, 11), date(2026, 9, 12)]
    assert [item.attachments[0].suffix for item in found] == [".pdf", ".pdf"]


def test_jungnang_sends_the_listing_address_as_the_referer() -> None:
    rows = (
        "<tr><td>8523</td>"
        '<td><a href="/portal/bbs/view/B0000143/167663.do?searchCnd=">'
        "2026년 8월 업무추진비 집행내역(행정지원과)</a></td><td>행정지원과</td>"
        "<td>2608 업무추진비 집행내역.pdf</td>"
        '<td><a href="/portal/cmm/fms/FileDown.do?atchFileId=FILE_1&amp;fileSn=1">내려받기</a></td>'
        "<td>2026-09-12</td></tr>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.jungnang.go.kr/portal/bbs/list/B0000143.do",
                    {"menuNo": "200432", "pageIndex": "1"},
                    page(rows, 1),
                )
            ]
        )
    )
    found = list(JungnangBoard(board(JUNGNANG, JungnangBoard), transport).postings(never))
    attachment = found[0].attachments[0]
    assert found[0].post_id == "167663"
    assert attachment.suffix == ".pdf"
    assert attachment.referer == (
        "https://www.jungnang.go.kr/portal/bbs/list/B0000143.do?menuNo=200432"
    )


def jungnang_row(post_id: str, title: str, posted: str) -> str:
    """중랑 목록 한 줄. 첨부 링크를 목록에 싣는다(2026-09-14 실측)."""
    return (
        f"<tr><td>{post_id}</td>"
        f'<td><a href="/portal/bbs/view/B0000143/{post_id}.do">{title}</a></td>'
        f"<td>행정지원과</td><td>{post_id}.pdf</td>"
        f'<td><a href="/portal/cmm/fms/FileDown.do?atchFileId=FILE_{post_id}&amp;fileSn=1">'
        f"내려받기</a></td><td>{posted}</td></tr>"
    )


# 두 쪽짜리 중랑 목록. 대상 연도 게시글 하나와 그 밖의 게시글 둘이 두 쪽에 흩어져 있다.
JUNGNANG_PAGES = {
    "1": page(
        jungnang_row("167663", "2026년 1월 업무추진비", "2026-02-10")
        + jungnang_row("167001", "2025년 12월 업무추진비", "2025-12-20"),
        2,
    ),
    "2": page(jungnang_row("166000", "2025년 6월 업무추진비", "2025-07-10"), 2),
}


class PagedJungnang:
    """쪽 번호로 중랑 목록을 돌려주고 첨부는 PDF로 준다. `down`의 쪽은 끊긴 것처럼 실패한다."""

    def __init__(
        self,
        pages: dict[str, str],
        down: frozenset[str] = frozenset(),
        original: bytes = b"%PDF-1.4 body",
    ) -> None:
        self.pages = pages
        self.down = down
        self.original = original
        self.listed: list[str] = []

    def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
        if "FileDown.do" in url:
            return self.original
        current = params["pageIndex"]
        self.listed.append(current)
        if current in self.down:
            # #141에서 실측한 끊김 모양이다.
            raise TimeoutError("The read operation timed out")
        return self.pages[current].encode()


def test_listing_resumes_at_the_page_it_is_given() -> None:
    transport = PagedJungnang(JUNGNANG_PAGES)
    scraper = JungnangBoard(board(JUNGNANG, JungnangBoard), transport)
    scraper.resume(2, 3, lambda page: None)
    assert [item.post_id for item in scraper.postings(always)] == ["166000"]
    assert transport.listed == ["2"]
    # 앞선 실행이 걸러 낸 수를 이어서 센다.
    assert scraper.filtered == 3


def test_listing_settles_a_page_only_after_its_rows_are_consumed() -> None:
    settled: list[int] = []
    scraper = JungnangBoard(board(JUNGNANG, JungnangBoard), PagedJungnang(JUNGNANG_PAGES))
    scraper.resume(1, 0, settled.append)
    walk = scraper.postings(always)
    next(walk)
    next(walk)
    # 1쪽 마지막 게시글을 호출자가 아직 처리하고 있을 수 있으니 그 쪽을 끝냈다고 하지 않는다.
    assert settled == []
    assert next(walk).post_id == "166000"
    assert settled == [2]
    assert list(walk) == []
    # 마지막 쪽은 다음 쪽이 없다. 순회를 마쳤다는 것은 제너레이터가 끝났다는 것으로 안다.
    assert settled == [2]


def test_an_interrupted_jungnang_walk_resumes_where_it_stopped(tmp_path: Path) -> None:
    """#154: 목록이 도중에 끊기면 다음 실행은 끊긴 쪽부터 잇는다. 두 실행이 센 게시글을 합쳐
    1쪽부터 끝까지 훑은 실행과 같은 게시글 단위의 수를 낸다."""
    target = select_target(CITIES, "seoul", "seoul-jungnang")
    paths = Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "out")
    first = collect(target, paths, PagedJungnang(JUNGNANG_PAGES, down=frozenset({"2"})))
    assert first.empty_reason == "collection failures: seoul-jungnang/expenses=service-unavailable"
    assert first.uncollected_postings == 1

    resumed = PagedJungnang(JUNGNANG_PAGES)
    second = collect(target, paths, resumed)
    assert resumed.listed == ["2"]
    assert second.empty_reason is None
    assert second.uncollected_postings == 2
    assert [item.path.name for item in second.sources] == ["167663-1.pdf"]
    assert [(item.posted, item.title) for item in second.sources] == [
        (date(2026, 2, 10), "2026년 1월 업무추진비")
    ]

    # 끝까지 훑은 뒤의 실행은 다시 1쪽부터 훑고 같은 수를 낸다.
    again = PagedJungnang(JUNGNANG_PAGES)
    third = collect(target, paths, again)
    assert again.listed == ["1", "2"]
    assert third.uncollected_postings == 2


def test_a_jungnang_walk_keeps_the_pages_it_passed_before_asking_the_next(tmp_path: Path) -> None:
    """메모리 부족으로 프로세스가 통째로 죽으면 `finally`도 돌지 않는다. 이어 갈 실행이 넘긴
    쪽의 게시글을 목록 색인에서 세므로, 다음 쪽을 묻기 전에 색인이 디스크에 있어야 한다."""
    target = select_target(CITIES, "seoul", "seoul-jungnang")
    paths = Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "out")
    index = paths.board_dir(target, "seoul-jungnang", "expenses") / "listing.jsonl"
    indexed: list[str] = []

    class Watching(PagedJungnang):
        def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
            if params.get("pageIndex") == "2":
                lines = index.read_text(encoding="utf-8") if index.exists() else ""
                indexed.extend(json.loads(line)["post_id"] for line in lines.splitlines())
            return super().fetch(url, params, headers)

    collect(target, paths, Watching(JUNGNANG_PAGES))
    assert indexed == ["167001", "167663"]


def test_a_resumed_walk_still_reports_an_original_it_could_not_accept(tmp_path: Path) -> None:
    """사람이 봐야 하는 첨부는 끝에 한 번에 알린다. 그 첨부가 있는 쪽을 넘긴 것으로 기록하면
    이어 간 실행이 그 첨부를 다시 보지 않아, 서울이 받아들이지 않은 형식이 성공으로 숨는다."""
    target = select_target(CITIES, "seoul", "seoul-jungnang")
    paths = Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "out")
    # Referer 없는 중랑 첨부가 주는 것과 같은 오류 화면. PDF 게시판의 원본이 아니다.
    screen = b"<!DOCTYPE html><html><body>error</body></html>"
    with pytest.raises(AdapterFailure):
        collect(target, paths, PagedJungnang(JUNGNANG_PAGES, frozenset({"2"}), screen))
    with pytest.raises(AdapterFailure) as raised:
        collect(target, paths, PagedJungnang(JUNGNANG_PAGES, original=screen))
    assert raised.value.cause is FailureCause.UNSUPPORTED_FORMAT


@pytest.mark.parametrize(
    "recorded",
    [
        '{"filtered": 0, "next_page": 2, "url": "https://example.invalid/other"}',
        '{"filtered": 0, "next_page": 1, "url": "' + JUNGNANG + '"}',
        '{"filtered": -1, "next_page": 2, "url": "' + JUNGNANG + '"}',
        '{"filtered": true, "next_page": 2, "url": "' + JUNGNANG + '"}',
        '{"next_page": 2, "url": "' + JUNGNANG + '"}',
        '{"filtered": 0, "next_page": 2',
    ],
)
def test_a_walk_starts_over_when_the_progress_record_is_not_this_listings(
    tmp_path: Path, recorded: str
) -> None:
    target = select_target(CITIES, "seoul", "seoul-jungnang")
    paths = Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "out")
    directory = paths.board_dir(target, "seoul-jungnang", "expenses")
    directory.mkdir(parents=True)
    (directory / "listing.jsonl").write_text("", encoding="utf-8")
    (directory / "listing-progress.json").write_text(recorded, encoding="utf-8")
    transport = PagedJungnang(JUNGNANG_PAGES)
    collect(target, paths, transport)
    assert transport.listed == ["1", "2"]


def test_a_walk_starts_over_when_the_listing_index_is_gone(tmp_path: Path) -> None:
    """이어 간 실행은 넘긴 쪽의 게시글을 색인에서 센다. 색인이 없으면 셀 근거가 없으므로
    이어 가지 않는다 — 이어 가면 받지 않은 게시글이 조용히 적게 나온다."""
    target = select_target(CITIES, "seoul", "seoul-jungnang")
    paths = Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "out")
    collect(target, paths, PagedJungnang(JUNGNANG_PAGES, down=frozenset({"2"})))
    directory = paths.board_dir(target, "seoul-jungnang", "expenses")
    (directory / "listing.jsonl").unlink()
    transport = PagedJungnang(JUNGNANG_PAGES)
    output = collect(target, paths, transport)
    assert transport.listed == ["1", "2"]
    assert output.uncollected_postings == 2


def test_portal_detail_board_opens_the_post() -> None:
    rows = (
        "<tr><td>9093</td>"
        '<td><a href="/portal/bbs/B0000591/view.do?nttId=10757100&amp;menuNo=200209">'
        "2026. 7월 업무추진비 집행내역 공개</a></td><td>사당5동</td><td>2026-09-12</td></tr>"
    )
    detail = (
        '<html><a href="/portal/cmmn/file/fileDown.do?atchFileId=01f5&amp;fileSn=1">'
        "다운로드</a></html>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.dongjak.go.kr/portal/bbs/B0000591/list.do",
                    {"menuNo": "200209", "pageIndex": "1"},
                    page(rows, 1),
                ),
                at(
                    "https://www.dongjak.go.kr/portal/bbs/B0000591/view.do",
                    {"nttId": "10757100", "menuNo": "200209"},
                    detail,
                ),
            ]
        )
    )
    url = "https://www.dongjak.go.kr/portal/bbs/B0000591/list.do?menuNo=200209"
    found = list(PortalDetailBoard(board(url, PortalDetailBoard), transport).postings(never))
    # 이름을 밝히지 않은 첨부는 빈 확장자로 남기고, 형식은 매직 바이트가 정한다.
    assert [item.suffix for item in found[0].attachments] == [""]


def test_cbidx_board_builds_its_view_address_and_filters_the_banner() -> None:
    rows = (
        "<tr><td>12330</td>"
        '<td><a href="/site/seocho/ex/bbs/View.do?cbIdx=33&amp;bcIdx=411258">'
        "2026년 8월 공공인프라과 업무추진비 집행내역 공개</a></td>"
        "<td>공공인프라과</td><td>2026.09.08</td></tr>"
    )
    detail = (
        '<html><a href="/common/files/DownloadViewFile.do?cfIdx=CF0001">올바른쓰레기배출요령</a>'
        '<a href="/common/board/Download.do?bcIdx=411258&amp;cbIdx=33&amp;streFileNm=a.pdf">'
        "2026년_8월_업무추진비.pdf [107.19 KB]</a></html>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.seocho.go.kr/site/seocho/ex/bbs/List.do",
                    {"cbIdx": "33", "pageIndex": "1"},
                    page(rows, 1),
                ),
                at(
                    "https://www.seocho.go.kr/site/seocho/ex/bbs/View.do",
                    {"cbIdx": "33", "bcIdx": "411258"},
                    detail,
                ),
            ]
        )
    )
    found = list(CbIdxBoard(board(CBIDX, CbIdxBoard), transport).postings(never))
    assert [item.suffix for item in found[0].attachments] == [".pdf"]
    assert found[0].post_id == "411258"


def test_yangcheon_reads_the_javascript_title_and_post_number() -> None:
    rows = (
        "<tr><td>7483</td>"
        "<td>document.write(wdigm_title('2026년 4월 업무추진비 집행내역 공개'));"
        "<a href=\"#view\" onclick=\"doBbsFView('397','314286','16010100','314286');"
        'return false;">보기</a></td>'
        "<td>신월4동</td><td>2026.09.14</td></tr>"
    )
    detail = (
        '<html><a href="/common/board/Download.do?bcIdx=314286&amp;cbIdx=397'
        '&amp;streFileNm=42ac.hwpx">업무추진비_집행내역(2026.4월).hwpx [70.07 KB]</a></html>'
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.yangcheon.go.kr/site/yangcheon/ex/bbs/List.do",
                    {"cbIdx": "397", "pageIndex": "1"},
                    page(rows, 1),
                ),
                at(
                    "https://www.yangcheon.go.kr/site/yangcheon/ex/bbs/View.do",
                    {"cbIdx": "397", "bcIdx": "314286"},
                    detail,
                ),
            ]
        )
    )
    found = list(YangcheonBoard(board(YANGCHEON, YangcheonBoard), transport).postings(never))
    assert found[0].post_id == "314286"
    assert found[0].title == "2026년 4월 업무추진비 집행내역 공개"
    assert [item.suffix for item in found[0].attachments] == [".hwpx"]


def jongno_row(post: str, year: str, month: str, department: str, officer: str) -> str:
    return (
        f'<ul class="respon-td">'
        f"<li><span>번호</span><em>12058</em></li>"
        f"<li><span>년도</span><em><a href=\"javascript:viewMove('{post}');\">{year}</a></em></li>"
        f"<li><span>해당 월\t</span><em><a href=\"javascript:viewMove('{post}');\">{month}</a>"
        f"</em></li>"
        f"<li><span>작성부서</span><em>{department}</em></li>"
        f"<li><span>구분</span><em>시책추진</em></li>"
        f"<li><span>담당자</span><em>{officer}</em></li>"
        f'<li><span>파일</span><em><a href="/cmm/fms/FileDown.do?atchFileId=FILE_1&amp;fileSn=1">'
        f'<img alt="공개내역 파일" /></a></em></li>'
        f"<li><span>작성일</span><em>2026년 09월 10일</em></li>"
        f"</ul>"
    )


def test_jongno_reads_the_spending_month_and_leaves_the_officer_name_out() -> None:
    body = (
        "<html><body>"
        + jongno_row("257188", "2026", "09", "자치행정과", "김민진")
        + '<a href="javascript:pageMove(1);">1</a></body></html>'
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.jongno.go.kr/portal/bbs/selectBoardList.do",
                    {
                        "bbsId": "BBSMSTR_000000001167",
                        "menuId": "110210",
                        "pageIndex": "1",
                    },
                    body,
                )
            ]
        )
    )
    found = list(JongnoBoard(board(JONGNO, JongnoBoard), transport).postings(never))
    assert len(found) == 1
    posting = found[0]
    assert posting.post_id == "257188"
    assert posting.posted == date(2026, 9, 10)
    assert posting.title == "2026년 9월 업무추진비"
    assert posting.department == "자치행정과"
    # 담당자 실명은 목록에 있지만 산출물에 싣지 않는다.
    assert "김민진" not in posting.title + posting.department
    assert [item.suffix for item in posting.attachments] == [""]


def test_collection_stores_attachments_and_records_their_provenance(tmp_path: Path) -> None:
    listing = page(
        bbsno_row(
            "1",
            "2026년 1월 재무과 업무추진비",
            "재무과",
            "2026.02.03",
            '<a href="downloadBbsFile.do?atchmnflNo=9">pdf파일첨부</a>',
        ),
        1,
    )

    class Transport:
        def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
            if "downloadBbsFile.do" in url:
                return b"%PDF-1.4 body"
            return listing.encode()

    target = select_target(CITIES, "seoul", "seoul-seongdong")
    paths = Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "out")
    output = collect(target, paths, Transport())  # type: ignore[arg-type]
    assert [item.container for item in output.sources] == ["pdf"]
    source = output.sources[0]
    assert source.organization == "seoul-seongdong"
    assert source.posted == date(2026, 2, 3)
    assert source.title == "2026년 1월 재무과 업무추진비"
    assert source.department == "재무과"


def test_seoul_registry_declares_twenty_six_organizations() -> None:
    target = select_target(CITIES, "seoul", None)
    assert len(target.organizations) == 26
    assert len({item.slug for item in target.organizations}) == 26
    assert all(item.boards or item.hold_reason for item in target.organizations)
    assert select_target(CITIES, "seoul", "seoul-songpa").organizations[0].slug == "seoul-songpa"


def test_jongno_reads_its_page_count_from_the_last_page_button() -> None:
    body = (
        "<html><body>"
        + jongno_row("257188", "2026", "09", "자치행정과", "김민진")
        + "<div class=\"paging\"><a href='javascript:pageMove(2);'>2</a>"
        + "<a href='javascript:pageMove(603);' class='last'>맨끝</a></div></body></html>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.jongno.go.kr/portal/bbs/selectBoardList.do",
                    {"bbsId": "BBSMSTR_000000001167", "menuId": "110210", "pageIndex": str(number)},
                    body,
                )
                for number in range(1, 604)
            ]
        )
    )
    found = list(JongnoBoard(board(JONGNO, JongnoBoard), transport).postings(never))
    assert len(found) == 603
    assert len(transport.calls) == 603


def test_an_impossible_posting_date_does_not_stop_the_board() -> None:
    """중구 실측(2026-09-14): 게시판이 `2021-05-70`을 게시일로 올려 두었다.

    기관이 잘못 적은 한 줄 때문에 그 기관의 2026년 원본까지 0건이 되지 않게 한다.
    날짜로 읽지 않았다는 사실은 게시일 없음으로 남고, 대상 여부는 제목이 정한다.
    """
    rows = bbsno_row("1", "2021년 4월 행정지원과 업무추진비", "행정지원과", "2021-05-70", "")
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.sd.go.kr/main/selectBbsNttList.do",
                    {"bbsNo": "172", "key": "1330", "pageIndex": "1"},
                    page(rows, 1),
                )
            ]
        )
    )
    found = list(BbsNoBoard(board(BBSNO, BbsNoBoard), transport).postings(never))
    assert [item.posted for item in found] == [None]
    assert found[0].title == "2021년 4월 행정지원과 업무추진비"


def test_a_page_where_no_row_declares_a_date_stops_the_board() -> None:
    # 그 쪽의 어느 줄도 게시일을 밝히지 않으면 게시판 구조가 바뀐 것이므로 멈춘다.
    rows = (
        '<tr><td>1</td><td><a href="./selectBbsNttView.do?bbsNo=172&amp;nttNo=9">가</a></td>'
        "<td>재무과</td></tr>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.sd.go.kr/main/selectBbsNttList.do",
                    {"bbsNo": "172", "key": "1330", "pageIndex": "1"},
                    page(rows, 1),
                )
            ]
        )
    )
    with pytest.raises(boards.UnreadableBoard):
        list(BbsNoBoard(board(BBSNO, BbsNoBoard), transport).postings(never))


def test_a_single_row_with_an_empty_date_cell_does_not_stop_the_board() -> None:
    """동작 실측(2026-09-14): 2017년 줄 몇 개가 공개일 칸을 비워 두었다.

    같은 쪽의 다른 줄은 게시일을 밝히므로 구조가 바뀐 것이 아니다. 그 줄만 게시일
    없음으로 두고, 가를 근거가 없는 게시글은 받는다(`period.collects`).
    """
    rows = bbsno_row("1", "2017.5월 업무추진비 공개", "상도2동", "", "") + bbsno_row(
        "2", "2026년 1월 업무추진비 공개", "재무과", "2026-02-03", ""
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.sd.go.kr/main/selectBbsNttList.do",
                    {"bbsNo": "172", "key": "1330", "pageIndex": "1"},
                    page(rows, 1),
                )
            ]
        )
    )
    found = list(BbsNoBoard(board(BBSNO, BbsNoBoard), transport).postings(never))
    assert [item.post_id for item in found] == ["1", "2"]
    assert [item.posted for item in found] == [None, date(2026, 2, 3)]
