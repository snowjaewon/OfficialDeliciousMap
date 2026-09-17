# 판정이 없던 울산 원본 509개를 판정한다 (#229)

2026-09-18, Windows 11 · Git Bash · Python 3.12.10.
범위: [feat(ulsan): 판정이 없는 원본 509개를 판정해 울산 절반을 지도에 올린다 #229](https://github.com/snowjaewon/OfficialDeliciousMap/issues/229).
입력은 이미 받아 둔 원본이다(`--raw-root` = `C:\Users\설재원\deliciousmap-raw`).
기관은 시청·중구·남구·동구·북구·울주군 6곳이다.

## 0. 이번 실행이 따른 결정

1. **헤더 매핑은 에이전트 CLI가 판정했다.** [폴백 정책](../specs/header-mapping-fallback.md)의
   `### 헤더 매핑 판정 경로`를 따랐고, 모델 API 헤더 매핑 호출은 0회다(3절).
2. **비식당 판별은 Gemini API로 했다.** 판정 경로 결정은 헤더 매핑만 다룬다.
3. **미해결은 사유별 건수로 남긴다.** 원본 결함과 지금 추출 구조가 읽지 못하는 모양은
   고쳐 읽지 않았다(폴백 정책 `## 끝내 읽지 못한 원본`).

## 1. 결과

단위: **원본**은 headermap이 다룬 대상 기간 원본, **레코드**는 `records.csv`의 레코드,
**마커**는 `build.json`의 `marker_count`(업소 수)다.

| 대상 | 대상 원본 | 매핑 원본 | 미해결 원본 | 레코드 | 식당 | 비식당 | 보류 | 마커 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 울산(도시) | 1,139 | 1,009 | 130 | 6,078 | 4,419 | 817 | 842 | **944** |
| 시청 | 502 | 468 | 34 | 3,205 | 2,396 | 353 | 456 | 463 |
| 중구 | 105 | 69 | 36 | 906 | 681 | 138 | 87 | 199 |
| 남구 | 271 | 237 | 34 | 767 | 560 | 82 | 125 | 196 |
| 동구 | 120 | 115 | 5 | 540 | 380 | 72 | 88 | 96 |
| 북구 | 135 | 116 | 19 | 549 | 333 | 150 | 66 | 123 |
| 울주군 | 6 | 4 | 2 | 111 | 69 | 22 | 20 | 30 |

출처는 `data/ulsan/{headermap,classify,build}.json`·`records.csv`와 `orgs/<slug>/`의 같은 파일이다.
매핑 원본은 `mappings`의 서로 다른 `source_hash` 수, 미해결 원본은 `unresolved`의 건수다.
여섯 기관 레코드의 합집합(6,078)은 도시 레코드와 레코드 id까지 같다. 여섯 기관 × 여섯 단계는
모두 종료 코드 0으로 끝났고 `--retry-failed`를 쓰지 않았다.

### 이전 값과 비교 (완료 기준 4)

| 값 | 이전 | 이번 | 차이 |
| --- | ---: | ---: | ---: |
| `record_count` | 3,554 | **6,078** | +2,524 |
| `marker_count` | 773 | **944** | +171 |
| 매핑 원본 | 517 | 1,009 | +492 |
| 미해결 원본 | 622 | 130 | −492 |

레코드가 71% 늘었는데 마커는 22%만 늘었다. 이유는 6절의 좌표 손실이다 — 같은 실행에서
이전에 있던 좌표 559건(고유 업소 242곳)이 [ADR-0011](../adr/0011-ask-providers-in-order.md)
때문에 보류로 내려앉았다.

기관 `build.json`의 이전 값은 시청 3,195/659 · 중구 198/65 · 남구 69/39 · 동구 33/11 ·
북구 59/19 · 울주군 0/0이었다(`record_count`/`marker_count`).
`closure.json`은 944곳 모두 `unknown`이다. 인허가 원본 폴더가 이 PC에 없다(대구·대전·광주와 같다).

## 2. 실행 전에 확인한 것

- **규모.** 판정이 없던 원본 509개를 열어 표 단위로 셌다. 표는 **571개**이고 모두 새 판정이
  필요했다(공통 캐시 적중 0). 원본당 표는 1개가 466건, 2개가 36건, 3개 이상이 7건이다.
  형식은 pdf 501 · zip 7 · ooxml 1이다.
- **LLM 비용.**
  - 헤더 매핑은 CLI 경로라 한도 밖이다.
  - 비식당 판별의 고유 정규화 상호는 2,672개이고 공통 캐시 적중이 1,441개, 미스가 1,231개다.
    미스를 40개씩 31회 물으므로 [#176](issue-176.md)의 회당 중앙값 USD 0.00825525·최대
    0.016557로 USD 0.26~0.52를 예상했다. 잔액 5.40109725 안이라 멈추지 않았다.
  - 시작 누적은 USD 9.59890275다.

## 3. 헤더 매핑 — 에이전트 판정 571표

판정이 없던 원본 509개의 표 571개를 판정해 `data/ulsan/headermap-answers-v1.jsonl`에 남겼다.
모두 `claude-opus-5/claude-read-1`, revision 1이다. 판정 방법은 다음과 같다.

- 헤더 글자에서 역할 초안을 만들었다. 금액·집행일·상호가 모두 잡히는 첫 행을 헤더로 봤다.
  `비목`·`인원`·`(명)`·`방법`·`연번`이 든 칸에는 역할을 주지 않았다.
- 초안을 헤더→역할 조합 97종으로 묶어 모두 읽었다. `지급처`/`지급액`/`지급일`(동구),
  `적요`·`건명(지급사유)`처럼 낱말이 다른 표를 따로 확인했다.
- 모든 판정은 `extract`의 코드 검증을 그대로 거쳤다.

직접 읽고 정한 것은 다음과 같다.

| 표 | 판정 |
| --- | --- |
| 머리글 없이 이어지는 쪽 21개 | 같은 원본의 머리글 있는 표에서 역할을 가져오고 `header_rows`를 비웠다. `연번` 열이 빠져 열이 밀린 쪽은 어긋남을 코드 검증으로 골랐다(중구 251f3009·6c582126, 울주 f8f09ac5) |
| 참석자 명단 첨부 2개 | 지출 표가 아니다(`layout=none`). 동구 `노사외국인지원과`·`퇴임자 오찬` 명단이며 파일 전체가 명단이다 |
| 쪽에서 떨어져 나온 열 조각 11개 | 같은 쪽의 표가 이미 같은 값을 싣는다. `layout=none`으로 판정했다(남구 4bba9938 9개·2a445067·a0093fc6) |
| 금액이 `계/현금/카드`로 나뉜 표 1개 | 지출 행은 카드 칸에만 값이 있다. 머리글 2행, 금액 열은 카드 칸으로 판정했다(북구 424602eb) |
| 괘선 없는 쪽 2개 | 쪽 전체가 한 칸으로 온다. 지출은 있으나 열을 가릴 수 없어 그대로 판정해 `missing required roles`로 남긴다(중구 9abb1898·fba73d11) |
| `금액(천원)` 표 20개 | 천원으로 판정했다. 나온 레코드는 14,000~1,480,000원으로 원 단위 값이 섞이지 않았다 |

답변 이력으로 도시 headermap을 다시 돌린 결과, 대상 원본 1,139개 중 1,009개가 매핑됐다
(이전 517개). 공통 캐시(`data/_shared/headermap.jsonl`)에는 검증을 통과한 새 서명이 쌓였다.

## 4. 실행 중에 고친 코드

| 커밋 | 문제 | 고친 뒤 |
| --- | --- | --- |
| `fix(extract)` 보이지 않는 이음표 | 북구 PDF가 `2026\u00ad04\u00ad14 12:40`처럼 날짜의 이음표 자리에 U+00AD(soft hyphen)를 싣는다. 집행일이 읽히지 않아 원본 두 개(`20b0e46d`·`3de558fc`)가 통째로 미해결이었다 | U+00AD를 값에서 뺀다. 줄을 나눌 때만 보이는 서식 글자다. 두 원본에서 레코드 19건이 나온다 |

판정이 있던 원본 2개(동구 `4d2a35e0`·`996ef797`, 사유 `amount_krw`)도 이번 재실행에서 풀렸다.
이 둘은 이번 고침이 아니라 [#176](issue-176.md)이 고친 `extract`가 아직 울산 산출물에 반영되지
않았던 것이다(#176 7절 "다른 도시는 다시 내지 않았다"). 선언 표의 금액 빈 행 한 줄만 빠지고
나머지 지출은 살아남는다(ADR-0008).

다른 도시 산출물은 이번에도 다시 내지 않았다.

## 5. geocode — ADR-0011로 잃은 좌표 559건

도시 geocode는 11분 만에 종료 코드 0으로 끝났다(`--retry-failed` 불필요). 식당 레코드 4,419건의
판정은 다음과 같다.

| reason | 레코드 |
| --- | ---: |
| `matched` | 2,702 |
| `insufficient_evidence` | 1,461 |
| `no_candidates` | 199 |
| `merged_merchant` | 56 |
| `no_match` | 1 |
| `lookup_error` | 0 |

**이번 재실행에서 이전에 있던 좌표 559건이 사라졌다.** 커밋된 판정과 레코드 id로 맞대어 센 수다
(옛 `geocode.json`+`geocode.002.json` 2,642건 대 새 4,419건, 겹치는 2,642건 비교).

| 옮겨간 곳 | 레코드 | 고유 업소 |
| --- | ---: | ---: |
| `matched` → `insufficient_evidence` | 559 | 242 |
| `conflicting_evidence` → `matched` | 18 | 2 |
| `human_confirmed` → `no_match` | 1 | 1 |

사라진 559건은 **모두** 옛 판정 근거가 `single-provider license nearest-hall`이었다. 원인은
[ADR-0011](../adr/0011-ask-providers-in-order.md)이다. 네이버가 후보를 낸 레코드는 인허가에
묻지 않으므로, 네이버 후보가 채택 규칙에 닿지 않으면 인허가 후보가 있었더라도 보류가 된다.
ADR-0011이 적어 둔 손실은 ADR-0009의 제공자 합의였고, ADR-0010의 인허가 단독 채택이 이렇게
줄어드는 것은 적혀 있지 않다. 울산은 ADR-0011 이후 처음 다시 도는, 인허가 단독 채택을 갖고
있던 도시다.

`human_confirmed` → `no_match` 1건은 남구 `경복궁`(#132에서 사용자가 승인한 확정)이다. 확정이
가리키는 후보가 인허가 것인데 그 제공자를 묻지 않아 후보 목록에 없다. 확정 줄
(`data/manual/ulsan/geocode.jsonl`)은 그대로 있고 산출물의 `confirmation`도 그대로 실린다.

이 손실은 이 이슈에서 고치지 않는다(2026-09-18 사용자 결정). 후속 이슈로 올린다.

## 6. 남긴 것

### 미해결 원본 130건 (완료 기준 2)

`data/ulsan/headermap.json` `unresolved`를 사유와 상세별로 센 원본 수다. 이전 622건에서 줄었고
`model_not_configured`는 0건이다(완료 기준 1).

| 사유 | 원본 | 기관 |
| --- | ---: | --- |
| `no_table` | 63 | 남구 31 · 북구 16 · 중구 12 · 동구 4 |
| `validation_failed` amount_unit | 34 | 시청 34 |
| `unsupported_format` | 14 | 중구 14 |
| `validation_failed` spent_on | 10 | 중구 6 · 남구 3 · 동구 1 |
| `validation_failed` total amount mismatch | 6 | 북구 3 · 울주 2 · 중구 1 |
| `validation_failed` missing required roles | 2 | 중구 2 |
| `validation_failed` merchant | 1 | 중구 1 |

열어 본 원인은 다음과 같다. 모두 원본 결함이거나 지금 추출 구조가 읽지 못하는 모양이라
고쳐 읽지 않았다(폴백 정책).

- **`no_table` 63건.** PDF 51개 중 47개는 글자 층이 없는 스캔본이라 `pdfplumber`가 글자를
  0자로 읽는다(OCR은 범위 밖). 글자가 있는 PDF는 4개, zip은 12개다.
- **`unsupported_format` 14건.** 중구 zip 안이 OLE2(구 HWP)다. 파서 선택은 별도 티켓이다.
- **amount_unit 34건.** 시청 `금액(천원)` 표에 원 단위 행이 섞여 있다. [#145](issue-145.md)의
  보류 결정 그대로 그 원본 전체를 미해결로 둔다(ADR-0008).
- **spent_on 10건.** 원본이 집행일을 잘못 적었거나(`2026, 1., 29.`, `2026 1. 27.`, `2026430`,
  `26. 3 10.`, `2026. 3 31 12:20`) 달을 빠뜨렸다(중구 분기 내역의 `7.`·`12.`·`26.`).
  중구 성안동 2건은 PDF 격자가 한 지출을 여러 행으로 쪼개 날짜와 금액이 다른 행에 있다.
  값을 짐작해 채우지 않는다(폴백 정책 `## 코드 검증`).
- **total amount mismatch 6건.** 울주 2건은 `계`가 쪽을 넘어 문서 전체를 덮는데 표는 쪽마다
  나뉜다. 나머지는 원본이 적은 합계가 행 합과 다르다(북구 `계 총 4건 331,400` 대 행 합
  657,400 등).
- **missing required roles 2건.** 중구 zip 2개는 괘선이 없어 쪽 전체가 한 칸으로 온다.
  지출은 있으나 열을 가릴 수 없다.
- **merchant 1건.** 중구 부의금 지급 행의 `장소(대상)`가 빈칸이다.

## 7. LLM 비용 (완료 기준 5)

단계마다 `Budget(Path("data/_shared/llm-budget.jsonl")).committed()`로 쟀다.

| 시점 | 누적 USD |
| --- | ---: |
| 시작 | 9.59890275 |
| 도시 classify 뒤 | **9.78868425** |
| 기관 classify·나머지 단계 뒤 | 9.78868425 |

이번 이슈의 API 사용액은 USD 0.18978150이다. 헤더 매핑 API 호출은 0회이고(3절), 한도 15 안이다.

## 8. 명령

Git Bash, 저장소 루트에서 실행했다. 보조 스크립트는 `run.py` 하나다 — `.env`를 읽고(첫 인자가
`1`이면 GEMINI 포함, `0`이면 제외) 나머지 인자로 `cli.main`을 부른다. `--raw-root`는 항상
`C:\Users\설재원\deliciousmap-raw`다.

```text
uv run python -m deliciousmap headermap --city ulsan       # 모델 없음, 답변 이력 검증 (5분 34초)
uv run python -m deliciousmap parse --city ulsan           # 3분 0초
run.py 1 classify --city ulsan                             # 5분 13초
run.py 0 geocode --city ulsan                              # 11분, 종료 코드 0
run.py 0 closure --city ulsan
run.py 0 build --city ulsan
# 기관마다(시청·중구·남구·동구·북구·울주군)
run.py 0 headermap|parse --city ulsan --org <slug>
run.py 1 classify --city ulsan --org <slug>
run.py 0 geocode|closure|build --city ulsan --org <slug>
uv run python -m deliciousmap.ci check-data --data-root data
```

판정 초안·저장에 쓴 스크립트는 저장소에 남기지 않았다. 판정 결과는
`data/ulsan/headermap-answers-v1.jsonl`에 그대로 있고, 그 파일만으로 headermap을 다시 낼 수 있다.

## 9. 검사 (완료 기준 6)

2026-09-18 브랜치 끝에서 저장소 루트, Git Bash로 돌렸다.

| 명령 | 결과 |
| --- | --- |
| `uv run pytest` | 1096 passed |
| `uv run ruff check . --extend-exclude ".pytest-tmp-180,.pytest-tmp-180b"` | All checks passed |
| `uv run ruff format --check . --extend-exclude ".pytest-tmp-180,.pytest-tmp-180b"` | 206 files already formatted |
| `git diff --check` | 출력 없음 |
| `uv run python -m deliciousmap.ci check-data --data-root data` | 종료 코드 0 (완료 기준 3) |
| `gitleaks git --log-opts="develop..HEAD"` | 9절 아래 |

`--extend-exclude`는 다른 세션이 남긴 접근 불가 폴더(`.pytest-tmp-180*`) 때문이다.
산출물에서 가장 큰 파일은 `geocode-history-v2.002.jsonl` 19,985,922바이트이고 모두 ADR-0001의
20MB 안이다.
