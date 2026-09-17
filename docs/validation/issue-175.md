# 대전 기관 원본을 parse부터 build까지 흘린다 (#175)

2026-09-17, Windows 11 · Git Bash · Python 3.12.10.
범위: [feat(pipeline): 대전 기관 원본을 parse부터 build까지 흘려 지도에 반영한다 #175](https://github.com/snowjaewon/OfficialDeliciousMap/issues/175).
입력은 [#172](issue-172.md)가 받은 원본(`--raw-root C:\Users\설재원\deliciousmap-raw`)이다. 수집 보류인
대전광역시(`bot_blocked`)는 원본이 없어 이 이슈의 대상이 아니다. 정규 기관은 동구·중구·서구·유성구·대덕구 5곳이다.

## 1. 결과

단위는 **원본**(수집 장부의 파일), **레코드**(`records.csv` 행), **마커**(`build.json`의 `marker_count`, 업소 수)다.

| 대상 | 대상 원본 | 매핑 원본 | 미해결 원본 | 레코드 | 식당 | 비식당 | 보류 | 마커 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 대전(도시) | 917 | 830 | 87 | 4,664 | 3,635 | 533 | 496 | **1,357** |
| 동구 | 114 | 109 | 5 | 1,253 | 946 | 136 | 171 | 378 |
| 중구 | 384 | 366 | 18 | 1,505 | 1,199 | 140 | 166 | 412 |
| 서구 | 212 | 160 | 52 | 796 | 570 | 160 | 66 | 297 |
| 유성구 | 5 | 3 | 2 | 30 | 8 | 17 | 5 | 5 |
| 대덕구 | 202 | 192 | 10 | 1,080 | 912 | 80 | 88 | 355 |

출처: `data/daejeon/{parse,headermap,classify,build}.json`·`records.csv`와 같은 파일의 `orgs/<slug>/` 판.
대상 원본은 `parse.json`의 `sources`, 매핑 원본은 `headermap.json` `mappings`의 서로 다른 `source_hash`,
미해결 원본은 `unresolved`의 건수다. 기관 레코드 합(4,664)과 판정은 도시와 레코드 id·판정까지 같다.

대상에서 뺀 원본은 `parse.json` `excluded_sources`에 있다: 제목이 밝힌 기간이 상반기 밖 493건, 제목이
기간을 밝히지 않은 2026년 게시글 2건(`undeclared_in_year`), 게시일이 대상 연도 밖 0건. 수집 장부 항목 1,417건은
대상 922건 + 제외 495건이고, 대상 922건은 같은 원본이 여러 게시글에 붙은 5건을 빼면 고유 원본 917건이다
(`period.targets`·`period.exclusion`으로 도시 `fetch.json` 항목을 센 값).

`check-data`는 `gwangju`·`daejeon`·`ulsan`을 내고 종료 코드 0이다. 가장 큰 파일은
`data/daejeon/geocode-history-v2.jsonl` 19,998,486바이트, `geocode.json` 19,956,969바이트로 ADR-0001의
20MB 안이며 넘는 몫은 `.002` 조각에 있다. `data/daejeon`은 149MB다(`du -sh`).

### 좌표 판정 — 레코드 3,635건

`data/daejeon/geocode.json` + `geocode.002.json`의 `reason`:

| reason | 레코드 |
| --- | --- |
| `matched` | 2,847 |
| `merged_merchant` | 363 |
| `no_candidates` | 222 |
| `insufficient_evidence` | 203 |
| `lookup_error` | 0 |

첫 실행은 `lookup_error` 38건으로 `lookup-failed`로 끝났고, `--retry-failed` 한 번에 0건이 됐다. 중구 기관
geocode도 업종 조회 실패로 한 번 `lookup-failed`였고 `--retry-failed`로 풀렸다. `merged_merchant` 363건(합쳐
적은 상호)은 사람 판정 몫이라 이 이슈에서 다루지 않았다(#128 계열).

`closure.json`은 1,357곳 모두 `unknown`이다. 인허가 원본 폴더(`<raw-root>/licenses`)가 이 PC에 없고, 광주
2,266곳·울산 773곳도 모두 `unknown`이라 대전만의 결손이 아니다.

### 광주·울산과 다른 이유

| 도시 | 레코드 | 마커 | 마커/레코드 |
| --- | --- | --- | --- |
| 광주 | 10,335 | 2,266 | 22% |
| 울산 | 3,554 | 773 | 22% |
| 대전 | 4,664 | 1,357 | 29% |

출처: 각 `data/<city>/build.json`의 `record_count`·`marker_count`(이슈 본문의 광주 9,825·2,096은 그 뒤 #128·#169
재실행 전 값이다).

- **시청이 빠졌다.** 대전은 가장 큰 발행 기관인 시청이 robots로 보류라, 레코드가 모두 자치구 것이다. 광주·울산은
  시청 레코드가 가장 많고, 시청 간담회는 청사 주변 몇 곳에 몰린다.
- **자치구 부서·동 단위 공개가 많다.** 중구 부서별·소속기관장, 대덕구 부서장, 서구 부서별 게시판이 동 주민센터
  단위 지출까지 싣는다. 지출이 구 전역으로 흩어져 레코드당 업소가 많다.
- **유성구는 레코드가 30건이다.** 구청장 게시판 하나뿐이고(#172), 대상 원본 5건 중 2건이 미해결이다.

## 2. 실행 전에 확인한 것

- **규모.** 대상 원본 917건, 수집한 고유 원본 1,410건의 표 2,016개(`grid.read_tables`로 센 수), 레코드 4,517건
  (첫 parse)으로 울산과 광주 사이다.
  20MB 분할 규칙 안에서 끝날 규모라 멈추지 않았다.
- **LLM 비용.** 헤더 매핑은 표의 헤더 서명이 106종이라 1회 약 USD 0.0014로 USD 1 안팎(최악 약 2.8)으로 봤다.
  비식당 판별은 캐시 미스 상호 2,575개 × USD 0.000185 ≈ USD 0.48로 봤다(키는 `classify.normalized`).
  시작 누적은 USD 1.28190825다(`Budget(...).committed()`).
- **형식.** 대상 원본의 컨테이너는 ooxml·zip·pdf·ole2이고 모두 현재 추출 경로가 있다(#195가 ZIP을 연다). 미지원
  형식은 0건이다.
- **모델 키.** `.env`를 읽어 GEMINI·NAVER·DATA_GO_KR 키가 모두 있음을 확인하고 headermap·classify를 돌렸다.
  geocode·closure·build는 GEMINI를 빼고 돌렸다.

## 3. 울산에서 되풀이하지 않은 것

- `data/daejeon/classify.json`에 `unclassified: model_not_configured`는 **0건**이다. 보류 496건은 모두 모델이
  스스로 보류로 답한 것이다(`gemini-3.6-flash/classify-1` 475건, 이전 `claude-opus-5/claude-read-1` 21건).
- `City.address_prefixes = ("대전광역시",)`와 5개 자치구 `Hall`을 선언했다(`src/deliciousmap/registry/daejeon.py`).
  이번 조회 캐시에서 `대전`으로 시작하는 후보 주소는 인허가 3,434건·지역검색 1,967건이고 모두 첫 어절이
  `대전광역시`다.

청사 좌표는 2026-09-17 네이버 지역검색에 기관 이름을 질의해 받은 첫 후보다. 응답 도로명주소가 각 구 누리집
푸터의 소재지와 같은 것을 확인했다. 시청은 레코드가 없고 푸터가 있는 `/`를 robots가 막아 적지 않았다.

| 기관 | 질의 | 응답 주소 | 좌표 |
| --- | --- | --- | --- |
| daejeon-dong | `대전광역시 동구청` | 대전광역시 동구 동구청로 147 | 36.312169, 127.454884 |
| daejeon-jung | `대전광역시 중구청` | 대전광역시 중구 중앙로 100 | 36.3256593, 127.4215464 |
| daejeon-seo | `대전광역시 서구청` | 대전광역시 서구 둔산서로 100 | 36.355504, 127.383844 |
| daejeon-yuseong | `대전광역시 유성구청` | 대전광역시 유성구 대학로 211 | 36.3623219, 127.3562683 |
| daejeon-daedeok | `대전광역시 대덕구청` | 대전광역시 대덕구 대전로1033번길 20 | 36.346735, 127.415502 |

## 4. 실행 중에 고친 코드

| 커밋 | 문제 | 고친 뒤 |
| --- | --- | --- |
| `fix(extract)` 배운 데이터 시작 위치 | 서구 원본의 헤더만 있는 시트(3행)에 다른 표에서 배운 매핑(데이터 5행부터)을 검증하다 `IndexError`로 headermap 전체가 멈췄다 | 표 안의 행만 본다. 그 시트는 지출 0건으로 읽힌다 |
| `feat(extract)` 연도 없는 집행일 | 유성구 PDF는 표에 제목 행이 없어 모델이 `year_hint`를 못 냈고, `6월 5일` 표기가 모두 `spent_on` 실패였다 | 매핑에 연도가 없으면 게시글 제목이 한 해의 기간을 밝힐 때만 그 해를 쓴다(2026-09-17 사용자 결정) |
| `fix(headermap)` 기관 답 이력 | 답 이력(`headermap-answers-v1.jsonl`)이 기관 폴더에 따로 있어 기관 실행이 도시가 이미 물은 표를 115번 다시 물었다. 답이 갈려 중구 기관 레코드 3건이 도시에 없었고 기관 geocode가 거부할 상태였다 | 기관 실행도 도시의 답 이력을 읽고 쓴다(2026-09-17 사용자 결정). 재실행에서 새 호출 0건, 기관·도시 레코드 일치 |

두 번째 고침으로 미해결 원본이 100건에서 87건으로 줄었다(유성구 4건 포함).

## 5. 남긴 것 — 미해결 원본 87건

`data/daejeon/headermap.json` `unresolved`의 사유는 모두 `validation_failed`다. 상세(`detail`)별 원본 수:

| 상세 | 원본 |
| --- | --- |
| total amount mismatch | 32 |
| missing data start or amount unit | 22 |
| spent_on | 20 |
| merchant | 5 |
| amount_krw | 4 |
| missing required roles | 4 |

기관별로는 서구 52 · 중구 18 · 대덕구 10 · 동구 5 · 유성구 2다. 서구 `total amount mismatch`를 열어 보니
`계` 행이 첫 지출 한 건의 금액만 적고 있다(예: `계 140,000` 아래 140,000·120,000 두 건). 원본 결함이라 고쳐
읽지 않았다(폴백 정책). 판별 보류 496건, 좌표를 못 정한 레코드(`no_candidates` 222 · `insufficient_evidence`
203 · `merged_merchant` 363)도 산출물에 그대로 있다.

## 6. LLM 비용

`Budget(Path("data/_shared/llm-budget.jsonl")).committed()`로 단계마다 쟀다.

| 시점 | 누적 USD |
| --- | --- |
| 시작 | 1.28190825 |
| 도시 headermap 뒤 | 1.62317250 |
| 도시 classify 뒤(재parse 뒤 추가분 포함) | 2.06533725 |
| 기관 headermap 버그 호출 115건 뒤 | **2.17668525** |

이번 이슈의 사용액은 USD 0.89477700이고, 한도 15 안이다. 버그로 쓴 약 USD 0.11도 장부에서 지우지 않았다.

## 7. 도시 페이지

`build --output-root <임시 폴더>` 뒤 `python -m deliciousmap.ci check-dist --dist <임시 폴더> --commit test
--city daejeon`이 `sealed 12 files`로 통과했다. 그 폴더를 `http.server`로 띄워 헤드리스 Edge로
`/daejeon/`을 캡처했고, 지도(마커)와 오른쪽 목록(`1,357곳 전체`, 1위 숨결커피 25회)이 함께 떴다. 임시 출력
build가 바꾼 `data/daejeon/build.json`은 되돌렸다.

## 8. 명령

Git Bash, 저장소 루트. `run.py`는 `.env`를 읽고(`1`이면 GEMINI 포함, `0`이면 제외) 아래 인자로 `cli.main`을
부르는 작은 실행기다. 도시 `fetch.json`은 5개 기관의 `fetch.json`을 레지스트리 순서로 이어 붙여 만들었다
(원본 1,417 · 누락 0 · 받지 않은 게시글 11,702 · 걸러 낸 게시글 78, #172 기록과 같다).

```text
run.py 1 headermap --city daejeon --raw-root <raw>
run.py 0 parse --city daejeon --raw-root <raw>
run.py 1 classify --city daejeon --raw-root <raw>
run.py 0 geocode --city daejeon --raw-root <raw>            # 2시간 7분, lookup-failed
run.py 0 geocode --city daejeon --raw-root <raw> --retry-failed
run.py 0 closure --city daejeon --raw-root <raw>
run.py 0 build --city daejeon --raw-root <raw>
# 기관마다(동구·중구·서구·유성구·대덕구)
run.py 1 headermap|parse|classify --city daejeon --org <slug> --raw-root <raw>
run.py 0 geocode|closure|build --city daejeon --org <slug> --raw-root <raw>
uv run python -m deliciousmap.ci check-data --data-root data
```

## 9. 남은 제한

- 광주 5개 기관 폴더의 `headermap-answers-v1.jsonl`은 이제 읽히지 않는다. 지우지 않고 두었다.
- 연도 폴백과 데이터 시작 고침은 광주·울산 산출물을 다시 내지 않았다. 다음 재실행에서 전에 미해결이던
  원본 일부가 매핑될 수 있다.
- 폐업 확인은 인허가 원본이 없어 모두 `unknown`이다.
- 대전광역시는 수집 보류이고, 유성구는 부서 단위 공개가 없다(#172).
