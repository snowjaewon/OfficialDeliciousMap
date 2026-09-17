# 서울 원본의 헤더 서명 캐시 적중률 (#214)

[#214](https://github.com/snowjaewon/OfficialDeliciousMap/issues/214)가 요구한 측정을
2026-09-17에 했다. `origin/develop` `54e7cdf` 기준이고, 모델 키를 설정하지 않아 **LLM 호출은
0회**다. `.env`를 읽지 않았고 `GEMINI_API_KEY`는 실행 내내 설정하지 않았다.

## 1. 결론

**에이전트 CLI가 새로 판정해야 할 표는 17,000개다.** 이슈가 갈랐던 "수백 건인지 1만 건인지"의
답은 1만 건 쪽이며, 1만보다도 1.7배 많다.

| 값 | 수 | 단위 |
| --- | --- | --- |
| 헤더 매핑이 연 표 | 17,493 | 표 |
| ├ 캐시 적중(판정 재사용) | 493 (2.8%) | 표 |
| ├ 캐시 적중했으나 검증 실패 | 34 (0.2%) | 표 |
| └ 캐시 미적중 | 16,966 (97.0%) | 표 |
| **신규 판정 필요** | **17,000** | **표** |

검증에 실패한 34표는 서명은 맞았으나 `extract()`가 후보를 못 냈다. 이 원본에서는 쓰지 않으므로
신규 판정 필요에 넣는다(`src/deliciousmap/headermap.py:196-206`).

### API 경로로는 감당하지 못한다

표당 API 단가는 USD 0.001792(`data/_shared/llm-budget.jsonl`의 `header_mapping` settlement
6.03364275 ÷ 3,367건)이고, 한도 15 중 잔여는 6.39318075다.

| 항목 | 값 |
| --- | --- |
| 17,000표를 API로 전량 판정 | USD 30.46 |
| 잔여 예산이 감당하는 표 | 3,567표 (전체의 21.0%) |
| 초과 배수 | 잔여 예산의 4.77배 |

그러므로 [폴백 정책](../specs/header-mapping-fallback.md)의 `### 헤더 매핑 판정 경로`대로
에이전트 CLI 경로로 판정한다. API 직접 호출은 CLI로 처리할 수 없는 건에만 쓴다.

## 2. 실행

```bash
# Git Bash, 저장소 루트
ls data/seoul/orgs | xargs -P 10 -I {} \
  uv run python -m deliciousmap headermap --city seoul --org {}
```

기관 25곳 모두 종료 코드 0이다. `--org`가 있으므로 산출물은
`data/seoul/orgs/<org>/headermap.json`으로 갈라졌고 도시 단위 `data/seoul/headermap.json`은
만들지 않았다.

실제 실행에는 위 명령에 표 단위 관찰만 덧붙인 스크립트를 썼다. `headermap.json`의 `unresolved`는
원본 단위라 표 단위 수를 담지 못하기 때문이다(3절). 관찰은 `_map_table()`의 결과를 세기만 하고
판정·저장 경로를 바꾸지 않았다.

- 소요: 전체 약 15분. 가장 큰 `seoul-city`(원본 2,488개)가 단독으로 886.9초를 썼고 나머지
  24곳은 그 안에 끝났다.
- `--raw-root`는 기본값 `../deliciousmap-raw`
  (`C:\Users\pc\orca\workspaces\OfficialDeliciousMap\deliciousmap-raw`)이고, 대상 원본
  **11,600개가 모두 있었다**(없는 파일 0개). 경로가 없어 못 읽은 원본은 없다.

### LLM 호출 0건 확인

`data/_shared`의 두 파일을 실행 전후로 대조했다. 줄 수·SHA-256·누적액이 모두 같다.

| 파일 | 실행 전후 줄 수 | SHA-256 |
| --- | --- | --- |
| `data/_shared/llm-budget.jsonl` | 7,556 (동일) | `483177bdd57c8e28…` (동일) |
| `data/_shared/headermap.jsonl` | 938 (동일) | `9a6a17abb0c53b22…` (동일) |

누적 settlement 합계도 USD 8.60681925로 실행 전후가 같다. `_map_table()`이 `_ask()` 이전에
`Unresolved("model_not_configured")`를 던지므로 예산 장부에 예약조차 들어가지 않는다
(`headermap.py:219-225`).

`data/seoul/headermap-answers-v1.jsonl`은 이 실행에서도 만들어지지 않았다. `_remember()`가
공통 캐시에 줄을 더하는 경로(`_accept`)는 answers 이력이 있어야 타므로, 25개 프로세스가 전부
읽기만 했다. 병렬 실행이 안전했던 근거는 이슈 본문의 표 그대로다.

## 3. 이슈 본문의 전제 두 가지가 실측과 달랐다

### 3.1 헤더 매핑이 여는 원본은 15,265개가 아니라 11,600개다

`headermap` 단계는 `fetch.json`의 전체 원본이 아니라 `reporting_sources()`가 대상 기간
(2026년 상반기)으로 자른 것만 연다(`src/deliciousmap/storage.py:771-781`).

| 구분 | 수 | 단위 |
| --- | --- | --- |
| `fetch.json`의 고유 원본 | 15,265 | 원본(`source_hash`) |
| `reporting_sources()`가 고른 원본 | 11,600 | 원본(`source_hash`) |
| 대상 기간 밖이라 열지 않은 원본 | 3,665 | 원본(`source_hash`) |

이슈의 15,265는 `fetch.json` 쪽 수로는 맞다. 두 수는 단위가 같고 고르는 기준이 다르다.

이슈의 컨테이너 표(pdf 9,051 · html 3,543 · ooxml 1,940 · ole2 704)는 합이 15,238로 15,265와
27 차이가 난다. 빠진 27개는 zip 2 · jpeg 22 · png 3이다.

### 3.2 `unresolved`는 표 수가 아니라 원본 수다

`resolve()`는 원본마다 **첫 실패 하나만** `UnresolvedSource`로 싣는다
(`headermap.py:122-130`). 표 세 개가 모두 미적중인 원본도 `unresolved` 한 줄이다. 그래서
`headermap.json`만으로는 신규 판정 필요 표 수를 셀 수 없고, 1절의 17,000은 표마다 센 값이다.

25개 산출물을 합친 값은 이렇다.

| 산출물의 항목 | 값 | 단위 |
| --- | --- | --- |
| `mappings` | 386 | 표 |
| `unresolved` | 11,228 | 원본 |
| `unresolved_mappings` | 141 | 표 |

`mappings` 386은 **표가 전부 판정된 원본의 표**뿐이다. 캐시에 적중했어도 같은 원본의 다른 표가
미적중이면 그 판정은 `unresolved_mappings`로 간다. 적중 493표 중 386표만 `mappings`에 남은
이유다(386 + 107 = 493, 나머지 34는 검증 실패분이라 `unresolved_mappings` 141을 채운다).

## 4. 기관별 신규 판정 필요 표 수

| 기관 | 연 표 | 적중 | 적중률 | **신규 판정 필요** | 미해결 원본 |
| --- | ---: | ---: | ---: | ---: | ---: |
| seoul-city | 7,381 | 0 | 0.0% | 7,381 | 2,488 |
| seoul-guro | 1,044 | 94 | 9.0% | 950 | 381 |
| seoul-seongdong | 889 | 29 | 3.3% | 860 | 338 |
| seoul-seocho | 666 | 0 | 0.0% | 666 | 470 |
| seoul-gangnam | 620 | 25 | 4.0% | 595 | 497 |
| seoul-jongno | 601 | 0 | 0.0% | 601 | 476 |
| seoul-songpa | 477 | 146 | 30.6% | 331 | 302 |
| seoul-gangseo | 463 | 7 | 1.5% | 456 | 461 |
| seoul-gangdong | 454 | 0 | 0.0% | 454 | 411 |
| seoul-nowon | 451 | 0 | 0.0% | 451 | 423 |
| seoul-geumcheon | 451 | 0 | 0.0% | 451 | 333 |
| seoul-jungnang | 428 | 0 | 0.0% | 428 | 380 |
| seoul-yongsan | 413 | 18 | 4.4% | 395 | 322 |
| seoul-dongjak | 390 | 0 | 0.0% | 390 | 367 |
| seoul-seongbuk | 367 | 1 | 0.3% | 366 | 354 |
| seoul-yeongdeungpo | 366 | 12 | 3.3% | 354 | 339 |
| seoul-dongdaemun | 355 | 82 | 23.1% | 273 | 275 |
| seoul-mapo | 348 | 0 | 0.0% | 348 | 355 |
| seoul-jung | 335 | 0 | 0.0% | 335 | 302 |
| seoul-yangcheon | 331 | 29 | 8.8% | 302 | 318 |
| seoul-gwangjin | 326 | 35 | 10.7% | 291 | 283 |
| seoul-dobong | 322 | 15 | 4.7% | 307 | 298 |
| seoul-eunpyeong | 9 | 0 | 0.0% | 9 | 9 |
| seoul-gwanak | 6 | 0 | 0.0% | 6 | 6 |
| seoul-seodaemun | 0 | 0 | — | 0 | 1,040 |
| **합계** | **17,493** | **493** | **2.8%** | **17,000** | **11,228** |

`seoul-city` 한 곳이 신규 판정 필요의 43.4%(7,381 / 17,000)를 차지한다. `seoul-seodaemun`은
표를 하나도 열지 못했다(5.2절).

## 5. 컨테이너별 적중률

### 5.1 표를 연 원본

| 컨테이너 | 원본 | 표 | 원본당 표 | 적중 | 검증 실패 | 미적중 | **적중률** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pdf | 5,945 | 8,278 | 1.39 | 387 | 27 | 7,864 | **4.7%** |
| html | 2,503 | 7,396 | 2.95 | 0 | 0 | 7,396 | **0.0%** |
| ooxml | 1,337 | 1,545 | 1.16 | 100 | 7 | 1,438 | **6.5%** |
| ole2 | 239 | 274 | 1.15 | 6 | 0 | 268 | **2.2%** |
| 합계 | 10,024 | 17,493 | 1.75 | 493 | 34 | 16,966 | **2.8%** |

공통 캐시 938줄은 광주 428 · 부산 385 · 대전 125줄이고(각 줄의 `evidence`가 인용한 원본
해시를 도시별 `fetch.json`과 대조해 셌다. 울산은 0줄로, 다른 도시의 캐시만 재사용했다),
판정 주체는 `gemini-3.6-flash` 798 · `claude-opus-5` 139 · `human` 1이다. 서울 표에는 거의
걸리지 않는다.

html 적중률 0.0%는 표가 많아서만은 아니다. html 원본 하나가 표 2.95개를 내는데, 게시판 쪽에는
집행내역 표 말고도 목록·안내 표가 함께 들어 있다. [ADR-0008](../adr/0008-declare-html-table-mappings.md)이
그 경우에 쓰라고 만든 게시판별 선언(`DeclaredTable`)은 **서울 레지스트리에 0건**이다
(`src/deliciousmap/registry/seoul.py`). 선언을 더하면 판정 대상 표가 줄어드는데, 얼마나 줄지는
이 이슈가 재지 않았다(미적중 표의 서식 분류는 제외 범위다).

### 5.2 표를 하나도 열지 못한 원본 1,576개

| 컨테이너 | 사유 | 원본 |
| --- | --- | ---: |
| html | `unreadable` | 1,040 |
| ole2 | `unsupported_format` | 273 |
| pdf | `no_table` | 239 |
| jpeg | `unsupported_format` | 15 |
| ooxml | `unreadable` | 6 |
| png | `unsupported_format` | 3 |
| 합계 | | **1,576** |

11,600 − 10,024 = 1,576이고, 미해결 원본 11,228의 14.0%다.

**`seoul-seodaemun`의 1,040개가 한 사유로 전부 걸렸다.** 이 게시판의 html 쪽은 EUC-KR인데
(`<meta charset=euc-kr>`, 실측) `grid.HTML_ENCODING`이 `"utf-8"`로 고정돼 있어
`_html()`이 `UnicodeDecodeError`를 `UnreadableOriginal`로 바꾼다
(`src/deliciousmap/grid.py:71`과 `grid.py:655-658`). 인코딩 문제이므로 판정 건수가 아니라 읽기 코드의 문제다. 고치면 표가 새로 열리고
신규 판정 필요 표 수도 그만큼 늘어난다. 이 이슈의 17,000은 **고치기 전 기준**이다.

## 6. 산출물을 커밋하지 않기로 했다 (2026-09-17 사용자 결정)

`data/seoul/orgs/<org>/headermap.json` 25개(합계 1.8MB, 최대 346KB)는 커밋하지 않는다.

- 판정이 17,493표 중 386표(2.2%)뿐인 부분 상태다. [#143](https://github.com/snowjaewon/OfficialDeliciousMap/issues/143)이
  25개 파일을 전량 다시 쓰므로 리베이스마다 충돌만 남긴다.
- 재측정 비용이 15분으로 작다.
- [ADR-0001](../adr/0001-commit-refined-artifacts.md)의 커밋 방침과, 부산·대전·광주·울산이 같은
  자리에 커밋한 `headermap.json` 35개(도시 단위 파일 포함, `git ls-files '*headermap.json'`)의
  선례를 알고도 이번만 따르지 않는 것이다. 20MB 상한에는 걸리지 않는다.

이 문서의 수치가 측정 결과로 남는 것이고, 산출물 파일은 남기지 않는다.

## 7. #143에 넘기는 값

- 신규 판정 필요: **17,000표** / 미해결 원본 11,228개. `seoul-city`가 표의 43.4%다.
- 판정 경로: 에이전트 CLI. API 전량은 USD 30.46으로 잔여 예산 6.39의 4.77배다.
- 착수 전에 정리할 것 둘. 어느 쪽도 이 이슈의 범위가 아니다.
  1. `seoul-seodaemun` html 1,040개의 EUC-KR 읽기(5.2절). 서울 미해결 원본의 9.3%다.
  2. 서울 html 게시판의 `DeclaredTable` 선언(5.1절). html 표 7,396개의 판정 대상을 줄인다.
