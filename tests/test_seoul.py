"""첨부를 내려받는 서울 계열 스크래퍼의 계약. 합성 목록으로 고정한다."""

from datetime import date
from pathlib import Path

import pytest

from deliciousmap import boards
from deliciousmap.collection import collect
from deliciousmap.paths import Paths
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
        + '<a href="?pageIndex=1">1</a></body></html>'
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
