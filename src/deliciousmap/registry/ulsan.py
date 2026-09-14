"""울산광역시와 5개 구·군의 검증된 업무추진비 게시판 레지스트리."""

from deliciousmap.registry.models import Board, City, MapBounds, Organization
from deliciousmap.scrapers.ulsan import (
    BukguBoard,
    CityMarketBoard,
    CityTransferBoard,
    DongguMayorBoard,
    EgovBoard,
    JungguBoard,
    JungguMayorBoard,
    NamguBoard,
    UljuBoard,
)

CITY_MARKET = (
    "https://www.ulsan.go.kr/u/rep/bbs/list.ulsan?bbsId=BBS_0000000000000255&mId=001003002007000000"
)
CITY_DIRECTOR = "https://www.ulsan.go.kr/u/rep/transfer/director/list.ulsan?mId=001003002003000000"
CITY_ECONOMIC = "https://www.ulsan.go.kr/u/rep/transfer/ecnmy/list.ulsan?mId=001003002001000000"
JUNGGU_MAYOR = "https://www.junggu.ulsan.kr/mayor/board/list.ulsan?boardId=BBS_0000006&listCel=1&listRow=10&menuCd=DOM_000000201005000000"
JUNGGU_DEPUTY = "https://www.junggu.ulsan.kr/index.ulsan?boardId=BBS_0000114&menuCd=DOM_000000104007001000&paging=ok&startPage=1"
JUNGGU_DIRECTOR = "https://www.junggu.ulsan.kr/board/list.ulsan?boardId=BBS_0000115&menuCd=DOM_000000104007002000&paging=ok&startPage=1"
JUNGGU_DEPARTMENT = "https://www.junggu.ulsan.kr/board/list.ulsan?boardId=BBS_0000116&menuCd=DOM_000000104007003000&paging=ok&startPage=1"
JUNGGU_LEGACY = "https://www.junggu.ulsan.kr/board/list.ulsan?boardId=BBS_0000117&menuCd=DOM_000000104007004000&paging=ok&startPage=1"
NAMGU_BASE = "https://www.ulsannamgu.go.kr/cop/bbs/selectBoardList.do"
DONGGU_BASE = "https://www.donggu.ulsan.kr/cop/bbs/selectBoardList.do"
ULJU_DEPUTY = "https://www.ulju.ulsan.kr/ulju/bbs/list.do?ptIdx=117&mId=0216040100"
ULJU_DIRECTOR = "https://www.ulju.ulsan.kr/ulju/bbs/list.do?ptIdx=117&mId=0216040200"
ULJU_DEPARTMENT = "https://www.ulju.ulsan.kr/ulju/bbs/list.do?ptIdx=117&mId=0216040300"

CITY = City(
    "ulsan",
    "울산",
    MapBounds(35.2989, 128.9774, 35.7361, 129.4640),
    (
        Organization(
            "ulsan-city",
            "울산광역시",
            (
                Board("expenses-market", CITY_MARKET, CityMarketBoard),
                Board("expenses-director", CITY_DIRECTOR, CityTransferBoard),
                Board("expenses-economic", CITY_ECONOMIC, CityTransferBoard),
            ),
        ),
        Organization(
            "ulsan-junggu",
            "울산광역시 중구",
            (
                Board("expenses-mayor", JUNGGU_MAYOR, JungguMayorBoard),
                Board("expenses-deputy", JUNGGU_DEPUTY, JungguBoard),
                Board("expenses-director", JUNGGU_DIRECTOR, JungguBoard),
                Board("expenses-department", JUNGGU_DEPARTMENT, JungguBoard),
                Board("expenses-legacy", JUNGGU_LEGACY, JungguBoard),
            ),
        ),
        Organization(
            "ulsan-namgu",
            "울산광역시 남구",
            tuple(
                Board(f"expenses-{slug}", f"{NAMGU_BASE}?bbsId={bbs}", NamguBoard)
                for slug, bbs in (
                    ("deputy", "PrmtFee"),
                    ("director", "PrmtFee1"),
                    ("department", "PrmtFee2"),
                    ("dong", "dongPrmtFee"),
                    ("health", "healthPrmtFee"),
                )
            ),
        ),
        Organization(
            "ulsan-donggu",
            "울산광역시 동구",
            (
                Board(
                    "expenses-mayor",
                    "https://www.donggu.ulsan.kr/mayor/expense/list.do",
                    DongguMayorBoard,
                ),
                Board("expenses-deputy", f"{DONGGU_BASE}?bbsId=BBSMSTR_000000000354", EgovBoard),
                Board("expenses-director", f"{DONGGU_BASE}?bbsId=BBSMSTR_000000000361", EgovBoard),
                Board(
                    "expenses-department", f"{DONGGU_BASE}?bbsId=BBSMSTR_000000000362", EgovBoard
                ),
            ),
        ),
        Organization(
            "ulsan-bukgu",
            "울산광역시 북구",
            (
                Board(
                    "expenses",
                    "https://www.bukgu.ulsan.kr/lay1/bbs/S1T136C1896/A/348/list.do",
                    BukguBoard,
                ),
            ),
        ),
        Organization(
            "ulsan-ulju",
            "울산광역시 울주군",
            (
                Board("expenses-deputy", ULJU_DEPUTY, UljuBoard),
                Board("expenses-director", ULJU_DIRECTOR, UljuBoard),
                Board("expenses-department", ULJU_DEPARTMENT, UljuBoard),
            ),
        ),
    ),
)
