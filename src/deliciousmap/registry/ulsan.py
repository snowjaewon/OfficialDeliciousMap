"""울산광역시와 5개 구·군의 검증된 업무추진비 게시판 레지스트리."""

from decimal import Decimal

from deliciousmap.registry.models import Board, City, DeclaredTable, Hall, MapBounds, Organization
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
# 시청 업무추진비 메뉴 진입점(`/u/rep/contents.ulsan?mId=…`)이 넘겨주는 주소(2026-09-14 실측).
# 게시판 내용은 경로와 `se`가 정하고 `mId`는 화면 제목만 정한다. 실·국장(구)는 2019년까지의
# 게시글형 옛 자료라 대상 기간 밖이어서 등록하지 않는다.
CITY_TRANSFER = "https://www.ulsan.go.kr/u/rep/transfer"
CITY_DEPUTY = f"{CITY_TRANSFER}/ecnmy/list.ulsan?se=2&mId=001003002001000000"
CITY_ECONOMIC = f"{CITY_TRANSFER}/ecnmy/list.ulsan?se=3&mId=001003002002000000"
CITY_FEZ = f"{CITY_TRANSFER}/ecnmy/list.ulsan?se=6&mId=001003002006000000"
CITY_DIRECTOR = f"{CITY_TRANSFER}/director/list.ulsan?mId=001003002003000000"
CITY_DEPARTMENT = f"{CITY_TRANSFER}/chief/list.ulsan?mId=001003002005000000"
# 시청 다섯 게시판의 상세 표(2026-09-14 실측). 집행일 열이 없어 상세 키의 날을 쓰고, 금액은
# 천원이다. `참석대상`에는 역할을 주지 않아 레코드로 옮기지 않는다.
CITY_TABLE = DeclaredTable(
    header=("번호", "결제내용", "결제방법", "인원(수량)", "금액(천원)", "참석대상", "장소"),
    columns={"purpose": 1, "amount_krw": 4, "merchant": 6},
    amount_multiplier=Decimal(1000),
)
# 중구 구청장 목록 표. 목록이 곧 집행내역이고 금액은 원이다(2022-07-01부터, 목록 안내문).
JUNGGU_MAYOR_TABLE = DeclaredTable(
    header=(
        "번호",
        "날짜",
        "시간",
        "장소",
        "집행목적",
        "대상 인원수",
        "금액(원)",
        "결제방법",
        "비목",
    ),
    columns={"spent_on": 1, "time": 2, "merchant": 3, "purpose": 4, "amount_krw": 6},
)
# 동구 구청장 상세 표. 집행일 열이 없어 상세 키의 날을 쓴다.
DONGGU_MAYOR_TABLE = DeclaredTable(
    header=("번호", "시간", "장소", "집행목적", "인원수", "금액(원)", "결제방법", "비목", "첨부"),
    columns={"time": 1, "merchant": 2, "purpose": 3, "amount_krw": 5},
)
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

# 2026-09-16 네이버 지역검색 실측으로 받은 청사 좌표. 질의는 기관 이름이며(`울산광역시청`,
# `울산 남구청` …) 응답이 밝힌 도로명주소가 그 기관이 누리집에 적은 소재지와 같은 것만 쓴다.
# 같은 상호가 도시 안 여러 곳에 있을 때 고르는 기준점일 뿐 기관의 경계가 아니다(ADR-0010).
CITY_HALL = Hall(35.5394772, 129.3112994)  # 남구 중앙로 201
JUNGGU_HALL = Hall(35.5694499, 129.3327)  # 중구 단장골길 1
NAMGU_HALL = Hall(35.5437979, 129.330109)  # 남구 돋질로 233
DONGGU_HALL = Hall(35.5048439, 129.416632)  # 동구 봉수로 155
BUKGU_HALL = Hall(35.5827089, 129.361313)  # 북구 산업로 1010
ULJU_HALL = Hall(35.5220885, 129.2422294)  # 울주군 청량읍 군청로 1

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
                Board("expenses-deputy", CITY_DEPUTY, CityTransferBoard, CITY_TABLE),
                Board("expenses-economic", CITY_ECONOMIC, CityTransferBoard, CITY_TABLE),
                Board("expenses-fez", CITY_FEZ, CityTransferBoard, CITY_TABLE),
                Board("expenses-director", CITY_DIRECTOR, CityTransferBoard, CITY_TABLE),
                Board("expenses-department", CITY_DEPARTMENT, CityTransferBoard, CITY_TABLE),
            ),
            hall=CITY_HALL,
        ),
        Organization(
            "ulsan-junggu",
            "울산광역시 중구",
            (
                Board("expenses-mayor", JUNGGU_MAYOR, JungguMayorBoard, JUNGGU_MAYOR_TABLE),
                Board("expenses-deputy", JUNGGU_DEPUTY, JungguBoard),
                Board("expenses-director", JUNGGU_DIRECTOR, JungguBoard),
                Board("expenses-department", JUNGGU_DEPARTMENT, JungguBoard),
                Board("expenses-legacy", JUNGGU_LEGACY, JungguBoard),
            ),
            hall=JUNGGU_HALL,
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
            hall=NAMGU_HALL,
        ),
        Organization(
            "ulsan-donggu",
            "울산광역시 동구",
            (
                Board(
                    "expenses-mayor",
                    "https://www.donggu.ulsan.kr/mayor/expense/list.do",
                    DongguMayorBoard,
                    DONGGU_MAYOR_TABLE,
                ),
                Board("expenses-deputy", f"{DONGGU_BASE}?bbsId=BBSMSTR_000000000354", EgovBoard),
                Board("expenses-director", f"{DONGGU_BASE}?bbsId=BBSMSTR_000000000361", EgovBoard),
                Board(
                    "expenses-department", f"{DONGGU_BASE}?bbsId=BBSMSTR_000000000362", EgovBoard
                ),
            ),
            hall=DONGGU_HALL,
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
            hall=BUKGU_HALL,
        ),
        Organization(
            "ulsan-ulju",
            "울산광역시 울주군",
            (
                Board("expenses-deputy", ULJU_DEPUTY, UljuBoard),
                Board("expenses-director", ULJU_DIRECTOR, UljuBoard),
                Board("expenses-department", ULJU_DEPARTMENT, UljuBoard),
            ),
            hall=ULJU_HALL,
        ),
    ),
    # 후보 주소가 울산광역시로 시작할 때만 독립 근거 없이 도시 안 업소로 채택한다.
    address_prefixes=("울산광역시",),
)
