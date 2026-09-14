"""서울특별시와 25개 자치구의 검증된 업무추진비 게시판 레지스트리.

2026-09-14에 프로젝트 UA로 26개 진입점을 모두 다시 실측했다. 판정 근거와 기관별
계약은 `docs/validation/issue-141.md`에 있다.
"""

from deliciousmap.registry.models import Board, City, MapBounds, Organization
from deliciousmap.scrapers.seoul_html import (
    CityExpenseBoard,
    EunpyeongBoard,
    GwanakBoard,
    SeodaemunBoard,
)

CITY_EXPENSE = "https://opengov.seoul.go.kr/expense/list"
EUNPYEONG = "https://www.ep.go.kr/www/selectJobPrtnCtWebList.do?key=666"
GWANAK = "https://www.gwanak.go.kr/site/gwanak/estimate/estimateListExcel.do"
SEODAEMUN = "https://www.sdm.go.kr/admininfo/budget/openmoney.do"

CITY = City(
    "seoul",
    "서울",
    MapBounds(37.413294, 126.734086, 37.715133, 127.269311),
    (
        Organization(
            "seoul-city",
            "서울특별시",
            (Board("expenses", CITY_EXPENSE, CityExpenseBoard),),
        ),
        Organization(
            "seoul-eunpyeong",
            "서울특별시 은평구",
            (Board("expenses", EUNPYEONG, EunpyeongBoard),),
        ),
        Organization(
            "seoul-gwanak",
            "서울특별시 관악구",
            (Board("expenses", GWANAK, GwanakBoard),),
        ),
        Organization(
            "seoul-seodaemun",
            "서울특별시 서대문구",
            (Board("expenses", SEODAEMUN, SeodaemunBoard),),
        ),
    ),
)
