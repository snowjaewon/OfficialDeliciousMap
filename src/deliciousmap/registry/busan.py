"""부산광역시와 16개 구·군의 검증된 업무추진비 게시판 레지스트리.

주소·계열·보류 사유는 2026-09-14에 프로젝트 UA로 다시 실측했다. 근거는
`docs/validation/issue-140.md`에 있다.
"""

from deliciousmap.registry.models import (
    Board,
    City,
    DeclaredTable,
    MapBounds,
    Organization,
)
from deliciousmap.scrapers.busan import (
    CityBoard,
    EgovPortalBoard,
    GijangBoard,
    MixedRfc3Board,
    Rfc3Board,
    YhLibBoard,
)

# 시청은 `schBizNo`로 게시판을 가른다. 46은 시장·부시장, 45는 4급 이상 공무원이 장인 부서다.
# 199(지방공기업 임원)는 넣지 않는다 — 그 게시판은 공표방법이 `링크`이고, 2014-09-23에 올린
# 글 하나가 부산도시공사 등 다섯 지방공기업의 각자 홈페이지로 보내는 안내일 뿐이다. 시청
# 집행내역도, 내려받을 원본도 없다(실측 2026-09-14).
CITY_LIST = "https://www.busan.go.kr/ghopen12/list"
# rfc3 계열. 사이트키는 도메인과 다를 수 있어 주소에 그대로 둔다(해운대 `do`, 남구 `namgu`).
RFC3 = "https://www.{host}/board/list.{key}?boardId={board}"


def _rfc3(host: str, key: str, board: str) -> str:
    return RFC3.format(host=host, key=key, board=board)


# 강서구 yhLib portal. `bcIdx`(게시판)·`mid`(메뉴) 없이 부르면 목록이 열리지 않아 함께 선언한다.
YHLIB = "https://www.bsgangseo.go.kr/portal/board/post/list.do?bcIdx={bcidx}&mid={mid}"


def _yhlib(bcidx: str, mid: str) -> str:
    return YHLIB.format(bcidx=bcidx, mid=mid)


# 기장군 목록 표의 열(2026-09-17 실측, 전량 3,297줄). 목록이 곧 집행내역이고 헤더가 `(원)`이라
# 금액 배수는 1이다. `사용자`·`대상인원(명)`·`사용방법`에는 역할을 주지 않는다. 마지막 두 열의
# 연도·월은 사람이 적은 분류라 3,215건 중 64건이 사용일자와 어긋나 집행일로 쓰지 않는다.
GIJANG_TABLE = DeclaredTable(
    header=(
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
    ),
    columns={"department": 0, "spent_on": 2, "merchant": 3, "purpose": 4, "amount_krw": 5},
)


CITY = City(
    "busan",
    "부산",
    MapBounds(34.879908, 128.738436, 35.395936, 129.314776),
    (
        Organization(
            "busan-city",
            "부산광역시",
            (
                Board("expenses-mayor", f"{CITY_LIST}?schBizNo=46", CityBoard),
                Board("expenses-director", f"{CITY_LIST}?schBizNo=45", CityBoard),
            ),
        ),
        Organization(
            "busan-jung",
            "부산광역시 중구",
            (
                Board(
                    "expenses",
                    _rfc3("bsjunggu.go.kr", "junggu", "BBS_0000018"),
                    MixedRfc3Board,
                ),
            ),
        ),
        Organization(
            "busan-seo",
            "부산광역시 서구",
            (Board("expenses", _rfc3("bsseogu.go.kr", "bsseogu", "BBS_0000151"), Rfc3Board),),
        ),
        Organization(
            "busan-dong",
            "부산광역시 동구",
            (Board("expenses", _rfc3("bsdonggu.go.kr", "donggu", "BBS_0000254"), Rfc3Board),),
        ),
        # 영도구: 목록은 열리지만 본문이 우리 UA에 400을 돌려준다. 2026년 상반기 게시글
        # 표본 10건 중 7건이 실패했고, 45초를 쉬고 8초 간격으로 다시 물어도 같았다
        # (실측 2026-09-14). 같은 호스트의 `/robots.txt`도 우리 요청의 IP를 적은 보안 차단
        # 화면을 준다. 우회하지 않고 보류로 남긴다.
        #
        # 차단은 클라이언트 단이다. 실제 브라우저에서는 같은 본문이 열린다(실측 2026-09-17:
        # `idx` 333900·331576·333662·332946 네 건 모두 성공). 목록은
        # `/00000/00067/00333.web?gcode=1037&cpage=N`으로 4,953건 496쪽이고, 쪽 넘김은
        # `cpage`만 받는다 — `page`·`pageIndex`는 무시되고 1쪽을 돌려준다. 첨부 확장자는
        # 목록 마크업의 `img[alt="…확장자를 가지는 첨부파일 포함"]`이 밝힌다. 그래도 보류는
        # 그대로다. 파이프라인에 브라우저 수집 경로가 없어 이 사실만으로는 수집이 되지 않는다.
        Organization("busan-yeongdo", "부산광역시 영도구", hold_reason="bot_blocked"),
        Organization(
            "busan-busanjin",
            "부산광역시 부산진구",
            (
                Board(
                    "expenses",
                    # `menuCd` 없이 부르면 403이다. 조회 조건을 주소에 함께 선언한다.
                    _rfc3("busanjin.go.kr", "busanjin", "BBS_0000023")
                    + "&menuCd=DOM_000000109001003000&contentsSid=276",
                    Rfc3Board,
                ),
            ),
        ),
        Organization(
            "busan-dongnae",
            "부산광역시 동래구",
            (Board("expenses", _rfc3("dongnae.go.kr", "dongnae", "BBS_0000200"), Rfc3Board),),
        ),
        # 남구: `robots.txt`는 여전히 `User-agent: *`에 `Disallow: /`를 선언한다(Yeti만 허용,
        # 2026-09-17 재실측). #140은 그 선언을 따라 보류로 두었으나, 2026-09-17 사용자가
        # 업무추진비 공개 원본을 받는 쪽을 골라 보류를 풀었다. 우리는 robots의 요청은 따르지
        # 않되 신분은 위장하지 않는다 — 요청은 프로젝트 UA 그대로 나간다. 기술적 차단은 없다.
        Organization(
            "busan-nam",
            "부산광역시 남구",
            (
                Board(
                    "expenses",
                    # 부산진구와 파라미터 구성이 같은 rfc3 전용 게시판이다(실측 2026-09-17:
                    # 목록 630쪽, 제목이 모두 `…업무추진비 등 클린카드 사용내역(부서)`).
                    _rfc3("bsnamgu.go.kr", "namgu", "BBS_0000149")
                    + "&menuCd=DOM_000000105005009000&contentsSid=1310",
                    Rfc3Board,
                ),
            ),
        ),
        Organization(
            "busan-buk",
            "부산광역시 북구",
            (Board("expenses", _rfc3("bsbukgu.go.kr", "bsbukgu", "BBS_0000030"), Rfc3Board),),
        ),
        Organization(
            "busan-haeundae",
            "부산광역시 해운대구",
            # 전 부서 통합 게시판이라 업무추진비 아닌 글이 섞인다. 실측 2026-09-14: 2026년
            # 게시글 가운데 `보건소 수의계약내역, 신용카드 사용내역 알림` 13건이 그것이고,
            # 거르지 않으면 수의계약 표가 집행내역으로 들어온다.
            (Board("expenses", _rfc3("haeundae.go.kr", "do", "BBS_0000004"), MixedRfc3Board),),
        ),
        # 사하구: 옛 게시판(`portal/bbs/list.do?ptIdx=29`)이 "삭제되었거나 존재하지 않습니다"를
        # 돌려준다. 같은 호스트의 `robots.txt`가 `Disallow: /*bbs*`를 선언해 새 게시판을
        # 훑어 찾을 수도 없다. 사람이 브라우저로 새 주소를 찾을 때까지 보류다.
        Organization("busan-saha", "부산광역시 사하구", hold_reason="board_lost"),
        Organization(
            "busan-geumjeong",
            "부산광역시 금정구",
            (Board("expenses", _rfc3("geumjeong.go.kr", "geumj", "BBS_0000331"), Rfc3Board),),
        ),
        # 강서구: `robots.txt`는 여전히 `User-agent:*`에 `Disallow:/`를 선언한다(2026-09-17
        # 재실측). #140은 그 선언을 따라 보류로 두었으나, 2026-09-17 사용자가 업무추진비 공개
        # 원본을 받는 쪽을 골라 보류를 풀었다. 목록·본문·첨부 모두 GET으로 열린다(실측).
        # yhLib portal 계열이라 게시글 번호가 링크의 `data-req-get-p-idx`에, 첨부는 본문의
        # `yhLib.file.download('<64자>','<32자>')` 호출에 있다.
        #
        # 게시판 셋 가운데 부서별(534)·과장급(535) 둘만 넣는다. 의회 업무추진비(536, 26건)는
        # 집행기관이 아니라 걸러 낸다 — 서울 시청 의회사무처와 같은 사유다(CONTEXT.md 「걸러 낸
        # 게시글」). 표본 5건 중 1건이 Fasoo DRM이었고, DRM 아닌 첨부는 그대로 받는다.
        Organization(
            "busan-gangseo",
            "부산광역시 강서구",
            (
                Board(
                    "expenses-department",
                    _yhlib("534", "0503030100"),
                    YhLibBoard,
                ),
                Board(
                    "expenses-director",
                    _yhlib("535", "0503030200"),
                    YhLibBoard,
                ),
            ),
        ),
        Organization(
            "busan-yeonje",
            "부산광역시 연제구",
            (
                Board(
                    "expenses",
                    # `mId` 없이 부르면 목록이 400, 본문이 500이다.
                    "https://www.yeonje.go.kr/portal/bbs/list.do?ptIdx=32&mId=0401090000",
                    EgovPortalBoard,
                ),
            ),
        ),
        Organization(
            "busan-suyeong",
            "부산광역시 수영구",
            (
                Board(
                    "expenses",
                    _rfc3("suyeong.go.kr", "suyeong", "BBS_0000116"),
                    MixedRfc3Board,
                ),
            ),
        ),
        Organization(
            "busan-sasang",
            "부산광역시 사상구",
            (Board("expenses", _rfc3("sasang.go.kr", "sasang", "BBS_0000175"), Rfc3Board),),
        ),
        Organization(
            "busan-gijang",
            "부산광역시 기장군",
            (
                Board(
                    "expenses",
                    # 정찰 기록의 `categoryCode1=000`은 넣지 않는다. 그 값은 연도가 아니라
                    # 부서 조건(41개 중 행정지원과(군수))이고, 붙이면 3,283건 중 530건만
                    # 보인다(실측 2026-09-14). 연도·월 조건(`categoryCode2`·`categoryCode3`)도
                    # 쓰지 않는다 — 그 값은 사람이 적은 분류라 사용일자와 3,215건 중 64건이
                    # 어긋난다. 기간은 받은 뒤 사용일자로 가른다.
                    _rfc3("gijang.go.kr", "gijang", "BBS_0000147")
                    + "&menuCd=DOM_000000101002014000&paging=ok",
                    GijangBoard,
                    GIJANG_TABLE,
                ),
            ),
        ),
    ),
)
