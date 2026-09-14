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
| 중구 | 공표부서에 `의회`가 들어간 줄 | 아래 수집 장부 참고 |
| 강남 | 담당부서에 `의회`가 들어간 줄 | 아래 수집 장부 참고 |
| 구로 | — | 2026년 줄에서 의회 부서가 나오지 않았다. 필터를 걸지 않았고 그 사실을 여기 남긴다 |

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
