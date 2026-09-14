"""부산 게시판 스크래퍼. 실측한 목록·본문·첨부 모양을 합성 fixture로 고정한다."""

from pathlib import Path

import pytest

from deliciousmap import boards
from deliciousmap.collection import collect
from deliciousmap.paths import Paths
from deliciousmap.registry import CITIES, Board, select_target
from deliciousmap.scrapers.busan import (
    CityBoard,
    EgovPortalBoard,
    GijangBoard,
    MixedRfc3Board,
    Rfc3Board,
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


def board(url: str, scraper: type = Rfc3Board) -> Board:
    return Board("expenses", url, scraper)


LIST_URL = "https://www.bsseogu.go.kr/board/list.bsseogu"
VIEW_URL = "https://www.bsseogu.go.kr/board/view.bsseogu"
DOWNLOAD_URL = "https://www.bsseogu.go.kr/board/download.bsseogu"
BOARD_URL = f"{LIST_URL}?boardId=BBS_0000151"


def row(data_sid: str, title: str, posted: str) -> str:
    """실측한 rfc3 목록 행. 게시일은 `2026. 09. 02`처럼 구분자 뒤에 공백이 있다."""
    return (
        f"<tr><td>1057</td><td class='l'>"
        f'<a href="/board/view.bsseogu?boardId=BBS_0000151&amp;orderBy=REGISTER_DATE DESC'
        f'&amp;paging=ok&amp;startPage=1&amp;dataSid={data_sid}" title="{title}">{title}</a>'
        f"</td><td>{posted}</td><td>39</td></tr>"
    )


def listing(*rows: str, last_page: int = 1, site_key: str = "bsseogu") -> str:
    """실측한 rfc3 목록. 마지막 쪽 단추가 그 게시판의 쪽 수를 밝힌다."""
    pages = "".join(
        f'<li><a href="/board/list.{site_key}?startPage={page}">{page}</a></li>'
        for page in range(1, last_page + 1)
    )
    return (
        f"<html><body><table>{''.join(rows)}</table>"
        f'<div class="paging-wrap2"><ul>{pages}'
        f'<li><a href="/board/list.{site_key}?startPage={last_page}">'
        f'<img src="/last.gif" alt="마지막 페이지"/></a></li></ul></div></body></html>'
    )


def detail(data_sid: str, *files: tuple[str, str]) -> str:
    """실측한 rfc3 본문. 첨부는 전용뷰어 링크와 내려받기 링크가 쌍으로 붙는다."""
    return (
        "<html><body>"
        + "".join(
            f'<a href="/board/SynapViewer.bsseogu?boardId=BBS_0000151&amp;dataSid={data_sid}'
            f'&amp;fileSid={file_sid}" title="{name} 전용뷰어 새창으로 열립니다. ">뷰어</a>'
            f'<a href="/board/download.bsseogu?boardId=BBS_0000151&amp;paging=ok&amp;startPage=1'
            f'&amp;dataSid={data_sid}&amp;command=update&amp;fileSid={file_sid}" '
            f'title="{name} 다운받기">{name}(13 kb)</a>'
            for file_sid, name in files
        )
        + "</body></html>"
    )


def page_params(page: int) -> dict[str, str]:
    return {"boardId": "BBS_0000151", "startPage": str(page)}


def test_rfc3_reads_the_listing_and_opens_the_detail_for_attachments() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    LIST_URL,
                    page_params(1),
                    listing(
                        row("274574", "2026년 2분기 교육진흥과 업무추진비 집행내역", "2026. 07. 21")
                    ),
                ),
                response(
                    VIEW_URL,
                    {"boardId": "BBS_0000151", "dataSid": "274574"},
                    detail("274574", ("117765", "2026년2분기업무추진비집행내역(교육진흥과).xlsx")),
                ),
            ]
        )
    )
    postings = list(Rfc3Board(board(BOARD_URL), transport).postings(lambda *_: False))
    assert [item.post_id for item in postings] == ["274574"]
    assert postings[0].title == "2026년 2분기 교육진흥과 업무추진비 집행내역"
    assert postings[0].posted is not None
    assert postings[0].posted.isoformat() == "2026-07-21"
    attachment = postings[0].attachments[0]
    assert attachment.suffix == ".xlsx"
    assert attachment.file_id == "117765"
    assert "download.bsseogu" in attachment.url
    assert "fileSid=117765" in attachment.url


def test_rfc3_walks_every_page_the_listing_declares() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    LIST_URL,
                    page_params(1),
                    listing(
                        row("2001", "2026년 1분기 총무과 업무추진비", "2026. 04. 10"), last_page=3
                    ),
                ),
                response(
                    LIST_URL,
                    page_params(2),
                    listing(
                        row("2002", "2026년 2월 총무과 업무추진비", "2026. 03. 10"), last_page=3
                    ),
                ),
                response(
                    LIST_URL,
                    page_params(3),
                    listing(
                        row("2003", "2026년 1월 총무과 업무추진비", "2026. 02. 10"), last_page=3
                    ),
                ),
            ]
        )
    )
    postings = list(Rfc3Board(board(BOARD_URL), transport).postings(lambda *_: True))
    assert [item.post_id for item in postings] == ["2001", "2002", "2003"]
    # 넘긴 게시글은 본문을 열지 않는다. 요청은 목록 세 쪽뿐이다.
    assert [url for url, _ in transport.calls] == [LIST_URL] * 3


def test_rfc3_keeps_a_posting_that_has_no_attachment() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    LIST_URL,
                    page_params(1),
                    listing(row("3001", "2026년 3월 자료 없음", "2026. 04. 01")),
                ),
                response(VIEW_URL, {"boardId": "BBS_0000151", "dataSid": "3001"}, detail("3001")),
            ]
        )
    )
    postings = list(Rfc3Board(board(BOARD_URL), transport).postings(lambda *_: False))
    assert postings[0].attachments == ()


def test_rfc3_reads_the_extension_from_the_declared_filename() -> None:
    """실측(부산진구 3977223): 파일 이름 안의 `(개금2동-2026.8.)`가 확장자처럼 보인다.

    앞에서부터 확장자를 줍는 방식은 그 자리에서 `.8`을 읽어 실측하지 않은 형식으로 돌린다.
    게시판이 밝힌 이름 전체를 읽고 마지막 확장자만 쓴다.
    """
    name = "업무추진비집행내역(개금2동-2026.8.).xlsx"
    transport = FakeTransport(
        dict(
            [
                response(
                    LIST_URL,
                    page_params(1),
                    listing(
                        row("3977223", "2026년 8월 개금2동 업무추진비 집행내역", "2026. 09. 14")
                    ),
                ),
                response(
                    VIEW_URL,
                    {"boardId": "BBS_0000151", "dataSid": "3977223"},
                    detail("3977223", ("195036", name)),
                ),
            ]
        )
    )
    postings = list(Rfc3Board(board(BOARD_URL), transport).postings(lambda *_: False))
    assert postings[0].attachments[0].suffix == ".xlsx"


def test_rfc3_leaves_an_undeclared_extension_empty() -> None:
    """이름이 형식을 밝히지 않으면 지어내지 않는다. 수집이 실측 선언과 대조해 걸러 낸다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    LIST_URL,
                    page_params(1),
                    listing(row("5001", "2026년 5월 총무과 업무추진비", "2026. 06. 01")),
                ),
                response(
                    VIEW_URL,
                    {"boardId": "BBS_0000151", "dataSid": "5001"},
                    detail("5001", ("501", "업무추진비집행내역(2026.5.)")),
                ),
            ]
        )
    )
    postings = list(Rfc3Board(board(BOARD_URL), transport).postings(lambda *_: False))
    assert postings[0].attachments[0].suffix == ""


def test_rfc3_refuses_a_listing_that_does_not_declare_its_page_count() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    LIST_URL,
                    page_params(1),
                    "<html><body><table>"
                    + row("4001", "2026년 4월 총무과", "2026. 05. 01")
                    + "</table></body></html>",
                )
            ]
        )
    )
    with pytest.raises(boards.UnreadableBoard):
        list(Rfc3Board(board(BOARD_URL), transport).postings(lambda *_: True))


def test_rfc3_requires_the_board_identifier() -> None:
    with pytest.raises(ValueError):
        Rfc3Board(board(LIST_URL), FakeTransport({}))


def test_rfc3_keeps_the_measured_query_conditions_of_the_board() -> None:
    """부산진구는 `menuCd` 없이는 403이다. 레지스트리가 밝힌 조건을 쪽마다 그대로 싣는다."""
    list_url = "https://www.busanjin.go.kr/board/list.busanjin"
    params = {
        "boardId": "BBS_0000023",
        "menuCd": "DOM_000000109001003000",
        "contentsSid": "276",
    }
    transport = FakeTransport(
        dict([response(list_url, {**params, "startPage": "1"}, listing(site_key="busanjin"))])
    )
    url = boards.address(list_url, params)
    list(Rfc3Board(board(url), transport).postings(lambda *_: True))
    assert transport.calls[0][1] == {**params, "startPage": "1"}


def test_mixed_boards_are_the_three_measured_shared_boards() -> None:
    """섞인 게시판만 제목으로 고른다. 전용 게시판에 조건을 걸면 조용히 빠지는 글이 생긴다."""
    target = select_target(CITIES, "busan", None)
    mixed = {
        org.slug
        for org in target.organizations
        for board_ in org.boards
        if board_.scraper is MixedRfc3Board
    }
    assert mixed == {"busan-jung", "busan-suyeong", "busan-haeundae"}


def test_busan_registry_declares_seventeen_organizations() -> None:
    target = select_target(CITIES, "busan", None)
    assert len(target.organizations) == 17
    assert select_target(CITIES, "busan", "busan-city").organizations[0].slug == "busan-city"


def test_busan_held_organizations_declare_a_reason_and_no_board() -> None:
    """보류 기관은 사유만 남기고 게시판을 선언하지 않는다. 우회로 대신 사유를 남긴다."""
    target = select_target(CITIES, "busan", None)
    held = {org.slug: org.hold_reason for org in target.organizations if org.hold_reason}
    assert held == {
        "busan-yeongdo": "bot_blocked",
        "busan-nam": "bot_blocked",
        "busan-gangseo": "bot_blocked",
        "busan-saha": "board_lost",
    }
    assert all(not org.boards for org in target.organizations if org.hold_reason is not None)
    assert all(org.boards for org in target.organizations if org.hold_reason is None)


def test_busan_collection_records_the_hold_reason_of_every_held_organization(
    tmp_path: Path,
) -> None:
    class Unused:
        def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
            raise AssertionError("a held organization must not be requested")

    target = select_target(CITIES, "busan", "busan-nam")
    output = collect(
        target,
        Paths(Path.cwd(), tmp_path / "raw", tmp_path / "data", tmp_path / "output"),
        Unused(),  # type: ignore[arg-type]
    )
    assert output.sources == ()
    assert output.empty_reason == "collection held: busan-nam=bot_blocked"


YEONJE_LIST = "https://www.yeonje.go.kr/portal/bbs/list.do"
YEONJE_VIEW = "https://www.yeonje.go.kr/portal/bbs/view.do"
YEONJE_IDS = {"ptIdx": "32", "mId": "0401090000"}
YEONJE_URL = f"{YEONJE_LIST}?ptIdx=32&mId=0401090000"


def yeonje_row(b_idx: str, title: str, posted: str, *, new: bool = False) -> str:
    """실측한 연제구 목록 행. 게시글 주소는 href가 아니라 onclick·data-action에 있다."""
    badge = '<img src="/common/img/board/ico_new.gif" alt="새글" class="ico_new">' if new else ""
    return (
        f'<tr><td class="list_bnum">3942</td><td class="list_tit">'
        f"<a href=\"#\" onclick=\"goTo.view('list','{b_idx}','32','0401090000'); return false;\" "
        f'data-action="/portal/bbs/view.do?bIdx={b_idx}&amp;ptIdx=32">{title}&nbsp;{badge}</a>'
        f'</td><td class="list_file"><img src="/common/img/board/xls.gif" alt="엑셀 파일"/></td>'
        f'<td class="list_write">도시안전과</td>'
        f'<td class="list_date">{posted}</td><td class="list_hit">1</td></tr>'
    )


def yeonje_listing(*rows: str, last_page: int = 1) -> str:
    """실측한 연제구 쪽 넘김. 주소가 `#`이라 쪽 수는 onclick의 `goPage`에만 있다."""
    pages = "".join(
        f'<a href="#" onclick="goPage({page}); return false;" title="{page}페이지로 이동">'
        f"{page}</a>"
        for page in range(2, min(last_page, 10) + 1)
    )
    return (
        f"<html><body><table>{''.join(rows)}</table>"
        f'<div class="bod_page"><a href="#" onclick="goPage(1); return false;" '
        f'class="btn_frist">처음 페이지</a>'
        f"<span>1<span class=blind>현재페이지</span></span>{pages}"
        f'<a href="#" onclick="goPage({last_page}); return false; " class="btn_end" '
        f'title="끝 페이지">끝 페이지</a></div></body></html>'
    )


def yeonje_detail(*files: tuple[str, str, str]) -> str:
    """실측한 연제구 본문. `fileSn`은 정수가 아니라 32자리 토큰이다."""
    return (
        '<html><body><div class="updateFileList"><ul>'
        + "".join(
            f"<li><a href=\"#\" onclick=\"fn_egov_downFile('{file_id}','{file_sn}'); "
            f'return false;"><span>{name}</span>&nbsp;[11.1 KByte]</a></li>'
            for file_id, file_sn, name in files
        )
        + "</ul></div></body></html>"
    )


def test_egov_portal_reads_the_post_id_from_the_listing_script() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    YEONJE_LIST,
                    {**YEONJE_IDS, "page": "1"},
                    yeonje_listing(
                        yeonje_row(
                            "130972",
                            "2026년 6월 도시안전과 업무추진비 집행내역",
                            "2026-07-14",
                            new=True,
                        )
                    ),
                ),
                response(
                    YEONJE_VIEW,
                    {**YEONJE_IDS, "bIdx": "130972"},
                    yeonje_detail(
                        ("31de8b40a1ec4c3f", "f9a1967c526603d1", "2026년 6월 사용내역.xlsx")
                    ),
                ),
            ]
        )
    )
    postings = list(
        EgovPortalBoard(board(YEONJE_URL, EgovPortalBoard), transport).postings(lambda *_: False)
    )
    assert [item.post_id for item in postings] == ["130972"]
    # 새 글 표시는 제목이 아니다. 목록이 붙인 아이콘 글자는 제목에서 뗀다.
    assert postings[0].title == "2026년 6월 도시안전과 업무추진비 집행내역"
    assert postings[0].department == "도시안전과"
    assert postings[0].posted is not None
    assert postings[0].posted.isoformat() == "2026-07-14"
    attachment = postings[0].attachments[0]
    assert attachment.suffix == ".xlsx"
    assert "FileDown.do" in attachment.url
    assert "fileSn=f9a1967c526603d1" in attachment.url


def test_egov_portal_reads_the_page_count_from_the_script_call() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    YEONJE_LIST,
                    {**YEONJE_IDS, "page": str(page)},
                    yeonje_listing(
                        yeonje_row(
                            f"13000{page}", f"2026년 {page}월 총무과 업무추진비", "2026-07-14"
                        ),
                        last_page=3,
                    ),
                )
                for page in (1, 2, 3)
            ]
        )
    )
    postings = list(
        EgovPortalBoard(board(YEONJE_URL, EgovPortalBoard), transport).postings(lambda *_: True)
    )
    assert [item.post_id for item in postings] == ["130001", "130002", "130003"]


def test_egov_portal_requires_the_menu_identifier() -> None:
    """`mId` 없이 부르면 목록은 400, 본문은 500이다. 선언이 빠진 채 훑지 않는다."""
    with pytest.raises(ValueError):
        EgovPortalBoard(board(f"{YEONJE_LIST}?ptIdx=32", EgovPortalBoard), FakeTransport({}))


def test_egov_portal_refuses_a_listing_without_a_page_count() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    YEONJE_LIST,
                    {**YEONJE_IDS, "page": "1"},
                    "<html><body><table>"
                    + yeonje_row("1", "2026년 6월 총무과", "2026-07-14")
                    + "</table></body></html>",
                )
            ]
        )
    )
    with pytest.raises(boards.UnreadableBoard):
        list(
            EgovPortalBoard(board(YEONJE_URL, EgovPortalBoard), transport).postings(lambda *_: True)
        )


DRM_BODY = b"\x9b DRMONE  This Document is encrypted and protected by Fasoo DRM"
XLSX_BODY = b"PK\x03\x04" + b"\x00" * 24


SOFTCAMP_BODY = bytes.fromhex("534344534130303400004100a1e42186dbaa4046555b9c93")


def test_every_measured_drm_product_is_recognised() -> None:
    """실측: 시청·강서구는 Fasoo, 북구는 Softcamp다. 둘 다 이름이 밝힌 형식이 아니다."""
    assert boards.is_protected(SOFTCAMP_BODY)
    with pytest.raises(boards.ProtectedOriginal):
        boards.container_of(SOFTCAMP_BODY)


def test_drm_attachment_is_recorded_instead_of_stopping_the_board() -> None:
    """실측(부산시청): 이름은 `.xlsx`인데 내용이 Fasoo DRM인 첨부가 섞여 있다.

    형식을 선언해도 읽히지 않으므로 실측하지 않은 형식과 같은 자리에 두지 않는다.
    표본 하나로 기관 전체를 보류하지도 않는다.
    """
    assert boards.is_protected(DRM_BODY)
    assert not boards.is_protected(XLSX_BODY)
    with pytest.raises(boards.ProtectedOriginal):
        boards.container_of(DRM_BODY)


def test_collection_counts_drm_and_keeps_the_unlocked_attachments(tmp_path: Path) -> None:
    from deliciousmap.collection import _ledger, _remember

    directory = tmp_path / "board"
    posting = boards.Posting(
        "21481",
        (
            boards.Attachment("21481", "2", ".xlsx", "https://x.invalid/a", "https://x.invalid/p"),
            boards.Attachment("21481", "3", ".xlsx", "https://x.invalid/b", "https://x.invalid/p"),
        ),
        None,
        "2026년 1분기 업무추진비 집행내역(시장, 부시장)",
    )
    _remember(directory, posting, [posting.attachments[0]], [], [], [posting.attachments[1]], [])
    collected, gone = _ledger(directory)
    assert collected["21481"].files == ("21481-2.xlsx",)
    assert gone["21481"].files == (("21481-3.xlsx", "drm"),)


CITY_LIST = "https://www.busan.go.kr/ghopen12/list"
CITY_VIEW = "https://www.busan.go.kr/ghopen12/view"
CITY_FILE = "https://www.busan.go.kr/comm/getFile"
CITY_URL = f"{CITY_LIST}?schBizNo=46"


def city_row(indx: str, title: str, posted: str, number: str = "108") -> str:
    """실측한 시청 목록 행. 주소의 `&&amp;`는 게시판이 낸 그대로다(빈 조회 조건)."""
    return (
        f'<tr><td class="pc_Y ta_Y mo_N">{number}</td>'
        f'<td class="pc_Y ta_Y mo_Y title">'
        f'<a href="/ghopen12/view?schCommand=Expense&amp;schIndx={indx}&amp;curPage=1&amp;'
        f'&amp;schBizNo=46">{title}</a></td>'
        f'<td class="pc_Y ta_Y mo_Y nowrap txtLeft">행정자치국 &gt; 총무과</td>'
        f'<td class="pc_Y ta_Y mo_Y nowrap">{posted}</td>'
        f'<td class="pc_Y ta_Y mo_Y nowrap">164</td></tr>'
    )


def city_listing(*rows: str, last_page: int = 1) -> str:
    return (
        f'<html><body><table class="boardList">{"".join(rows)}</table>'
        f'<a href="?curPage={last_page}&amp;schBizNo=46" class="pgEnd" '
        f'title="마지막 목록으로">마지막</a></body></html>'
    )


def city_detail(indx: str, *files: tuple[str, str]) -> str:
    """실측한 시청 본문. `fileNo`가 1부터 시작하지 않는 게시글이 있어 주소에서 읽는다."""
    return (
        '<html><body><ul class="attfiles">'
        + "".join(
            f'<li><a href="/comm/getFile?srvcId=OPENGOV&amp;upperNo={indx}&amp;'
            f'fileTy=ATTACH&amp;fileNo={file_no}" title="파일 다운로드">{name} (21 KB)</a>'
            f"<a href=\"javascript:f_filePreivew('OPENGOV', '{indx}', 'ATTACH', "
            f'\'{file_no}\');" class="btnTypeS">미리보기</a></li>'
            for file_no, name in files
        )
        + "</ul></body></html>"
    )


def test_city_board_reads_the_listing_and_its_attachments() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_LIST,
                    {"schBizNo": "46", "curPage": "1"},
                    city_listing(
                        city_row(
                            "21945", "2026년 2분기 업무추진비 집행내역(시장, 부시장)", "2026-07-31"
                        )
                    ),
                ),
                response(
                    CITY_VIEW,
                    {"schCommand": "Expense", "schIndx": "21945"},
                    city_detail(
                        "21945",
                        ("1", "2026년 2분기 업무추진비 집행내역(시장).xlsx"),
                        ("2", "2026년 2분기 업무추진비 집행내역(부시장).xlsx"),
                    ),
                ),
            ]
        )
    )
    postings = list(CityBoard(board(CITY_URL, CityBoard), transport).postings(lambda *_: False))
    assert [item.post_id for item in postings] == ["21945"]
    assert postings[0].department == "행정자치국 > 총무과"
    assert postings[0].posted is not None
    assert postings[0].posted.isoformat() == "2026-07-31"
    assert [item.file_id for item in postings[0].attachments] == ["1", "2"]
    assert [item.suffix for item in postings[0].attachments] == [".xlsx", ".xlsx"]
    assert "upperNo=21945" in postings[0].attachments[0].url
    assert "fileNo=1" in postings[0].attachments[0].url


def test_city_board_does_not_assume_the_first_attachment_is_numbered_one() -> None:
    """실측(21481): `fileNo`가 2·3이고 1이 없다. 번호를 지어내지 않고 본문에서 읽는다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_LIST,
                    {"schBizNo": "46", "curPage": "1"},
                    city_listing(
                        city_row(
                            "21481", "2026년 1분기 업무추진비 집행내역(시장, 부시장)", "2026-04-30"
                        )
                    ),
                ),
                response(
                    CITY_VIEW,
                    {"schCommand": "Expense", "schIndx": "21481"},
                    city_detail(
                        "21481",
                        ("2", "2026년 1분기 업무추진비 집행내역(부시장)_00.xlsx"),
                        ("3", "2026년 1분기 업무추진비 집행내역(시장)_00.xlsx"),
                    ),
                ),
            ]
        )
    )
    postings = list(CityBoard(board(CITY_URL, CityBoard), transport).postings(lambda *_: False))
    assert [item.file_id for item in postings[0].attachments] == ["2", "3"]


def test_city_board_reads_the_page_count_only_from_paging_links() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_LIST,
                    {"schBizNo": "46", "curPage": str(page)},
                    city_listing(
                        city_row(f"219{page}0", f"2026년 {page}분기 업무추진비", "2026-07-31"),
                        last_page=2,
                    ),
                )
                for page in (1, 2)
            ]
        )
    )
    postings = list(CityBoard(board(CITY_URL, CityBoard), transport).postings(lambda *_: True))
    assert [item.post_id for item in postings] == ["21910", "21920"]


def test_city_board_refuses_a_listing_without_paging() -> None:
    """게시글 주소도 `curPage`를 달고 다닌다. 그것을 쪽 수로 읽으면 한 쪽만 훑고 끝난다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_LIST,
                    {"schBizNo": "46", "curPage": "1"},
                    '<html><body><table class="boardList">'
                    + city_row("21945", "2026년 2분기 업무추진비", "2026-07-31")
                    + "</table></body></html>",
                )
            ]
        )
    )
    with pytest.raises(boards.UnreadableBoard):
        list(CityBoard(board(CITY_URL, CityBoard), transport).postings(lambda *_: True))


JUNG_LIST = "https://www.bsjunggu.go.kr/board/list.junggu"
JUNG_URL = f"{JUNG_LIST}?boardId=BBS_0000018"


def jung_row(data_sid: str, title: str, posted: str) -> str:
    return (
        f"<tr><td>1</td><td class='l'>"
        f'<a href="/board/view.junggu?boardId=BBS_0000018&amp;dataSid={data_sid}" '
        f'title="{title}">{title}</a></td><td>{posted}</td></tr>'
    )


def test_mixed_board_opens_only_the_expense_postings() -> None:
    """실측 2026-09-14 1쪽: 중구 10건 중 9건, 수영구 10건 중 6건만 업무추진비다.

    거르지 않으면 점검 결과·현황 공개 같은 다른 글의 첨부까지 받는다.
    """
    transport = FakeTransport(
        dict(
            [
                response(
                    JUNG_LIST,
                    {"boardId": "BBS_0000018", "startPage": "1"},
                    "<html><body><table>"
                    + jung_row("1", "2026년 3월 대청동 업무추진비 사용내역", "2026. 04. 02")
                    + jung_row("2", "공개공지 관리실태 점검결과(2026년)", "2026. 04. 03")
                    + jung_row(
                        "3", "기획감사실 시책추진업무추진비 사용내역(2026.3월)", "2026. 04. 04"
                    )
                    + "</table>"
                    + '<div class="page"><a href="/board/list.junggu?startPage=1">1</a></div>'
                    + "</body></html>",
                ),
                response(
                    "https://www.bsjunggu.go.kr/board/view.junggu",
                    {"boardId": "BBS_0000018", "dataSid": "1"},
                    "<html><body></body></html>",
                ),
                response(
                    "https://www.bsjunggu.go.kr/board/view.junggu",
                    {"boardId": "BBS_0000018", "dataSid": "3"},
                    "<html><body></body></html>",
                ),
            ]
        )
    )
    postings = list(
        MixedRfc3Board(board(JUNG_URL, MixedRfc3Board), transport).postings(lambda *_: False)
    )
    assert [item.post_id for item in postings] == ["1", "2", "3"]
    # 업무추진비가 아닌 글은 본문을 열지 않는다. 요청은 목록 한 쪽과 본문 두 번뿐이다.
    opened = [params.get("dataSid") for url, params in transport.calls if "view" in url]
    assert opened == ["1", "3"]


GIJANG_LIST = "https://www.gijang.go.kr/board/list.gijang"
GIJANG_URL = f"{GIJANG_LIST}?boardId=BBS_0000147"


def gijang_row(department: str, spent: str, purpose: str) -> str:
    """실측한 기장군 목록 행. 한 줄이 집행 한 건이고 게시글도 첨부도 없다."""
    return (
        f"<tr><td>{department}</td><td>군수 합성인</td><td>{spent}</td><td>-</td>"
        f"<td>{purpose}</td><td>100,000</td><td>2</td><td>현금지급</td>"
        f"<td>2026년</td><td>3월</td></tr>"
    )


def test_gijang_board_keeps_every_spending_row_without_an_attachment() -> None:
    """표가 곧 집행내역이라 받을 원본이 없다. 그 사실을 조용한 0건으로 두지 않는다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    GIJANG_LIST,
                    {"boardId": "BBS_0000147", "startPage": "1"},
                    "<html><body><table><thead>"
                    + "<tr>"
                    + "".join(
                        f"<th>{name}</th>"
                        for name in (
                            "부서",
                            "사용자",
                            "사용일자(일시)",
                            "사용장소(가맹점)",
                            "사용목적(내역)",
                            "사용금액(원)",
                            "대상인원(명)",
                            "사용방법",
                            "연도",
                            "월",
                        )
                    )
                    + "</tr></thead><tbody>"
                    + gijang_row("행정지원과(군수)", "2026. 3. 20.", "직원 경조사비")
                    + gijang_row("행정지원과(군수)", "2026. 3. 21.", "간담회")
                    + "</tbody></table>"
                    + '<div class="page"><a href="/board/list.gijang?startPage=1">1</a></div>'
                    + "</body></html>",
                )
            ]
        )
    )
    postings = list(
        GijangBoard(board(GIJANG_URL, GijangBoard), transport).postings(lambda *_: False)
    )
    assert [item.posted.isoformat() for item in postings if item.posted] == [
        "2026-03-20",
        "2026-03-21",
    ]
    assert all(item.attachments == () for item in postings)
    assert [item.title for item in postings] == ["직원 경조사비", "간담회"]
    assert postings[0].department == "행정지원과(군수)"
    # 열 이름 줄은 집행 줄이 아니다. 머리글이 `사용목적(내역)`이라는 게시글로 새지 않는다.
    assert "사용목적(내역)" not in [item.title for item in postings]
    # 게시글 번호가 없는 표라 집행일과 자리로 만든다. 같은 날 두 건이 겹치지 않아야 한다.
    assert len({item.post_id for item in postings}) == 2


def test_rfc3_reads_every_measured_date_format() -> None:
    """실측 2026-09-14: 아홉 게시판이 네 가지 표기를 쓴다. 하나로 굳히면 전부 읽지 못한다."""
    formats = {
        "2026-09-14": "2026-09-14",
        "2026.08.18": "2026-08-18",
        "26.09.14": "2026-09-14",
        "2026. 09. 02": "2026-09-02",
    }
    for index, (text, expected) in enumerate(formats.items()):
        transport = FakeTransport(
            dict(
                [
                    response(
                        LIST_URL,
                        page_params(1),
                        listing(row(f"90{index}", "2026년 6월 총무과 업무추진비 집행내역", text)),
                    )
                ]
            )
        )
        posting = next(Rfc3Board(board(BOARD_URL), transport).postings(lambda *_: True))
        assert posting.posted is not None
        assert posting.posted.isoformat() == expected, text


def test_rfc3_does_not_read_a_date_out_of_the_title() -> None:
    """제목 칸이 게시일 칸보다 앞에 온다. 줄 전체를 훑으면 제목의 날짜를 게시일로 읽는다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    LIST_URL,
                    page_params(1),
                    listing(row("9100", "2020-01-02 개청 기념 업무추진비 집행내역", "2026-06-30")),
                )
            ]
        )
    )
    posting = next(Rfc3Board(board(BOARD_URL), transport).postings(lambda *_: True))
    assert posting.posted is not None
    assert posting.posted.isoformat() == "2026-06-30"


def test_rfc3_counts_one_attachment_per_file_identifier() -> None:
    """실측(동래구·해운대구): 같은 `fileSid`에 내려받기 링크가 둘씩 붙는다.

    링크를 세면 첨부가 두 배가 되고 같은 원본을 두 번 내려받는다.
    """
    detail_body = (
        '<html><body><dd class="file">'
        '<a href="/board/download.bsseogu?boardId=BBS_0000151&amp;dataSid=1&amp;fileSid=77" '
        'title="업무추진비(2026년 2분기).pdf 다운받기">업무추진비(2026년 2분기).pdf</a>'
        '<a href="/tour/board/download.bsseogu?boardId=BBS_0000151&amp;dataSid=1&amp;fileSid=77">'
        "다운받기</a></dd></body></html>"
    )
    transport = FakeTransport(
        dict(
            [
                response(
                    LIST_URL,
                    page_params(1),
                    listing(row("1", "2026년 2분기 안락2동 업무추진비 집행내역", "2026.07.02")),
                ),
                response(VIEW_URL, {"boardId": "BBS_0000151", "dataSid": "1"}, detail_body),
            ]
        )
    )
    postings = list(Rfc3Board(board(BOARD_URL), transport).postings(lambda *_: False))
    assert [item.file_id for item in postings[0].attachments] == ["77"]
    assert postings[0].attachments[0].suffix == ".pdf"


def test_rfc3_reads_a_filename_that_omits_its_size() -> None:
    """실측(동래구): 내려받기 링크 글자에 크기가 없다. 이름만 있어도 형식을 읽는다."""
    detail_body = (
        '<html><body><a href="/board/download.bsseogu?boardId=BBS_0000151&amp;dataSid=2'
        '&amp;fileSid=88">2026년2분기업무추진비집행내역(안락2동).pdf</a></body></html>'
    )
    transport = FakeTransport(
        dict(
            [
                response(
                    LIST_URL,
                    page_params(1),
                    listing(row("2", "2026년 2분기 안락2동 업무추진비 집행내역", "2026.07.02")),
                ),
                response(VIEW_URL, {"boardId": "BBS_0000151", "dataSid": "2"}, detail_body),
            ]
        )
    )
    postings = list(Rfc3Board(board(BOARD_URL), transport).postings(lambda *_: False))
    assert postings[0].attachments[0].suffix == ".pdf"


def test_mixed_board_keeps_a_posting_whose_title_drops_a_syllable() -> None:
    """실측(중구): `일자리경제과과장급이상무추진비사용내역(2026.8.)` — `업`이 빠졌다.

    낱말 하나를 통째로 찾으면 이런 글이 빠진다. 오기까지 덮는 짧은 조건을 쓴다.
    """
    transport = FakeTransport(
        dict(
            [
                response(
                    JUNG_LIST,
                    {"boardId": "BBS_0000018", "startPage": "1"},
                    "<html><body><table>"
                    + jung_row("7", "일자리경제과과장급이상무추진비사용내역(2026.3.)", "2026-04-02")
                    + jung_row("8", "2026년 3월 이륜자동차 등록현황", "2026-04-03")
                    + "</table>"
                    + '<div class="page"><a href="/board/list.junggu?startPage=1">1</a></div>'
                    + "</body></html>",
                ),
                response(
                    "https://www.bsjunggu.go.kr/board/view.junggu",
                    {"boardId": "BBS_0000018", "dataSid": "7"},
                    "<html><body></body></html>",
                ),
            ]
        )
    )
    list(MixedRfc3Board(board(JUNG_URL, MixedRfc3Board), transport).postings(lambda *_: False))
    opened = [params.get("dataSid") for url, params in transport.calls if "view" in url]
    assert opened == ["7"]


def test_listing_ignores_script_text_inside_a_cell() -> None:
    """실측(동래구): 제목 칸 안의 `console.log('제목')`이 칸 글자에 섞여 제목이 두 번 나온다."""
    from deliciousmap.scrapers import listing as listing_module

    parser = listing_module.parse(
        b"<table><tr><td class='subject'><script>console.log('titre');</script>"
        b"<a href='/x'>hello</a></td></tr></table>"
    )
    assert parser.rows[0].cells[0].text == "hello"


HWPML_BODY = (
    b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8" standalone="no" ?>'
    b'<HWPML Style="embed" SubVersion="8.0.0.0" Version="2.8"><HEAD/></HWPML>'
)


def test_hwpml_is_an_original_container() -> None:
    """실측(동구): `.hwp`·`.hwpx` 이름으로 한글 XML(HWPML)을 올린다.

    이름이 밝힌 확장자와 내용이 다르지만 원본은 원본이다. 컨테이너로 판정해 받아 두고,
    무엇이었는지는 출처에 남긴다. 표를 읽는 것은 이 이슈의 범위가 아니다(#140 제외 범위).
    """
    assert boards.container_of(HWPML_BODY) == "hwpml"


def test_a_byte_order_mark_does_not_hide_the_container() -> None:
    """BOM은 형식이 아니라 인코딩 표시다. 그것 때문에 원본을 못 알아보지 않는다."""
    spreadsheet = (
        b'<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"/>'
    )
    assert boards.container_of(spreadsheet) == "spreadsheetml"
    assert boards.container_of(b"\xef\xbb\xbf" + spreadsheet) == "spreadsheetml"


def test_xml_that_is_neither_is_still_refused() -> None:
    """`<?xml`로 시작한다고 다 원본이 아니다. 표식이 있어야 받는다."""
    with pytest.raises(boards.UnsupportedOriginal):
        boards.container_of(b'\xef\xbb\xbf<?xml version="1.0"?><rss><channel/></rss>')


def hwpx(*names: str) -> bytes:
    from io import BytesIO
    from zipfile import ZIP_STORED, ZipFile

    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        # ODF·EPUB과 같은 규칙으로 `mimetype`을 압축 없이 맨 앞에 둔다.
        archive.writestr("mimetype", "application/hwp+zip", compress_type=ZIP_STORED)
        for name in names or ("Contents/header.xml", "version.xml"):
            archive.writestr(name, "<x/>")
    return buffer.getvalue()


def test_hwpx_is_not_reported_as_a_plain_archive() -> None:
    """실측(북구): `.hwpx` 139건이 한글 문서인데 일반 압축으로 세어졌다.

    컨테이너별 수를 남기는 것이 이 이슈의 완료 기준이라, 압축이라는 사실보다 무엇이
    들어 있는지가 값이다. 다음 단계가 풀어 볼 압축과 섞이지 않게 따로 센다.
    """
    assert boards.container_of(hwpx()) == "hwpx"


def test_a_real_archive_is_still_a_plain_archive() -> None:
    from io import BytesIO
    from zipfile import ZipFile

    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("업무추진비/1월.xls", "x")
    assert boards.container_of(buffer.getvalue()) == "zip"


def test_rfc3_takes_the_filename_from_whichever_anchor_declares_it() -> None:
    """실측(해운대 3173652): 링크 둘이 같은 첨부를 가리키는데 이름이 한쪽에만 온전하다.

    보이는 글자는 `…(문화관광경제국_문화관광과).... (14 kb)`로 잘려 있고, 온전한 이름은
    옆 링크의 `title`에 있다. 잘린 쪽을 읽으면 확장자가 없어 실측하지 않은 형식이 된다.
    """
    detail_body = (
        '<html><body><dd class="file">'
        '<a href="/mayor/board/download.bsseogu?boardId=BBS_0000151&amp;dataSid=1'
        '&amp;fileSid=3135888" title="첨부파일 다운로드">'
        "26년8월업무추진비집행내역(문화관광경제국_문화관광과).... (14 kb)</a>"
        '<a href="/mayor/board/download.bsseogu?boardId=BBS_0000151&amp;dataSid=1'
        '&amp;fileSid=3135888" title="26년8월업무추진비집행내역(문화관광경제국_문화관광과)'
        '.xlsx 첨부파일 다운로드"><span class="down"></span>내려받기</a>'
        "</dd></body></html>"
    )
    transport = FakeTransport(
        dict(
            [
                response(
                    LIST_URL,
                    page_params(1),
                    listing(row("1", "2026년 8월 문화관광과 업무추진비 집행내역", "2026.09.09")),
                ),
                response(VIEW_URL, {"boardId": "BBS_0000151", "dataSid": "1"}, detail_body),
            ]
        )
    )
    postings = list(Rfc3Board(board(BOARD_URL), transport).postings(lambda *_: False))
    assert [item.file_id for item in postings[0].attachments] == ["3135888"]
    assert postings[0].attachments[0].suffix == ".xlsx"


SHARE_STUB = "HCellShareFileInfo".encode("utf-16-le") + b"\x00" * 32


def test_an_editor_side_file_is_recorded_rather_than_stopping_the_board() -> None:
    """실측(부산진구 3966536): 668바이트짜리 한셀 공유 정보 파일이 표 대신 올라와 있다.

    집행 표가 아니고 형식을 선언해도 표가 생기지 않는다. 실측하지 않은 형식으로 두면 이
    한 건이 같은 게시판의 나머지 원본까지 수집 실패로 만든다.
    """
    assert boards.is_placeholder(SHARE_STUB)
    with pytest.raises(boards.NotAnOriginal):
        boards.container_of(SHARE_STUB)


def test_a_real_original_is_not_taken_for_an_editor_side_file() -> None:
    assert not boards.is_placeholder(XLSX_BODY)
    assert not boards.is_placeholder(HWPML_BODY)


def test_city_board_counts_one_attachment_per_file_number() -> None:
    """실측(시청 21660): `/comm/getFile` 링크가 둘이고 이름은 한쪽에만 있다.

    이름 없는 쪽을 첨부로 세면 확장자가 없어 실측하지 않은 형식이 되고, 같은 원본을 두 번
    내려받는다.
    """
    detail_body = (
        '<html><body><ul class="attfiles"><li>'
        '<a href="/comm/getFile?srvcId=OPENGOV&amp;upperNo=21660&amp;fileTy=ATTACH'
        '&amp;fileNo=1" title="파일 다운로드">'
        "2026년 2분기 업무추진비 집행내역(상수도 북부사업소).hwpx (35 KB)</a>"
        '<a href="/comm/getFile?srvcId=OPENGOV&amp;upperNo=21660&amp;fileTy=ATTACH'
        '&amp;fileNo=1" class="btnTypeS btnColorType5" title="새창">다운로드</a>'
        "</li></ul></body></html>"
    )
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_LIST,
                    {"schBizNo": "46", "curPage": "1"},
                    city_listing(
                        city_row("21660", "2026년 2분기 업무추진비 집행내역(상수도)", "2026-07-08")
                    ),
                ),
                response(
                    CITY_VIEW,
                    {"schCommand": "Expense", "schIndx": "21660"},
                    detail_body,
                ),
            ]
        )
    )
    postings = list(CityBoard(board(CITY_URL, CityBoard), transport).postings(lambda *_: False))
    assert [item.file_id for item in postings[0].attachments] == ["1"]
    assert postings[0].attachments[0].suffix == ".hwpx"
