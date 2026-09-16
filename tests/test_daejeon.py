"""대전 자치구 게시판의 계약. 2026-09-17 실측한 목록·본문·첨부 모양을 합성 fixture로 고정한다."""

from pathlib import Path

import pytest

from deliciousmap import boards
from deliciousmap.collection import collect
from deliciousmap.paths import Paths
from deliciousmap.registry import CITIES, Board, select_target
from deliciousmap.scrapers.daejeon import ArticleBoard, BbsBoard, DptBoard, ZipBbsBoard
from tests.test_busan import FakeTransport, response


def board(url: str, scraper: type) -> Board:
    return Board("expenses", url, scraper)


def never(post_id: str, posted: object) -> bool:
    return False


# eGov `/bbs` 계열 — 중구·서구·유성구.
JUNG_LIST = "https://www.djjunggu.go.kr/bbs/BBSMSTR_000000000104/list.do"
JUNG_VIEW = "https://www.djjunggu.go.kr/bbs/BBSMSTR_000000000104/view.do"
JUNG_DOWN = "https://www.djjunggu.go.kr/cmm/fms/FileDown.do"
SEO_LIST = "https://www.seogu.go.kr/bbs/BBSMSTR_000000000263/list.do"
SEO_VIEW = "https://www.seogu.go.kr/bbs/BBSMSTR_000000000263/view.do"
SEO_ZIP = "https://www.seogu.go.kr/cmm/fms/zipDownload.do"


def bbs_row(ntt_id: str, title: str, posted: str, department: str, *, button: bool = False) -> str:
    """실측한 eGov 목록 행. 중구·유성구는 `<a onclick>`, 서구는 `<button onclick>`으로 연다.

    첨부 칸에는 내려받기 함수를 정의하는 `<script>`가 줄마다 들어 있다.
    """
    call = f"javascript: fn_search_detail('{ntt_id}'); return false;"
    opener = (
        f'<button onclick="{call}" class="link"><strong class="bbs-subject-txt">{title}</strong>'
        "</button>"
        if button
        else f'<a href="#view" onclick="{call}">{title}</a>'
    )
    return (
        f'<tr><td data-cell-header="번호" class="hit">2904</td>'
        f'<td data-cell-header="제목" class="subject">{opener}</td>'
        f'<td data-cell-header="작성자" class="{"deptName" if button else "writer"}">'
        f"{department}</td>"
        f'<td data-cell-header="조회수" class="hit">6</td>'
        f'<td data-cell-header="등록일" class="regDate">{posted}</td>'
        '<td data-cell-header="첨부파일" class="atchFileId"><script>function fn_egov_downFile('
        'atchFileId, fileSn){ window.open("/cmm/fms/FileDown.do?atchFileId="+atchFileId); }'
        "</script></td></tr>"
    )


def bbs_listing(*rows: str, page: int = 1, last_page: int = 1) -> str:
    """실측한 eGov 목록. 쪽 수는 `페이지 1 / 15` 글자로 밝힌다."""
    return (
        '<html><body><div class="ui program--count"><span>총 게시물 <strong> 142</strong></span>, '
        f'<span class="ui program--division-line">페이지 <strong>{page}</strong> / {last_page}'
        f'</span></div><table class="board_list"><tbody>{"".join(rows)}</tbody></table>'
        "</body></html>"
    )


def bbs_detail(*files: tuple[str, str, str]) -> str:
    """실측한 eGov 본문. 사이트 공통 메뉴에도 `FileDown.do` 링크가 있다(중구)."""
    return (
        '<html><body><a href="/cmm/fms/FileDown.do?atchFileId=FILE_000000051408Wn6&amp;fileSn=0">'
        "사전정보공개목록 다운로드</a><ul>"
        + "".join(
            f"<li><a href=\"javascript:fn_egov_downFile('{file_id}','{serial}')\">"
            f"{name}&nbsp;[197.4&nbsp;KB] 다운로드</a></li>"
            for file_id, serial, name in files
        )
        + "</ul></body></html>"
    )


def test_bbs_board_reads_the_listing_and_the_detail_attachments() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    JUNG_LIST,
                    {"pageIndex": "1"},
                    bbs_listing(
                        bbs_row(
                            "B000000228919Lx4gG7",
                            "기획홍보실 시책추진업무추진비 사용내역(2026년 8월)",
                            "2026-09-11",
                            "기획홍보실",
                        )
                    ),
                ),
                response(
                    JUNG_VIEW,
                    {"nttId": "B000000228919Lx4gG7"},
                    bbs_detail(
                        (
                            "FILE_000000062108Ut1",
                            "0",
                            "pdf 파일 다운로드기획홍보실 사용내역(2026년 8월).pdf",
                        )
                    ),
                ),
            ]
        )
    )
    postings = list(BbsBoard(board(JUNG_LIST, BbsBoard), transport).postings(never))
    assert [item.post_id for item in postings] == ["B000000228919Lx4gG7"]
    posting = postings[0]
    assert posting.title == "기획홍보실 시책추진업무추진비 사용내역(2026년 8월)"
    assert posting.department == "기획홍보실"
    assert posting.posted is not None and posting.posted.isoformat() == "2026-09-11"
    assert [(item.file_id, item.suffix) for item in posting.attachments] == [("1", ".pdf")]
    assert posting.attachments[0].url == (f"{JUNG_DOWN}?atchFileId=FILE_000000062108Ut1&fileSn=0")
    assert posting.attachments[0].page_url == f"{JUNG_VIEW}?nttId=B000000228919Lx4gG7"


def test_bbs_board_walks_every_page_and_skips_the_detail_of_skipped_postings() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    JUNG_LIST,
                    {"pageIndex": "1"},
                    bbs_listing(
                        bbs_row("B1", "사용내역(2026년 8월)", "2026-09-11", "건설과"), last_page=2
                    ),
                ),
                response(
                    JUNG_LIST,
                    {"pageIndex": "2"},
                    bbs_listing(
                        bbs_row("B2", "사용내역(2025년 12월)", "2026-01-05", "건설과"),
                        page=2,
                        last_page=2,
                    ),
                ),
                response(JUNG_VIEW, {"nttId": "B2"}, bbs_detail()),
            ]
        )
    )
    postings = list(
        BbsBoard(board(JUNG_LIST, BbsBoard), transport).postings(
            lambda post_id, posted: post_id == "B1"
        )
    )
    assert [(item.post_id, item.attachments) for item in postings] == [("B1", ()), ("B2", ())]
    assert [url for url, _ in transport.calls].count(JUNG_VIEW) == 1


def test_bbs_board_keeps_a_posting_that_declares_no_spending() -> None:
    """`…(2026년 5월)_없음`은 첨부가 없다. 게시글은 남기고 받을 원본이 없다는 것만 밝힌다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    JUNG_LIST,
                    {"pageIndex": "1"},
                    bbs_listing(bbs_row("B3", "사용내역(2026년 5월)_없음", "2026-06-05", "행정")),
                ),
                response(JUNG_VIEW, {"nttId": "B3"}, bbs_detail()),
            ]
        )
    )
    postings = list(BbsBoard(board(JUNG_LIST, BbsBoard), transport).postings(never))
    assert [(item.post_id, item.attachments) for item in postings] == [("B3", ())]


def test_bbs_board_refuses_a_listing_without_a_page_count() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    JUNG_LIST,
                    {"pageIndex": "1"},
                    "<html><body><table><tbody></tbody></table></body></html>",
                )
            ]
        )
    )
    with pytest.raises(boards.UnreadableBoard):
        list(BbsBoard(board(JUNG_LIST, BbsBoard), transport).postings(never))


def test_bbs_board_requires_a_bbs_listing_address() -> None:
    with pytest.raises(ValueError):
        BbsBoard(board("https://www.djjunggu.go.kr/kr/sub01.do", BbsBoard), FakeTransport({}))


def test_zip_board_opens_the_posting_from_a_button_and_takes_one_archive() -> None:
    """서구는 `FileDown.do`가 우리 요청에 404이고, 목록이 내주는 묶음 내려받기는 200이다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    SEO_LIST,
                    {"pageIndex": "1"},
                    bbs_listing(
                        bbs_row(
                            "B000000219284Rx0uA2",
                            "2026년 8월중 구청장 업무추진비 집행내역",
                            "2026-09-10",
                            "운영지원과",
                            button=True,
                        )
                    ),
                ),
                response(
                    SEO_VIEW,
                    {"nttId": "B000000219284Rx0uA2"},
                    bbs_detail(
                        ("FILE_000000045088Tb3", "0", "집행내역.pdf"),
                        ("FILE_000000045088Tb3", "1", "집행내역.xlsx"),
                    ),
                ),
            ]
        )
    )
    postings = list(ZipBbsBoard(board(SEO_LIST, ZipBbsBoard), transport).postings(never))
    posting = postings[0]
    assert posting.title == "2026년 8월중 구청장 업무추진비 집행내역"
    assert posting.department == "운영지원과"
    assert [(item.file_id, item.suffix) for item in posting.attachments] == [("1", ".zip")]
    assert posting.attachments[0].url == (
        f"{SEO_ZIP}?atchFileIdStr=FILE_000000045088Tb3&zipFileName=zipDownload.zip"
    )


# 동구 article 계열.
DONG_LIST = "https://www.donggu.go.kr/dg/kor/article/senior"


def article_item(seq: str, title: str, posted: str, writer: str) -> str:
    """실측한 동구 목록 항목. 표가 아니라 `div.notice_list` 안의 `<li>`다."""
    return (
        f'<li><p class="no">1290</p><p class="subject align_left">'
        f'<a href="#" onclick="article.view(\'{seq}\');" class=""><strong>{title}</strong></a>'
        f'</p><p class="date">{posted}</p><p class="writer">{writer}</p>'
        '<p class="counter">20</p><p class="file_atch"><span>첨부파일 있음</span></p></li>'
    )


def article_listing(*items: str, last_page: int = 1) -> str:
    return (
        '<html><body><div class="gnb"><ul><li><a href="/dg/kor/article/senior">메뉴</a></li>'
        '</ul></div><div class="notice_list div_senior"><ul><li class="thead">'
        '<strong class="no">번호</strong><strong class="subject">제목</strong></li>'
        f'{"".join(items)}</ul></div><div class="page">'
        '<a href="?pageIndex=1" onclick="article.list(1);return false;" class="page_first"></a>'
        f'<a href="?pageIndex={last_page}" onclick="article.list({last_page});return false;" '
        'class="page_end" title="마지막 페이지로 이동"></a></div></body></html>'
    )


def article_detail(*files: tuple[str, str, str]) -> str:
    """실측한 동구 본문. 내려받기 옆에 같은 해시의 미리보기 링크가 붙는다."""
    return (
        '<html><body><div class="filebox">'
        + "".join(
            f'<a class="icon_file" href="/dg/attach/{first}/{second}">{name}</a>'
            f'<a class="btn small fileview" href="/dg/attach/preview/{first}/{second}">미리보기</a>'
            for first, second, name in files
        )
        + "</div></body></html>"
    )


def test_article_board_reads_the_list_items_and_the_attachments() -> None:
    first, second = "de96e330e35f471348650497d8c0070d", "9a9db098b587ee18b321c826f3707a49"
    transport = FakeTransport(
        dict(
            [
                response(
                    DONG_LIST,
                    {"pageIndex": "1"},
                    article_listing(
                        article_item(
                            "143316",
                            "(건축과) 2026년 8월 시책추진업무추진비 사용내역",
                            "2026-09-03",
                            "건축과",
                        ),
                        last_page=2,
                    ),
                ),
                response(
                    f"{DONG_LIST}/143316",
                    {},
                    article_detail((first, second, "사용내역(건축과).xlsx")),
                ),
                response(DONG_LIST, {"pageIndex": "2"}, article_listing(last_page=2)),
            ]
        )
    )
    postings = list(ArticleBoard(board(DONG_LIST, ArticleBoard), transport).postings(never))
    assert [item.post_id for item in postings] == ["143316"]
    posting = postings[0]
    assert posting.title == "(건축과) 2026년 8월 시책추진업무추진비 사용내역"
    assert posting.department == "건축과"
    assert posting.posted is not None and posting.posted.isoformat() == "2026-09-03"
    assert [(item.file_id, item.suffix) for item in posting.attachments] == [(second, ".xlsx")]
    assert posting.attachments[0].url == f"https://www.donggu.go.kr/dg/attach/{first}/{second}"
    assert posting.attachments[0].page_url == f"{DONG_LIST}/143316"


def test_article_board_filters_the_council_secretariat() -> None:
    """5급 이상 게시판에 구의회 사무국 글이 섞인다. 집행기관이 아니라 걸러 내고 센다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    DONG_LIST,
                    {"pageIndex": "1"},
                    article_listing(
                        article_item(
                            "143379",
                            "(의회사무국) 2026년 8월 과장급 이상 사용내역",
                            "2026-09-10",
                            "의회사무국",
                        )
                    ),
                )
            ]
        )
    )
    scraper = ArticleBoard(board(DONG_LIST, ArticleBoard), transport)
    assert list(scraper.postings(never)) == []
    assert isinstance(scraper, boards.FiltersRows)
    assert scraper.filtered == 1


def test_article_board_refuses_a_listing_without_a_last_page() -> None:
    transport = FakeTransport(
        dict([response(DONG_LIST, {"pageIndex": "1"}, "<html><body></body></html>")])
    )
    with pytest.raises(boards.UnreadableBoard):
        list(ArticleBoard(board(DONG_LIST, ArticleBoard), transport).postings(never))


# 대덕구 dpt 계열.
DPT_LIST = "https://www.daedeok.go.kr/dpt/dpt02/DPT02010404_cmmBoardList.do"
DPT_VIEW = "https://www.daedeok.go.kr/dpt/dpt02/DPT02010404_cmmBoardView.do"


def dpt_row(seq: str, title: str, posted: str, writer: str) -> str:
    """실측한 대덕구 목록 행. 제목 링크 안에 모바일용 `게시일 | 작성자 | 제목` 줄이 숨어 있다."""
    return (
        f'<tr><td>1506</td><td class="title"><a href="/dpt/dpt02/DPT02010404_cmmBoardView.do?'
        f'boardId=DPT_000077&amp;pageIndex=1&amp;ntatcSeq={seq}"><p class="mobile_con">'
        f'<span class="do02 cssradius"></span> {posted} | {writer} | {title}</p> {title}</a></td>'
        f'<td>{writer}</td><td><span class="file">이 게시글에는 첨부파일이 있어요</span></td>'
        f"<td>{posted}</td><td>21</td></tr>"
    )


def dpt_listing(*rows: str, last_page: int = 1) -> str:
    return (
        f"<html><body><table><tbody>{''.join(rows)}</tbody></table>"
        '<div class="paging"><div class="pagination"><strong>1</strong>'
        f'<a class="direction" href="#url" onclick="fn_link_page({last_page});">'
        '<img alt="마지막 페이지 이동" src="/images/btn_num_back.gif"></a></div></div>'
        "</body></html>"
    )


def dpt_detail(*files: tuple[str, str]) -> str:
    """실측한 대덕구 본문. 같은 첨부가 데스크톱·모바일 영역에 한 번씩 나온다."""
    links = "".join(
        f'<a href="/board/binary/DPT_000077/{number}" class="file">{name}(22.3KB)</a>'
        for number, name in files
    )
    return f"<html><body><ul>{links}</ul><table><tr><td>{links}</td></tr></table></body></html>"


def test_dpt_board_reads_the_listing_without_the_hidden_author_line() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    DPT_LIST,
                    {"pageIndex": "1"},
                    dpt_listing(
                        dpt_row(
                            "1107804173",
                            "2026년 8월 도시계획과 시책추진업무추진비 집행내역",
                            "2026-09-07",
                            "김주윤",
                        )
                    ),
                ),
                response(
                    DPT_VIEW,
                    {"boardId": "DPT_000077", "ntatcSeq": "1107804173"},
                    dpt_detail(("2114987.xlsx", "2026년 8월 도시계획과 집행내역.xlsx")),
                ),
            ]
        )
    )
    postings = list(DptBoard(board(DPT_LIST, DptBoard), transport).postings(never))
    posting = postings[0]
    assert posting.post_id == "1107804173"
    assert posting.title == "2026년 8월 도시계획과 시책추진업무추진비 집행내역"
    # 작성자 칸은 부서가 아니라 사람 이름이다. 부서로 옮기지 않는다.
    assert posting.department == ""
    assert posting.posted is not None and posting.posted.isoformat() == "2026-09-07"
    assert [(item.file_id, item.suffix) for item in posting.attachments] == [("2114987", ".xlsx")]
    assert posting.attachments[0].url == (
        "https://www.daedeok.go.kr/board/binary/DPT_000077/2114987.xlsx"
    )


def test_dpt_board_walks_to_the_last_page_the_script_declares() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    DPT_LIST,
                    {"pageIndex": "1"},
                    dpt_listing(
                        dpt_row("1", "2025년 1월 집행내역", "2025-02-01", "가"), last_page=2
                    ),
                ),
                response(
                    DPT_LIST,
                    {"pageIndex": "2"},
                    dpt_listing(
                        dpt_row("2", "2024년 1월 집행내역", "2024-02-01", "나"), last_page=2
                    ),
                ),
            ]
        )
    )
    postings = list(DptBoard(board(DPT_LIST, DptBoard), transport).postings(lambda *_: True))
    assert [item.post_id for item in postings] == ["1", "2"]


def test_dpt_board_refuses_a_listing_without_paging() -> None:
    transport = FakeTransport(
        dict([response(DPT_LIST, {"pageIndex": "1"}, "<html><body><table></table></body></html>")])
    )
    with pytest.raises(boards.UnreadableBoard):
        list(DptBoard(board(DPT_LIST, DptBoard), transport).postings(never))


# 레지스트리.
def test_daejeon_registry_declares_the_city_and_five_districts() -> None:
    target = select_target(CITIES, "daejeon", None)
    assert [(org.slug, len(org.boards)) for org in target.organizations] == [
        ("daejeon-city", 0),
        ("daejeon-dong", 2),
        ("daejeon-jung", 4),
        ("daejeon-seo", 2),
        ("daejeon-yuseong", 1),
        ("daejeon-daedeok", 5),
    ]


def test_daejeon_city_is_held_because_robots_disallows_its_originals(tmp_path: Path) -> None:
    class Unused:
        def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
            raise AssertionError("a held organization must not be requested")

    target = select_target(CITIES, "daejeon", "daejeon-city")
    output = collect(
        target,
        Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "output"),
        Unused(),  # type: ignore[arg-type]
    )
    assert output.sources == ()
    assert output.empty_reason == "collection held: daejeon-city=bot_blocked"
