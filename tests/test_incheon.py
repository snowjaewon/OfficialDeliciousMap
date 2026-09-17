"""인천 게시판 스크래퍼. 실측한 목록·본문·첨부 모양을 합성 fixture로 고정한다."""

from datetime import date

import pytest

from deliciousmap import boards
from deliciousmap.registry import CITIES, Board, select_target
from deliciousmap.scrapers.incheon import (
    BbsBoard,
    CityBoard,
    MichuholBoard,
    YeongjongBoard,
    YeonsuBoard,
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


def board(url: str, scraper: type, slug: str = "expenses") -> Board:
    return Board(slug, url, scraper)


def collected(*_: object) -> bool:
    """모든 게시글을 이번 수집의 대상으로 보는 판정."""
    return False


# --- 인천시청 --------------------------------------------------------------

CITY_LIST = "https://www.incheon.go.kr/open/OPEN010301"
CITY_FILE = "https://www.incheon.go.kr/comm/getFile"


def city_row(post_id: str, title: str, department: str, posted: str) -> str:
    """실측한 시청 목록 행. 담당부서 칸이 작성일 칸 바로 앞에 온다."""
    return (
        f"<tr><td>153</td>"
        f'<td class="board-list-subject al sm-view"><a href="/open/OPEN010301/{post_id}">'
        f"{title}</a></td>"
        f"<td>{department}</td><td class='sm-view'>{posted}</td><td>18</td></tr>"
    )


def city_listing(*rows: str, last_page: int = 1) -> str:
    """실측한 시청 목록. 쪽 넘김은 주소 없이 조회 조건만 적는다(`?curPage=2&cntPerPage=100`)."""
    pages = "".join(
        f'<a href="?curPage={page}&amp;cntPerPage=100" title="{page} 페이지로 이동">{page}</a>'
        for page in range(1, last_page + 1)
    )
    return (
        f"<html><body><table>{''.join(rows)}</table>"
        f'<div class="pagination">{pages}</div></body></html>'
    )


def city_detail(post_id: str, *files: tuple[str, str]) -> str:
    """실측한 시청 본문. 파일 이름은 링크가 아니라 앞선 `file-name` 칸에 있다."""
    groups = "".join(
        f'<div class="file-preview-down-group">'
        f'<span class="file-name">{name}</span>'
        f'<a href="/comm/fileViewSynapSever?srvcId=BBSTY1&amp;upperNo={post_id}'
        f'&amp;fileTy=ATTACH&amp;fileNo={file_no}&amp;convertParam=IMAGE">미리보기</a>'
        f'<a class="btn" href="/comm/getFile?srvcId=BBSTY1&amp;upperNo={post_id}'
        f'&amp;fileTy=ATTACH&amp;fileNo={file_no}"><span>다운로드</span></a></div>'
        for file_no, name in files
    )
    return f'<html><body><div class="board-item-group">{groups}</div></body></html>'


def city_page(page: int) -> dict[str, str]:
    return {"curPage": str(page), "cntPerPage": "100"}


def test_city_reads_the_listing_and_opens_the_detail_for_attachments() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_LIST,
                    city_page(1),
                    city_listing(
                        city_row(
                            "3081521", "2026년 6월 시장 업무추진비 사용내역", "총무과", "2026-07-15"
                        )
                    ),
                ),
                response(
                    CITY_LIST + "/3081521",
                    {},
                    city_detail("3081521", ("1", "1. 시장 기관운영업무추진비 사용내역(6월).pdf")),
                ),
            ]
        )
    )
    postings = list(CityBoard(board(CITY_LIST, CityBoard), transport).postings(collected))
    assert [item.post_id for item in postings] == ["3081521"]
    assert postings[0].posted == date(2026, 7, 15)
    assert postings[0].title == "2026년 6월 시장 업무추진비 사용내역"
    assert postings[0].department == "총무과"
    attachment = postings[0].attachments[0]
    assert attachment.suffix == ".pdf"
    assert attachment.name == "3081521-1.pdf"
    assert attachment.url == (f"{CITY_FILE}?srvcId=BBSTY1&upperNo=3081521&fileTy=ATTACH&fileNo=1")


def test_city_walks_every_page_and_skips_the_detail_of_collected_postings() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    CITY_LIST,
                    city_page(1),
                    city_listing(
                        city_row("3081521", "2026년 6월 시장 업무추진비", "총무과", "2026-07-15"),
                        last_page=2,
                    ),
                ),
                response(
                    CITY_LIST,
                    city_page(2),
                    city_listing(
                        city_row("3064270", "2026년 1월 시장 업무추진비", "총무과", "2026-02-20"),
                        last_page=2,
                    ),
                ),
            ]
        )
    )
    scraper = CityBoard(board(CITY_LIST, CityBoard), transport)
    postings = list(scraper.postings(lambda *_: True))
    assert [item.post_id for item in postings] == ["3081521", "3064270"]
    assert all(item.attachments == () for item in postings)
    assert [url for url, _ in transport.calls] == [CITY_LIST, CITY_LIST]


def test_city_rejects_a_listing_that_does_not_declare_its_page_count() -> None:
    transport = FakeTransport(
        dict([response(CITY_LIST, city_page(1), "<html><body><table></table></body></html>")])
    )
    scraper = CityBoard(board(CITY_LIST, CityBoard), transport)
    with pytest.raises(boards.UnreadableBoard):
        list(scraper.postings(collected))


# --- bbsMsgList 계열 -------------------------------------------------------

BBS_LIST = "https://www.seohae.go.kr/open_content/main/bbs/bbsMsgList.do"
BBS_DETAIL = "https://www.seohae.go.kr/open_content/main/bbs/bbsMsgDetail.do"
BBS_DOWN = "https://www.seohae.go.kr/open_content/main/bbs/bbsMsgFileDown.do"
BBS_URL = f"{BBS_LIST}?bcd=clean_cost"


def bbs_row(msg_seq: str, title: str, posted: str, prefix: str = "") -> str:
    """실측한 표 모양 목록 행(서해·계양·강화·옹진·검단·제물포)."""
    return (
        f"<tr><td>4735</td>"
        f'<td class="title"><a href="{prefix}/bbsMsgDetail.do?msg_seq={msg_seq}'
        f"&amp;bcd=clean_cost\"><p class='tit'>{title}</p></a></td>"
        f"<td>경제정책팀</td><td>{posted}</td><td>10</td></tr>"
    )


def bbs_item(msg_seq: str, title: str, posted: str) -> str:
    """실측한 목록 모양 행(남동·부평). 항목 안에 또 목록이 있어 같은 태그가 겹친다."""
    return (
        f'<li><p class="title"><a href="/main/bbs/bbsMsgDetail.do?msg_seq={msg_seq}'
        f'&amp;bcd=cost">{title}</a></p>'
        f'<div class="writer_info"><ul>'
        f'<li class="center">공원녹지과</li><li class="center">{posted}</li>'
        f"</ul></div></li>"
    )


def bbs_listing(*items: str, last_page: int = 1, prefix: str = "") -> str:
    pages = "".join(
        f'<a href="{prefix}/bbsMsgList.do?bcd=clean_cost&amp;pgno={page}">{page}</a>'
        for page in range(1, last_page + 1)
    )
    return (
        f"<html><body><table><tbody>{''.join(items)}</tbody></table>"
        f'<div class="paging">{pages}</div></body></html>'
    )


def bbs_detail(msg_seq: str, *files: tuple[str, str], bcd: str = "clean_cost") -> str:
    """실측한 본문. 첨부 이름은 확장자 아이콘의 대체 글자 뒤에 온다."""
    links = "".join(
        f'<li><a href="/open_content/main/bbs/bbsMsgFileDown.do?bcd={bcd}'
        f'&amp;msg_seq={msg_seq}&amp;fileno={fileno}" title="{fileno}번째 첨부파일 다운로드">'
        f'<img src="/share/images/filetype/xlsx.gif" alt="xlsx"/> {name}</a>'
        f'<span class="sfont">(11KByte)</span></li>'
        for fileno, name in files
    )
    return f'<html><body><ul class="datalist">{links}</ul></body></html>'


def bbs_page(page: int) -> dict[str, str]:
    return {"bcd": "clean_cost", "listsz": "100", "pgno": str(page)}


def test_bbs_reads_the_table_listing_and_the_detail_attachments() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    BBS_LIST,
                    bbs_page(1),
                    bbs_listing(
                        bbs_row("4735", "2026년 6월 경제정책과 업무추진비 사용내역", "2026.07.15")
                    ),
                ),
                response(
                    BBS_DETAIL,
                    {"bcd": "clean_cost", "msg_seq": "4735"},
                    bbs_detail("4735", ("1", "2026년_6월_업무추진비(경제정책과장).xlsx")),
                ),
            ]
        )
    )
    postings = list(BbsBoard(board(BBS_URL, BbsBoard), transport).postings(collected))
    assert [item.post_id for item in postings] == ["4735"]
    assert postings[0].posted == date(2026, 7, 15)
    assert postings[0].title == "2026년 6월 경제정책과 업무추진비 사용내역"
    attachment = postings[0].attachments[0]
    assert attachment.suffix == ".xlsx"
    assert attachment.url == f"{BBS_DOWN}?bcd=clean_cost&msg_seq=4735&fileno=1"


def test_bbs_reads_the_list_rendering_that_leaves_a_tag_unclosed() -> None:
    """남동·부평은 목록으로 그리고 닫는 태그를 하나 빠뜨린다(실측). 요소 경계로 가르지 않는다."""
    url = "https://www.icbp.go.kr/main/bbs/bbsMsgList.do?bcd=cost&cate1=d"
    list_url = "https://www.icbp.go.kr/main/bbs/bbsMsgList.do"
    transport = FakeTransport(
        dict(
            [
                response(
                    list_url,
                    {"bcd": "cost", "cate1": "d", "listsz": "100", "pgno": "1"},
                    '<html><body><ul class="gnb"><li><a href="/main/index.do">구정</a></ul><ul>'
                    + bbs_item("1189", "2026년 6월 공원녹지과 업무추진비 집행내역", "2026.07.15")
                    + '</ul><div class="paging">'
                    + '<a href="/main/bbs/bbsMsgList.do?bcd=cost&amp;pgno=1">1</a>'
                    + "</div></body></html>",
                ),
                response(
                    "https://www.icbp.go.kr/main/bbs/bbsMsgDetail.do",
                    {"bcd": "cost", "cate1": "d", "msg_seq": "1189"},
                    bbs_detail(
                        "1189", ("1", "업무추진비_집행내역_공개(공원녹지과).xlsx"), bcd="cost"
                    ),
                ),
            ]
        )
    )
    postings = list(BbsBoard(board(url, BbsBoard), transport).postings(collected))
    assert [item.post_id for item in postings] == ["1189"]
    assert postings[0].posted == date(2026, 7, 15)
    assert postings[0].attachments[0].suffix == ".xlsx"


def test_bbs_reads_the_posting_date_written_after_a_date_in_the_title() -> None:
    """제목과 파일 이름에도 날짜가 적힌다. 행이 마지막에 적은 날짜가 게시일이다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    BBS_LIST,
                    bbs_page(1),
                    bbs_listing(bbs_row("4641", "2026.08.01. 업무추진비 사용내역", "2026.09.09")),
                ),
                response(
                    BBS_DETAIL,
                    {"bcd": "clean_cost", "msg_seq": "4641"},
                    bbs_detail("4641", ("1", "2026.08월_업무추진비(오류왕길동).xlsx")),
                ),
            ]
        )
    )
    postings = list(BbsBoard(board(BBS_URL, BbsBoard), transport).postings(collected))
    assert postings[0].posted == date(2026, 9, 9)
    assert postings[0].attachments[0].suffix == ".xlsx"


def test_bbs_leaves_the_posting_date_empty_when_the_row_shows_only_a_time() -> None:
    """오늘 올라온 글은 날짜 대신 시각만 적는 게시판이 있다(검단 실측). 짐작하지 않는다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    BBS_LIST,
                    bbs_page(1),
                    bbs_listing(bbs_row("4644", "업무추진비 사용내역(정보통신과)", "13:06:12")),
                ),
                response(
                    BBS_DETAIL,
                    {"bcd": "clean_cost", "msg_seq": "4644"},
                    bbs_detail("4644", ("1", "업무추진비_사용내역.xlsx")),
                ),
            ]
        )
    )
    postings = list(BbsBoard(board(BBS_URL, BbsBoard), transport).postings(collected))
    assert postings[0].posted is None


def test_bbs_filters_the_council_rows_and_counts_them() -> None:
    """구·군의회 글이 같은 게시판에 섞인다(남동·강화·옹진 실측). 집행기관이 아니라 걸러 낸다."""
    transport = FakeTransport(
        dict(
            [
                response(
                    BBS_LIST,
                    bbs_page(1),
                    bbs_listing(
                        bbs_row("4735", "2026년 6월 의회사무과 업무추진비 집행내역", "2026.07.15"),
                        bbs_row("4734", "2026년 6월 재무과 업무추진비 집행내역", "2026.07.15"),
                    ),
                ),
                response(
                    BBS_DETAIL,
                    {"bcd": "clean_cost", "msg_seq": "4734"},
                    bbs_detail("4734", ("1", "2026년_6월_업무추진비(재무과).xlsx")),
                ),
            ]
        )
    )
    scraper = BbsBoard(board(BBS_URL, BbsBoard), transport)
    postings = list(scraper.postings(collected))
    assert [item.post_id for item in postings] == ["4734"]
    assert scraper.filtered == 1


def test_bbs_filters_a_row_whose_department_names_the_council() -> None:
    """제목이 밝히지 않아도 목록 칸이 밝힌다(남동 목록의 `남동구의회` 실측)."""
    body = (
        "<html><body><table><tbody>"
        '<tr><td>1177</td><td class="title">'
        '<a href="/bbsMsgDetail.do?msg_seq=1177&amp;bcd=clean_cost">'
        "2026년 6월 업무추진비 집행내역</a></td>"
        "<td>남동구의회</td><td>2026.07.15</td></tr></tbody></table>"
        '<div class="paging"><a href="/bbsMsgList.do?bcd=clean_cost&amp;pgno=1">1</a></div>'
        "</body></html>"
    )
    transport = FakeTransport(dict([response(BBS_LIST, bbs_page(1), body)]))
    scraper = BbsBoard(board(BBS_URL, BbsBoard), transport)
    assert list(scraper.postings(collected)) == []
    assert scraper.filtered == 1


def test_yeonsu_filters_the_council_rows_and_counts_them() -> None:
    """연수구 목록은 담당부서 칸에 `의회사무국`을 적는다(2026년 게시글 9건 실측)."""
    transport = FakeTransport(
        dict(
            [
                response(
                    YEONSU_LIST,
                    {"gotopage": "1"},
                    yeonsu_listing(
                        yeonsu_row(
                            "11613", "2026년 5월 업무추진비 집행내역", "의회사무국", "2026-06-11"
                        )
                    ),
                )
            ]
        )
    )
    scraper = YeonsuBoard(board(YEONSU_LIST, YeonsuBoard), transport)
    assert list(scraper.postings(collected)) == []
    assert scraper.filtered == 1


def test_bbs_reads_a_listing_whose_links_carry_a_session_path_parameter() -> None:
    """강화군 목록은 주소 경로에 `;jsessionid=…`를 달고 온다(실측)."""
    prefix = "/open_content/main/bbs"
    session = ";jsessionid=A2B6766B36E18654D86741917F8360B9"
    body = (
        "<html><body><table><tbody>"
        f'<tr><td>2859</td><td class="title">'
        f'<a href="{prefix}/bbsMsgDetail.do{session}?msg_seq=6292&amp;bcd=clean_cost">'
        f"2026년 6월 서도면 업무추진비 집행내역</a></td>"
        f"<td>서도면</td><td>2026.07.16</td></tr></tbody></table>"
        f'<div class="paging">'
        f'<a href="{prefix}/bbsMsgList.do{session}?bcd=clean_cost&amp;pgno=1">1</a>'
        "</div></body></html>"
    )
    transport = FakeTransport(
        dict(
            [
                response(BBS_LIST, bbs_page(1), body),
                response(
                    BBS_DETAIL,
                    {"bcd": "clean_cost", "msg_seq": "6292"},
                    bbs_detail("6292", ("1", "서도면_업무추진비_집행현황(26년_6월).xlsx")),
                ),
            ]
        )
    )
    postings = list(BbsBoard(board(BBS_URL, BbsBoard), transport).postings(collected))
    assert [item.post_id for item in postings] == ["6292"]
    assert postings[0].attachments[0].url == f"{BBS_DOWN}?bcd=clean_cost&msg_seq=6292&fileno=1"


def test_bbs_reads_its_own_page_as_a_lost_original() -> None:
    """원본이 없는 게시글은 파일 대신 이 게시판의 화면을 준다(옹진군 실측). 유실로 알린다."""
    scraper = BbsBoard(board(BBS_URL, BbsBoard), FakeTransport({}))
    page = (
        "<html><body><a href='/bbs/bbsMsgDetail.do?bcd=clean_cost&msg_seq=2211'>"
        "2026년 6월 업무추진비 집행현황</a></body></html>"
    ).encode()
    with pytest.raises(boards.OriginalGone):
        scraper.verify(page)


def test_bbs_leaves_another_screen_for_a_person_to_look_at() -> None:
    """점검·차단 화면은 유실이 아니다. 추가형 장부에 박히면 다시 받지 않기 때문이다."""
    scraper = BbsBoard(board(BBS_URL, BbsBoard), FakeTransport({}))
    scraper.verify("<html><body>서비스 점검 중입니다</body></html>".encode())
    scraper.verify(b"%PDF-1.7 not a screen at all")


def test_bbs_requires_the_board_code() -> None:
    with pytest.raises(ValueError):
        BbsBoard(board(BBS_LIST, BbsBoard), FakeTransport({}))


# --- 미추홀구 --------------------------------------------------------------

MICHUHOL_LIST = "https://www.michuhol.go.kr/main/board/list.do"
MICHUHOL_VIEW = "https://www.michuhol.go.kr/main/board/view.do"
MICHUHOL_DOWN = "https://www.michuhol.go.kr/other/file_down.do"
MICHUHOL_URL = f"{MICHUHOL_LIST}?board_code=business_promotion"


def michuhol_listing(*rows: str, last_page: int = 1) -> str:
    pages = "".join(
        f"<a href=\"javascript:;\" onclick=\"fnList({{'page' : '{page}'}});\">{page}</a>"
        for page in range(1, last_page + 1)
    )
    return (
        f'<html><body><table>{"".join(rows)}</table><div class="paging">{pages}</div></body></html>'
    )


def michuhol_row(sq: str, title: str, department: str, posted: str) -> str:
    return (
        f"<tr><td>7120</td>"
        f'<td class="title"><a href="view.do?sq={sq}&amp;board_code=business_promotion'
        f'&amp;search=eyJib2FyZCI6MX0=">{title}</a></td>'
        f'<td><img src="/file.png" alt="첨부파일"></td>'
        f"<td>{department}</td><td>{posted}</td><td>1</td></tr>"
    )


def test_michuhol_reads_the_listing_and_the_keyed_download() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    MICHUHOL_LIST,
                    {"board_code": "business_promotion", "page": "1"},
                    michuhol_listing(
                        michuhol_row(
                            "313533",
                            "2026년 6월 세무1과 업무추진비 집행내역",
                            "세무1과",
                            "2026-07-17",
                        )
                    ),
                ),
                response(
                    MICHUHOL_VIEW,
                    {"board_code": "business_promotion", "sq": "313533"},
                    '<html><body><div class="file-area">'
                    '<a href="/other/file_down.do?sq=1219734&amp;key=5EC89FCAFA" '
                    'class="file-link">2026년 6월 업무추진비 집행내역(세무1과).xlsx</a>'
                    "</div></body></html>",
                ),
            ]
        )
    )
    postings = list(
        MichuholBoard(board(MICHUHOL_URL, MichuholBoard), transport).postings(collected)
    )
    assert [item.post_id for item in postings] == ["313533"]
    assert postings[0].department == "세무1과"
    assert postings[0].posted == date(2026, 7, 17)
    attachment = postings[0].attachments[0]
    assert attachment.file_id == "1219734"
    assert attachment.suffix == ".xlsx"
    assert attachment.url == f"{MICHUHOL_DOWN}?sq=1219734&key=5EC89FCAFA"


# --- 연수구 ----------------------------------------------------------------

YEONSU_LIST = "https://www.yeonsu.go.kr/main/administration/open_info/charge.asp"
YEONSU_DOWN = "https://www.yeonsu.go.kr/shareEtc/download_utf.asp"


def yeonsu_listing(*rows: str, last_page: int = 1) -> str:
    pages = "".join(
        f'<a href="/main/administration/open_info/charge.asp?gotopage={page}">{page}</a>'
        for page in range(1, last_page + 1)
    )
    return (
        f'<html><body><table>{"".join(rows)}</table><div class="paging">{pages}</div></body></html>'
    )


def yeonsu_row(idx: str, title: str, department: str, posted: str) -> str:
    return (
        f"<tr><td>8381</td>"
        f'<td class="title"><a href="/main/administration/open_info/charge.asp?page=v'
        f'&amp;gotopage=1&amp;idx={idx}&amp;keyfield=&amp;keyword=">{title}</a></td>'
        f'<td><img src="/ic_file.gif" alt="첨부파일 있음" /></td>'
        f"<td>{department}</td><td>{posted}</td><td>10</td></tr>"
    )


def test_yeonsu_sends_the_referer_the_download_requires() -> None:
    """첨부는 파일 이름이 열쇠이고, Referer 없이 부르면 오류 화면이 200으로 온다(실측)."""
    transport = FakeTransport(
        dict(
            [
                response(
                    YEONSU_LIST,
                    {"gotopage": "1"},
                    yeonsu_listing(
                        yeonsu_row(
                            "11824",
                            "2026년 6월 업무추진비 집행내역(연수구립도서관)",
                            "연수구립도서관",
                            "2026-07-15",
                        )
                    ),
                ),
                response(
                    YEONSU_LIST,
                    {"page": "v", "idx": "11824"},
                    "<html><body><ul class='addfile'><li>"
                    '<a href="/shareEtc/download_utf.asp?filename=%EC%97%85%EB%AC%B4.xlsx'
                    '&amp;filepath=etc_account"><img src="/xlsx.gif" alt="" />'
                    "업무추진비_공개_연수구립도서관(6월).xlsx (0MB)</a></li></ul></body></html>",
                ),
            ]
        )
    )
    postings = list(YeonsuBoard(board(YEONSU_LIST, YeonsuBoard), transport).postings(collected))
    assert [item.post_id for item in postings] == ["11824"]
    assert postings[0].department == "연수구립도서관"
    attachment = postings[0].attachments[0]
    assert attachment.file_id == "1"
    assert attachment.suffix == ".xlsx"
    assert attachment.url.startswith(f"{YEONSU_DOWN}?filename=")
    assert attachment.referer == f"{YEONSU_LIST}?page=v&idx=11824"


# --- 영종구 ----------------------------------------------------------------

YEONGJONG_LIST = "https://www.yeongjong.go.kr/main/pst/list.do"
YEONGJONG_VIEW = "https://www.yeongjong.go.kr/main/pst/view.do"
YEONGJONG_DOWN = "https://www.yeongjong.go.kr/other/attach/process.file.do"
YEONGJONG_URL = f"{YEONGJONG_LIST}?pst_id=mn_exp_head"


def yeongjong_listing(*rows: str, last_page: int = 1) -> str:
    pages = "".join(
        f"<a href=\"javascript: ;\" onclick=\"fnList({{'page' : '{page}'}});\">{page}</a>"
        for page in range(1, last_page + 1)
    )
    return (
        f"<html><body><table>{''.join(rows)}</table>"
        f'<div class="cm_paging1">{pages}</div></body></html>'
    )


def yeongjong_row(pst_sn: str, title: str, department: str, posted: str) -> str:
    return (
        f"<tr><td>168</td>"
        f'<td class="title"><a href="view.do?pst_id=mn_exp_head&amp;pst_sn={pst_sn}'
        f'&amp;search=c2xUTFRHb28=">{title}</a></td>'
        f'<td><span class="cm_icon file2"><span class="skip">첨부파일</span></span></td>'
        f'<td data-th="담당부서">{department}</td><td>{posted}</td><td>114</td></tr>'
    )


def test_yeongjong_reads_the_download_call_and_its_guard_key() -> None:
    transport = FakeTransport(
        dict(
            [
                response(
                    YEONGJONG_LIST,
                    {"pst_id": "mn_exp_head", "page": "1"},
                    yeongjong_listing(
                        yeongjong_row(
                            "331851",
                            "2026년 6월 인천 중구청장 업무추진비 사용내역",
                            "총무과",
                            "2026-06-29",
                        )
                    ),
                ),
                response(
                    YEONGJONG_VIEW,
                    {"pst_id": "mn_exp_head", "pst_sn": "331851"},
                    '<html><body><ul class="cm_file_list2"><li>'
                    '<a href="/other/synap_viewer/view.do?atch_file_sn=340612">'
                    '<span class="skip">2026년 6월 사용내역.xlsx</span>미리보기</a>'
                    '<a href="/other/attach/process.file.do?TP=dn&amp;sn=340612'
                    '&amp;key=58F32FB65750C31" download="">'
                    '<span class="skip">2026년 6월 사용내역.xlsx</span>다운로드</a>'
                    "</li></ul></body></html>",
                ),
            ]
        )
    )
    postings = list(
        YeongjongBoard(board(YEONGJONG_URL, YeongjongBoard), transport).postings(collected)
    )
    assert [item.post_id for item in postings] == ["331851"]
    assert postings[0].department == "총무과"
    assert postings[0].posted == date(2026, 6, 29)
    attachment = postings[0].attachments[0]
    assert attachment.file_id == "340612"
    assert attachment.suffix == ".xlsx"
    assert attachment.url == f"{YEONGJONG_DOWN}?TP=dn&sn=340612&key=58F32FB65750C31"


# --- 레지스트리 ------------------------------------------------------------


def city() -> object:
    return select_target(CITIES, "incheon", None).city


def test_registry_declares_twelve_organizations() -> None:
    assert len(city().organizations) == 12


def test_registry_boards_are_reachable_with_the_declared_scraper() -> None:
    """선언한 주소가 그 스크래퍼의 조회 조건을 갖추었는지 훑기 전에 확인한다."""
    for organization in city().organizations:
        for item in organization.boards:
            item.scraper(item, FakeTransport({}))


def test_registry_organization_slugs_are_unique_and_named_for_incheon() -> None:
    slugs = [organization.slug for organization in city().organizations]
    assert len(set(slugs)) == len(slugs)
    assert all(slug.startswith("incheon-") for slug in slugs)
    assert all(organization.name.startswith("인천광역시") for organization in city().organizations)
