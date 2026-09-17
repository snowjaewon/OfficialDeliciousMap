"""게시판 HTML 표를 원본으로 받아 레코드까지 흘리는 일을 공개 CLI로 관찰한다.

게시판 응답은 울산 게시판의 표 구조만 흉내 낸 합성이다. 실제 게시글·상호는 쓰지 않는다.
"""

import csv
import json
from decimal import Decimal
from pathlib import Path

from deliciousmap.cli import main
from deliciousmap.registry import Board, City, DeclaredTable, MapBounds, Organization
from deliciousmap.scrapers.busan import GijangBoard
from deliciousmap.scrapers.ulsan import CityTransferBoard, DongguMayorBoard, JungguMayorBoard

DATA = Path("저장소") / "data"
ORG = "ulsan-city"
LIST_URL = "https://example.invalid/u/rep/transfer/ecnmy/list.ulsan"
BOARD_URL = f"{LIST_URL}?se=2&mId=M1"
# 시청 이전 게시판 상세 표의 열(2026-09-14 실측). 날짜 열이 없고 금액이 천원이다.
CITY_HEADER = ("번호", "결제내용", "결제방법", "인원(수량)", "금액(천원)", "참석대상", "장소")
CITY_TABLE = DeclaredTable(
    header=CITY_HEADER,
    columns={"purpose": 1, "amount_krw": 4, "merchant": 6},
    amount_multiplier=Decimal(1000),
)


class FakeTransport:
    def __init__(self, responses: dict[tuple[str, frozenset[tuple[str, str]]], str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
        self.calls.append((url, dict(params)))
        key = (url, frozenset(params.items()))
        if key not in self.responses:
            raise AssertionError(f"unexpected request: {url} {params}")
        return self.responses[key].encode("utf-8")


def city(*boards: Board) -> City:
    return City(
        "ulsan",
        "울산",
        MapBounds(35.2989, 128.9774, 35.7361, 129.4640),
        (Organization(ORG, "합성시", boards),),
    )


def run(
    root: Path,
    stage: str,
    cities: tuple[City, ...],
    board: FakeTransport | None,
    slug: str = "ulsan",
) -> int:
    return main(
        [
            stage,
            "--city",
            slug,
            "--raw-root",
            str(root / "외부 원본"),
            "--data-root",
            str(root / DATA),
            "--output-root",
            str(root / "출력"),
        ],
        cities=cities,
        board_transport=board,
    )


def payload(root: Path, stage: str, slug: str = "ulsan") -> dict:
    path = root / DATA / slug / f"{stage}.json"
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


def records(root: Path, slug: str = "ulsan") -> list[dict[str, str]]:
    with (root / DATA / slug / "records.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def listing(*days: str) -> str:
    """시청 이전 게시판 목록 한 쪽. 행 하나가 하루치 게시글이다."""
    rows = "".join(
        f"<tr><td>{index}</td><td>{day}</td><td class=subject>"
        f"<a href=\"#\" onclick=\"f_detail('{day}', '2');return false;\">"
        f"합성부시장 업무추진비 집행내역(1건)</a></td><td>9</td></tr>"
        for index, day in enumerate(days, start=1)
    )
    return (
        "<html><body><table><caption>목록</caption><thead><tr><th>번호</th><th>사용일자</th>"
        f"<th>제목</th><th>조회</th></tr></thead><tbody>{rows}</tbody></table>"
        "<ul class=pagination><li class=active><a href=#none title=현재페이지>1</a></li></ul>"
        "</body></html>"
    )


def detail(day: str, *rows: tuple[str, ...], header: tuple[str, ...] = CITY_HEADER) -> str:
    """시청 이전 게시판 상세 쪽. 본문 표 아래에 목록 표가 한 번 더 들어 있다(실측)."""
    head = "".join(f"<th scope=col>{cell}</th>" for cell in header)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return (
        f'<html><body><h2 class="tit_h2">{day}합성부시장 업무추진비 상세내용 목록</h2>'
        f"<table><caption>상세내용</caption><thead><tr>{head}</tr></thead>"
        f"<tbody>{body}</tbody></table>" + listing(day).removeprefix("<html><body>")
    )


def transfer_board(*details: tuple[str, str]) -> FakeTransport:
    days = [day for day, _ in details]
    return FakeTransport(
        {
            (LIST_URL, frozenset({"se": "2", "mId": "M1", "curPage": "1"}.items())): listing(*days),
            **{
                (LIST_URL, frozenset({"se": "2", "mId": "M1", "useDe": day}.items())): page
                for day, page in details
            },
        }
    )


def test_a_daily_html_table_becomes_records_dated_by_the_detail_key(tmp_path: Path) -> None:
    cities = (city(Board("expenses-deputy", BOARD_URL, CityTransferBoard, CITY_TABLE)),)
    board = transfer_board(
        (
            "2026-03-05",
            detail(
                "2026-03-05",
                ("1", "합성 현안 간담회", "카드", "4", "147", "시 및 관계자 등", "합성식당"),
                ("2", "합성 직원 격려", "카드", "20", "60", "소속직원", "합성카페"),
            ),
        )
    )

    assert run(tmp_path, "fetch", cities, board) == 0
    assert run(tmp_path, "headermap", cities, None) == 0
    assert run(tmp_path, "parse", cities, None) == 0

    (source,) = payload(tmp_path, "fetch")["sources"]
    assert source["container"] == "html"
    assert source["spent_on"] == "2026-03-05"
    assert source["url"] == f"{LIST_URL}?se=2&mId=M1&useDe=2026-03-05"
    found = [
        (row["spent_on"], row["merchant"], row["amount_krw"], row["purpose"])
        for row in records(tmp_path)
    ]
    assert found == [
        ("2026-03-05", "합성식당", "147000", "합성 현안 간담회"),
        ("2026-03-05", "합성카페", "60000", "합성 직원 격려"),
    ]


def test_a_won_amount_under_a_thousand_won_header_holds_that_day(tmp_path: Path) -> None:
    # 시청 표는 헤더가 천원인데 몇 행을 원으로 적었다(목업 실측 7건). 곱하면 1억 원대 지출이
    # 되고 나누면 원본을 고친 것이 된다. 그날 원본을 미해결로 두고 다른 날은 그대로 둔다.
    cities = (city(Board("expenses-deputy", BOARD_URL, CityTransferBoard, CITY_TABLE)),)
    board = transfer_board(
        (
            "2026-03-05",
            detail(
                "2026-03-05",
                ("1", "합성 간담회", "카드", "6", "187,000", "시 및 관계자 등", "합성한정식"),
                ("2", "합성 격려", "카드", "5", "91", "직원", "합성분식"),
            ),
        ),
        (
            "2026-03-06",
            detail("2026-03-06", ("1", "합성 협의", "카드", "4", "88", "직원", "합성국밥")),
        ),
    )

    assert run(tmp_path, "fetch", cities, board) == 0
    assert run(tmp_path, "headermap", cities, None) == 0
    assert run(tmp_path, "parse", cities, None) == 0

    held = {item["spent_on"]: item["source_hash"] for item in payload(tmp_path, "fetch")["sources"]}
    reports = {item["source_hash"]: item for item in payload(tmp_path, "parse")["sources"]}
    assert reports[held["2026-03-05"]]["status"] == "unresolved"
    assert reports[held["2026-03-05"]]["reason"] == "validation_failed"
    assert reports[held["2026-03-05"]]["detail"] == "table1:R2 amount_unit"
    assert [(row["merchant"], row["amount_krw"]) for row in records(tmp_path)] == [
        ("합성국밥", "88000")
    ]


JUNGGU_LIST = "https://example.invalid/mayor/board/list.ulsan"
JUNGGU_URL = f"{JUNGGU_LIST}?boardId=BBS_6&listRow=10"
# 중구 구청장 목록 표의 열(2026-09-14 실측). 목록이 곧 집행내역이고 금액은 원이다.
JUNGGU_HEADER = (
    "번호",
    "날짜",
    "시간",
    "장소",
    "집행목적",
    "대상 인원수",
    "금액(원)",
    "결제방법",
    "비목",
)
JUNGGU_TABLE = DeclaredTable(
    header=JUNGGU_HEADER,
    columns={"spent_on": 1, "time": 2, "merchant": 3, "purpose": 4, "amount_krw": 6},
)


def junggu_year(*rows: tuple[str, ...], pages: str = "1/1") -> str:
    head = "".join(f"<th scope=col>{cell}</th>" for cell in JUNGGU_HEADER)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return (
        f"<html><body><p class=total>총게시물 <strong>{len(rows)}</strong> / 페이지 :"
        f"<strong>{pages}</strong></p><table><caption>업무추진비 목록 게시판</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></body></html>"
    )


def junggu_board(page: str) -> FakeTransport:
    params = {
        "boardId": "BBS_6",
        "listRow": "1000",
        "searchType": "TMP_FIELD1",
        "searchOperation": "OR",
        "keyword": "2026",
        "startPage": "1",
    }
    return FakeTransport({(JUNGGU_LIST, frozenset(params.items())): page})


def test_the_fiscal_year_listing_is_one_original_read_by_its_date_column(tmp_path: Path) -> None:
    cities = (city(Board("expenses-mayor", JUNGGU_URL, JungguMayorBoard, JUNGGU_TABLE)),)
    board = junggu_board(
        junggu_year(
            (
                "3",
                "2026-07-02",
                "12:10",
                "합성갈비",
                "합성 행사 노고 격려",
                "7",
                "176,800",
                "카드결제",
                "기관",
            ),
            ("2", "2026-06-29", "", "", "부의금 지급", "1", "50,000", "현금", "기관"),
            (
                "1",
                "2026-06-28",
                "12:42",
                "합성하우스 외 1",
                "합성 간담회",
                "14",
                "521,400",
                "카드결제",
                "시책",
            ),
        )
    )

    assert run(tmp_path, "fetch", cities, board) == 0
    assert run(tmp_path, "headermap", cities, None) == 0
    assert run(tmp_path, "parse", cities, None) == 0

    (source,) = payload(tmp_path, "fetch")["sources"]
    assert source["container"] == "html"
    assert source["spent_on"] is None
    (report,) = payload(tmp_path, "parse")["sources"]
    assert (report["candidates"], report["records"], report["out_of_range"]) == (3, 2, 1)
    assert [(row["spent_on"], row["merchant"], row["amount_krw"]) for row in records(tmp_path)] == [
        ("2026-06-29", "개인(성명 비공개)", "50000"),
        ("2026-06-28", "합성하우스 외 1", "521400"),
    ]


def test_a_fiscal_year_listing_beyond_one_page_is_not_guessed(tmp_path: Path) -> None:
    # 해 목록은 새 행이 위에 쌓여 둘째 쪽부터 내용이 밀린다. 한 쪽에 담기지 않으면 알린다.
    cities = (city(Board("expenses-mayor", JUNGGU_URL, JungguMayorBoard, JUNGGU_TABLE)),)
    board = junggu_board(
        junggu_year(("1", "2026-06-28", "", "합성", "합성", "1", "1", "카드", "기관"), pages="1/2")
    )

    assert run(tmp_path, "fetch", cities, board) == 0
    assert payload(tmp_path, "fetch")["sources"] == []
    assert "ulsan-city/expenses-mayor=adapter-failed" in payload(tmp_path, "fetch")["empty_reason"]


DONGGU_LIST = "https://example.invalid/mayor/expense/list.do"
DONGGU_VIEW = "https://example.invalid/mayor/expense/view.do"
# 동구 구청장 상세 표의 열(2026-09-14 실측). 날짜 열이 없고, 칸마다 열 이름을 되풀이한다.
DONGGU_HEADER = (
    "번호",
    "시간",
    "장소",
    "집행목적",
    "인원수",
    "금액(원)",
    "결제방법",
    "비목",
    "첨부",
)
DONGGU_TABLE = DeclaredTable(
    header=DONGGU_HEADER,
    columns={"time": 1, "merchant": 2, "purpose": 3, "amount_krw": 5},
)


def donggu_detail(day: str, *rows: tuple[str, ...]) -> str:
    head = "".join(f"<th scope=col>{cell}</th>" for cell in DONGGU_HEADER)
    body = "".join(
        "<tr>"
        + "".join(
            f'<td><span class="add-head">{label}</span><span class="tds">{cell}</span></td>'
            for label, cell in zip(DONGGU_HEADER, row, strict=True)
        )
        + "</tr>"
        for row in rows
    )
    return (
        f'<html><body><p class="result-txt">{day} 집행내역입니다.</p>'
        f'<table class="bbs_list2"><caption>일일업무추진비 공개 상세보기</caption>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        "<table><caption>업무추진비 공개 게시물목록</caption><tr><th>집행일</th><th>시간</th>"
        "</tr><tr><td colspan=6>등록(검색)된 데이터가 없습니다.</td></tr></table></body></html>"
    )


def donggu_board(*days: tuple[str, str]) -> FakeTransport:
    responses = {}
    for month in range(1, 13):
        rows = "".join(
            f"<tr><td>{day[:4]}-{day[4:6]}-{day[6:]}</td><td>"
            f'<a href="./view.do?ymd2={day}&pageIndex=1">구청장 집행내역(1)</a></td></tr>'
            for day, _ in days
            if int(day[4:6]) == month
        )
        page = f"<p>총게시물 : 1 / 페이지 : 1/1</p><table>{rows}</table>"
        params = {"searchWrd": f"2026{month:02d}", "pageIndex": "1"}
        responses[(DONGGU_LIST, frozenset(params.items()))] = page
    for day, page in days:
        responses[(DONGGU_VIEW, frozenset({"ymd2": day}.items()))] = page
    return FakeTransport(responses)


def test_a_daily_detail_reads_values_past_the_repeated_column_labels(tmp_path: Path) -> None:
    cities = (city(Board("expenses-mayor", DONGGU_LIST, DongguMayorBoard, DONGGU_TABLE)),)
    board = donggu_board(
        (
            "20260209",
            donggu_detail(
                "2026-02-09",
                ("1", "11:40", "합성곤지", "합성 업무협의", "7", "140,000", "카드", "기관", ""),
                ("2", "15:18", "합성마켓", "합성 직원 격려", "60", "780,000", "카드", "기관", ""),
            ),
        )
    )

    assert run(tmp_path, "fetch", cities, board) == 0
    assert run(tmp_path, "headermap", cities, None) == 0
    assert run(tmp_path, "parse", cities, None) == 0

    (source,) = payload(tmp_path, "fetch")["sources"]
    assert (source["url"], source["spent_on"]) == (f"{DONGGU_VIEW}?ymd2=20260209", "2026-02-09")
    assert [(row["spent_on"], row["merchant"], row["amount_krw"]) for row in records(tmp_path)] == [
        ("2026-02-09", "합성곤지", "140000"),
        ("2026-02-09", "합성마켓", "780000"),
    ]


def test_a_detail_row_without_an_amount_is_not_filled_in(tmp_path: Path) -> None:
    # 동구 상세에는 금액 칸이 빈 채 첨부만 단 행이 있다(2026-02-09 실측). 채우지 않는다.
    cities = (city(Board("expenses-mayor", DONGGU_LIST, DongguMayorBoard, DONGGU_TABLE)),)
    board = donggu_board(
        (
            "20260209",
            donggu_detail(
                "2026-02-09",
                (
                    "1",
                    "19:47",
                    "합성횟집",
                    "합성 타운홀 격려",
                    "28",
                    "1,220,000",
                    "카드",
                    "기관",
                    "",
                ),
                ("2", "19:47", "합성횟집", "합성 타운홀 격려", "28", "", "카드", "기관", ""),
            ),
        )
    )

    assert run(tmp_path, "fetch", cities, board) == 0
    assert run(tmp_path, "headermap", cities, None) == 0
    assert run(tmp_path, "parse", cities, None) == 0

    (report,) = payload(tmp_path, "parse")["sources"]
    assert (report["status"], report["reason"], report["detail"]) == (
        "unresolved",
        "validation_failed",
        "table1:R3 amount_krw",
    )
    assert report["candidates"] == 2
    assert records(tmp_path) == []


def test_a_page_whose_header_differs_from_the_declaration_stays_unresolved(tmp_path: Path) -> None:
    # 사이트 틀이 열을 바꾸면 선언이 맞지 않는다. 짐작해 맞추지 않고 원본을 미해결로 둔다.
    cities = (city(Board("expenses-deputy", BOARD_URL, CityTransferBoard, CITY_TABLE)),)
    changed = ("번호", "결제내용", "결제방법", "인원(수량)", "금액(원)", "참석대상", "장소")
    board = transfer_board(
        (
            "2026-03-05",
            detail(
                "2026-03-05", ("1", "합성", "카드", "4", "88,000", "직원", "합성"), header=changed
            ),
        )
    )

    assert run(tmp_path, "fetch", cities, board) == 0
    assert run(tmp_path, "headermap", cities, None) == 0
    assert run(tmp_path, "parse", cities, None) == 0

    (report,) = payload(tmp_path, "parse")["sources"]
    assert (report["status"], report["reason"], report["detail"]) == (
        "unresolved",
        "validation_failed",
        "declared header not found",
    )


def test_a_daily_posting_is_targeted_by_its_day_not_its_title(tmp_path: Path) -> None:
    # 하루치 게시글의 제목(`...집행내역(1건)`)은 기간을 적지 않는다. 그 날로 가른다.
    cities = (city(Board("expenses-deputy", BOARD_URL, CityTransferBoard, CITY_TABLE)),)
    board = transfer_board(
        ("2026-07-01", detail("2026-07-01", ("1", "합성", "카드", "4", "88", "직원", "합성탕"))),
        ("2026-06-30", detail("2026-06-30", ("1", "합성", "카드", "4", "77", "직원", "합성면"))),
    )

    assert run(tmp_path, "fetch", cities, board) == 0
    assert run(tmp_path, "headermap", cities, None) == 0
    assert run(tmp_path, "parse", cities, None) == 0

    assert len(payload(tmp_path, "fetch")["sources"]) == 2
    assert payload(tmp_path, "parse")["excluded_sources"] == {
        "posted_out_of_range": 0,
        "declared_out_of_range": 1,
        "undeclared_in_year": 0,
    }
    assert [row["merchant"] for row in records(tmp_path)] == ["합성면"]


def test_a_board_that_fails_later_keeps_the_days_it_already_listed(tmp_path: Path) -> None:
    # 시청 부서장 목록은 2020년 구간의 한 행이 사용일자를 `202-12-28`로 적었다(2026-09-14
    # 실측). 그 행에서 게시판이 실패로 끝나도, 앞서 받은 날의 원본은 그 날을 잃지 않는다.
    cities = (city(Board("expenses-deputy", BOARD_URL, CityTransferBoard, CITY_TABLE)),)
    first = listing("2026-03-05").replace(
        "<a href=#none title=현재페이지>1</a></li>",
        "<a href=#none title=현재페이지>1</a></li><li><a href='?curPage=2&se=2&mId=M1'>2</a></li>",
    )
    broken = listing("202-12-28").replace("현재페이지>1", "현재페이지>2")
    board = FakeTransport(
        {
            (LIST_URL, frozenset({"se": "2", "mId": "M1", "curPage": "1"}.items())): first,
            (LIST_URL, frozenset({"se": "2", "mId": "M1", "curPage": "2"}.items())): broken,
            (LIST_URL, frozenset({"se": "2", "mId": "M1", "useDe": "2026-03-05"}.items())): detail(
                "2026-03-05", ("1", "합성 협의", "카드", "4", "88", "직원", "합성국밥")
            ),
        }
    )

    assert run(tmp_path, "fetch", cities, board) == 0
    assert run(tmp_path, "headermap", cities, None) == 0
    assert run(tmp_path, "parse", cities, None) == 0

    fetched = payload(tmp_path, "fetch")
    assert "ulsan-city/expenses-deputy=adapter-failed" in fetched["empty_reason"]
    (source,) = fetched["sources"]
    assert source["spent_on"] == "2026-03-05"
    assert [(row["spent_on"], row["merchant"]) for row in records(tmp_path)] == [
        ("2026-03-05", "합성국밥")
    ]


def test_a_page_with_the_declared_header_twice_is_not_guessed(tmp_path: Path) -> None:
    # 선언한 헤더의 표가 둘이면 어느 쪽이 그날의 집행내역인지 가를 근거가 없다.
    cities = (city(Board("expenses-deputy", BOARD_URL, CityTransferBoard, CITY_TABLE)),)
    once = detail("2026-03-05", ("1", "합성", "카드", "4", "88", "직원", "합성탕"))
    twice = once.replace(
        "<table><caption>목록</caption>", _first_table(once) + "<table><caption>목록</caption>"
    )
    board = transfer_board(("2026-03-05", twice))

    assert run(tmp_path, "fetch", cities, board) == 0
    assert run(tmp_path, "headermap", cities, None) == 0
    assert run(tmp_path, "parse", cities, None) == 0

    (report,) = payload(tmp_path, "parse")["sources"]
    assert (report["status"], report["detail"]) == ("unresolved", "declared header repeated")
    assert records(tmp_path) == []


def _first_table(page: str) -> str:
    start = page.index("<table>")
    return page[start : page.index("</table>", start) + len("</table>")]


GIJANG_LIST = "https://example.invalid/board/list.gijang"
GIJANG_URL = f"{GIJANG_LIST}?boardId=BBS_0000147&paging=ok"
# 기장군 목록 표의 열(2026-09-17 실측). 목록 전량이 한 쪽이고 금액은 원이다.
GIJANG_HEADER = (
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
GIJANG_TABLE = DeclaredTable(
    header=GIJANG_HEADER,
    columns={"department": 0, "spent_on": 2, "merchant": 3, "purpose": 4, "amount_krw": 5},
)


def busan(*boards: Board) -> City:
    return City(
        "busan",
        "부산",
        MapBounds(34.879908, 128.738436, 35.395936, 129.314776),
        (Organization("busan-gijang", "합성군", boards),),
    )


def gijang_listing(*rows: tuple[str, ...], pages: str = "1/1") -> str:
    head = "".join(f"<th>{cell}</th>" for cell in GIJANG_HEADER)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return (
        f"<html><body><p>총게시물 <b>{len(rows)}</b>건 <span>｜</span> 페이지 : {pages}</p>"
        f"<table><caption>업무 추진비 공개 게시판 리스트</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        '<div class="page"><a href="/board/list.gijang?startPage=1">1</a></div></body></html>'
    )


def gijang_board(page: str) -> FakeTransport:
    params = {
        "boardId": "BBS_0000147",
        "paging": "ok",
        "listCel": "1",
        "listRow": GijangBoard.page_size,
        "startPage": "1",
    }
    return FakeTransport({(GIJANG_LIST, frozenset(params.items())): page})


def gijang_row(spent: str, merchant: str, amount: str) -> tuple[str, ...]:
    return ("행정지원과", "군수", spent, merchant, "합성 간담회", amount, "2", "카드", "", "")


def test_the_gijang_table_becomes_records_read_by_its_use_date_column(tmp_path: Path) -> None:
    """첨부 없는 HTML 표에서 집행 줄을 레코드로 뽑는다. 선언 매핑만 쓰고 모델은 부르지 않는다."""
    cities = (busan(Board("expenses", GIJANG_URL, GijangBoard, GIJANG_TABLE)),)
    board = gijang_board(
        gijang_listing(
            gijang_row("2026. 3. 20.", "합성식당", "176,800"),
            gijang_row("20260628", "합성갈비", "521,400"),
            gijang_row("26.6.11.", "합성카페", "60,000"),
            gijang_row("2025. 3. 20.", "합성국밥", "50,000"),
        )
    )

    assert run(tmp_path, "fetch", cities, board, "busan") == 0
    assert run(tmp_path, "headermap", cities, None, "busan") == 0
    assert run(tmp_path, "parse", cities, None, "busan") == 0

    fetched = payload(tmp_path, "fetch", "busan")
    assert fetched["empty_reason"] is None
    (source,) = fetched["sources"]
    assert (source["container"], source["spent_on"]) == ("html", None)
    (report,) = payload(tmp_path, "parse", "busan")["sources"]
    assert (report["candidates"], report["records"], report["out_of_range"]) == (4, 3, 1)
    assert [
        (row["spent_on"], row["merchant"], row["amount_krw"], row["department"])
        for row in records(tmp_path, "busan")
    ] == [
        ("2026-03-20", "합성식당", "176800", "행정지원과"),
        ("2026-06-28", "합성갈비", "521400", "행정지원과"),
        ("2026-06-11", "합성카페", "60000", "행정지원과"),
    ]


def test_a_gijang_row_without_a_use_date_leaves_the_rest_of_the_table(tmp_path: Path) -> None:
    """사용일자 칸은 자유 입력이라 읽지 못하는 줄이 섞인다(실측 3,297줄 중 67줄).

    그 줄만 레코드에서 빠지고 위치와 사유가 제외 목록에 남는다. 후보 수에서는 사라지지 않는다.
    """
    cities = (busan(Board("expenses", GIJANG_URL, GijangBoard, GIJANG_TABLE)),)
    board = gijang_board(
        gijang_listing(
            gijang_row("2026. 3. 20.", "합성식당", "176,800"),
            gijang_row("", "합성찻집", "27,000"),
            gijang_row("6.27.(금)", "합성분식", "31,000"),
            gijang_row("2026. 4. 2.", "합성국밥", "50,000"),
        )
    )

    assert run(tmp_path, "fetch", cities, board, "busan") == 0
    assert run(tmp_path, "headermap", cities, None, "busan") == 0
    assert run(tmp_path, "parse", cities, None, "busan") == 0

    (report,) = payload(tmp_path, "parse", "busan")["sources"]
    assert report["status"] == "parsed"
    assert (report["candidates"], report["records"], report["out_of_range"]) == (4, 2, 0)
    assert report["excluded"] == ["table1:R3 spent_on", "table1:R4 spent_on"]
    assert [row["merchant"] for row in records(tmp_path, "busan")] == ["합성식당", "합성국밥"]


def test_a_gijang_header_that_no_longer_matches_stays_unresolved(tmp_path: Path) -> None:
    """틀이 바뀐 표는 짐작해 맞추지 않는다. 모델이 없어도 선언만으로 이 판정이 난다."""
    cities = (busan(Board("expenses", GIJANG_URL, GijangBoard, GIJANG_TABLE)),)
    changed = gijang_listing(gijang_row("2026. 3. 20.", "합성식당", "176,800")).replace(
        "<th>사용일자(일시)</th>", "<th>사용일자</th>"
    )

    assert run(tmp_path, "fetch", cities, gijang_board(changed), "busan") == 0
    assert run(tmp_path, "headermap", cities, None, "busan") == 0
    assert run(tmp_path, "parse", cities, None, "busan") == 0

    (report,) = payload(tmp_path, "parse", "busan")["sources"]
    assert (report["status"], report["reason"], report["detail"]) == (
        "unresolved",
        "validation_failed",
        "declared header not found",
    )
    assert records(tmp_path, "busan") == []


def test_a_gijang_table_beyond_one_page_is_reported_not_collected(tmp_path: Path) -> None:
    """전량이 한 쪽에 담기지 않으면 조용한 부분 수집 대신 읽지 못한 게시판으로 실패한다."""
    cities = (busan(Board("expenses", GIJANG_URL, GijangBoard, GIJANG_TABLE)),)
    board = gijang_board(
        gijang_listing(gijang_row("2026. 3. 20.", "합성식당", "176,800"), pages="1/2")
    )

    # 부산은 게시판 장애를 이어 가지 않는 도시라(#140) 수집 자체가 실패로 끝난다.
    assert run(tmp_path, "fetch", cities, board, "busan") == 1
    assert not (tmp_path / DATA / "busan" / "fetch.json").exists()
