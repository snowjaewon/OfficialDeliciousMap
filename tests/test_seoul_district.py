"""계열을 이루지 않는 서울 자치구 게시판의 계약. 합성 목록으로 고정한다."""

from datetime import date

import pytest

from deliciousmap import boards
from deliciousmap.registry import CITIES, Board, select_target
from deliciousmap.scrapers.seoul_district import (
    DobongBoard,
    GangdongBoard,
    GangnamBoard,
    GangseoBoard,
    JungguBoard,
    MapoBoard,
    NowonBoard,
)
from tests.test_seoul import FakeTransport, at, never

JUNG = "https://www.junggu.seoul.kr/content.do?cmsid=15383&exclude=Y"
DOBONG = "https://www.dobong.go.kr/bbs.asp?code=10008860"
NOWON = "https://www.nowon.kr/www/user/bbs/BD_selectBbsList.do?q_bbsCode=1012"
MAPO = "https://www.mapo.go.kr/site/main/board/expense/list"
GANGSEO = "https://www.gangseo.seoul.kr/gs030325"
GANGNAM = "https://www.gangnam.go.kr/board/B_000673/list.do?mid=ID05_04200502"
GANGDONG = "https://www.gangdong.go.kr/web/newportal/bbs/b_054"


def board(url: str, scraper: type) -> Board:
    return Board("expenses", url, scraper)


def wrap(rows: str, tail: str = "") -> str:
    return f"<html><body><table>{rows}</table>{tail}</body></html>"


def test_junggu_filters_the_council_rows_and_the_site_image() -> None:
    rows = (
        '<tr><td>7948</td><td><a href="/content.do?cmsid=15383&amp;mode=view&amp;cid=1474436341">'
        "2026년 8월 업무추진비 집행내역</a></td><td>세무관리과</td><td>2026-09-14</td></tr>"
        '<tr><td>7947</td><td><a href="/content.do?cmsid=15383&amp;mode=view&amp;cid=1474374816">'
        "2026년 8월 의회 업무추진비</a></td><td>의회사무과</td><td>2026-09-11</td></tr>"
    )
    detail = (
        '<html><a href="/cwsboard/board.do?mode=download&amp;bid=1&amp;cid=1&amp;fileIndex=0'
        '&amp;filename=logo.png">그림</a>'
        '<a href="/cwsboard/board.do?mode=download&amp;bid=1&amp;cid=1&amp;fileIndex=1'
        '&amp;filename=2026-08.xlsx">집행내역</a></html>'
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.junggu.seoul.kr/content.do",
                    {"cmsid": "15383", "exclude": "Y", "page2": "1"},
                    wrap(rows, '<a href="?page2=1">1</a>'),
                ),
                at(
                    "https://www.junggu.seoul.kr/content.do",
                    {"cmsid": "15383", "mode": "view", "cid": "1474436341"},
                    detail,
                ),
            ]
        )
    )
    scraper = JungguBoard(board(JUNG, JungguBoard), transport)
    found = list(scraper.postings(never))
    assert [item.post_id for item in found] == ["1474436341"]
    assert scraper.excluded == 1
    assert [item.suffix for item in found[0].attachments] == [".xlsx"]


def test_dobong_reads_its_asp_post_number_and_department() -> None:
    rows = (
        '<tr><td>7877</td><td><a href="./bbs.asp?bmode=D&amp;pcode=12746251&amp;code=10008860">'
        "2026년 8월 문화체육과 업무추진비</a></td><td>2026.09.14</td><td>문화체육과</td>"
        "<td>0</td></tr>"
    )
    detail = (
        '<html><a href="/WDB_common/include/download.asp?fcode=1&amp;bcode=2">'
        "2026년8월.xlsx</a></html>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.dobong.go.kr/bbs.asp",
                    {"code": "10008860", "intPage": "1"},
                    wrap(rows, '<a href="?intPage=1">1</a>'),
                ),
                at(
                    "https://www.dobong.go.kr/bbs.asp",
                    {"bmode": "D", "pcode": "12746251", "code": "10008860"},
                    detail,
                ),
            ]
        )
    )
    found = list(DobongBoard(board(DOBONG, DobongBoard), transport).postings(never))
    assert found[0].post_id == "12746251"
    assert found[0].posted == date(2026, 9, 14)
    assert found[0].department == "문화체육과"
    assert [item.suffix for item in found[0].attachments] == [".xlsx"]


def test_nowon_reads_its_page_count_and_stores_each_original_once() -> None:
    call = "fnRecntCnt(this, '1012', '20260910161420785');"
    rows = (
        "<tr><td>10165</td>"
        f'<td><a href="/component/file/ND_fileDownload.do?q_fileSn=308407&amp;q_fileId=a.pdf" '
        f'onclick="{call}">2026년 8월 업무추진비 사용내역 공개</a>'
        f'<a href="/component/file/ND_fileDownload.do?q_fileSn=308407&amp;q_fileId=a.pdf" '
        f'onclick="{call}">첨부파일</a></td>'
        "<td>기획예산과</td><td>2026-09-10</td></tr>"
    )
    body = wrap(rows, '<script>var lastPageNum = "3";</script>')
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.nowon.kr/www/user/bbs/BD_selectBbsList.do",
                    {"q_bbsCode": "1012", "q_currPage": str(number)},
                    body,
                )
                for number in (1, 2, 3)
            ]
        )
    )
    found = list(NowonBoard(board(NOWON, NowonBoard), transport).postings(never))
    assert len(found) == 3
    # 같은 원본을 이름 링크와 아이콘 링크로 두 번 싣지만 한 번만 받는다.
    assert [item.suffix for item in found[0].attachments] == [".pdf"]
    assert found[0].department == "기획예산과"


def test_nowon_reports_a_listing_without_its_page_count() -> None:
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.nowon.kr/www/user/bbs/BD_selectBbsList.do",
                    {"q_bbsCode": "1012", "q_currPage": "1"},
                    wrap("<tr><td>a</td><td>2026-09-10</td></tr>"),
                )
            ]
        )
    )
    with pytest.raises(boards.UnreadableBoard):
        list(NowonBoard(board(NOWON, NowonBoard), transport).postings(never))


def test_mapo_reads_the_listing_download() -> None:
    rows = (
        '<tr><td>7374</td><td><a href="/site/main/board/expense/277872?cp=1">'
        "2026년 8월 주택과 업무추진비 집행내역</a></td><td>주택과</td><td></td>"
        '<td><a href="/site/main/file/download/uu/440429bee33c4ebda275687aafe5f716">받기</a></td>'
        "<td>2026.09.11</td></tr>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.mapo.go.kr/site/main/board/expense/list",
                    {"cp": "1"},
                    wrap(rows, '<a href="?cp=1">1</a>'),
                )
            ]
        )
    )
    found = list(MapoBoard(board(MAPO, MapoBoard), transport).postings(never))
    assert found[0].post_id == "277872"
    assert found[0].department == "주택과"
    # 이름을 밝히지 않는 uuid 주소라 형식은 매직 바이트가 정한다.
    assert [item.suffix for item in found[0].attachments] == [""]


def test_gangseo_uses_the_measured_department_column() -> None:
    rows = (
        '<tr><td>9527</td><td><a href="/gs030325/323835?curPage=">'
        "2026년 8월 가양1동 업무추진비 집행내역 공개</a></td><td>첨부파일</td>"
        "<td>가양1동</td><td>2026-09-14</td><td>1</td></tr>"
    )
    detail = (
        '<html><a href="/comm/getFile?srvcId=BBSTY1&amp;upperNo=abc&amp;fileTy=ATTACH'
        '&amp;fileNo=def">2026년 8월.pdf</a>'
        '<a href="/comm/filePreview?srvcId=BBSTY1&amp;upperNo=abc">미리보기</a></html>'
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.gangseo.seoul.kr/gs030325",
                    {"curPage": "1"},
                    wrap(rows, '<a href="?curPage=1">1</a>'),
                ),
                at(
                    "https://www.gangseo.seoul.kr/gs030325/323835",
                    {"curPage": ""},
                    detail,
                ),
            ]
        )
    )
    found = list(GangseoBoard(board(GANGSEO, GangseoBoard), transport).postings(never))
    assert found[0].department == "가양1동"
    assert [item.suffix for item in found[0].attachments] == [".pdf"]


def test_gangnam_reads_the_listing_number_and_skips_the_preview_link() -> None:
    rows = (
        "<tr><td>9367</td><td>2026년 8월 업무추진비 집행내역 공개</td>"
        '<td><a href="/file/1/get/55b1d1e5-807c-480a-8fe3-e68ffd8f1736/download.do">받기</a>'
        '<a href="/file/1/get/55b1d1e5-807c-480a-8fe3-e68ffd8f1736/preview.do">미리보기</a></td>'
        "<td>사회보장과</td><td>2026-09-14</td></tr>"
        "<tr><td>9366</td><td>2026년 8월 의회 업무추진비</td>"
        '<td><a href="/file/1/get/aaaaaaaa-807c-480a-8fe3-e68ffd8f1736/download.do">받기</a></td>'
        "<td>의회사무국</td><td>2026-09-13</td></tr>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.gangnam.go.kr/board/B_000673/list.do",
                    {"mid": "ID05_04200502", "pgno": "1"},
                    wrap(rows, '<a onclick="selectPage_func(937)">937</a>'),
                )
            ]
            + [
                at(
                    "https://www.gangnam.go.kr/board/B_000673/list.do",
                    {"mid": "ID05_04200502", "pgno": str(number)},
                    wrap("", '<a onclick="selectPage_func(937)">937</a>'),
                )
                for number in range(2, 938)
            ]
        )
    )
    scraper = GangnamBoard(board(GANGNAM, GangnamBoard), transport)
    found = list(scraper.postings(never))
    assert [item.post_id for item in found] == ["9367"]
    assert scraper.excluded == 1
    assert [item.suffix for item in found[0].attachments] == [""]
    assert found[0].attachments[0].url.endswith("/download.do")
    assert found[0].department == "사회보장과"


def test_gangdong_opens_the_post_for_its_attachment() -> None:
    rows = (
        '<tr><td>3981</td><td><a href="/web/newportal/bbs/b_054/157567?cp=1&amp;pageSize=15">'
        "2026년 8월 보건위생과 업무추진비 집행내역</a></td><td>보건위생과</td>"
        "<td>2026-09-14</td><td>3</td></tr>"
    )
    detail = (
        '<html><a href="/web/newportal/file/download/uu/8217ebf13cda4b7b8b8c6ee0bc20a693">'
        "2026년 8월.pdf</a></html>"
    )
    transport = FakeTransport(
        dict(
            [
                at(
                    "https://www.gangdong.go.kr/web/newportal/bbs/b_054",
                    {"cp": "1"},
                    wrap(rows, '<a href="?cp=1">1</a>'),
                ),
                at(
                    "https://www.gangdong.go.kr/web/newportal/bbs/b_054/157567",
                    {"cp": "1", "pageSize": "15"},
                    detail,
                ),
            ]
        )
    )
    found = list(GangdongBoard(board(GANGDONG, GangdongBoard), transport).postings(never))
    assert found[0].post_id == "157567"
    assert found[0].department == "보건위생과"
    assert [item.suffix for item in found[0].attachments] == [".pdf"]


def test_gangbuk_is_held_for_its_bot_check() -> None:
    target = select_target(CITIES, "seoul", "seoul-gangbuk")
    organization = target.organizations[0]
    assert organization.hold_reason == "bot_blocked"
    assert organization.boards == ()
