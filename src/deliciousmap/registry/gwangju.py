from deliciousmap.registry.models import Board, City, MapBounds, Organization
from deliciousmap.scrapers.gwangju import GwangjuCityBoard

# 2026-09-11 실측으로 확인한 게시판. 게시글 10,476건(2004~2026년 2분기), 첨부는 .xls·.xlsx다.
# 근거와 실측 방법은 docs/validation/issue-51.md에 있다. 폐기된 `pageId`는 붙이지 않는다.
CITY_HALL_EXPENSES = "https://www.gwangju.go.kr/boardList.do?boardId=BD_0000000252&recordCnt=100"
# 이 기관이 스스로 밝히는 이름을 그대로 쓴다(실측: `<title>`·`og:site_name`). 통합 전 이름은
# 광주광역시청이며 푸터 주소도 `전남광주통합특별시 서구 내방로 111`로 바뀌었다.
CITY_HALL_NAME = "전남광주통합특별시(구)광주광역시"

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
    ),
)
