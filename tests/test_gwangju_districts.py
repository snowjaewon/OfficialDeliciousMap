"""광주 자치구 게시판 세 계열의 해석을 검증한다. 합성 응답만 쓰고 기관에 요청하지 않는다."""

import json
from collections.abc import Mapping
from datetime import date
from html import escape

import pytest

from deliciousmap import boards
from deliciousmap.registry import Board
from deliciousmap.scrapers.gwangju_district import GwangjuDistrictBoard
from deliciousmap.scrapers.gwangju_gwangsan import GwangsanInfoOpenBoard
from deliciousmap.scrapers.gwangju_seogu import SeoguExpenseBoard


def nothing_collected(post_id: str, posted: date | None) -> bool:
    """아직 아무것도 수집하지 않았고 기간으로도 거르지 않은 상태. 모든 게시글의 본문을 연다."""
    return False


# 실측한 주소 모양을 그대로 쓴다. 값은 합성이다.
BUK_URL = "https://bukgu.example.invalid/board.es?mid=a10502050000&bid=0004"
NAM_URL = "https://namgu.example.invalid/board.es?mid=a10304100000&bid=0007"
SEO_URL = "https://seogu.example.invalid/openInfoCostList.es?mid=a10518030100&oi_seq=110"
GWANGSAN_URL = (
    "https://gwangsan.example.invalid/contentsView.do"
    "?pageId=www159&infoOpenSn=292&infoOpenCtgryUpper=O130000"
)


def list_rows(rows: str, page: int = 1, pages: int = 1) -> bytes:
    """`.es` 계열 목록 한 쪽. 쪽 수는 `현재 페이지 N/P`에만 있다."""
    return f"""<html><body>
      <ul class="menu"><li><a href="/menu.es?mid=a10502050000">업무추진비</a></li></ul>
      <p class="page_info">전체 <span>9</span>건,
        현재 페이지 <strong>{page}</strong>/<span>{pages}</span></p>
      <div class="dbody">{rows}</div></body></html>""".encode()


def buk_row(post: int, title: str, department: str, posted: str, filed: bool = True) -> str:
    """북구·동구형 줄. 칸이 `<li>`이고 번호·제목·부서·게시일 차례다."""
    mark = '<img src="/x.gif" alt="xlsx 첨부파일" />' if filed else ""
    href = (
        f"/board.es?mid=a10502050000&amp;bid=0004&amp;act=view"
        f"&amp;list_no={post}&amp;tag=&amp;nPage=1"
    )
    return (
        f'<ul><li class="col01">{post}</li>'
        f'<li class="title"><a href="{href}">{escape(title)}</a></li>'
        f'<li class="col02">{escape(department)}</li>'
        f'<li class="col03">{posted}</li>'
        f'<li class="col04">{mark}</li>'
        f'<li class="col05">38</li></ul>'
    )


def nam_row(post: int, title: str, department: str, posted: str, filed: bool = True) -> str:
    """남구형 줄. 같은 계열이지만 칸이 `<td>`인 표다."""
    mark = '<img src="/x.gif" alt="xlsx 첨부파일" />' if filed else ""
    href = (
        f"/board.es?mid=a10304100000&amp;bid=0007&amp;act=view"
        f"&amp;list_no={post}&amp;tag=&amp;nPage=1"
    )
    return (
        f'<tr><td class="num">{post}</td>'
        f'<td class="txt_left"><a href="{href}">{escape(title)}</a></td>'
        f'<td class="name">{escape(department)}</td>'
        f'<td class="date">{posted}</td>'
        f'<td class="file">{mark}</td>'
        f'<td class="hit">59</td></tr>'
    )


def buk_view(post: int, names: tuple[str, ...]) -> bytes:
    """북구형 본문. 첨부 형식이 링크 글자가 아니라 `title`에만 있다(실측)."""
    items = "".join(
        f"""<li><strong>{escape(name)}&nbsp;[xlsx, 16KB]</strong>
          <a class="btn-down" href="/boardDownload.es?bid=0004&amp;list_no={post}"""
        f"""&amp;seq={index}" title="{escape(name)} 다운로드">다운로드</a></li>"""
        for index, name in enumerate(names, start=1)
    )
    return f"""<html><body><ul class="add_file">{items}</ul></body></html>""".encode()


def nam_view(post: int, names: tuple[str, ...]) -> bytes:
    """남구·동구형 본문. 첨부 형식이 링크 글자와 `filename`에 함께 있다(실측)."""
    items = "".join(
        f"""<li><a href="/download.es?filename={escape(name)}&amp;f_path=board&amp;bid=0007"""
        f"""&amp;type=board&amp;bid=0007&amp;list_no={post}&amp;seq={index}">
          {escape(name)} <span class="fileSize">(17KByte / 다운로드:21)</span></a></li>"""
        for index, name in enumerate(names, start=1)
    )
    return f"""<html><body><ul>{items}</ul></body></html>""".encode()


def seo_rows(rows: tuple[tuple[int, str, str], ...]) -> bytes:
    """서구형 목록. 쪽 넘김도 본문도 없고 줄에서 곧바로 첨부로 이어진다."""
    body = "".join(
        f"""<tr><td>{index}</td><td>{escape(title)}</td>
          <td><div class="btn"><a class="down" href="/openInfoDataFileDownload.es"""
        f"""?oid_seq={post}&amp;file_seq=1" title="">다운로드</a></div></td>
          <td></td><td>{posted}</td></tr>"""
        for index, (post, title, posted) in enumerate(rows, start=1)
    )
    return f"""<html><body><table><thead><tr><th>번호</th><th>제목</th></tr></thead>
      <tbody>{body}</tbody></table></body></html>""".encode()


def gwangsan_entry() -> bytes:
    return (
        b'<html><head><meta name="csrf" content="5b1a482c-a735-4ab1-96bd-0690268477ec"/>'
        b'<meta name="csrf_header" content="X-CSRF-TOKEN"/></head><body></body></html>'
    )


def gwangsan_list(rows: tuple[tuple[int, str, str, str], ...], pages: int = 1) -> bytes:
    return json.dumps(
        {
            "dataMap": {
                "pageCnt": float(pages),
                "totalCnt": float(len(rows)),
                "page": 1,
                "list": [
                    {
                        "sn": 292,
                        "detailSn": post,
                        "detailNm": title,
                        "deptNm": department,
                        "regDt": posted,
                    }
                    for post, title, department, posted in rows
                ],
            },
            "error": "N",
        },
        ensure_ascii=False,
    ).encode()


def gwangsan_detail(post: int, files: tuple[str, ...]) -> bytes:
    return json.dumps(
        {
            "dataMap": {
                "detailSn": post,
                "fileList": [
                    {
                        "fileSe": "IO",
                        "fileSn": index,
                        "fileNm": f"합성 {index}.{suffix}",
                        "fileExtsn": suffix,
                        "fileUrl": f"/fileDownload.do?fileSe=IO&fileKey=292%7C{post}"
                        f"&fileSn={index}",
                    }
                    for index, suffix in enumerate(files, start=1)
                ],
            },
            "error": "N",
        },
        ensure_ascii=False,
    ).encode()


class FakeTransport:
    """게시판 응답만 대신한다. 주소 조립·쪽 넘김·첨부 해석은 실제 스크래퍼가 한다."""

    def __init__(self, answers: dict[str, bytes]) -> None:
        self.answers = answers
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.posts: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes:
        self.requests.append((url, dict(params)))
        address = boards.address(url, params)
        if address not in self.answers:
            raise AssertionError(f"unexpected request {address}")
        return self.answers[address]

    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> bytes:
        form = dict(item.split("=", 1) for item in body.decode("utf-8").split("&"))
        self.posts.append((url, form, dict(headers)))
        key = f"{url}#{form.get('movePage', form.get('detailSn', ''))}"
        if key not in self.answers:
            raise AssertionError(f"unexpected post {key}")
        return self.answers[key]


def board(url: str, scraper: type) -> Board:
    return Board("expenses", url, scraper)


def scrape(url: str, scraper: type, answers: dict[str, bytes]) -> list[boards.Posting]:
    transport = FakeTransport(answers)
    return list(scraper(board(url, scraper), transport).postings(nothing_collected))


def buk_answers(rows: str, views: dict[int, bytes]) -> dict[str, bytes]:
    base = "https://bukgu.example.invalid/board.es"
    answers = {
        boards.address(base, {"mid": "a10502050000", "bid": "0004", "nPage": "1"}): list_rows(rows)
    }
    for post, body in views.items():
        answers[
            boards.address(
                base,
                {"mid": "a10502050000", "bid": "0004", "act": "view", "list_no": str(post)},
            )
        ] = body
    return answers


def test_district_board_reads_a_listing_row_and_its_attachment() -> None:
    """북구형 줄에서 게시일·제목·부서를 읽고, 본문의 `title`에서 첨부 형식을 읽는다."""
    rows = buk_row(1204, "2025년 4분기 업무추진비 집행내역 공개(세무1과)", "세무1과", "2026/08/11")
    answers = buk_answers(rows, {1204: buk_view(1204, ("합성 집행내역.xlsx",))})
    (posting,) = scrape(BUK_URL, GwangjuDistrictBoard, answers)
    assert posting.post_id == "1204"
    assert posting.posted == date(2026, 8, 11)
    assert posting.department == "세무1과"
    assert posting.title == "2025년 4분기 업무추진비 집행내역 공개(세무1과)"
    (attachment,) = posting.attachments
    assert attachment.name == "1204-1.xlsx"
    assert attachment.url.endswith("/boardDownload.es?bid=0004&list_no=1204&seq=1")


def test_district_board_reads_a_table_listing_from_the_same_family() -> None:
    """같은 계열인데 남구만 줄이 표다. 칸의 차례가 같으므로 한 스크래퍼가 둘 다 읽는다."""
    base = "https://namgu.example.invalid/board.es"
    rows = nam_row(1169, "2026년 2분기 구청장 업무추진비 집행내역", "총무과", "2026/07/31")
    answers = {
        boards.address(base, {"mid": "a10304100000", "bid": "0007", "nPage": "1"}): list_rows(rows),
        boards.address(
            base, {"mid": "a10304100000", "bid": "0007", "act": "view", "list_no": "1169"}
        ): nam_view(1169, ("지출내역(구청장).xlsx", "지출내역(부구청장).xlsx")),
    }
    (posting,) = scrape(NAM_URL, GwangjuDistrictBoard, answers)
    assert posting.posted == date(2026, 7, 31)
    assert posting.department == "총무과"
    assert [item.name for item in posting.attachments] == ["1169-1.xlsx", "1169-2.xlsx"]


def test_district_board_skips_a_row_without_an_attachment_mark() -> None:
    """첨부 표시가 없는 줄은 본문을 열지 않는다. 목록만 보고 가른다."""
    rows = buk_row(1204, "첨부 없는 글", "세무1과", "2026/08/11", filed=False) + buk_row(
        1200, "첨부 있는 글", "두암2동", "2026/07/31"
    )
    answers = buk_answers(rows, {1200: buk_view(1200, ("합성.xlsx",))})
    (posting,) = scrape(BUK_URL, GwangjuDistrictBoard, answers)
    assert posting.post_id == "1200"


def test_district_board_walks_every_page_the_listing_declares() -> None:
    base = "https://bukgu.example.invalid/board.es"
    answers = {
        boards.address(base, {"mid": "a10502050000", "bid": "0004", "nPage": "1"}): list_rows(
            buk_row(1204, "첫 쪽", "세무1과", "2026/08/11"), page=1, pages=2
        ),
        boards.address(base, {"mid": "a10502050000", "bid": "0004", "nPage": "2"}): list_rows(
            buk_row(1100, "둘째 쪽", "총무과", "2026/02/02"), page=2, pages=2
        ),
        boards.address(
            base, {"mid": "a10502050000", "bid": "0004", "act": "view", "list_no": "1204"}
        ): buk_view(1204, ("합성.xlsx",)),
        boards.address(
            base, {"mid": "a10502050000", "bid": "0004", "act": "view", "list_no": "1100"}
        ): buk_view(1100, ("합성.xlsx",)),
    }
    assert [item.post_id for item in scrape(BUK_URL, GwangjuDistrictBoard, answers)] == [
        "1204",
        "1100",
    ]


def test_district_board_refuses_a_listing_without_a_page_count() -> None:
    """쪽 수를 못 읽으면 게시판이 바뀐 것이다. 한 쪽만 훑고 끝난 척하지 않는다."""
    rows = buk_row(1204, "제목", "세무1과", "2026/08/11")
    answers = buk_answers(rows, {1204: buk_view(1204, ("합성.xlsx",))})
    (address,) = [key for key in answers if "nPage" in key]
    answers[address] = answers[address].replace("현재 페이지".encode(), b"")
    with pytest.raises(boards.UnreadableBoard):
        scrape(BUK_URL, GwangjuDistrictBoard, answers)


def test_district_board_refuses_a_row_whose_date_is_impossible() -> None:
    rows = buk_row(1204, "제목", "세무1과", "2026/02/31")
    answers = buk_answers(rows, {1204: buk_view(1204, ("합성.xlsx",))})
    with pytest.raises(boards.UnreadableBoard):
        scrape(BUK_URL, GwangjuDistrictBoard, answers)


def test_district_board_does_not_open_a_posting_already_collected() -> None:
    """이미 끝낸 게시글은 본문을 열지 않고 목록에서 읽은 값만 낸다."""
    rows = buk_row(1204, "제목", "세무1과", "2026/08/11")
    transport = FakeTransport(buk_answers(rows, {}))
    scraper = GwangjuDistrictBoard(board(BUK_URL, GwangjuDistrictBoard), transport)
    (posting,) = list(scraper.postings(lambda post_id, posted: post_id == "1204"))
    assert posting.attachments == ()
    assert posting.posted == date(2026, 8, 11)
    assert [params.get("act") for _, params in transport.requests] == [None]


def test_seogu_board_reads_attachments_without_opening_a_posting() -> None:
    """서구는 게시글 본문이 없다. 목록 한 번으로 첨부 주소까지 다 읽는다."""
    answers = {
        boards.address(
            "https://seogu.example.invalid/openInfoCostList.es",
            {"mid": "a10518030100", "oi_seq": "110"},
        ): seo_rows(((4631, "2026년 2/4분기 기관장 업무추진비 공개", "2026-07-10"),))
    }
    transport = FakeTransport(answers)
    scraper = SeoguExpenseBoard(board(SEO_URL, SeoguExpenseBoard), transport)
    (posting,) = list(scraper.postings(nothing_collected))
    assert posting.post_id == "4631"
    assert posting.posted == date(2026, 7, 10)
    assert posting.title == "2026년 2/4분기 기관장 업무추진비 공개"
    (attachment,) = posting.attachments
    # 이 게시판은 첨부 이름을 밝히지 않는다. 형식은 받은 내용의 매직 바이트가 정한다.
    assert attachment.suffix == ""
    assert attachment.name == "4631-1"
    assert len(transport.requests) == 1


def test_seogu_board_declares_that_it_publishes_no_extension() -> None:
    """선언과 대조하는 수집이 이 게시판을 미실측 형식으로 보지 않게 한다."""
    assert SeoguExpenseBoard.published_suffixes == frozenset({""})


def test_seogu_board_refuses_a_row_without_a_posting_date() -> None:
    answers = {
        boards.address(
            "https://seogu.example.invalid/openInfoCostList.es",
            {"mid": "a10518030100", "oi_seq": "110"},
        ): seo_rows(
            (
                (
                    4631,
                    "제목",
                    "게시일 없음",
                ),
            )
        )
    }
    with pytest.raises(boards.UnreadableBoard):
        list(
            SeoguExpenseBoard(board(SEO_URL, SeoguExpenseBoard), FakeTransport(answers)).postings(
                nothing_collected
            )
        )


def gwangsan_answers(
    rows: tuple[tuple[int, str, str, str], ...],
    details: dict[int, bytes],
    pages: int = 1,
) -> dict[str, bytes]:
    origin = "https://gwangsan.example.invalid"
    answers = {
        boards.address(
            f"{origin}/contentsView.do",
            {"pageId": "www159", "infoOpenSn": "292", "infoOpenCtgryUpper": "O130000"},
        ): gwangsan_entry(),
        f"{origin}/getInfoOpenList.do#1": gwangsan_list(rows, pages),
    }
    for post, body in details.items():
        answers[f"{origin}/getInfoOpenData.do#{post}"] = body
    return answers


def test_gwangsan_board_takes_a_token_from_the_entry_page_before_asking() -> None:
    """진입 화면이 세션과 토큰을 내준 뒤에야 목록을 준다. 토큰은 요청 머리에 실린다."""
    answers = gwangsan_answers(
        ((1660, "2026년 2분기 업무추진비 집행내역(시민소통과)", "시민소통과", "2026-08-29"),),
        {1660: gwangsan_detail(1660, ("xlsx",))},
    )
    transport = FakeTransport(answers)
    scraper = GwangsanInfoOpenBoard(board(GWANGSAN_URL, GwangsanInfoOpenBoard), transport)
    (posting,) = list(scraper.postings(nothing_collected))
    assert posting.post_id == "1660"
    assert posting.posted == date(2026, 8, 29)
    assert posting.department == "시민소통과"
    (attachment,) = posting.attachments
    assert attachment.name == "1660-1.xlsx"
    assert attachment.url.endswith("/fileDownload.do?fileSe=IO&fileKey=292%7C1660&fileSn=1")
    # 진입 화면을 먼저 열고, 그 뒤의 모든 요청이 같은 토큰을 싣는다.
    assert [url for url, _ in transport.requests] == [
        "https://gwangsan.example.invalid/contentsView.do"
    ]
    assert {headers["X-CSRF-TOKEN"] for _, _, headers in transport.posts} == {
        "5b1a482c-a735-4ab1-96bd-0690268477ec"
    }


def test_gwangsan_board_walks_every_page_the_answer_declares() -> None:
    answers = gwangsan_answers(
        ((1660, "첫 쪽", "시민소통과", "2026-08-29"),),
        {1660: gwangsan_detail(1660, ("xlsx",)), 1500: gwangsan_detail(1500, ("pdf",))},
        pages=2,
    )
    answers["https://gwangsan.example.invalid/getInfoOpenList.do#2"] = gwangsan_list(
        ((1500, "둘째 쪽", "총무과", "2026-02-02"),), pages=2
    )
    transport = FakeTransport(answers)
    scraper = GwangsanInfoOpenBoard(board(GWANGSAN_URL, GwangsanInfoOpenBoard), transport)
    assert [item.post_id for item in scraper.postings(nothing_collected)] == ["1660", "1500"]


def test_gwangsan_board_refuses_an_answer_that_is_not_the_measured_json() -> None:
    answers = gwangsan_answers((), {})
    answers["https://gwangsan.example.invalid/getInfoOpenList.do#1"] = b"<html>error</html>"
    transport = FakeTransport(answers)
    scraper = GwangsanInfoOpenBoard(board(GWANGSAN_URL, GwangsanInfoOpenBoard), transport)
    with pytest.raises(boards.UnreadableBoard):
        list(scraper.postings(nothing_collected))


def test_gwangsan_board_refuses_an_entry_page_without_a_token() -> None:
    """토큰을 못 읽으면 진입 화면이 바뀐 것이다. 토큰 없이 불러 403을 받지 않는다."""
    answers = gwangsan_answers((), {})
    (entry,) = [key for key in answers if "contentsView.do" in key]
    answers[entry] = b"<html><head></head><body></body></html>"
    transport = FakeTransport(answers)
    scraper = GwangsanInfoOpenBoard(board(GWANGSAN_URL, GwangsanInfoOpenBoard), transport)
    with pytest.raises(boards.UnreadableBoard):
        list(scraper.postings(nothing_collected))


@pytest.mark.parametrize(
    ("url", "scraper"),
    [
        ("https://bukgu.example.invalid/board.es?mid=a10502050000", GwangjuDistrictBoard),
        ("https://seogu.example.invalid/openInfoCostList.es?mid=a10518030100", SeoguExpenseBoard),
        ("https://gwangsan.example.invalid/contentsView.do?pageId=www159", GwangsanInfoOpenBoard),
    ],
)
def test_board_url_must_declare_what_its_scraper_needs(url: str, scraper: type) -> None:
    """빠진 조건은 선언한 자리에서 걸린다. 요청을 보내고 빈 목록으로 끝나지 않는다."""
    with pytest.raises(ValueError):
        scraper(board(url, scraper), FakeTransport({}))


def asked(calls: list[tuple[str, date | None]]) -> "boards.Skipped":
    """무엇을 물어 왔는지 적어 두고 모두 넘긴다. 스크래퍼는 본문을 열지 않는다."""

    def skipped(post_id: str, posted: date | None) -> bool:
        calls.append((post_id, posted))
        return True

    return skipped


def test_district_board_asks_with_the_posting_date_the_listing_declares() -> None:
    """수집이 기간 밖 게시글의 본문까지 여는 일을 막으려면 게시일을 함께 물어야 한다."""
    calls: list[tuple[str, date | None]] = []
    rows = buk_row(1204, "제목", "세무1과", "2019/08/11")
    transport = FakeTransport(buk_answers(rows, {}))
    scraper = GwangjuDistrictBoard(board(BUK_URL, GwangjuDistrictBoard), transport)
    assert [item.attachments for item in scraper.postings(asked(calls))] == [()]
    assert calls == [("1204", date(2019, 8, 11))]
    assert [params.get("act") for _, params in transport.requests] == [None]


def test_seogu_board_asks_with_the_posting_date_the_listing_declares() -> None:
    calls: list[tuple[str, date | None]] = []
    answers = {
        boards.address(
            "https://seogu.example.invalid/openInfoCostList.es",
            {"mid": "a10518030100", "oi_seq": "110"},
        ): seo_rows(((4631, "2019년 2/4분기 기관장 업무추진비 공개", "2019-07-10"),))
    }
    scraper = SeoguExpenseBoard(board(SEO_URL, SeoguExpenseBoard), FakeTransport(answers))
    assert [item.attachments for item in scraper.postings(asked(calls))] == [()]
    assert calls == [("4631", date(2019, 7, 10))]


def test_gwangsan_board_asks_with_the_posting_date_the_listing_declares() -> None:
    calls: list[tuple[str, date | None]] = []
    answers = gwangsan_answers(((1660, "제목", "시민소통과", "2019-08-29"),), {})
    declared = board(GWANGSAN_URL, GwangsanInfoOpenBoard)
    scraper = GwangsanInfoOpenBoard(declared, FakeTransport(answers))
    assert [item.attachments for item in scraper.postings(asked(calls))] == [()]
    assert calls == [("1660", date(2019, 8, 29))]
