"""대구 게시판의 계약. 2026-09-17 실측한 목록·본문·첨부 모양을 합성 fixture로 고정한다."""

from pathlib import Path

import pytest

from deliciousmap import boards
from deliciousmap.collection import collect
from deliciousmap.paths import Paths
from deliciousmap.registry import CITIES, Board, select_target
from deliciousmap.scrapers.daegu import (
    CouncilFilteredYhLibBoard,
    GunwiBoard,
    IcmsBoard,
    OfficialTableBoard,
)
from tests.test_busan import FakeTransport, response


def board(url: str, scraper: type) -> Board:
    return Board("expenses", url, scraper)


def never(post_id: str, posted: object) -> bool:
    return False


# ICMS 계열 — 시청·남구·달성군.
CITY_INDEX = "https://www.daegu.go.kr/index.do"
CITY_BOARD = f"{CITY_INDEX}?menu_id=00000084&postPerPage=50"
CITY_DOWN = "https://www.daegu.go.kr/icms/cmm/fms/FileDown.do"
LIST_PARAMS = {"menu_id": "00000084", "postPerPage": "50"}


def icms_row(ntt_id: str, title: str, department: str, posted: str, file_id: str) -> str:
    """실측한 ICMS 목록 행. 첨부 칸에는 내려받기 함수를 정의하는 `<script>`가 줄마다 있다."""
    return (
        f'<tr><td data-table-type="number"> 5234 </td>'
        f'<td class="tal" data-table-type="subject"><a href="javascript:;" '
        f"onclick=\"fn_icms_navi_common('view', '{ntt_id}');return false;\">{title}</a></td>"
        f'<td data-table-type="hide_t">{department}</td>'
        f'<td data-table-type="date">{posted}</td>'
        '<td data-table-type="hide_t"><script>function fn_egov_downFile(atchFileId, fileSn){ '
        'window.open("/icms/cmm/fms/FileDown.do?atchFileId="+atchFileId); }</script>'
        f"<a href=\"javascript:fn_egov_downFile('{file_id}','0')\">"
        f"<img src='/ico_file_xlsx.jpg' alt='{title}.xlsx [11758 byte]'></a></td>"
        '<td data-table-type="hide_t">10</td></tr>'
    )


def icms_listing(*rows: str, last_page: int = 1, department: str = "부서명") -> str:
    """실측한 ICMS 목록. 게시판 번호는 폼의 숨은 칸에, 쪽 수는 `?pageIndex=N` 주소에 있다."""
    pages = "".join(
        f'<a href="?pageIndex={page}" onclick="fn_icms_navi_list({page},\'\');return false;">'
        f"{page}</a>"
        for page in range(1, last_page + 1)
    )
    return (
        '<html><body><form name="board" id="board" method="post">'
        '<input type="hidden" name="menu_id" value="00000084" />'
        '<input type="hidden" name="bbsId" value="BBS_00040" />'
        "<table><thead><tr><th>번호</th><th>제목</th>"
        f"<th>{department}</th><th>등록일</th><th>첨부</th><th>조회</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f'<div class="pagination">{pages}'
        f'<a href="?pageIndex={last_page}" class="page_nextend">마지막</a></div>'
        "</form></body></html>"
    )


def icms_detail(*files: tuple[str, str, str]) -> str:
    """실측한 ICMS 본문. 내려받기마다 같은 파일의 미리보기 링크가 붙는다."""
    links = "".join(
        f"<div><a href=\"javascript:fn_egov_downFile('{file_id}','{serial}')\" "
        f'class="link_button txt download" title="다운로드"><span>{name}</span></a>'
        f"<a title=\"{name} 새창\" href=\"javascript:filePreview('{file_id}','{serial}')\">"
        "미리보기</a></div>"
        for file_id, serial, name in files
    )
    return (
        '<html><body><form name="board"><input type="hidden" name="nttId" value="1">'
        f"<dl><dt>첨부파일목록</dt><dd>{links}</dd></dl></form></body></html>"
    )


def city_view(ntt_id: str) -> tuple[str, dict[str, str]]:
    return CITY_INDEX, {
        "menu_id": "00000084",
        "menu_link": "/icms/bbs/selectBoardArticle.do",
        "bbsId": "BBS_00040",
        "nttId": ntt_id,
    }


def test_icms_board_reads_the_listing_and_every_detail_attachment() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_INDEX,
                    {**LIST_PARAMS, "pageIndex": "1"},
                    icms_listing(
                        icms_row(
                            "822458",
                            "2026년 8월분 업무추진비 집행내역(기획조정실장, 정책기획관)",
                            "정책기획관",
                            "2026-09-07",
                            "FILE_000000000720279",
                        )
                    ),
                ),
                response(
                    *city_view("822458"),
                    icms_detail(
                        ("FILE_000000000720279", "0", "기획조정실장.xlsx"),
                        ("FILE_000000000720279", "1", "★정책기획관.pdf&nbsp;[12339&nbsp;byte]"),
                    ),
                ),
            ]
        )
    )
    postings = list(IcmsBoard(board(CITY_BOARD, IcmsBoard), transport).postings(never))
    assert [item.post_id for item in postings] == ["822458"]
    posting = postings[0]
    assert posting.title == "2026년 8월분 업무추진비 집행내역(기획조정실장, 정책기획관)"
    assert posting.department == "정책기획관"
    assert posting.posted is not None and posting.posted.isoformat() == "2026-09-07"
    assert [(item.file_id, item.suffix) for item in posting.attachments] == [
        ("1", ".xlsx"),
        ("2", ".pdf"),
    ]
    assert posting.attachments[1].url == (f"{CITY_DOWN}?atchFileId=FILE_000000000720279&fileSn=1")
    view_url, view_params = city_view("822458")
    assert posting.attachments[0].page_url == boards.address(view_url, view_params)


def test_icms_board_reads_the_extension_before_the_size_and_the_icon() -> None:
    """남구 본문은 이름·크기 뒤에 아이콘(`alt="첨부파일"`)을 같은 링크 안에 둔다."""
    name = '2026년 8월 보건행정과.xlsx&nbsp;[16934&nbsp;byte] <img alt="첨부파일" src="/ico.jpg">'
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_INDEX,
                    {**LIST_PARAMS, "pageIndex": "1"},
                    icms_listing(icms_row("7", "2026년 8월", "보건행정과", "2026-09-15", "F7")),
                ),
                response(*city_view("7"), icms_detail(("72FDFC6C", "202E3B74", name))),
            ]
        )
    )
    postings = list(IcmsBoard(board(CITY_BOARD, IcmsBoard), transport).postings(never))
    assert [item.suffix for item in postings[0].attachments] == [".xlsx"]


def test_icms_board_reads_the_department_column_by_its_header() -> None:
    """남구는 부서 열 이름이 `담당부서`다. 열 차례가 아니라 머리글로 찾는다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_INDEX,
                    {**LIST_PARAMS, "pageIndex": "1"},
                    icms_listing(
                        icms_row(
                            "192586", "2026년 8월 보건행정과", "보건행정과", "2026-09-15", "A1"
                        ),
                        department="담당부서",
                    ),
                ),
            ]
        )
    )
    postings = list(IcmsBoard(board(CITY_BOARD, IcmsBoard), transport).postings(lambda *_: True))
    assert [(item.department, item.attachments) for item in postings] == [("보건행정과", ())]


def test_icms_board_walks_every_page_and_skips_the_detail_of_skipped_postings() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_INDEX,
                    {**LIST_PARAMS, "pageIndex": "1"},
                    icms_listing(
                        icms_row("2", "2026년 1월 집행내역", "총무과", "2026-02-03", "F2"),
                        last_page=2,
                    ),
                ),
                response(
                    CITY_INDEX,
                    {**LIST_PARAMS, "pageIndex": "2"},
                    icms_listing(
                        icms_row("1", "2025년 12월 집행내역", "총무과", "2025-12-30", "F1"),
                        last_page=2,
                    ),
                ),
                response(*city_view("2"), icms_detail()),
            ]
        )
    )
    postings = list(
        IcmsBoard(board(CITY_BOARD, IcmsBoard), transport).postings(
            lambda post_id, posted: post_id == "1"
        )
    )
    assert [(item.post_id, item.attachments) for item in postings] == [("2", ()), ("1", ())]
    assert [params.get("pageIndex") for _, params in transport.calls] == ["1", None, "2"]


def test_icms_board_filters_the_council_secretariat() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_INDEX,
                    {**LIST_PARAMS, "pageIndex": "1"},
                    icms_listing(
                        icms_row("3", "2026년 8월 업무추진비", "의회사무국", "2026-09-01", "F3"),
                        icms_row("4", "2026년 8월 의회사무국", "총무과", "2026-09-01", "F4"),
                    ),
                ),
            ]
        )
    )
    scraper = IcmsBoard(board(CITY_BOARD, IcmsBoard), transport)
    assert list(scraper.postings(never)) == []
    assert scraper.filtered == 2


def test_icms_board_refuses_a_listing_without_its_board_number() -> None:
    body = icms_listing(icms_row("5", "제목", "총무과", "2026-09-01", "F5")).replace(
        'name="bbsId"', 'name="other"'
    )
    transport = FakeTransport(dict([response(CITY_INDEX, {**LIST_PARAMS, "pageIndex": "1"}, body)]))
    with pytest.raises(boards.UnreadableBoard):
        list(IcmsBoard(board(CITY_BOARD, IcmsBoard), transport).postings(never))


def test_icms_board_refuses_an_unusable_attachment_identifier() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_INDEX,
                    {**LIST_PARAMS, "pageIndex": "1"},
                    icms_listing(icms_row("6", "제목", "총무과", "2026-09-01", "F6")),
                ),
                response(*city_view("6"), icms_detail(("../etc", "0", "a.xlsx"))),
            ]
        )
    )
    with pytest.raises(boards.UnreadableBoard):
        list(IcmsBoard(board(CITY_BOARD, IcmsBoard), transport).postings(never))


def test_icms_board_requires_a_menu_address() -> None:
    with pytest.raises(ValueError):
        IcmsBoard(board(f"{CITY_INDEX}?postPerPage=50", IcmsBoard), FakeTransport({}))


# yhLib 계열 — 동구·서구. 서구는 게시글 번호를 data 속성이 아니라 링크 주소에 싣는다.
SEO_LIST = "https://www.dgs.go.kr/portal/board/post/list.do"
SEO_VIEW = "https://www.dgs.go.kr/portal/board/post/view.do"
SEO_PARAMS = {"bcIdx": "511", "mid": "0502030000"}


def seo_row(idx: str, title: str, department: str) -> str:
    return (
        '<tr><td class="list_num"> 4589 </td><td class="list_tit">'
        f'<a href="/portal/board/post/view.do?bcIdx=511&mid=0502030000&idx={idx}" '
        f'title="게시글 상세 열람"> {title} </a></td>'
        '<td class="list_file"><img src="/xls.gif" alt="엑셀 파일"/></td>'
        f'<td class="list_write"> {department} </td><td class="list_date"> 2026-09-10 </td>'
        '<td class="list_hit"> 19 </td></tr>'
    )


def test_yhlib_board_reads_the_link_address_and_filters_the_council() -> None:
    row = seo_row("252051", "2026년 8월 보건행정과장 업무추진비 집행내역", "보건행정과") + seo_row(
        "252052", "2026년 8월 의회사무국장 업무추진비 집행내역", "의회사무국"
    )
    listing = (
        f"<html><body><table><tbody>{row}</tbody></table>"
        '<a href="#" onclick="goPage(1); return false; " class="btn_end">끝</a></body></html>'
    )
    detail = (
        "<html><body><a href=\"#\" onclick=\"yhLib.file.download('4663FF60','125EB0AE'); "
        'return false;" class="download"><span class="mR5"> 2026년 8월(보건행정과장).xlsx '
        '</span><span class="file_size">[0.02MB]</span></a></body></html>'
    )
    transport = FakeTransport(
        dict(
            [
                response(SEO_LIST, {**SEO_PARAMS, "page": "1"}, listing),
                response(SEO_VIEW, {**SEO_PARAMS, "idx": "252051"}, detail),
            ]
        )
    )
    url = boards.address(SEO_LIST, SEO_PARAMS)
    scraper = CouncilFilteredYhLibBoard(board(url, CouncilFilteredYhLibBoard), transport)
    postings = list(scraper.postings(never))
    assert [(item.post_id, item.department) for item in postings] == [("252051", "보건행정과")]
    assert scraper.filtered == 1
    assert [item.url for item in postings[0].attachments] == [
        "https://www.dgs.go.kr/common/file/download.do?atchFileId=4663FF60&fileSn=125EB0AE"
    ]


# 수성구 — 게시판이 아니라 해마다 대상자별 월 집행표를 여는 화면이다.
SUSEONG_INDEX = "https://www.suseong.kr/index.do"
SUSEONG_BOARD = f"{SUSEONG_INDEX}?menu_id=00042650"
SUSEONG_DOWN = "https://www.suseong.kr/icms/cmm/fms/FileDown.do"
SUSEONG_LINK = "/front/businessOperatingExpense/icmsOperatingExpenseFront.do"


def official_page(selected: str, *months: tuple[str, str, str]) -> str:
    """실측한 수성구 집행표. 대상자 선택 상자와 월마다 건수·금액 두 줄이 있다."""
    options = "".join(
        f'<option value="{name}"{" selected" if name == selected else ""}>{name}</option>'
        for name in ("구청장", "의회사무국장", "행정지원과장", "------------------", "범어1동장")
    )
    rows = "".join(
        f"<tr><th rowspan='2'>{month}</th><th>건수</th><td>3</td><td rowspan='2'>"
        + (
            f'<input type="hidden" name="atchFileId" value="{file_id}">'
            f"<a href=\"javascript:fn_egov_downFile('{file_id}','0')\">"
            f"\n\t\t{name}&nbsp;[16618&nbsp;byte]\n\t</a>"
            f"<a href=\"javascript:filePreview('{file_id}','0')\">미리보기</a>"
            if file_id
            else ""
        )
        + "</td></tr><tr><th>금액</th><td>16,078</td></tr>"
        for month, file_id, name in months
    )
    return (
        '<html><body><form id="icmsBoeVO" name="icmsBoeVO" method="post">'
        '<input type="hidden" name="search_year" value="2026">'
        f'<select name="search_target" id="search_target">{options}</select>'
        "<table><caption>업무추진비 집행액 집계</caption><tr><td>80,240</td></tr></table>"
        "<p>월별집행내역</p><table><tr><th>내용</th><th>계</th></tr>"
        f"{rows}<tr><th>계</th><th>건수</th><td>278</td></tr></table></form></body></html>"
    )


def official(target: str) -> dict[str, str]:
    return {"menu_id": "00042650", "menu_link": SUSEONG_LINK, "search_target": target}


def official_transport(pages: dict[str, str]) -> FakeTransport:
    """첫 화면이 대상자 목록을 밝히고, 대상자마다 같은 화면을 그 사람으로 다시 연다."""
    return FakeTransport(
        dict(
            [
                response(SUSEONG_INDEX, {"menu_id": "00042650"}, pages["구청장"]),
                *(response(SUSEONG_INDEX, official(name), page) for name, page in pages.items()),
            ]
        )
    )


def test_official_table_board_takes_each_official_month_as_a_posting() -> None:
    transport = official_transport(
        {
            "구청장": official_page(
                "구청장",
                ("1월", "FILE_00000140205GNNF", "2026년 1월 업무추진비공개(구청장).xlsx"),
                ("4월", "", ""),
            ),
            "의회사무국장": official_page(
                "의회사무국장", ("1월", "FILE_9", "2026년 1월 업무추진비공개(의회사무국장).xlsx")
            ),
            "행정지원과장": official_page(
                "행정지원과장",
                ("2월", "FILE_00000140206SZNQ", "2026년 2월 업무추진비공개(행정지원과장).xlsx"),
            ),
            "범어1동장": official_page("범어1동장"),
        }
    )
    scraper = OfficialTableBoard(board(SUSEONG_BOARD, OfficialTableBoard), transport)
    postings = list(scraper.postings(never))
    assert [(item.post_id, item.title, item.department, item.posted) for item in postings] == [
        ("FILE00000140205GNNF", "2026년 1월 업무추진비공개(구청장)", "구청장", None),
        ("FILE00000140206SZNQ", "2026년 2월 업무추진비공개(행정지원과장)", "행정지원과장", None),
    ]
    assert scraper.filtered == 1
    attachment = postings[0].attachments[0]
    assert (attachment.file_id, attachment.suffix) == ("1", ".xlsx")
    assert attachment.url == f"{SUSEONG_DOWN}?atchFileId=FILE_00000140205GNNF&fileSn=0"
    assert attachment.page_url == boards.address(SUSEONG_INDEX, official("구청장"))


def test_official_table_board_refuses_a_page_whose_official_is_not_the_one_asked() -> None:
    """화면이 고른 대상자를 밝히지 않으면 다른 사람의 표를 그 사람 것으로 적게 된다."""
    mayor = official_page("구청장")
    transport = official_transport({"구청장": mayor, "의회사무국장": mayor})
    with pytest.raises(boards.UnreadableBoard):
        list(
            OfficialTableBoard(board(SUSEONG_BOARD, OfficialTableBoard), transport).postings(never)
        )


def test_official_table_board_skips_a_month_already_collected() -> None:
    transport = official_transport(
        {
            "구청장": official_page("구청장", ("1월", "FILE_1", "2026년 1월(구청장).xlsx")),
            "의회사무국장": official_page("의회사무국장"),
            "행정지원과장": official_page("행정지원과장"),
            "범어1동장": official_page("범어1동장"),
        }
    )
    scraper = OfficialTableBoard(board(SUSEONG_BOARD, OfficialTableBoard), transport)
    assert [(item.post_id, item.attachments) for item in scraper.postings(lambda *_: True)] == [
        ("FILE1", ())
    ]


# 군위군 — 자체 CMS. 목록 주소가 조회수를 올린 뒤 `cmd=258` 본문으로 넘긴다.
GUNWI_PAGE = "https://www.gunwi.go.kr/ko/page.do"


def gunwi_listing(*rows: tuple[str, str, str, str], total_pages: int = 1) -> str:
    items = "".join(
        f'<tr><td class="num">310</td><td class="taL subject"><a href="?srchVote=-1&amp;'
        f'srchOrder=&amp;mnu_uid=160&amp;&amp;bod_uid={uid}&amp;pageNo=1&amp;cmd=2">'
        f'<span class="bod_title">{title}</span></a></td><td> {writer} </td>'
        f'<td class="date"> {posted} </td><td class="file"></td><td class="hit">15</td></tr>'
        for uid, title, writer, posted in rows
    )
    return (
        f"<html><body><p>전체 게시물 310 / 전체 페이지 {total_pages}</p>"
        '<table><thead><tr><th class="num">번호</th><th class="subject">제목</th>'
        '<th class="writer">작성자</th><th class="date">작성일</th><th class="file">파일</th>'
        f'<th class="hit">조회</th></tr></thead><tbody>{items}</tbody>'
        "</table></body></html>"
    )


def gunwi_detail(*files: tuple[str, str]) -> str:
    links = "".join(
        f'<p class="file"><a title="{name} 파일 다운로드" href="/board_download.do?file_uid={uid}">'
        f' {name} </a><a title="{name} 미리보기 새창" href="#self" '
        f'onclick="openViewFiles({uid})">[미리보기]</a></p>'
        for uid, name in files
    )
    return f'<html><body><div class="boardView"><ul><li>{links}</li></ul></div></body></html>'


def test_gunwi_board_reads_the_listing_and_the_detail_downloads() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    GUNWI_PAGE,
                    {"mnu_uid": "160", "pageNo": "1"},
                    gunwi_listing(
                        ("141036", "2026년 2분기 군위군수 업무추진비", "총무과", "2026-07-30"),
                        (
                            "141037",
                            "2026년 2분기 의회사무과 업무추진비",
                            "의회사무과",
                            "2026-07-30",
                        ),
                        total_pages=2,
                    ),
                ),
                response(
                    GUNWI_PAGE,
                    {"mnu_uid": "160", "bod_uid": "141036", "cmd": "258"},
                    gunwi_detail(("180131", "군위군수(기관).pdf"), ("180132", "군위군수.xlsx")),
                ),
                response(
                    GUNWI_PAGE,
                    {"mnu_uid": "160", "pageNo": "2"},
                    gunwi_listing(
                        ("100", "2012년 업무추진비", "총무과", "2012-01-30"), total_pages=2
                    ),
                ),
            ]
        )
    )
    scraper = GunwiBoard(board(f"{GUNWI_PAGE}?mnu_uid=160", GunwiBoard), transport)
    postings = list(scraper.postings(lambda post_id, posted: post_id == "100"))
    assert [(item.post_id, item.department) for item in postings] == [
        ("141036", "총무과"),
        ("100", "총무과"),
    ]
    assert scraper.filtered == 1
    assert [(item.file_id, item.suffix, item.url) for item in postings[0].attachments] == [
        ("180131", ".pdf", "https://www.gunwi.go.kr/board_download.do?file_uid=180131"),
        ("180132", ".xlsx", "https://www.gunwi.go.kr/board_download.do?file_uid=180132"),
    ]
    assert postings[0].attachments[0].page_url == (
        f"{GUNWI_PAGE}?mnu_uid=160&bod_uid=141036&cmd=258"
    )


def test_gunwi_board_refuses_a_listing_without_a_page_count() -> None:
    body = gunwi_listing(("1", "제목", "총무과", "2026-01-01")).replace("전체 페이지 1", "")
    transport = FakeTransport(dict([response(GUNWI_PAGE, {"mnu_uid": "160", "pageNo": "1"}, body)]))
    with pytest.raises(boards.UnreadableBoard):
        list(
            GunwiBoard(board(f"{GUNWI_PAGE}?mnu_uid=160", GunwiBoard), transport).postings(
                lambda *_: True
            )
        )


# 레지스트리.
def test_daegu_registry_declares_the_city_and_nine_districts() -> None:
    target = select_target(CITIES, "daegu", None)
    assert [(org.slug, len(org.boards), org.hold_reason) for org in target.organizations] == [
        ("daegu-city", 1, None),
        ("daegu-jung", 0, "bot_blocked"),
        ("daegu-dong", 1, None),
        ("daegu-seo", 1, None),
        ("daegu-nam", 1, None),
        ("daegu-buk", 0, "bot_blocked"),
        ("daegu-suseong", 1, None),
        ("daegu-dalseo", 0, "bot_blocked"),
        ("daegu-dalseong", 1, None),
        ("daegu-gunwi", 1, None),
    ]


@pytest.mark.parametrize("org", ["daegu-jung", "daegu-buk", "daegu-dalseo"])
def test_daegu_held_organizations_are_never_requested(tmp_path: Path, org: str) -> None:
    class Unused:
        def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
            raise AssertionError("a held organization must not be requested")

    output = collect(
        select_target(CITIES, "daegu", org),
        Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "output"),
        Unused(),  # type: ignore[arg-type]
    )
    assert output.sources == ()
    assert output.empty_reason == f"collection held: {org}=bot_blocked"


def test_daegu_city_collection_stores_the_original(tmp_path: Path) -> None:
    """`--org daegu-city` 수집이 원본을 받아 기관 장부에 남긴다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_INDEX,
                    {**LIST_PARAMS, "pageIndex": "1"},
                    icms_listing(
                        icms_row("822458", "2026년 8월분", "정책기획관", "2026-09-07", "F1"),
                        icms_row("1", "2025년 8월분", "정책기획관", "2025-09-07", "F0"),
                    ),
                ),
                response(*city_view("822458"), icms_detail(("F1", "0", "8월분.pdf"))),
                ((CITY_DOWN, frozenset({"atchFileId": "F1", "fileSn": "0"}.items())), b"%PDF-1.7"),
            ]
        )
    )
    output = collect(
        select_target(CITIES, "daegu", "daegu-city"),
        Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "output"),
        transport,
    )
    assert [(item.board, item.container) for item in output.sources] == [("expenses", "pdf")]
    assert output.empty_reason is None
