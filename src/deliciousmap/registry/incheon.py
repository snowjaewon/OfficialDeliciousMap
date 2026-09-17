"""인천광역시와 9구 2군의 검증된 업무추진비 게시판 레지스트리.

주소·계열은 2026-09-17에 프로젝트 UA로 실측했다. 근거는 `docs/validation/issue-174.md`에 있다.

기관이 열둘인 것은 2026-07-01 행정체제 개편 때문이다. 옛 중구·동구가 제물포구와 영종구로,
서구가 서해구와 검단구로 갈려 8구 2군이 9구 2군이 되었고, 시청을 더해 열둘이다. 대상 기간인
2026년 상반기는 개편 전이라 그때의 집행내역은 새 구가 이어받아 싣는다(영종구 게시판의
`2026년 6월 인천 중구청장 업무추진비 사용내역` 실측).
"""

from deliciousmap.registry.models import Board, City, MapBounds, Organization
from deliciousmap.scrapers.incheon import (
    BbsBoard,
    CityBoard,
    MichuholBoard,
    YeongjongBoard,
    YeonsuBoard,
)

# 시청 정보공개포털의 업무추진비 다섯 게시판. 게시판은 경로가 가르고 조회 조건이 없다.
CITY_OPEN = "https://www.incheon.go.kr/open/{section}"
# `bbsMsgList.do` 계열. 게시판은 `bcd`가, 그 안의 갈래는 `cate1`이 가른다.
BBS = "https://{host}/{prefix}bbs/bbsMsgList.do?bcd={bcd}"


def _city(section: str) -> str:
    return CITY_OPEN.format(section=section)


def _bbs(host: str, bcd: str, prefix: str = "main/", cate1: str = "") -> str:
    url = BBS.format(host=host, prefix=prefix, bcd=bcd)
    return f"{url}&cate1={cate1}" if cate1 else url


# 제물포구 사전정보공표 자료실의 갈래. 값은 분류 코드 앞에 대분류를 붙인 모양이다.
JEMULPO_MAYOR = "01||57"
JEMULPO_DIRECTOR = "01||54"
JEMULPO_DEPARTMENT = "01||55"
# 영종구 게시판. 게시판 하나를 `pst_id`가 가른다.
YEONGJONG = "https://www.yeongjong.go.kr/main/pst/list.do?pst_id={pst_id}"


def _yeongjong(pst_id: str) -> str:
    return YEONGJONG.format(pst_id=pst_id)


CITY = City(
    "incheon",
    "인천",
    MapBounds(37.0027, 124.6007, 37.9812, 126.7933),
    (
        Organization(
            "incheon-city",
            "인천광역시",
            (
                Board("expenses-mayor", _city("OPEN010301"), CityBoard),
                Board("expenses-deputy", _city("OPEN010303"), CityBoard),
                Board("expenses-director", _city("OPEN010305"), CityBoard),
                Board("expenses-agency", _city("OPEN010307"), CityBoard),
                Board("expenses-fire", _city("OPEN010309"), CityBoard),
            ),
        ),
        # 제물포구: 2026-07-01에 옛 중구 내륙과 동구를 이어받았다. 사전정보공표 자료실 하나에
        # 갈래를 셋 두며, 업무추진비가 아닌 갈래는 같은 게시판에 있어도 부르지 않는다.
        Organization(
            "incheon-jemulpo",
            "인천광역시 제물포구",
            (
                Board(
                    "expenses-mayor",
                    _bbs("www.jemulpo.go.kr", "opendata", cate1=JEMULPO_MAYOR),
                    BbsBoard,
                ),
                Board(
                    "expenses-director",
                    _bbs("www.jemulpo.go.kr", "opendata", cate1=JEMULPO_DIRECTOR),
                    BbsBoard,
                ),
                Board(
                    "expenses-department",
                    _bbs("www.jemulpo.go.kr", "opendata", cate1=JEMULPO_DEPARTMENT),
                    BbsBoard,
                ),
            ),
        ),
        # 영종구: 2026-07-01에 옛 중구 영종도를 이어받았다. 직급별로 게시판이 다섯이다.
        Organization(
            "incheon-yeongjong",
            "인천광역시 영종구",
            (
                Board("expenses-mayor", _yeongjong("mn_exp_head"), YeongjongBoard),
                Board("expenses-deputy", _yeongjong("mn_exp_shead"), YeongjongBoard),
                Board("expenses-director", _yeongjong("mn_exp_dir"), YeongjongBoard),
                Board("expenses-manager", _yeongjong("mn_exp_cap"), YeongjongBoard),
                Board("expenses-dong", _yeongjong("mn_exp_dong"), YeongjongBoard),
            ),
        ),
        Organization(
            "incheon-michuhol",
            "인천광역시 미추홀구",
            (
                Board(
                    "expenses",
                    "https://www.michuhol.go.kr/main/board/list.do?board_code=business_promotion",
                    MichuholBoard,
                ),
            ),
        ),
        Organization(
            "incheon-yeonsu",
            "인천광역시 연수구",
            (
                Board(
                    "expenses",
                    "https://www.yeonsu.go.kr/main/administration/open_info/charge.asp",
                    YeonsuBoard,
                ),
            ),
        ),
        # 남동구: 2025년부터의 게시판만 등록한다. 2024년까지의 공개는 게시판이 아니라 연도를
        # 고르는 화면(`/operation/operationList.do`)이고 연도 목록이 2025년에서 끝난다.
        Organization(
            "incheon-namdong",
            "인천광역시 남동구",
            (Board("expenses", _bbs("www.namdong.go.kr", "disclosure"), BbsBoard),),
        ),
        # 부평구: 직급 갈래 넷만 넣는다. 다섯째 갈래(`cate1=e`, 68건)는 의회라 걸러 낸다 —
        # 서울 시청 의회사무처와 같은 사유다(CONTEXT.md 「걸러 낸 게시글」). `robots.txt`는
        # `User-agent: *`에 `Disallow: /`를 선언하지만(Yeti만 허용) 기술적 차단은 없다.
        # 2026-09-17 사용자 결정으로 부산 남구·강서구와 같게 공개 원본을 받는다 — robots의
        # 요청은 따르지 않되 신분은 위장하지 않으며, 요청은 프로젝트 UA 그대로 나간다.
        Organization(
            "incheon-bupyeong",
            "인천광역시 부평구",
            (
                Board("expenses-mayor", _bbs("www.icbp.go.kr", "cost", cate1="a"), BbsBoard),
                Board("expenses-deputy", _bbs("www.icbp.go.kr", "cost", cate1="b"), BbsBoard),
                Board("expenses-director", _bbs("www.icbp.go.kr", "cost", cate1="c"), BbsBoard),
                Board("expenses-department", _bbs("www.icbp.go.kr", "cost", cate1="d"), BbsBoard),
            ),
        ),
        # 계양구: 사전정보공표 게시판(board_14) 하나에 갈래가 여럿이고, 업무추진비 공개는
        # `cate1=94`다. 갈래를 주지 않으면 CCTV 현황 같은 다른 공표 자료가 함께 실린다.
        Organization(
            "incheon-gyeyang",
            "인천광역시 계양구",
            (
                Board(
                    "expenses",
                    _bbs("www.gyeyang.go.kr", "board_14", "open_content/main/", "94"),
                    BbsBoard,
                ),
            ),
        ),
        # 서해구: 2026-07-01 개편으로 옛 서구가 이름을 바꾸고 검단 지역을 검단구로 내보냈다.
        # 옛 주소 `www.seo.incheon.kr`도 같은 사이트를 주지만, 기관이 스스로 쓰는 새 주소를
        # 선언한다(실측 2026-09-17: 두 주소가 같은 목록·첨부를 주고 `robots.txt`도 같다).
        Organization(
            "incheon-seohae",
            "인천광역시 서해구",
            (
                Board(
                    "expenses",
                    _bbs("www.seohae.go.kr", "clean_cost", "open_content/main/"),
                    BbsBoard,
                ),
            ),
        ),
        # 검단구: 2026-07-01에 옛 서구 검단 지역을 이어받았다. 게시판이 그날 열려 7쪽뿐이다.
        Organization(
            "incheon-geomdan",
            "인천광역시 검단구",
            (Board("expenses", _bbs("www.geomdan.go.kr", "clean_cost"), BbsBoard),),
        ),
        Organization(
            "incheon-ganghwa",
            "인천광역시 강화군",
            (
                Board(
                    "expenses",
                    _bbs("www.ganghwa.go.kr", "operation", "open_content/main/"),
                    BbsBoard,
                ),
            ),
        ),
        Organization(
            "incheon-ongjin",
            "인천광역시 옹진군",
            (
                Board(
                    "expenses",
                    _bbs("www.ongjin.go.kr", "opendata1", "open_content/main/"),
                    BbsBoard,
                ),
            ),
        ),
    ),
)
