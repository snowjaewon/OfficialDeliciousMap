from deliciousmap.registry.models import Board, City, MapBounds, Organization
from deliciousmap.scrapers.gwangju import GwangjuCityBoard
from deliciousmap.scrapers.gwangju_district import GwangjuDistrictBoard
from deliciousmap.scrapers.gwangju_gwangsan import GwangsanInfoOpenBoard
from deliciousmap.scrapers.gwangju_seogu import SeoguExpenseBoard

# 2026-09-11 실측으로 확인한 게시판. 게시글 10,476건(2004~2026년 2분기), 첨부는 .xls·.xlsx다.
# 근거와 실측 방법은 docs/validation/issue-51.md에 있다. 폐기된 `pageId`는 붙이지 않는다.
CITY_HALL_EXPENSES = "https://www.gwangju.go.kr/boardList.do?boardId=BD_0000000252&recordCnt=100"
# 이 기관이 스스로 밝히는 이름을 그대로 쓴다(실측: `<title>`·`og:site_name`). 통합 전 이름은
# 광주광역시청이며 푸터 주소도 `전남광주통합특별시 서구 내방로 111`로 바뀌었다.
CITY_HALL_NAME = "전남광주통합특별시(구)광주광역시"

# 2026-09-13 실측으로 확인한 5개 자치구 게시판. 근거는 docs/validation/issue-97.md에 있다.
# 기관 이름은 저마다 `<title>`·푸터로 밝힌 표기를 그대로 쓴다.
BUK_EXPENSES = "https://bukgu.gwangju.kr/board.es?mid=a10502050000&bid=0004"
BUK_NAME = "전남광주통합특별시 북구"
NAM_EXPENSES = "https://www.namgu.gwangju.kr/board.es?mid=a10304100000&bid=0007"
NAM_NAME = "전남광주통합특별시 남구"
# 동구는 같은 업무추진비를 직급별 게시판 넷으로 나눈다. `bid=0160`("2020년 이전자료")은 이름과
# 달리 위원회 회의록이 실려 있고 업무추진비 게시글이 없어(실측) 선언하지 않는다.
DONG_HEAD = "https://www.donggu.kr/board.es?mid=a10301080100&bid=0267"
DONG_DIRECTOR = "https://www.donggu.kr/board.es?mid=a10301080300&bid=0269"
DONG_DEPARTMENT = "https://www.donggu.kr/board.es?mid=a10301080400&bid=0270"
DONG_NAME = "전남광주통합특별시 동구"
# 서구도 넷으로 나누며 게시글 본문 없이 목록에서 곧바로 첨부를 내준다.
SEO_HEAD = "https://www.seogu.gwangju.kr/openInfoCostList.es?mid=a10518030100&oi_seq=110"
SEO_DIRECTOR = "https://www.seogu.gwangju.kr/openInfoCostList.es?mid=a10518030200&oi_seq=109"
SEO_COUNCIL = "https://www.seogu.gwangju.kr/openInfoCostList.es?mid=a10518030300&oi_seq=401"
SEO_DEPARTMENT = "https://www.seogu.gwangju.kr/openInfoCostList.es?mid=a10518030400&oi_seq=517"
SEO_NAME = "전남광주통합특별시 서구청 #착한도시 서구"
# 광산구는 게시판 HTML이 없다. 진입 화면이 세션과 토큰을 내주고 목록·본문은 JSON으로 답한다.
GWANGSAN_EXPENSES = (
    "https://www.gwangsan.go.kr/contentsView.do"
    "?pageId=www159&infoOpenSn=292&infoOpenCtgryUpper=O130000"
)
GWANGSAN_NAME = "광산구청"

# 통합에 따른 도시 이름·경계·기관 범위는 이 이슈의 범위가 아니어서 그대로 두고 근거만 남긴다.
# `map_bounds`는 통합 전 광주광역시 경계이며 통합특별시를 담지 못한다.
CITY = City(
    "gwangju",
    "광주",
    MapBounds(35.0362, 126.6495, 35.2588, 127.0228),
    (
        Organization(
            "gwangju-city",
            CITY_HALL_NAME,
            (Board("expenses", CITY_HALL_EXPENSES, GwangjuCityBoard),),
        ),
        Organization(
            "gwangju-gwangsan",
            GWANGSAN_NAME,
            (Board("expenses", GWANGSAN_EXPENSES, GwangsanInfoOpenBoard),),
        ),
        Organization(
            "gwangju-seo",
            SEO_NAME,
            (
                Board("expenses-head", SEO_HEAD, SeoguExpenseBoard),
                Board("expenses-director", SEO_DIRECTOR, SeoguExpenseBoard),
                Board("expenses-council", SEO_COUNCIL, SeoguExpenseBoard),
                Board("expenses-department", SEO_DEPARTMENT, SeoguExpenseBoard),
            ),
        ),
        Organization(
            "gwangju-buk",
            BUK_NAME,
            (Board("expenses", BUK_EXPENSES, GwangjuDistrictBoard),),
        ),
        Organization(
            "gwangju-nam",
            NAM_NAME,
            (Board("expenses", NAM_EXPENSES, GwangjuDistrictBoard),),
        ),
        Organization(
            "gwangju-dong",
            DONG_NAME,
            (
                Board("expenses-head", DONG_HEAD, GwangjuDistrictBoard),
                Board("expenses-director", DONG_DIRECTOR, GwangjuDistrictBoard),
                Board("expenses-department", DONG_DEPARTMENT, GwangjuDistrictBoard),
            ),
        ),
    ),
)
