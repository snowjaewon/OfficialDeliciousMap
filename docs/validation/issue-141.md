# Issue #141 validation — 서울특별시 26개 기관 업무추진비 게시판

실측일: 2026-09-14. 모든 요청은 프로젝트 UA
`OfficialDeliciousMap/0.1 (+https://github.com/snowjaewon/OfficialDeliciousMap)`로 보냈다.
브라우저를 가장하지 않았고 인증·DRM·봇 확인을 우회하지 않았다. 정찰에 쓴 응답과 받은 원본은
저장소 밖(`--raw-root`)에 두었고 원본·`dist/`는 커밋하지 않았다.

출발점은 [#3의 서울·부산 게시판 정찰](https://github.com/snowjaewon/OfficialDeliciousMap/blob/research/seoul-busan-boards/docs/research/seoul-busan-boards.md)(2026-09-09)이며,
26개 진입점을 이번에 모두 다시 실측했다. 아래 값은 정찰 문서가 아니라 이번 실측이다.

## robots.txt 판정

`robots.txt`를 프로젝트 UA로 받아 RFC 9309의 최장일치 규칙(와일드카드 `*`, 끝 고정 `$`)으로
우리가 쓰는 경로를 판정했다. 우리 UA 이름을 가리키는 그룹은 어느 호스트에도 없어 모두 `*`
그룹이 적용된다.

| 판정 | 기관 | 근거 |
| --- | --- | --- |
| 허용 | 서울시청 | `allow: /expense` (같은 그룹이 `/og/com/`은 막는다) |
| 허용 | 중구 | `Disallow`가 `/content.do?cmsid=14232`·`/search`뿐 |
| 허용 | 동대문 | `robots.txt`가 정책 문서가 아니라 오류 화면(485바이트 HTML) |
| 허용 | 성북·노원·관악·영등포 | `*` 그룹이 없다(영등포는 아래 단서 참고) |
| 허용 | 서대문 | `Disallow: /admin/`은 `/admininfo/`에 걸리지 않는다 |
| 허용 | 구로·금천 | `Disallow`가 `/search/`와 무관한 몇 경로뿐 |
| 목록 허용·첨부 차단 | 서초 | 목록 `Allow:/site/*.do`, 첨부 `Disallow:/common/*` |
| 목록 허용·첨부 차단 | 강남 | 목록에 걸리는 규칙 없음, 첨부 `Disallow: /file/*` |
| 목록 허용·첨부 차단 | 강동 | 목록 `Allow:/web/*/bbs/`, 첨부 `Disallow:/*/*/` |
| 차단 | 종로·용산·성동·중랑·은평·마포·양천·강서·동작 | `User-agent: *` + `Disallow: /` |
| 차단 | 광진 | `Disallow: /` + 허용 목록에 `B0000027`이 없다 |
| 차단 | 도봉 | `Disallow: /bbs.asp`·`/WDB_common/`을 이름으로 막는다 |
| 차단 | 송파 | `Disallow: /www/selectBbsNttList.do`를 이름으로 막는다 |
| 봇 확인 | 강북 | `robots.txt` 자체가 433바이트 봇 확인 스크립트다 |

영등포의 `robots.txt`는 파일 전체가 `Disallow: /` 11바이트이고 `User-agent` 줄이 없다.
RFC 9309는 user-agent 줄 없이 시작하는 규칙을 무시하므로 형식상 우리 UA에 적용되는 규칙이
없다. 뜻은 전체 차단으로 읽히므로 이 단서를 여기 남긴다.

**수집 여부 결정.** 광주 북·남·동구도 `Disallow: /`였고 2026-09-13 사용자 결정으로 그대로
수집했다(`docs/validation/issue-97.md`). 서울의 차단 14곳에도 같은 결정을 적용한다
(2026-09-14 사용자 결정). 강북구만 `bot_blocked`로 수집을 보류한다 — 첫 응답의
`sabSignature` 쿠키를 되돌려 보내야 목록이 열리고, 그것은 이슈 #141이 제외한 봇 확인
우회다. Referer처럼 일반 브라우저가 보내는 헤더를 붙이는 것은 우회로 보지 않는다.

## 기관·게시판 계약

`--raw-root` 아래 `seoul/<기관>/<게시판>/`에 원본을 둔다. 쪽 수는 2026-09-14 목록이 밝힌 값이다.

| 기관 | 게시판 주소 | 계열 | 쪽 넘김 | 목록/상세/첨부 경계 |
| --- | --- | --- | --- | --- |
| 서울특별시 `seoul-city` | `opengov.seoul.go.kr/expense/list` | HTML 화면 | `page`(+`items_per_page=50`) | 사용월(`ym[year]`·`ym[month]`)로 거른 목록 → 상세 `/expense/<번호>`가 원본 |
| 은평구 | `ep.go.kr/www/selectJobPrtnCtWebList.do?key=666` | HTML 화면 | `pageIndex`(+`pageUnit=1000`) | 집행 한 건이 한 줄. `searchDeDtMonth`로 사용월을 고르고 화면이 원본 |
| 관악구 | `gwanak.go.kr/site/gwanak/estimate/estimateListExcel.do` | HTML 화면 | 없음(달 하나가 요청 하나) | 공식 월별 내려받기. `Content-Type: text/html`에 `.xls` 이름 |
| 서대문구 | `sdm.go.kr/admininfo/budget/openmoney.do` | HTML 화면 | `cp` | EUC-KR. 검색 조건을 GET에 함께 실으면 쪽이 바뀐다. 화면이 원본 |
| 종로구 | `jongno.go.kr/portal/bbs/selectBoardList.do?bbsId=BBSMSTR_000000001167&menuId=110210` | egov 변형 | `pageIndex` | 목록이 바로 `/cmm/fms/FileDown.do`를 준다. 상세는 `selectBoardArticle.do` |
| 용산구 | `yongsan.go.kr/portal/bbs/B0000030/list.do?menuNo=200140` | portal-bbs | `pageIndex` | 목록 줄에 `portal/cmmn/file/fileDown.do`. 파일 이름은 링크 `title`에만 있다 |
| 광진구 | `gwangjin.go.kr/portal/bbs/B0000027/list.do?menuNo=201646` | portal-bbs | `pageIndex` | `li` 하나가 게시글. 쪽 수를 `[ 1 / 571 페이지 ]`로 밝힌다 |
| 중랑구 | `jungnang.go.kr/portal/bbs/list/B0000143.do?menuNo=200432` | portal-bbs 변형 | `pageIndex` | 첨부 `portal/cmm/fms/FileDown.do`가 **Referer를 요구한다** |
| 동작구 | `dongjak.go.kr/portal/bbs/B0000591/list.do?menuNo=200209` | portal-bbs | `pageIndex` | 상세 `view.do?nttId=` → `portal/cmmn/file/fileDown.do` |
| 성동구 | `sd.go.kr/main/selectBbsNttList.do?bbsNo=172&key=1330` | bbsNo | `pageIndex` | 목록 줄에 `downloadBbsFileStr.do?atchmnflStr=` |
| 동대문구 | `ddm.go.kr/www/selectBbsNttList.do?bbsNo=160&key=152` | bbsNo | `pageIndex` | 상세 `selectBbsNttView.do` → `downloadBbsFile.do?atchmnflNo=` |
| 성북구 | `sb.go.kr/www/selectBbsNttList.do?bbsNo=28&key=5923` | bbsNo | `pageIndex` | 상세 → `downloadBbsFile.do?atchmnflNo=` |
| 구로구 | `guro.go.kr/www/selectBbsNttList.do?bbsNo=655&key=1732` | bbsNo | `pageIndex` | 목록 줄에 `downloadBbsFile.do?atchmnflNo=` |
| 금천구 | `geumcheon.go.kr/portal/selectBbsNttList.do?bbsNo=86&key=269` | bbsNo | `pageIndex` | 상세 → `/portal/downloadBbsFileStr.do?atchmnflStr=` |
| 영등포구 | `ydp.go.kr/www/selectBbsNttList.do?bbsNo=31&key=2814` | bbsNo | `pageIndex` | 목록 줄에 `downloadBbsFileStr.do?bbsNo=&atchmnflStr=` |
| 송파구 | `songpa.go.kr/www/selectBbsNttList.do?bbsNo=327&key=2323` | bbsNo | `pageIndex` | 목록 줄에 `downloadBbsFile.do?atchmnflNo=` |
| 양천구 | `yangcheon.go.kr/site/yangcheon/ex/bbs/List.do?cbIdx=397` | cbIdx | `pageIndex` | 제목이 `wdigm_title(...)`, 게시글 번호가 `doBbsFView(...)`. 상세 → `/common/board/Download.do` |
| 서초구 | `seocho.go.kr/site/seocho/ex/bbs/List.do?cbIdx=33` | cbIdx | `pageIndex` | 목록이 `View.do?cbIdx=&bcIdx=`를 그대로 준다 → `/common/board/Download.do` |
| 중구 | `junggu.seoul.kr/content.do?cmsid=15383&exclude=Y` | 단독 | `page2` | 상세 `mode=view&cid=` → `/cwsboard/board.do?mode=download&…&filename=` |
| 도봉구 | `dobong.go.kr/bbs.asp?code=10008860` | 단독 | `intPage` | 상세 `bbs.asp?bmode=D&pcode=` → `/WDB_common/include/download.asp` |
| 노원구 | `nowon.kr/www/user/bbs/BD_selectBbsList.do?q_bbsCode=1012` | 단독 | `q_currPage` | 목록 줄에 `/component/file/ND_fileDownload.do`. 같은 원본이 두 링크로 실린다 |
| 마포구 | `mapo.go.kr/site/main/board/expense/list` | 단독 | `cp` | 목록 줄에 `/site/main/file/download/uu/<uuid>` |
| 강서구 | `gangseo.seoul.kr/gs030325` | 단독 | `curPage` | 상세 `/gs030325/<번호>` → `/comm/getFile?srvcId=BBSTY1&…` |
| 강남구 | `gangnam.go.kr/board/B_000673/list.do?mid=ID05_04200502` + `B_000672` | 단독 | `pgno` | 상세 없음. 목록 줄에 `/file/1/get/<uuid>/download.do` |
| 강동구 | `gangdong.go.kr/web/newportal/bbs/b_054` | 단독 | `cp` | 상세 `/bbs/b_054/<번호>` → `/web/newportal/file/download/uu/<uuid>` |
| 강북구 | `gangbuk.go.kr/portal/intgty/deptJobPrtnCt/list.do?menuNo=200155` | — | — | 수집 보류(`bot_blocked`) |

계열 스크래퍼는 `src/deliciousmap/scrapers/seoul.py`(bbsNo·portal-bbs·cbIdx·종로),
`seoul_html.py`(화면이 원본인 4곳), `seoul_district.py`(단독 7곳)에 있다. 기관마다 다른
값은 모두 레지스트리의 게시판 주소에서 온다.

### 200이 성공이 아니었던 자리

| 자리 | Referer/조건 없이 | 붙이고 나서 |
| --- | --- | --- |
| 중랑 첨부 `portal/cmm/fms/FileDown.do` | 200 + 1,052바이트 HTML | 200 + 106,017바이트 `%PDF-1.4` |
| 강북 목록·`robots.txt` | 200 + 433바이트 봇 확인 스크립트 | (우회하지 않음 → 수집 보류) |
| 서대문 엑셀 `excelDownLoad.do` | 200 + **0바이트**, 59.9초 | (쓰지 않음 → 화면을 원본으로) |
| 관악 월별 내려받기 | 200, `.xls` 이름, `Content-Type: text/html` | (HTML 표로 받아들임) |
| 중구 상세 첫 파일 | `filename=`이 `.png`인 사이트 그림 | `filename=` 확장자로 거른다 |
| 양천 상세 첫 파일 | `DownloadViewFile.do?cfIdx=` 배너 | `Download.do?cbIdx=`로만 받는다 |

## 첨부 없는 HTML 원본의 수집 계약

서울시청·은평·관악·서대문은 첨부를 내려받지 않는다. 기관이 주는 공식 내려받기는 관악의
HTML 표 하나뿐이고 그마저 매직 바이트가 없다. **2026-09-14 사용자 결정으로 받은 화면을
원본으로 저장하고 해시한다.** 그래서 `boards.py`에 `html` 컨테이너를 더했다.

| 기관 | 원본으로 삼은 것 | 근거 |
| --- | --- | --- |
| 서울시청 | 상세 화면 `/expense/<번호>` | 집행 표가 상세 안 `<table>`에 그대로 있다(실측 18행). 상세의 HWPX 내려받기는 `/og/com/`이고 이 호스트의 robots.txt가 막는 유일한 경로다 |
| 은평구 | 사용월·쪽으로 거른 목록 화면 | 집행 한 건이 한 줄이고 내려받기가 없다 |
| 관악구 | 공식 월별 내려받기 산출 | 기관이 주는 산출이므로 그것을 원본으로 삼는다. 다만 내용은 HTML 표다(`.xls` 이름, `text/html`, 매직 바이트 없음) |
| 서대문구 | 사용월·쪽으로 거른 목록 화면 | 엑셀 내려받기가 60초 뒤 0바이트를 준다. 금액 단위는 `집행액(천원)`이다 |

`html` 판정은 게시판 단위로만 켠다 — 스크래퍼가 `.html`을 실측 확장자로 선언한 게시판에서만
켜므로, Referer 없는 중랑 첨부처럼 200으로 오는 오류 화면이 첨부 게시판의 원본이 되지 않는다
(`tests/test_boards.py`·`tests/test_collection.py`).

사용월을 직접 고를 수 있는 게시판은 대상 기간의 달만 받는다(`period.months`). 게시일로만
가를 수 있는 게시판의 해 단위 규칙(`period.collects`)과 다른 자리이고, 그 이유를
`period.months`의 도크스트링에 적었다.

## 섞인 게시판의 필터

| 기관 | 기준 | 걸러 낸 수 |
| --- | --- | --- |
| 서울시청 | 목록 제목의 기관 축이 `의회사무처`인 게시글 | 2026 상반기 117건(축 전수: 사업소 1,167·서울시본청 1,074·소방재난본부(소방서) 247·의회사무처 117, 합계 2,605) |
| 중구 | 공표부서에 `의회`가 들어간 줄 | 139건 |
| 구로 | 담당부서에 `의회`가 들어간 줄 | 171건 |
| 강남 | 담당부서에 `의회`가 들어간 줄 | 0건. 필터는 걸어 두었으나 2026년 줄에서 걸린 것이 없다 |

구로는 처음에 2026년 줄만 눈으로 훑고 "의회 부서가 없다"고 적었으나, 기준을 선언해
전 기간을 세니 171건이 나왔다. 섞임은 그 해의 성질이 아니라 게시판의 성질이므로 이슈가
지목한 넷 모두에 기준을 선언하고 수를 센다.

서울시청의 `dept[]` 필터는 GET으로는 걸러지지 않아(일곱 값 모두 0건) 제목 축으로 거른다.
축은 2026 상반기 2,605건 전수에서 위 네 가지만 나왔다 — `투자출연기관`·`서울시립대학교`·
`민간위탁사무 수탁기관`은 상반기 게시글이 없다.

## 개인정보

종로구 목록은 담당자 실명을 칸으로 싣는다. `JongnoBoard`는 그 칸을 읽지 않고, 제목 칸이
없는 게시판이라 게시판이 밝힌 `년도`·`해당 월` 두 칸을 기간 표기로 옮겨 싣는다. 산출물에
실명이 들어가지 않는 것을 `tests/test_seoul_district.py`가 고정한다.

## 확인한 검사

- `uv run pytest`
- `uv run ruff check .` / `uv run ruff format --check .`
- `uv run mypy src`
- `git diff --check`
- gitleaks(커밋 훅)

## 2026년 상반기 수집 장부

`python -m deliciousmap fetch --city seoul --org <slug>`를 기관마다 실행했다. 원본은 저장소 밖
`deliciousmap-raw/seoul/<기관>/<게시판>/`에 두었다(ADR-0001). 아래 값은
`data/seoul/orgs/<slug>/fetch.json`을 그대로 읽은 것이다.

- **게시글**: 수집을 마친 게시글 수(`collected.jsonl`의 줄 수).
- **원본**: 그 게시글에 달려 받은 원본 파일 수(`sources`). 게시글 하나에 첨부가 여럿일 수 있어
  게시글 수보다 클 수 있다.
- **받지 않은 게시글**: 게시일이 2026년 밖이라 본문도 열지 않은 게시글 수(`uncollected_postings`).
- **걸러 낸 게시글**: 업무추진비 집행기관이 아니어서 뺀 게시글 수(`filtered_postings`).

| 기관 | 게시글 | 원본 | 컨테이너 | 받지 않은 게시글 | 걸러 낸 게시글 |
| --- | --- | --- | --- | --- | --- |
| 서울특별시 `seoul-city` | 2,488 | 2,488 | html 2,488 | 0 | 117 |
| 종로구 `seoul-jongno` | 724 | 724 | ooxml 27 · pdf 697 | 11,334 | 0 |
| 중구 `seoul-jung` | 417 | 432 | ole2 32 · ooxml 353 · pdf 47 | 7,389 | 139 |
| 용산구 `seoul-yongsan` | 474 | 484 | jpeg 7 · ole2 1 · ooxml 28 · pdf 445 · png 3 | 7,138 | 0 |
| 성동구 `seoul-seongdong` | 520 | 520 | pdf 520 | 3,006 | 0 |
| 광진구 `seoul-gwangjin` | 445 | 444 | ooxml 91 · pdf 353 | 5,248 | 0 |
| 동대문구 `seoul-dongdaemun` | 482 | 501 | pdf 500 · zip 1 | 8,168 | 0 |
| 중랑구 `seoul-jungnang` | 540 | 574 | ole2 10 · ooxml 30 · pdf 534 | 0 | 0 |
| 성북구 `seoul-seongbuk` | 508 | 521 | jpeg 10 · ooxml 13 · pdf 497 · zip 1 | 8,596 | 0 |
| 도봉구 `seoul-dobong` | 464 | 466 | ole2 26 · ooxml 287 · pdf 153 | 7,413 | 0 |
| 노원구 `seoul-nowon` | 632 | 632 | ole2 80 · ooxml 154 · pdf 398 | 9,496 | 0 |
| 은평구 `seoul-eunpyeong` | 9 | 9 | html 9 | 0 | 0 |
| 서대문구 `seoul-seodaemun` | 1,040 | 1,040 | html 1,040 | 0 | 0 |
| 마포구 `seoul-mapo` | 528 | 528 | ooxml 9 · pdf 519 | 6,846 | 0 |
| 양천구 `seoul-yangcheon` | 518 | 518 | ole2 128 · ooxml 373 · pdf 17 | 6,965 | 0 |
| 강서구 `seoul-gangseo` | 594 | 683 | ole2 11 · ooxml 46 · pdf 626 | 8,934 | 0 |
| 구로구 `seoul-guro` | 555 | 555 | ole2 185 · pdf 370 | 10,135 | 171 |
| 금천구 `seoul-geumcheon` | 502 | 502 | ole2 11 · pdf 491 | 8,379 | 0 |
| 영등포구 `seoul-yeongdeungpo` | 501 | 501 | pdf 501 | 3,833 | 0 |
| 동작구 `seoul-dongjak` | 530 | 564 | jpeg 7 · ole2 5 · ooxml 16 · pdf 536 | 8,556 | 0 |
| 관악구 `seoul-gwanak` | 6 | 6 | html 6 | 0 | 0 |
| 서초구 `seoul-seocho` | 647 | 681 | ooxml 33 · pdf 648 | 11,681 | 0 |
| 강남구 `seoul-gangnam` | 704 | 706 | ole2 216 · ooxml 474 · pdf 16 | 8,058 | 0 |
| 송파구 `seoul-songpa` | 638 | 638 | ooxml 4 · pdf 634 | 11,866 | 0 |
| 강동구 `seoul-gangdong` | 582 | 589 | ooxml 3 · pdf 586 | 3,391 | 0 |
| 강북구 `seoul-gangbuk` | — | — | — | — | 수집 보류 `bot_blocked` |

**받지 못한 원본(`missing`)은 25개 기관 전부에서 0건이다.**

받지 않은 게시글·걸러 낸 게시글은 게시판을 끝까지 훑은 기관의 값이다. 순회를 마치지 못한
중랑은 두 값이 0으로 남는다 — 실제로 없어서가 아니라 세지 못해서다(아래 "실패한 게시판").

컨테이너 합계: `html 3,543 · jpeg 24 · ole2 705 · ooxml 1,941 · pdf 9,088 · png 3 · zip 2`
= 원본 15,306건, 게시글 15,048건, 받지 않은 게시글 156,432건,
걸러 낸 게시글 427건.

### 실패한 게시판

중랑구 `seoul-jungnang/expenses`만 사유가 달렸다: `service-unavailable`.

이 호스트는 목록 한 쪽에 3.3초가 걸리고(853쪽 ≈ 47분) 그 사이 읽기가 간헐적으로 끊긴다.
프로젝트 UA로 목록만 훑는 별도 측정에서는 853쪽을 2,522초에 완주했고 재시도 4회가 그 끊김을
흡수했지만, 원본을 함께 받는 실제 수집은 열두 번 시도해 한 번도 순회를 마치지 못했다.
2026년 원본 574건은 모두 받아 두었고 그 사실이 장부에 남는다. `uncollected_postings`가 0인 것은
받지 않은 게시글이 없어서가 아니라 순회가 2026년 구간을 지나 끝까지 가지 못했기 때문이다 —
이 값은 중랑에서만 전 기간을 센 값이 아니다.

게시판 하나의 장애를 기관 전체의 0건으로 바꾸지 않는 동작은 원래 울산에만 켜져 있었다
(`collection.FAILURE_TOLERANT`). 광주는 받지 않았고 다섯 기관이 모두 실패 없이 끝나 차이가
드러나지 않았을 뿐이다. 서울은 기관마다 게시판이 하나여서 실패하면 그 기관의 장부 자체가 남지
않으므로, 2026-09-14 사용자 결정으로 서울을 울산과 같게 두었다. 나머지 도시로 넓힐지는
[#140](https://github.com/snowjaewon/OfficialDeliciousMap/issues/140)에서 정한다.

실측하지 않은 형식을 경고로만 남기고 통과시키는 완화(`collection.UNMEASURED_TOLERANT`)는 서울에
켜지 않았다. 그 완화는 첨부를 조용히 빠뜨리며(울산 장부 실측: 북구 18·동구 28·남구 10건),
서울에서는 그 엄격함 덕분에 용산·성북·동작의 스캔본 24건을 찾아 형식으로 선언할 수 있었다.

### 화면이 원본인 게시판의 집행 줄 수

저장한 화면 안의 집행 줄을 세었다. 표 추출은 이 이슈의 범위 밖이므로 줄 수만 남긴다.

| 기관 | 2026년 상반기 집행 줄 | 대조 |
| --- | --- | --- |
| 서울특별시 | 34,751 | 원본 2,488건 중 83건은 게시판이 "해당 월 업무추진비 사용내역이 없습니다"라고 밝힌 화면이다. HWPX 내려받기도 없어 수집 실패가 아니라 기관이 공개한 0건이다 |
| 은평구 | 5,906 | 달별 996·874·1,096·1,062·776·1,102 |
| 관악구 | 9,585 | 달별 1,527·1,390·1,754·1,736·1,323·1,855 |
| 서대문구 | 4,152 | 6월 724건이 게시판이 스스로 밝힌 `집행건수 724 건`과 같다 |

### 형식은 확장자가 아니라 바이트로 갈렸다

- **스캔본**: 용산 10건(jpeg 7·png 3), 성북 10건(jpeg), 동작 7건(jpeg)이 집행내역을 표가 아니라
  이미지로 공개한다(`7월 업무추진비 집행내역001.jpg`, `기관업무추진비202609.jpg`). 그 몇 건 때문에
  기관 전체가 `unsupported-format`으로 멈추지 않도록 실측 서명으로 `jpeg`·`png` 컨테이너를 더했다.
- **같은 게시판 안에서 형식이 섞인다**: 양천 ooxml 373·ole2 128·pdf 17, 강남 ooxml 474·ole2 216·pdf 16,
  도봉 ooxml 287·ole2 26·pdf 153. 정찰이 경고한 "화면 글자는 형식 근거가 아니다"가 그대로 확인됐다.
- **HWPX**: `Contents/`를 문서 묶음 표식에 더해 일반 ZIP과 갈랐다. 그전에는 같은 HWPX가 게시판에 따라
  `ooxml`과 `zip`으로 갈려 세어졌다(커밋된 광주 장부는 `ooxml` 6건).

## 제목이 밝힌 지출 기간

제목이 있는 원본 13,677건을 `period.exclusion`으로 읽었다. 나머지 1,629건은 게시판이 제목을
밝히지 않아(은평·관악·서대문의 화면 1,055건, 그 밖에 목록에 제목 칸이 없는 게시글) 읽을 제목이
없다 — 원본 15,306건과 다른 단위다.

| 판정 | 수 |
| --- | --- |
| 대상(`None`) | 10,161 |
| 대상 기간 밖(`declared_out_of_range`) | 3,416 |
| 게시일이 대상 연도 밖(`posted_out_of_range`) | 63 |
| **기간 미선언(`undeclared_in_year`)** | **37** |

`period.DECLARATION`에 더한 표기는 없다. 37건은 아래 네 갈래이고, 짐작으로 읽지 않고 기간
미선언으로 남긴다.

| 갈래 | 수 | 실측 예 |
| --- | --- | --- |
| 해를 `년` 없이 적고 달을 제목 끝 괄호에 둔다 | 28 | 구로 `2026 행정관리국 기관운영업무추진비 집행내역(4월)`, `2026 3월 자동차관리과시책추진업무추진비 공개` |
| 달만 적고 해가 없다 | 4 | 성북 `민원여권과 1월 시책추진업무추진비 공개`, `지역경제과 시책추진업무추진비 집행내역 공개(8월)` |
| 기관이 잘못 적었다 | 2 | 성동 `2026월 1월 …`(`년`이 `월`), 성북 `…공개(206.4월)`(해가 세 자리) |
| 기간을 적지 않은 게시글 | 3 | 강남 `지방보조금으로 취득한 중요재산`, 강서 `안전교통국, 안전관리과 업무추진비 누락 내역 공개`, 서초 `방배2동 기관운영업무추진비 내역공개(현금)` |

달만 적은 제목 여섯 건(동작 `8월 업무추진비 사용내역 공개`, 중구 `12월 자치행정과 …`,
양천 `7월 업무추진비 공개`, 용산 `1월 후암동 …`)은 develop의 `#137`·`#146`이 더한
"달만 적힌 제목은 게시일의 해로 읽는다" 규칙이 그대로 읽어 낸다. 이 브랜치를 develop에
리베이스한 뒤 43건에서 37건으로 줄었다. 서울에서 그 규칙을 따로 손보지 않았다.

첫 갈래는 읽을 수 있어 보이지만 더하지 않았다. `DECLARATION`은 해 뒤에 바로 붙은 표기만 읽어
제목 뒤쪽의 다른 숫자를 기간으로 오해하지 않는데, 해와 달 사이에 구분자가 없는 형태와 제목 끝
괄호의 달을 받아들이면 그 보호가 사라진다. 이 모듈은 광주 제목 10,476건으로 고정돼 있고 이미
커밋된 광주 산출물이 그 동작에 걸려 있어, 표기를 넓히는 일은 그 영향까지 함께 재는 후속 작업으로
남긴다. 지금은 43건이 원본으로는 수집돼 있고 대상 선별에서만 빠진다.

## 실행에서 드러난 게시판 쪽 문제

| 기관 | 게시판이 준 것 | 우리가 한 일 |
| --- | --- | --- |
| 중구 | 206쪽에 게시일 `2021-05-70` | 달력에 없는 날은 그 줄만 게시일 없음으로 둔다 |
| 동작 | 2017년 줄 몇 개가 공개일 칸이 빈 채로 올라와 있다 | 같은 줄만 게시일 없음으로 두고, 한 쪽의 어느 줄에도 날짜 모양이 없을 때만 구조 변경으로 멈춘다 |
| 종로 | 쪽 넘김이 `pageMove(n)`이라 주소에 쪽 번호가 없다 | 맨끝 단추의 603을 전체 쪽 수로 읽는다 |
| 노원 | 같은 원본을 이름 링크와 아이콘 링크로 두 번 싣는다 | 주소로 한 번만 받는다 |
| 동작·강동·강서·동대문·영등포·성북 | 긴 순회 중 간헐적으로 연결이 끊긴다 | 이어받기로 다시 실행한다. 이미 받은 원본은 다시 내려받지 않는다(강동 4회·동작 2회·강서 2회) |
| 중랑 | 목록 한 쪽에 3.3초가 걸리고 그 사이 읽기가 끊긴다 | 열두 번 시도해도 순회를 마치지 못했다. 2026년 원본 574건과 실패 사유를 장부에 남긴다 |
