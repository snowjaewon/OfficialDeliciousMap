"""대구광역시와 9개 구·군의 업무추진비 게시판 레지스트리.

주소·계열·보류 사유는 2026-09-17에 프로젝트 UA로 실측했다. 근거는
`docs/validation/issue-173.md`에 있다. 기관마다 업무추진비 게시판이 하나라 게시판 slug는
`expenses` 하나다(부서·직급을 한 게시판에 모아 싣는다).
"""

from deliciousmap.registry.models import Board, City, MapBounds, Organization
from deliciousmap.scrapers.daegu import (
    CouncilFilteredYhLibBoard,
    GunwiBoard,
    IcmsBoard,
    OfficialTableBoard,
)

CITY = City(
    "daegu",
    "대구",
    MapBounds(35.607011, 128.349735, 36.015004, 128.761788),
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
        ),
        # 군위군: 2023년 대구 편입 뒤에도 옛 군 누리집 CMS를 쓴다.
        Organization(
            "daegu-gunwi",
            "대구광역시 군위군",
            (Board("expenses", "https://www.gunwi.go.kr/ko/page.do?mnu_uid=160", GunwiBoard),),
        ),
    ),
)
