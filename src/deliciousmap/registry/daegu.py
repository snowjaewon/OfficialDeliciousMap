"""대구광역시와 9개 구·군의 업무추진비 게시판 레지스트리.

주소·계열·보류 사유는 2026-09-17에 프로젝트 UA로 실측했다. 근거는
`docs/validation/issue-173.md`에 있다. 기관마다 업무추진비 게시판이 하나라 게시판 slug는
`expenses` 하나다(부서·직급을 한 게시판에 모아 싣는다).
"""

from deliciousmap.registry.models import Board, City, Hall, MapBounds, Organization
from deliciousmap.scrapers.daegu import (
    CouncilFilteredYhLibBoard,
    GunwiBoard,
    IcmsBoard,
    OfficialTableBoard,
)

# 2026-09-17 네이버 지역검색 실측으로 받은 청사 좌표. 질의는 기관 이름이며(`대구광역시 동구청` …)
# 첫 후보의 도로명주소가 그 기관이 누리집 푸터에 적은 소재지와 같은 것만 쓴다. 시청 푸터는
# 동인청사와 산격청사를 함께 적는다. 먼저 적은 동인청사(중구 공평로 88)를 쓴다. 수집 보류인
# 중구·북구·달서구는 레코드가 없어 적지 않는다. 같은 상호가 도시 안 여러 곳에 있을 때 고르는
# 기준점일 뿐이다(ADR-0010).
CITY_HALL = Hall(35.8713898, 128.601763)  # 중구 공평로 88 (동인청사)
DONG_HALL = Hall(35.8866639, 128.6356089)  # 동구 아양로 207
SEO_HALL = Hall(35.8717569, 128.559175)  # 서구 국채보상로 257
NAM_HALL = Hall(35.8459999, 128.597486)  # 남구 이천로 51
SUSEONG_HALL = Hall(35.8581653, 128.630625)  # 수성구 달구벌대로 2450
DALSEONG_HALL = Hall(35.7745999, 128.431445)  # 달성군 논공읍 달성군청로 33
GUNWI_HALL = Hall(36.2429449, 128.572657)  # 군위군 군위읍 군청로 200

CITY = City(
    "daegu",
    "대구",
    # 북·동 끝은 2023년 편입한 군위군까지 넓혔다. 2026-09-18 조회 캐시의 군위군 후보는 북 36.2559·
    # 동 128.7954까지이고, 네이버 지역검색의 소보면 사리2리마을회관이 북 36.3211이다. 그 위로 약
    # 3km를 더 둔다(docs/validation/issue-176.md).
    MapBounds(35.607011, 128.349735, 36.35, 128.82),
    (
        # 시청: 목록 한 쪽에 50건씩 받는다(선택 상자가 내주는 가장 큰 값). 5,234건·105쪽.
        Organization(
            "daegu-city",
            "대구광역시",
            (
                Board(
                    "expenses",
                    "https://www.daegu.go.kr/index.do?menu_id=00000084&postPerPage=50",
                    IcmsBoard,
                ),
            ),
            hall=CITY_HALL,
        ),
        # 중구: robots.txt를 포함한 모든 요청에 스크립트가 쿠키(`sabFingerPrint`·`sabSignature`)를
        # 심고 다시 불러오라는 441바이트 화면만 준다(`www.jung.daegu.kr`·`gu.jung.daegu.kr` 모두).
        # 스크립트를 흉내 내 쿠키를 만드는 것은 차단 우회라 보류한다(실측 2026-09-17).
        Organization("daegu-jung", "대구광역시 중구", hold_reason="bot_blocked"),
        Organization(
            "daegu-dong",
            "대구광역시 동구",
            (
                Board(
                    "expenses",
                    "https://www.dong.daegu.kr/portal/board/post/list.do?bcIdx=557&mid=0501040000",
                    CouncilFilteredYhLibBoard,
                ),
            ),
            hall=DONG_HALL,
        ),
        # 서구: robots가 `/*/board/post/`를 막고 업무추진비(`bcIdx=511`) 등 여덟 게시판만 허용한다.
        Organization(
            "daegu-seo",
            "대구광역시 서구",
            (
                Board(
                    "expenses",
                    "https://www.dgs.go.kr/portal/board/post/list.do?bcIdx=511&mid=0502030000",
                    CouncilFilteredYhLibBoard,
                ),
            ),
            hall=SEO_HALL,
        ),
        Organization(
            "daegu-nam",
            "대구광역시 남구",
            (
                Board(
                    "expenses",
                    "https://www.nam.daegu.kr/index.do?menu_id=00001247&postPerPage=50",
                    IcmsBoard,
                ),
            ),
            hall=NAM_HALL,
        ),
        # 북구: 게시판은 열리지만 원본은 `/icms/cmm/fms/FileDown.do`로만 나오고, robots의
        # `User-agent:*`가 그 경로를 `Disallow`한다. 미리보기(`/filePreview.do`)는 변환본이라
        # 원본이 아니다. robots 정책을 바꾸지 않고 보류한다(실측 2026-09-17).
        Organization("daegu-buk", "대구광역시 북구", hold_reason="bot_blocked"),
        # 수성구: 해마다 메뉴가 따로다. `00042650`이 2026년 화면이다.
        Organization(
            "daegu-suseong",
            "대구광역시 수성구",
            (
                Board(
                    "expenses",
                    "https://www.suseong.kr/index.do?menu_id=00042650",
                    OfficialTableBoard,
                ),
            ),
            hall=SUSEONG_HALL,
        ),
        # 달서구: robots.txt가 `User-agent: *`에 `Disallow: /`다(실측 2026-09-17).
        Organization("daegu-dalseo", "대구광역시 달서구", hold_reason="bot_blocked"),
        # 달성군: 목록 선택 상자가 내주는 가장 큰 값이 20건이다.
        Organization(
            "daegu-dalseong",
            "대구광역시 달성군",
            (
                Board(
                    "expenses",
                    "https://www.dalseong.daegu.kr/index.do?menu_id=00001704&postPerPage=20",
                    IcmsBoard,
                ),
            ),
            hall=DALSEONG_HALL,
        ),
        # 군위군: 2023년 대구 편입 뒤에도 옛 군 누리집 CMS를 쓴다.
        Organization(
            "daegu-gunwi",
            "대구광역시 군위군",
            (Board("expenses", "https://www.gunwi.go.kr/ko/page.do?mnu_uid=160", GunwiBoard),),
            hall=GUNWI_HALL,
        ),
    ),
    # 2026-09-17 네이버 지역검색 실측: 시청·구청과 군위군 업소 후보가 모두 `대구광역시`로 시작한다
    # (군위군은 2023년 편입 뒤 `대구광역시 군위군`). 인허가 후보는 조회 캐시로 확인했다
    # (docs/validation/issue-176.md).
    address_prefixes=("대구광역시",),
)
