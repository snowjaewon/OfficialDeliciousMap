"""대전광역시와 5개 자치구의 업무추진비 게시판 레지스트리.

주소·계열·보류 사유는 2026-09-17에 프로젝트 UA로 실측했다. 근거는
`docs/validation/issue-172.md`에 있다.
"""

from deliciousmap.registry.models import Board, City, MapBounds, Organization
from deliciousmap.scrapers.daejeon import ArticleBoard, BbsBoard, DptBoard, ZipBbsBoard

DONGGU = "https://www.donggu.go.kr/dg/kor/article/{code}"
JUNGGU = "https://www.djjunggu.go.kr/bbs/BBSMSTR_{bbs}/list.do"
SEOGU = "https://www.seogu.go.kr/bbs/BBSMSTR_{bbs}/list.do"
YUSEONG = "https://www.yuseong.go.kr/bbs/BBSMSTR_{bbs}/list.do"
# 대덕구는 메뉴 번호마다 목록이 따로다. `DPT02010401`~`05`가 업무추진비내역 아래 다섯 게시판이다.
DAEDEOK = "https://www.daedeok.go.kr/dpt/dpt02/{menu}_cmmBoardList.do"

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
        ),
        Organization(
            "daejeon-seo",
            "대전광역시 서구",
            (
                Board("expenses-mayor", SEOGU.format(bbs="000000000571"), ZipBbsBoard),
                Board("expenses-department", SEOGU.format(bbs="000000000263"), ZipBbsBoard),
            ),
        ),
        # 유성구: 업무추진비공개 메뉴 아래 게시판이 단체장(구청장) 하나뿐이다. 부서 단위 공개는
        # 없지만 공개된 원본은 받는다(2026-09-17 사용자 결정).
        Organization(
            "daejeon-yuseong",
            "대전광역시 유성구",
            (Board("expenses-mayor", YUSEONG.format(bbs="000000000111"), BbsBoard),),
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
        ),
    ),
)
