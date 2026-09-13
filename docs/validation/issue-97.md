# 광주 5개 자치구 게시판 실측 (#97)

2026-09-13 실측. 도구는 `curl`과 프로젝트 UA(`OfficialDeliciousMap/0.1`)이며 브라우저로
위장하지 않았다. 이 문서는 `registry/gwangju.py`와 자치구 스크래퍼 셋이 따르는 근거다.

## 기관과 게시판

| 기관 slug | 기관이 밝힌 이름 | 게시판 | 스크래퍼 |
| --- | --- | --- | --- |
| `gwangju-gwangsan` | 광산구청 | `expenses` | `GwangsanInfoOpenBoard` |
| `gwangju-seo` | 전남광주통합특별시 서구청 #착한도시 서구 | `expenses-head`·`-director`·`-council`·`-department` | `SeoguExpenseBoard` |
| `gwangju-buk` | 전남광주통합특별시 북구 | `expenses` | `GwangjuDistrictBoard` |
| `gwangju-nam` | 전남광주통합특별시 남구 | `expenses` | `GwangjuDistrictBoard` |
| `gwangju-dong` | 전남광주통합특별시 동구 | `expenses-head`·`-director`·`-department` | `GwangjuDistrictBoard` |

이름은 저마다 `<title>`·`og:site_name`·푸터가 밝힌 표기를 그대로 옮겼다. 광산구만 통합 전
`광산구청`을 쓰고 나머지 넷은 통합 뒤 `전남광주통합특별시 <구>`를 쓴다. 시청과 같은 규칙이다.

## 게시판 계열이 셋으로 갈린다

시청의 `GwangjuCityBoard`(`boardList.do`/`boardView.do`/`fileDownload.do`)를 그대로 쓸 수 있는
구가 하나도 없다.

### 1. `.es` 게시판 — 북구·남구·동구

- 목록 `board.es?mid=<메뉴>&bid=<게시판>&nPage=<쪽>`, 본문 `...&act=view&list_no=<번호>`
- 전체 쪽 수는 `<p class="page_info">… 현재 페이지 N/<span>P</span></p>`에만 있다.
- 게시일은 `YYYY/MM/DD`다. 시청의 `YYYY-MM-DD`와 다르다.
- 줄은 북구·동구가 `<ul><li>`, 남구가 `<tr><td>`로 갈리지만 칸 차례는 셋 다
  번호·제목·부서·게시일·첨부·조회수로 같다. 그래서 스크래퍼는 요소 이름이 아니라 칸 차례로 읽고,
  제목 칸은 게시글 링크가 들어 있는 칸으로 가린다.
- 첨부가 달린 줄은 `<img alt="… 첨부파일">`로 알린다. 동구는 확장자 없이 `" 첨부파일"`만 준다.
- 첨부 주소가 구마다 다르다. 북구 `boardDownload.es?bid=&list_no=&seq=`,
  남구·동구 `download.es?filename=&f_path=board&bid=&type=board&bid=&list_no=&seq=`
  (`bid`가 두 번 실리는 것은 실측 그대로다).
- 첨부 형식이 놓인 자리도 다르다. 북구는 링크의 `title`에만, 남구·동구는 링크 글자와
  `filename`에 함께 있다. 스크래퍼는 셋을 차례로 보고 첫 번째로 읽히는 확장자를 쓴다.
- 동구는 같은 업무추진비를 직급별 게시판 넷으로 나눈다. `bid=0160`("2020년 이전자료")은 이름과
  달리 민원조정위원회 회의록 같은 글이 실려 있고 업무추진비 게시글이 없어 선언하지 않았다.

### 2. `openInfoCostList.es` 전용 화면 — 서구

- 게시글 본문이 없다. 목록 한 줄이 곧바로 `openInfoDataFileDownload.es?oid_seq=&file_seq=`다.
- 쪽 넘김이 없어 한 응답에 그 게시판 전부가 실린다. 부서장 탭이 약 16.8MB로,
  `boards.MAX_RESPONSE_BYTES`(20MB) 안이지만 여유가 크지 않다.
- 첨부 이름·형식을 목록에도 링크에도 밝히지 않는다. 그래서 이 게시판의 `published_suffixes`는
  `frozenset({""})`이고, 무엇을 받았는지는 `boards.container_of`의 매직 바이트만 정한다.
- 게시일은 `YYYY-MM-DD`이고 작성 부서는 밝히지 않는다.
- 의원 탭(`oi_seq=401`)은 2023-08-29가 마지막이라 2026년 게시글이 없다. 게시판은 살아 있으므로
  그대로 선언했다.

### 3. SiiRU 사전정보공표 — 광산구

- 게시판 HTML을 주지 않는다. 진입 화면 `contentsView.do?pageId=www159`가 세션 쿠키와
  1회용 토큰을 `<meta name="csrf" content="…">`로 내준다.
- 목록·본문은 그 토큰을 `X-CSRF-TOKEN` 머리에 실은
  `POST getInfoOpenList.do`·`POST getInfoOpenData.do`가 JSON으로 답한다. 토큰 없이 부르면 403이다.
- 목록 요청은 `infoOpenSn=292`·`recordCnt`·`movePage` 말고도
  `infoOpen=D`·`infoOpenCtgryUpper=O130000`·`infoOpenType=S`·`infoOpenCtgryTy=S`를 함께 실어야
  답이 채워진다. 빼면 빈 목록이 온다.
- 목록은 `dataMap.list`에 `detailSn`·`detailNm`·`deptNm`·`regDt`를, 전체 쪽 수는
  `dataMap.pageCnt`를, 본문은 `dataMap.fileList`에 `fileSn`·`fileExtsn`·`fileUrl`을 담는다.
- 첨부 주소의 `fileSe`가 시청의 `BB`가 아니라 `IO`다.

이 게시판 때문에 요청 경계에 쿠키를 이어 드는 자리를 더했다(`HttpTransport(session=True)`).
여는 방법은 그대로 `urllib.request.urlopen`이고 쿠키만 직접 싣는다. 보내는 자리가 하나여야
재시도·상한·간격이 요청 모양에 따라 갈리지 않는다.

## robots.txt

프로젝트 UA로 실측했다.

| 기관 | robots.txt | 우리가 쓰는 경로 |
| --- | --- | --- |
| 광산구 | `Disallow: /siiru/`, `/search/` | 허용 (`/getInfoOpenList.do`·`/fileDownload.do`는 해당 없음) |
| 서구 | `Disallow: /board*`, `/gallery*`, `/findeepSearch*` | 허용 (`/openInfoCostList.es`는 해당 없음) |
| 북구 | `Disallow:/` (전체) | **차단** |
| 남구 | `Disallow: /` + `Allow: /index.es?sid=a1` | **차단** |
| 동구 | `Disallow : /` + `Allow : /index.es?sid=a1` | **차단** |

시청(`www.gwangju.go.kr`)은 `User-agent: Googlebot`에만 `Disallow: /`가 있고 `*` 규칙이 없어
현재 수집이 robots와 충돌하지 않는다.

**북구·남구·동구는 robots.txt가 전체 경로를 막는다.** 2026-09-13 사용자 결정으로 이 셋도
`Organization`으로 선언해 수집한다. 되돌릴 때는 `hold_reason="bot_blocked"`를 달면 되며,
`CONTEXT.md`의 수집 보류 사유 "봇 차단"이 그 상태다. 이 결정은 코드가 아니라 여기에만 있다.

부수 실측: 북구는 User-Agent가 아예 없는 요청을 WAF가 400(`Request Blocked`)으로 막는다.
프로젝트 UA로는 200을 준다. 브라우저 위장은 필요 없고 `boards.USER_AGENT` 정책을 그대로 둔다.

## 2026년 게시글 전량 수집 실측

게시일 2026-01-01 이상만 받아 매직 바이트까지 대조했다. 원본은 저장소 밖
`deliciousmap-raw/gwangju/<기관>/<게시판>/`에 두었다(ADR-0001).

| 구 | 게시글 | 첨부 | 확장자 | 게시일 범위 |
| --- | --- | --- | --- | --- |
| 광산구 | 182 | 190 | xlsx 180, pdf 8, xls 2 | 2026-01-01 ~ 08-29 |
| 북구 | 147 | 147 | xlsx 120, pdf 14, xls 13 | 2026-01-02 ~ 08-11 |
| 동구 | 144 | 144 | xlsx 142, pdf 2 | 2026-01-01 ~ 08-26 |
| 서구 | 117 | 117 | xlsx 108, xls 9 | 2026-01-02 ~ 07-28 |
| 남구 | 88 | 91 | xlsx 82, hwpx 6, pdf 3 | 2026-01-02 ~ 07-31 |
| 합계 | 678 | 689 | | |

매직 바이트 불일치 0건, 0바이트·HTML 에러 응답 0건, 다운로드 실패 0건.
게시판 전체 규모는 광산구 1,612건(2016~), 북구 1,145건(2009~), 서구 1,241건(2015~),
남구 1,119건(2012~), 동구 약 1,070건이다.

## 등록 뒤 실제 게시판으로 한 확인

`boards.default_transport()`와 레지스트리 선언 그대로, 기관마다 첫 3건을 훑었다.
다섯 기관 모두 게시글 번호·게시일·부서·제목·첨부 이름을 실제 값으로 냈다. 남구
`list_no=1169`는 첨부가 둘(`1169-1.xlsx`·`1169-2.xlsx`), `1168`은 `.hwpx`였고,
동구 `47722`는 첨부 번호가 1이 아니라 2로 시작했다. 서구는 첨부 이름이 없어 `4631-1`처럼
확장자 없는 이름이 나왔다.

## 남은 제한

- 이번 실측은 2026년 게시글에 한정했다. 전량 수집에서는 다른 확장자·구조가 나올 수 있고,
  그때는 미실측 형식으로 걸려 알려진다.
- 서구 부서장 탭 응답이 게시글이 쌓이면 `MAX_RESPONSE_BYTES`(20MB)를 넘을 수 있다. 넘으면
  잘라 쓰지 않고 받지 못한 것으로 알린다.
- 광산구 토큰의 유효 기간과 재발급 조건은 측정하지 않았다. 스크래퍼는 요청이 한 번 실패하면
  토큰을 버리고 진입 화면부터 한 번만 다시 한다.
- `.pdf` 27건과 `.hwpx` 6건을 parse 단계가 다루는지는 이 범위에서 확인하지 않았다.
- 동구 `bid=0160`에 2020년 이전 업무추진비가 실제로 어디 있는지는 찾지 못했다.
