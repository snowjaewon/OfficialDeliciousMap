"""대전광역시와 5개 자치구의 업무추진비 게시판 레지스트리.

주소·계열·보류 사유는 2026-09-17에 프로젝트 UA로 실측했다. 근거는
`docs/validation/issue-172.md`에 있다.
"""

from deliciousmap.registry.models import Board, City, Hall, MapBounds, Organization
from deliciousmap.scrapers.daejeon import ArticleBoard, BbsBoard, DptBoard, ZipBbsBoard

DONGGU = "https://www.donggu.go.kr/dg/kor/article/{code}"
JUNGGU = "https://www.djjunggu.go.kr/bbs/BBSMSTR_{bbs}/list.do"
SEOGU = "https://www.seogu.go.kr/bbs/BBSMSTR_{bbs}/list.do"
YUSEONG = "https://www.yuseong.go.kr/bbs/BBSMSTR_{bbs}/list.do"
# 대덕구는 메뉴 번호마다 목록이 따로다. `DPT02010401`~`05`가 업무추진비내역 아래 다섯 게시판이다.
DAEDEOK = "https://www.daedeok.go.kr/dpt/dpt02/{menu}_cmmBoardList.do"

# 2026-09-17 네이버 지역검색 실측으로 받은 청사 좌표. 질의는 기관 이름이며(`대전광역시 동구청` …)
# 첫 후보의 도로명주소가 그 구가 누리집 푸터에 적은 소재지와 같은 것만 쓴다. 시청은 수집 보류라
# 레코드가 없고, 푸터가 있는 `/`도 robots가 막아 소재지를 확인하지 않았으므로 적지 않는다.
# 같은 상호가 도시 안 여러 곳에 있을 때 고르는 기준점일 뿐 기관의 경계가 아니다(ADR-0010).
DONGGU_HALL = Hall(36.312169, 127.454884)  # 동구 동구청로 147
JUNGGU_HALL = Hall(36.3256593, 127.4215464)  # 중구 중앙로 100
SEOGU_HALL = Hall(36.355504, 127.383844)  # 서구 둔산서로 100
YUSEONG_HALL = Hall(36.3623219, 127.3562683)  # 유성구 대학로 211
DAEDEOK_HALL = Hall(36.346735, 127.415502)  # 대덕구 대전로1033번길 20

CITY = City(
    "daejeon",
    "대전",
    MapBounds(36.1833, 127.2463, 36.4992, 127.559),
    (
        # 시청: 목록·본문(`/drh/…`)은 robots가 허용하지만 원본은 `fileDownLoad('FileUpload/DRH/…')`
        # 로만 나오고, `/FileUpload`는 `User-agent: *`의 `Disallow: /`에 걸린다(Allow는 `/drh`
        # 등만). robots 정책을 바꾸지 않고 보류로 남긴다(실측 2026-09-17).
        Organization("daejeon-city", "대전광역시", hold_reason="bot_blocked"),
        Organization(
            "daejeon-dong",
            "대전광역시 동구",
            (
                Board("expenses-mayor", DONGGU.format(code="secretBusiness"), ArticleBoard),
                Board("expenses-director", DONGGU.format(code="senior"), ArticleBoard),
            ),
            hall=DONGGU_HALL,
        ),
        Organization(
            "daejeon-jung",
            "대전광역시 중구",
            (
                Board("expenses-mayor", JUNGGU.format(bbs="000000000103"), BbsBoard),
                Board("expenses-agency", JUNGGU.format(bbs="000000000611"), BbsBoard),
                Board("expenses-director", JUNGGU.format(bbs="000000000104"), BbsBoard),
                Board("expenses-department", JUNGGU.format(bbs="000000000105"), BbsBoard),
            ),
            hall=JUNGGU_HALL,
        ),
        Organization(
            "daejeon-seo",
            "대전광역시 서구",
            (
                Board("expenses-mayor", SEOGU.format(bbs="000000000571"), ZipBbsBoard),
                Board("expenses-department", SEOGU.format(bbs="000000000263"), ZipBbsBoard),
            ),
            hall=SEOGU_HALL,
        ),
        # 유성구: 업무추진비공개 메뉴 아래 게시판이 단체장(구청장) 하나뿐이다. 부서 단위 공개는
        # 없지만 공개된 원본은 받는다(2026-09-17 사용자 결정).
        Organization(
            "daejeon-yuseong",
            "대전광역시 유성구",
            (Board("expenses-mayor", YUSEONG.format(bbs="000000000111"), BbsBoard),),
            hall=YUSEONG_HALL,
        ),
        Organization(
            "daejeon-daedeok",
            "대전광역시 대덕구",
            (
                Board("expenses-mayor", DAEDEOK.format(menu="DPT02010401"), DptBoard),
                Board("expenses-deputy", DAEDEOK.format(menu="DPT02010402"), DptBoard),
                Board("expenses-bureau", DAEDEOK.format(menu="DPT02010403"), DptBoard),
                Board("expenses-director", DAEDEOK.format(menu="DPT02010404"), DptBoard),
                Board("expenses-department", DAEDEOK.format(menu="DPT02010405"), DptBoard),
            ),
            hall=DAEDEOK_HALL,
        ),
    ),
    # 네이버·인허가 후보의 도로명주소가 이 접두로 시작한다(2026-09-17 실측).
    address_prefixes=("대전광역시",),
)
