# 서울·부산 기관 게시판 정찰 (2026-09-09)

이슈 [#3](https://github.com/snowjaewon/OfficialDeliciousMap/issues/3) (parent #1) 산출물.
서울특별시(시청 + 25 자치구)·부산광역시(시청 + 16 구·군) **43개 기관**의 업무추진비 게시판이
지금 어디에 있고 어떤 형태인지 실측했다.

## 근거와 방법

- 출발점(2차 자료): 목업 저장소의 정찰 문서
  [docs/서울_수집_정찰.md](https://github.com/snowjaewon/governdeliciousmap/blob/main/docs/서울_수집_정찰.md) (2026-08-22/23),
  [docs/부산_수집_정찰.md](https://github.com/snowjaewon/governdeliciousmap/blob/main/docs/부산_수집_정찰.md) (2026-08-21),
  [docs/서울_파싱집계_20260823.json](https://github.com/snowjaewon/governdeliciousmap/blob/main/docs/서울_파싱집계_20260823.json),
  [HANDOFF.md](https://github.com/snowjaewon/governdeliciousmap/blob/main/HANDOFF.md)의 지뢰 목록.
- 실측(1차 자료): 2026-09-09에 기관 사이트에 `curl -L`(Chrome UA, 리다이렉트 추적, 60s 타임아웃)로
  **목록 1쪽·2쪽**을 받아 본문 바이트를 확인했다. 2쪽은 md5 비교 + 첫 게시물 id/첨부 id 비교로
  "정말 다른 쪽인지" 확인했다. CMS 계열별 대표 기관은 상세 1건 → 첨부 1건의 **첫 32바이트**를
  Referer 있이/없이 받아 형식(매직 바이트)과 Referer 요구를 쟀다. 대량 수집은 하지 않았다.
- 표기: **실측** = 이번 curl로 확인. **목업** = 목업 문서 값을 인용(재검증 안 함).
- "2026 상반기 게시글": 목록 1·2쪽은 대부분 2026-07~09 게시물이라 상반기 제목이 직접 보이는
  기관은 따로 적었다. 나머지는 (a) 월별 게시가 2026-08까지 끊기지 않았고 (b) 서울은 목업 JSON에
  2026-01~06 레코드가 기관별로 있으므로 **간접 확인**으로 표기했다.

## 서울특별시 (26개 기관)

페이징 열은 GET 파라미터 이름이며, 특별히 적지 않으면 GET 2쪽이 1쪽과 다른 내용임을 실측했다.
첨부 열은 실측 매직 바이트(`%PDF`, `PK`=OOXML, `D0CF11E0`=OLE2) 또는 목업 값.

| 기관 | 게시판 URL (목록) | CMS | 페이징 | 첨부/표 | Referer | 2026 상반기 | 비고 |
|---|---|---|---|---|---|---|---|
| 서울시청 | `opengov.seoul.go.kr/expense/list` | 정보소통광장(Drupal) | `page` | **HTML 표** (상세 `/expense/{id}` 안 `<table>`, 실측 3표 32행) | 불필요 | 간접(목업 2026-01~06 31,289건) | 의회사무처 등 7갈래 기관 축 → 제목 필터. 첨부(HWPX)는 열 필요 없음 |
| 종로구 | `jongno.go.kr/portal/bbs/selectBoardList.do?bbsId=BBSMSTR_000000001167&menuId=110210` | egov 표준 | `pageIndex` | PDF (목록 행에 `/cmm/fms/FileDown.do?atchFileId=&fileSn=`) | 불필요(실측) | 간접(목업 4,138건) | 목록에 담당자 실명 열. 상세 없이 목록에서 바로 첨부 |
| 중구 | `junggu.seoul.kr/content.do?cmsid=15383&exclude=Y` | 자체(cwsboard) | **`page2`** | **XLSX**(실측 `PK`; 목업 8/23은 PDF) — `cwsboard/board.do?mode=download&bid=&cid=&fileIndex=&filename=` | 불필요(실측) | 간접(목업 5,325건) | 상세 첫 파일 링크가 1.7MB **PNG**(사이트 이미지)다 — `filename=` 확장자로 걸러야 함. 의회사무과 행 섞임 |
| 용산구 | `yongsan.go.kr/portal/bbs/B0000030/list.do?menuNo=200140` | portal-bbs | `pageIndex` | PDF (목록 행 `portal/cmmn/file/fileDown.do?atchFileId=&fileSn=`) | 불필요(실측) | 간접(목업 3,741건) | |
| 성동구 | `sd.go.kr/main/selectBbsNttList.do?bbsNo=172&key=1330` | bbsNo 계열 | `pageIndex` | PDF (목록 행 `downloadBbsFileStr.do?atchmnflStr=`) | 불필요(실측) | 간접(목업 3,710건) | |
| 광진구 | `gwangjin.go.kr/portal/bbs/B0000027/list.do?menuNo=201646` | portal-bbs | `pageIndex` | **XLSX**(실측 `PK`) — `portal/cmmn/file/fileDown.do` | 불필요(실측) | 간접(목업 2,563건) | |
| 동대문구 | `ddm.go.kr/www/selectBbsNttList.do?bbsNo=160&key=152` | bbsNo 계열 | `pageIndex` | PDF — 상세 `selectBbsNttView.do?bbsNo=&nttNo=` → `downloadBbsFile.do?atchmnflNo=` | 불필요(실측) | 간접(목업 4,532건) | |
| 중랑구 | `jungnang.go.kr/portal/bbs/list/B0000143.do?menuNo=200432` | portal-bbs(변형) | `pageIndex` | PDF (목록 행 `portal/cmm/fms/FileDown.do?atchFileId=&fileSn=`) | **필요** — 없으면 `200` + 1,052B HTML | 간접(목업 3,968건) | 🔴 서울에서 유일하게 Referer 없이 200-오류페이지를 준다 |
| 성북구 | `sb.go.kr/www/selectBbsNttList.do?bbsNo=28&key=5923` | bbsNo 계열 | `pageIndex` | PDF(목업) | 목업: 불필요 | 간접(목업 5,907건) | 첨부 재확인 안 함(동대문과 같은 계열) |
| 강북구 | `gangbuk.go.kr/portal/intgty/deptJobPrtnCt/list.do?menuNo=200155` | 전용 컨트롤러 | `pageIndex`(쿠키 붙여 실측) | PDF (목록 행 `fileDownLoad.do?streFileNm=….pdf&menuNo=200155`) | 불필요(실측) | 간접(목업 4,238건) | 🔴 **봇 차단 여전** — 첫 응답 433B JS. 응답의 `sabSignature`와 `sabFingerPrint=1920,1080,www.gangbuk.go.kr` 쿠키로 통과(실측 374KB). 상세 없음. 목록 열: 번호/년도/월/작성부서/구분/파일/작성일 |
| 도봉구 | `dobong.go.kr/Contents.asp?code=10008860` → **`/bbs.asp?code=10008860`** | ASP | `intPage` — **`bbs.asp`에 붙여야 함**(`Contents.asp?…&intPage=2`는 리다이렉트에서 떨어져 1쪽) | PDF — 상세 `bbs.asp?bmode=D&pcode=&code=` → `/WDB_common/include/download.asp?fcode=&bcode=` | 불필요(실측) | 간접(목업 3,653건) | 787쪽(실측) |
| 노원구 | `nowon.kr/www/user/bbs/BD_selectBbsList.do?q_bbsCode=1012` | BD 계열 | **`q_currPage`**(hidden input 실측, GET 동작) + `q_rowPerPage` | **PDF**(실측; 목업은 XLSX·HWPX) — 목록 행 `/component/file/ND_fileDownload.do?q_fileSn=&q_fileId=` | 불필요(실측) | 간접(목업 3,988건) | 형식이 섞인다 → 바이트로 판정. 1,016쪽 |
| 은평구 | `ep.go.kr/www/selectJobPrtnCtWebList.do?key=666` | 전용 컨트롤러 | `pageIndex` + **`pageUnit`**(50 실측 51행; 목업 1000 동작) | **HTML 라인**(집행 1건 = 행) | 해당 없음 | 간접(목업 2026-01~06 5,705건) | 첨부 없음 |
| 서대문구 | `sdm.go.kr/admininfo/budget/openmoney.do` | 자체 | **POST `cp`** — 🔴 `searchGUBUN/searchDept/searchYear/searchMonth` 를 (빈 값이라도) 같이 보내야 쪽이 바뀐다(`cp=2`만 보내면 1쪽 그대로) | **HTML 라인**, EUC-KR, `집행액(천원)` | 해당 없음 | **실측**: `searchYear=2026&searchMonth=06` → 723건 | 엑셀: POST `/excelDownLoad.do?actionNm=/admininfo/budget/openmoney.do`(searchMonth 필수) — 이번엔 60/120s 안에 응답이 안 끝났다(164KB 예고 후 중단). 목업은 6월 160KB 성공. 필터 없는 전체 151,141건 |
| 마포구 | `mapo.go.kr/site/main/board/expense/list` | 자체(REST) | `cp` | PDF (목록 행 `/site/main/file/download/uu/{uuid}`, Range 206 지원) | 불필요(실측) | 간접(목업 3,526건) | |
| 양천구 | `yangcheon.go.kr/site/yangcheon/ex/bbs/List.do?cbIdx=397` | cbIdx 계열 | `pageIndex`(UI는 `doBbsFPag(n)`) | **XLSX** — 상세는 JS `doBbsFView('397',bcIdx,…)` → `View.do?cbIdx=397&bcIdx=` → `/common/board/Download.do?bcIdx=&cbIdx=&streFileNm=….xlsx` | 목업: 불필요 | 간접(목업 3,936건) | 첫 파일 링크 `DownloadViewFile.do?cfIdx=`는 배너 — 무시. 제목이 `document.write(...)` JS. 398/399는 옛 자료 |
| 강서구 | `gangseo.seoul.kr/gs030325` | 자체 | `curPage` | PDF — 상세 `/gs030325/{id}` → `/comm/getFile?srvcId=BBSTY1&upperNo=&fileNo=` | 불필요(실측) | 간접(목업 4,654건) | |
| 구로구 | `guro.go.kr/www/selectBbsNttList.do?bbsNo=655&key=1732` | bbsNo 계열 | `pageIndex` | PDF/HWP(목업) | 목업: 불필요 | 간접(목업 3,619건) | 의회 행 섞임 |
| 금천구 | `geumcheon.go.kr/portal/selectBbsNttList.do?bbsNo=86&key=269` | bbsNo 계열(`/portal/`) | `pageIndex` | PDF(목업) | 목업: 불필요 | 간접(목업 3,551건) | UTF-8 명시. 목록에 건수/인원/금액 합계 열 |
| 영등포구 | `ydp.go.kr/www/selectBbsNttList.do?bbsNo=31&key=2814` | bbsNo 계열 | `pageIndex` | PDF(목업) | 목업: 불필요 | 간접(목업 5,203건) | |
| 동작구 | `dongjak.go.kr/portal/bbs/B0000591/list.do?menuNo=200209` | portal-bbs | `pageIndex` | PDF — 상세 `view.do?nttId=` → `portal/cmmn/file/fileDown.do` | 불필요(실측) | 간접(목업 5,104건) | 게시판명 "업무추진비 및 강사료" |
| 관악구 | `gwanak.go.kr/site/gwanak/estimate/estimateList.do` | 자체 | `pageIndex`(GET 실측) | **HTML 라인**(카드형) | 해당 없음 | 간접(목업 2026-01~06 9,279건) | 월별 내려받기: form `EstimateVo` POST `/site/gwanak/estimate/estimateListExcel.do` (`searchCondition3/4` = 시작/종료일, 31일 이내). 목업: `.xls` 이름의 HTML 표 |
| 서초구 | `seocho.go.kr/site/seocho/ex/bbs/List.do?cbIdx=33` | cbIdx 계열 | `pageIndex` | PDF — 상세 `View.do?cbIdx=33&bcIdx=` → `/common/board/Download.do` | 불필요(실측) | 간접(목업 5,556건) | 이번엔 느리지 않았다(목업은 20s 타임아웃) |
| 강남구 | `gangnam.go.kr/board/B_000673/list.do?mid=ID05_04200502` **+ `B_000672`**(보조금·업무추진비, 실측 200) | 자체 | `pageIndex` | **XLSX** (목록 행 `/file/1/get/{uuid}/download.do`) | 불필요(실측) | 간접(목업 4,835건) | 상세 없음. 게시판 둘 다 확인 |
| 송파구 | `songpa.go.kr/www/selectBbsNttList.do?bbsNo=327&key=2323` | bbsNo 계열 | `pageIndex` | PDF(목업) | 목업: 불필요 | 간접(목업 4,850건) | |
| 강동구 | `gangdong.go.kr/web/newportal/bbs/b_054` | 자체(REST) | `cp`(+`pageSize=15`) | PDF — 상세 `/bbs/b_054/{id}` → `/web/newportal/file/download/uu/{uuid}` | 불필요(실측) | 간접(목업 5,165건) | 목업: delay 0.3s에서 400 |

## 부산광역시 (17개 기관)

rfc3 계열: `/board/list.<사이트키>?boardId=BBS_…`, 페이징 `startPage`, 상세 `view.<키>?…&dataSid=`,
첨부 `download.<키>?boardId=&dataSid=&fileSid=`. 사이트키는 도메인과 다를 수 있다(목업 표 그대로 유효).

| 기관 | 게시판 URL (목록) | CMS | 페이징 | 첨부/표 | Referer | 2026 상반기 | 비고 |
|---|---|---|---|---|---|---|---|
| 부산시청 | `busan.go.kr/ghopen12/list` (`schBizNo` 46 시장·부시장 / 45 4급 이상 / 199 지방공기업) | 자체 | `curPage` | 상세 `/ghopen12/view?schCommand=Expense&schIndx=` → `/comm/getFile?srvcId=OPENGOV&upperNo=&fileTy=ATTACH&fileNo=1` — **표본 1건 Fasoo DRM**(`\x9bDRMONE`, 이름은 .xlsx 20KB) | 불필요(실측) | **실측**: 1쪽 제목 2026-01~08(분기 단위 "2026년 2분기") | 🔴 DRM 손실 계속(목업 15%). 199 포함 여부는 제품 결정 |
| 중구 | `bsjunggu.go.kr/board/list.junggu?boardId=BBS_0000018` | rfc3 | `startPage` | 첨부(계열) | 계열: 불필요 | 간접 | 정보공개 통합 게시판(섞임) → 제목 필터, 등록일 기준 중단 |
| 서구 | `bsseogu.go.kr/board/list.bsseogu?boardId=BBS_0000151` | rfc3 | `startPage` | 첨부(계열) | 계열: 불필요 | **실측**: 2쪽 제목 2026-01~07 | |
| 동구 | `bsdonggu.go.kr/board/list.donggu?boardId=BBS_0000254` | rfc3 | `startPage` | 첨부(계열) | 계열: 불필요 | **실측**: 1쪽 제목 2026-01~08 | |
| 영도구 | `yeongdo.go.kr/00000/00067/00333.web`(gcode=1037 일반) **+ `/00492/00493/00498.web`**(gcode=1052 구청장) | `.web` 자체 | `cpage`(+`gcode`) | 상세 `?gcode=&idx=&amode=view` — 표본 2건 모두 "집행내역 없음"(첨부 없음)이라 형식 재확인 못 함(목업: 첨부) | 미측정 | 간접(2쪽 2026-07~08) | 목록 `<a>` 안에 행 전체 → `strong.t1`/`i.wrap1t3`로 나눌 것 |
| 부산진구 | `busanjin.go.kr/board/list.busanjin?boardId=BBS_0000023&menuCd=DOM_000000109001003000&contentsSid=276` | rfc3 | `startPage` | **XLSX**(실측 `PK`) `download.busanjin` | 불필요(실측; 오늘은 Referer 없이도 200) | 간접(1·2쪽 2026-08) | 🔴 `boardId`만으로는 **403** — `menuCd` 필수(목업과 동일) |
| 동래구 | `dongnae.go.kr/board/list.dongnae?boardId=BBS_0000200` | rfc3 | `startPage` | 첨부(계열) | 계열: 불필요 | **실측**: 2쪽 제목 2026-02~07 | |
| 남구 | `bsnamgu.go.kr/board/list.namgu?boardId=BBS_0000149` | rfc3 | `startPage` | 첨부(계열) | 계열: 불필요 | 간접 | 사이트키 `namgu` |
| 북구 | `bsbukgu.go.kr/board/list.bsbukgu?boardId=BBS_0000030` | rfc3 | `startPage` | 첨부(계열) | 계열: 불필요 | 간접 | |
| 해운대구 | `haeundae.go.kr/board/list.do?boardId=BBS_0000004` | rfc3(사이트키 `do`) | `startPage` | **XLSX**(실측 `PK`) `download.do` | 불필요(실측) | 간접(1쪽 2026-06~09) | `menuCd` 없이 **전 부서 통합 4,500건**(목업 4,475) |
| 사하구 | ~~`saha.go.kr/portal/bbs/list.do?ptIdx=29`~~ | (yhLib portal) | — | — | — | — | 🔴 **진입점 유실**: `ptIdx=29`는 "게시판이 삭제되었거나 존재하지 않습니다"(200 + 177B). 메뉴 `contents.do?mId=0302070000`("업무추진비 공개")는 본문 없이 만족도 폼만 렌더. 사이트 검색(`/RSA/front/Search.jsp`)은 0건/403. **사람이 브라우저로 새 위치를 찾아야 한다** |
| 금정구 | `geumjeong.go.kr/board/list.geumj?boardId=BBS_0000331` | rfc3 | `startPage` | 첨부(계열) | 계열: 불필요 | 간접 | 전용 게시판(목업 정정 유지) |
| 강서구 | `bsgangseo.go.kr/portal/board/post/list.do?bcIdx=534&mid=0503030100` (진입 `contents.do?mid=0503030000`이 여기로 리다이렉트) | yhLib portal | **`page`**(GET 실측) | 상세는 **GET** `post/view.do?bcIdx=534&mid=0503030100&idx=`로 열린다(POST 불필요). 첨부 `yhLib.file.download(a,b)` → `/common/file/download.do?atchFileId=&fileSn=` — **표본 1건 Fasoo DRM** | 불필요(실측) | **실측**: 1쪽 제목 2026-06~08 | 🔴 부산에서 DRM이 시청 밖에서도 나왔다(21KB .xlsx 이름). `_csrf` hidden 있음 |
| 연제구 | `yeonje.go.kr/portal/bbs/list.do?ptIdx=32&mId=0401090000` | egov portal | **`page`**(GET 실측; POST는 CSRF 403) | 상세 `view.do?bIdx=&ptIdx=32&mId=0401090000`(**`mId` 없으면 500**) → `fn_egov_downFile` = `/cmm/fms/FileDown.do?atchFileId=&fileSn=`(id는 해시) | 미측정 | 간접(1쪽 2026-08) | 🔴 `mId` 없이 목록을 부르면 **400 "잘못된 요청"** — 목업 URL은 이제 안 열린다 |
| 수영구 | `suyeong.go.kr/board/list.suyeong?boardId=BBS_0000116` | rfc3 | `startPage` | 첨부(계열) | 계열: 불필요 | 간접(2쪽 2026-07~08) | 섞인 게시판 → 제목 필터 |
| 사상구 | `sasang.go.kr/board/list.sasang?boardId=BBS_0000175` | rfc3 | `startPage` | **HWP**(실측 OLE2 `D0CF11E0`) `download.sasang` | 불필요(실측) | 간접 | HWP 표 0행이 표어(목업) |
| 기장군 | `gijang.go.kr/board/list.gijang?boardId=BBS_0000147&menuCd=DOM_000000101002014000&paging=ok&categoryCode1=000&startPage=N` | rfc3 | `startPage` | **HTML 표**(부서/사용자/사용일자/사용장소/사용목적/사용금액/대상인원/사용방법/연도, 10행/쪽) | 해당 없음 | **실측**: 2쪽이 2026-05~06 | 옛 `BBS_0000029`는 2021-12에서 멈춤. 메뉴명 "업무 추진비"(공백) |

## HANDOFF 지뢰 체크리스트 — 이번 실측 결과

| 지뢰 | 이번에 걸린 곳 |
|---|---|
| 200이 성공이 아니다 | 강북(200 + 433B JS), 사하(200 + 177B alert), 중랑 첨부 Referer 없음(200 + 1,052B HTML), 서대문 `cp=2`만 POST(200인데 1쪽), 부산시청·부산강서 첨부(200인데 DRM), 중구 첫 파일(200인데 PNG) |
| 기관 하나에 게시판 여럿 | 강남(B_000672/673), 영도(gcode 1037/1052), 부산시청(schBizNo 3), 해운대(menuCd는 부서 필터, 게시판은 하나) |
| 페이징 이름 실측 | `pageIndex` 17 · `startPage` 12 · `page` 3(서울시청·부산강서·연제) · `cp` 3(마포·강동·서대문 POST) · `curPage` 2(서울강서·부산시청) · `page2`(중구) · `intPage`(도봉, bbs.asp에만) · `q_currPage`(노원) · `cpage`(영도). 도봉은 진입 URL에 붙이면 리다이렉트에서 사라진다 |
| Referer | 목록·첨부 모두 필요한 곳은 **중랑구 첨부 하나**. 부산진구는 오늘 Referer 없이도 200이지만 `menuCd`는 필수 |
| JS 렌더 단정 금지 | 양천 상세·강북 목록·부산강서 상세·연제 상세가 겉으론 JS/POST인데 전부 **GET 등가 URL**이 있다. 강북 첫 응답만 진짜 JS(쿠키)다 |
| 게시판이 전용이 아님 | 부산 중구·수영구(섞임), 서울 중구·구로·강남(의회 행 섞임) |
| 화면 글자는 형식 근거가 아니다 | 노원(목업 XLSX → 오늘 PDF), 서울 중구(목업 PDF → 오늘 XLSX), 부산시청·강서(.xlsx 이름의 DRM) |

## 요약

**43개 기관 중 42개 진입점 확인, 1개(부산 사하구) 유실.** 목업(8/21~23) 이후 바뀐 것: 사하구 게시판 삭제,
연제구 `mId` 필수화, 부산 강서구 리다이렉트 경로·DRM, 서대문 페이징 조건. 나머지 URL은 그대로 살아 있다.

### 공용 스크래퍼 재사용 가능 묶음

| 계열 | 기관 수 | 기관 |
|---|---|---|
| 부산 rfc3 (`list.<키>?boardId=` + `startPage`) | **12** | 중·서·동·부산진·동래·남·북·해운대·금정·수영·사상 (첨부) + 기장(HTML 표, 목록 파서만 다름) |
| 서울 bbsNo (`selectBbsNttList.do?bbsNo=` + `pageIndex`) | **7** | 성동·동대문·성북·구로·금천·영등포·송파 |
| 서울 portal-bbs (`/portal/bbs/…/list.do` + `pageIndex` + `fileDown.do`) | **4~5** | 용산·광진·동작·중랑(Referer) (+종로는 egov `selectBoardList` 변형) |
| 서울 cbIdx (`ex/bbs/List.do?cbIdx=` + `View.do` + `Download.do`) | **2** | 양천·서초 |
| HTML 라인/표 (첨부 없음, 각각 개별) | **6** | 서울시청·은평·관악·서대문·기장(위 rfc3에 포함)·(부산시청은 첨부) |
| 단독 | **9** | 서울 중구·강북·도봉·노원·마포·강서·강남·강동(마포≈강동 uuid 다운로드) · 부산시청·영도·부산강서·연제 |

→ 계열 4벌로 **25개 기관**(부산 12 + 서울 13)이 덮인다. 서울은 목업 추정대로 8~10벌이 더 필요하다.

### 권장 착수 순서

1. **부산 rfc3 12곳** — 스크래퍼 한 벌로 도시의 70%. 부산진구 `menuCd`, 중구·수영구 제목 필터, 기장 HTML 표 파서만 예외.
2. **서울 HTML 4곳**(시청·은평·관악·서대문) — 파일 파서 없이 상반기 5만 건(목업 실측). 서대문은 POST 조건·EUC-KR·천원 단위 셋을 한 번에.
3. **서울 bbsNo 7곳 → portal-bbs 5곳 → cbIdx 2곳** — 한 벌씩 붙일 때마다 5~7곳.
4. **서울 단독 8곳** — 강남·마포·강동(상세 없음/uuid)부터, 강북(쿠키)·도봉(ASP)·노원(형식 혼합) 순.
5. **부산 단독 4곳** — 영도·연제(첨부 형식 미확인) → 부산시청·강서(DRM 손실 계수 필수).
6. **부산 사하구** — 사람이 브라우저로 새 게시판을 찾은 뒤. 못 찾으면 "수집 불가 기관" 표시 규칙(#1 미정 항목)으로.

### 다음 티켓이 알아야 할 것

- DRM은 부산시청만의 문제가 아니다(강서구도). 첨부 파서 앞에 `is_drm` 계수를 두고 손실을 따로 센다.
- 첨부 형식은 같은 게시판 안에서도 바뀐다(노원·서울중구). 확장자·아이콘이 아니라 바이트로 판정.
- 서울 상반기 규모는 목업 JSON 기준 **145,951건**(시청 31,289 포함). #1의 "대도시 데이터 분할" 미정 항목에 이 수치를 넘긴다.

## 재현

```bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
# 목록 1·2쪽 (예: 성동구)
curl -sSL -A "$UA" -o p1.html -w '%{http_code} %{size_download}\n' "https://www.sd.go.kr/main/selectBbsNttList.do?bbsNo=172&key=1330"
curl -sSL -A "$UA" -o p2.html -w '%{http_code} %{size_download}\n' "https://www.sd.go.kr/main/selectBbsNttList.do?bbsNo=172&key=1330&pageIndex=2"
md5sum p1.html p2.html      # 같으면 페이징 이름이 틀린 것
# 첨부 첫 32바이트 (Referer 유무 비교)
curl -sSL -A "$UA" -r 0-31 -o a.bin -H "Referer: <목록 URL>" "<첨부 URL>"; head -c 8 a.bin | od -c
# 강북구 봇 차단 통과
curl -sSL -A "$UA" -H "Cookie: sabFingerPrint=1920,1080,www.gangbuk.go.kr; sabSignature=<첫 응답의 값>" "https://www.gangbuk.go.kr/portal/intgty/deptJobPrtnCt/list.do?menuNo=200155"
# 서대문구 월별 목록 (POST, 검색 필드 동반 필수)
curl -sSL -A "$UA" --data "cp=1&searchGUBUN=&searchDept=&searchYear=2026&searchMonth=06" "https://www.sdm.go.kr/admininfo/budget/openmoney.do" | iconv -f cp949 -t utf-8 | grep -o '[0-9,]* 건'
```
