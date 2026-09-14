"""서울특별시와 25개 자치구의 검증된 업무추진비 게시판 레지스트리.

2026-09-14에 프로젝트 UA로 26개 진입점을 모두 다시 실측했다. 판정 근거와 기관별
계약은 `docs/validation/issue-141.md`에 있다.
"""

from deliciousmap.registry.models import Board, City, MapBounds, Organization
from deliciousmap.scrapers.seoul import (
    BbsNoBoard,
    BbsNoDetailBoard,
    CbIdxBoard,
    GwangjinBoard,
    JongnoBoard,
    JungnangBoard,
    PortalBoard,
    PortalDetailBoard,
    YangcheonBoard,
)
from deliciousmap.scrapers.seoul_district import (
    DobongBoard,
    GangdongBoard,
    GangnamBoard,
    GangseoBoard,
    JungguBoard,
    MapoBoard,
    NowonBoard,
)
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
JONGNO = (
    "https://www.jongno.go.kr/portal/bbs/selectBoardList.do"
    "?bbsId=BBSMSTR_000000001167&menuId=110210"
)
YONGSAN = "https://www.yongsan.go.kr/portal/bbs/B0000030/list.do?menuNo=200140"
GWANGJIN = "https://www.gwangjin.go.kr/portal/bbs/B0000027/list.do?menuNo=201646"
DONGJAK = "https://www.dongjak.go.kr/portal/bbs/B0000591/list.do?menuNo=200209"
JUNGNANG = "https://www.jungnang.go.kr/portal/bbs/list/B0000143.do?menuNo=200432"
SEONGDONG = "https://www.sd.go.kr/main/selectBbsNttList.do?bbsNo=172&key=1330"
DONGDAEMUN = "https://www.ddm.go.kr/www/selectBbsNttList.do?bbsNo=160&key=152"
SEONGBUK = "https://www.sb.go.kr/www/selectBbsNttList.do?bbsNo=28&key=5923"
GURO = "https://www.guro.go.kr/www/selectBbsNttList.do?bbsNo=655&key=1732"
GEUMCHEON = "https://www.geumcheon.go.kr/portal/selectBbsNttList.do?bbsNo=86&key=269"
YEONGDEUNGPO = "https://www.ydp.go.kr/www/selectBbsNttList.do?bbsNo=31&key=2814"
SONGPA = "https://www.songpa.go.kr/www/selectBbsNttList.do?bbsNo=327&key=2323"
YANGCHEON = "https://www.yangcheon.go.kr/site/yangcheon/ex/bbs/List.do?cbIdx=397"
SEOCHO = "https://www.seocho.go.kr/site/seocho/ex/bbs/List.do?cbIdx=33"
JUNG = "https://www.junggu.seoul.kr/content.do?cmsid=15383&exclude=Y"
DOBONG = "https://www.dobong.go.kr/bbs.asp?code=10008860"
NOWON = "https://www.nowon.kr/www/user/bbs/BD_selectBbsList.do?q_bbsCode=1012"
MAPO = "https://www.mapo.go.kr/site/main/board/expense/list"
GANGSEO = "https://www.gangseo.seoul.kr/gs030325"
GANGNAM = "https://www.gangnam.go.kr/board/B_000673/list.do?mid=ID05_04200502"
GANGNAM_SUBSIDY = "https://www.gangnam.go.kr/board/B_000672/list.do?mid=ID05_04200502"
GANGDONG = "https://www.gangdong.go.kr/web/newportal/bbs/b_054"

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
        Organization(
            "seoul-jongno", "서울특별시 종로구", (Board("expenses", JONGNO, JongnoBoard),)
        ),
        Organization(
            "seoul-yongsan", "서울특별시 용산구", (Board("expenses", YONGSAN, PortalBoard),)
        ),
        Organization(
            "seoul-gwangjin", "서울특별시 광진구", (Board("expenses", GWANGJIN, GwangjinBoard),)
        ),
        Organization(
            "seoul-jungnang", "서울특별시 중랑구", (Board("expenses", JUNGNANG, JungnangBoard),)
        ),
        Organization(
            "seoul-dongjak", "서울특별시 동작구", (Board("expenses", DONGJAK, PortalDetailBoard),)
        ),
        Organization(
            "seoul-seongdong", "서울특별시 성동구", (Board("expenses", SEONGDONG, BbsNoBoard),)
        ),
        Organization(
            "seoul-dongdaemun",
            "서울특별시 동대문구",
            (Board("expenses", DONGDAEMUN, BbsNoDetailBoard),),
        ),
        Organization(
            "seoul-seongbuk", "서울특별시 성북구", (Board("expenses", SEONGBUK, BbsNoDetailBoard),)
        ),
        Organization("seoul-guro", "서울특별시 구로구", (Board("expenses", GURO, BbsNoBoard),)),
        Organization(
            "seoul-geumcheon",
            "서울특별시 금천구",
            (Board("expenses", GEUMCHEON, BbsNoDetailBoard),),
        ),
        Organization(
            "seoul-yeongdeungpo",
            "서울특별시 영등포구",
            (Board("expenses", YEONGDEUNGPO, BbsNoBoard),),
        ),
        Organization("seoul-songpa", "서울특별시 송파구", (Board("expenses", SONGPA, BbsNoBoard),)),
        Organization(
            "seoul-yangcheon", "서울특별시 양천구", (Board("expenses", YANGCHEON, YangcheonBoard),)
        ),
        Organization("seoul-seocho", "서울특별시 서초구", (Board("expenses", SEOCHO, CbIdxBoard),)),
        Organization("seoul-jung", "서울특별시 중구", (Board("expenses", JUNG, JungguBoard),)),
        Organization(
            "seoul-dobong", "서울특별시 도봉구", (Board("expenses", DOBONG, DobongBoard),)
        ),
        Organization("seoul-nowon", "서울특별시 노원구", (Board("expenses", NOWON, NowonBoard),)),
        Organization("seoul-mapo", "서울특별시 마포구", (Board("expenses", MAPO, MapoBoard),)),
        Organization(
            "seoul-gangseo", "서울특별시 강서구", (Board("expenses", GANGSEO, GangseoBoard),)
        ),
        Organization(
            "seoul-gangnam",
            "서울특별시 강남구",
            (
                Board("expenses", GANGNAM, GangnamBoard),
                Board("expenses-subsidy", GANGNAM_SUBSIDY, GangnamBoard),
            ),
        ),
        Organization(
            "seoul-gangdong", "서울특별시 강동구", (Board("expenses", GANGDONG, GangdongBoard),)
        ),
        # 첫 응답이 쿠키 서명을 되돌려 보내라는 433바이트 스크립트다. 그 서명을 돌려보내는
        # 것은 봇 확인 우회이므로 수집을 보류한다(이슈 #141, 2026-09-14 실측).
        Organization("seoul-gangbuk", "서울특별시 강북구", (), hold_reason="bot_blocked"),
    ),
)
