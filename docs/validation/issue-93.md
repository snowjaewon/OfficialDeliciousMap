# 이슈 #93 미해결 원본 15개의 `confirmed_by` 확정 기록

2026-09-15, Windows 11 · Git Bash · Python 3.12.10. 도시는 광주, 기관은 시청과 다섯 구다.
작업 브랜치의 기반은 `develop` `1110d5e`다.

## 이 대조가 무엇이고 무엇이 아닌가

**원본 파일을 열지 않았다.** 이 작업은 [#62](https://github.com/snowjaewon/OfficialDeliciousMap/issues/62)와
[#99](https://github.com/snowjaewon/OfficialDeliciousMap/issues/99)가 이미 남긴 대조 기록을
`data/manual/gwangju/sources.jsonl`로 **전재**하고, 사람 확인은 **PR 검토로 갈음**한 것이다
(2026-09-15 사용자 결정). `classify.jsonl`·`geocode.jsonl`의 사람 입력이 지금까지 PR 검토로
승인된 것과 같은 관례다.

그래서 이번 기록은 저장소가 적어 둔 문구를 **글자 그대로는 지키지 못한다.** 같은 요구가 세
곳에 있다.

- [폴백 정책](../specs/header-mapping-fallback.md) 59줄 — "사람이 원본과 전수로 대조해 …
  `confirmed_by`를 채운 원본만 원본 결함 확정이다"
- `CONTEXT.md`의 `원본 결함 확정` — "사람이 원본과 전수로 대조해 확정한 원본. … 대조가 없으면
  사유가 같아도 미해결이다"
- `SourceReview.confirmed_by`의 주석(`src/deliciousmap/contracts.py`) — "원본과 전수로 대조한
  사람. 코드 훑기만 끝났으면 비워 둔다"

15줄의 `confirmed_by`를 `sihun0927-sketch (PR 검토, #62·#99 기록 전재)`로 적어 무엇을 근거로
채웠는지를 값 자체에 남겼다. 세 문구를 이 관례에 맞출지는 이 이슈의 제외 범위이며 별도 제안
사항이다. 그때까지 **커밋된 데이터와 커밋된 문구는 서로 어긋난 채로 남는다.**

원본 자체는 raw-root(`../deliciousmap-raw/gwangju/`)에 15개 모두 있다. 열지 않은 것은 사용자
결정이며, 파일이 없어서가 아니다.

## 대조 대상 15개

이슈 본문이 적은 16개는 [#110](https://github.com/snowjaewon/OfficialDeliciousMap/pull/110)이
경조사 지출의 빈 상호를 `개인(성명 비공개)`로 읽게 되면서 시청 7개가 풀려 **9개**가 되었고,
#99가 닫히며 다섯 구 6개가 더해져 **15개**다(2026-09-13 댓글). `후보` 열은 `sources.jsonl`의
`candidates`이고, `코드가 낸 사유`는 `data/gwangju/parse.json`의 `detail` 그대로다.

| 기관 | 원본 | 부서 | 사유 | 후보 | 결함 행 | 코드가 낸 사유 | 기록 출처 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `gwangju-city` | `expenses/10909-1.xls` | 자원순환과 | 합계 불일치 | 6 | `sheet1:R4` | `sheet1:R4 total amount mismatch` | #62 |
| `gwangju-city` | `expenses/10933-1.xls` | 소방행정과 | 상호 빈칸 | 13 | `sheet1:R6` | `sheet1:R6 merchant` | #62 |
| `gwangju-city` | `expenses/10956-1.xlsx` | 경영부 | 합계 불일치 | 110 | `sheet1:R4` | `sheet1:R4 total amount mismatch` | #62 |
| `gwangju-city` | `expenses/10977-1.xls` | 연구지원과 | 합계 불일치 | 6 | `sheet1:R5` | `sheet1:R5 total amount mismatch` | #62 |
| `gwangju-city` | `expenses/10990-1.xls` | 콘텐츠산업과 | 합계 불일치 | 17 | `sheet1:R4` | `sheet1:R4 total amount mismatch` | #62 |
| `gwangju-city` | `expenses/10991-1.xls` | 아동청소년과 | 합계 불일치 | 15 | `sheet1:R4` | `sheet1:R4 total amount mismatch` | #62 |
| `gwangju-city` | `expenses/10999-1.xls` | 연구지원과 | 합계 불일치 | 5 | `sheet1:R5` | `sheet1:R5 total amount mismatch` | #62 |
| `gwangju-city` | `expenses/11015-1.xls` | 관광도시과 | 합계 불일치 | 21 | `sheet1:R4` | `sheet1:R4 total amount mismatch` | #62 |
| `gwangju-city` | `expenses/11017-1.xlsx` | 국제교류담당관 | 상호 빈칸 | 29 | `sheet1:R14` | `sheet1:R14 merchant` | #62 |
| `gwangju-buk` | `expenses/1193-1.xlsx` | 행정지원과 | 상호 빈칸 | 56 | `sheet1:R23` | `sheet1:R23 merchant` | #99 |
| `gwangju-dong` | `expenses-head/48747-1.xlsx` | 행정지원과 | 상호 빈칸 | 17 | `sheet1:R9` | `sheet1:R9 merchant` | #99 |
| `gwangju-gwangsan` | `expenses/1534-1.xlsx` | 월곡2동 | 합계 불일치 | 35 | `sheet1:R4` | `sheet1:R4 total amount mismatch` | #99 |
| `gwangju-gwangsan` | `expenses/1592-1.xlsx` | 문화예술과 | 합계 불일치 | 16 | `sheet1:R3` | `sheet1:R3 total amount mismatch` | #99 |
| `gwangju-gwangsan` | `expenses/1598-1.xlsx` | 세무2과 | 합계 불일치 | 5 | `sheet1:R5` | `sheet1:R5 total amount mismatch` | #99 |
| `gwangju-gwangsan` | `expenses/1607-1.xlsx` | 월곡2동 | 합계 불일치 | 35 | `sheet1:R4` | `sheet1:R4 total amount mismatch` | #99 |
| **합계** | 15개 | | 합계 불일치 11 · 상호 빈칸 4 | **386** | | | |

후보 386건은 시청 222 + 다섯 구 164다. 이슈 본문의 663건은 시청 16개 기준이라 #110으로 풀린
7개를 뺀 지금과 다르다.

## 줄마다 무엇이 달라졌나

- **시청 9줄** — `confirmed_by`만 채웠다. `evidence`는 #62가 후보 663건을 전수로 훑어 남긴
  문장 그대로이고 손대지 않았다.
- **다섯 구 6줄** — 줄 자체가 없어 새로 썼다. `evidence`는 커밋된 `parse.json`의 `detail`·
  `candidates`·`excluded`와 #99·#116의 문장만으로 적었다. **금액은 적지 않았고, 원본을 열지
  않아 금액이 없다는 것을 각 줄에 밝혔다.** #62가 남긴 시청 줄이 합계·항목 합·차이를 적고 있는
  것과 다른 점이다.

새 6줄이 #99에서 가져온 내용은 이것뿐이다.

- 북구 `1193-1`·동구 `48747-1`의 빈 상호는 경조사가 아닌 격려금이라 #110의 `개인(성명 비공개)`
  처리로 풀리지 않는다([issue-99.md](issue-99.md) "미해결 25개의 사유").
- 동구 `48747-1`은 경조사 근거가 없어 무엇이 빠졌는지 알 수 없다([issue-116.md](issue-116.md) 4절).
- 광산 `1592-1`은 16행 가운데 앞 11행의 합만 `계`에 적혀 있다(#99 실측).
- 나머지 합계 불일치 셋은 원본의 `계`가 그 표의 지출 합과 다르다는 것까지만 적었다.

**어긋난 줄은 없다.** 15줄의 `candidates`·`rows`·`finding`·`organization`을 `parse.json`의
원본별 보고와 `fetch.json`의 기관과 맞춰 보았고 고칠 줄이 없었다. 다만 이 일치는 코드가 낸
값끼리의 일치이지 원본과의 일치가 아니다.

## 대조 대상이 아닌 미해결 9개

`parse.json`의 미해결 24개 가운데 15개가 이번 대상이고 9개는 아니다. `SourceFinding`은
`merchant_blank`·`total_mismatch` 둘뿐이라 나머지는 `sources.jsonl`에 적을 수 없다.

| 원본 | 코드가 낸 사유 | 어디로 |
| --- | --- | --- |
| `gwangju-gwangsan/expenses/1577-1.xlsx` | `sheet2:R3 spent_on` | [#113](https://github.com/snowjaewon/OfficialDeliciousMap/issues/113) |
| `gwangju-gwangsan/expenses/1578-1.xlsx` | `sheet2:R3 spent_on` | #113 |
| `gwangju-gwangsan/expenses/1658-1.xlsx` | `sheet2:R3 spent_on` | #113 |
| `gwangju-gwangsan/expenses/1659-1.xlsx` | `sheet2:R3 spent_on` | #113 |
| `gwangju-nam/expenses/1112-1.hwpx` | `model_not_configured table1` | [#112](https://github.com/snowjaewon/OfficialDeliciousMap/issues/112) |
| `gwangju-gwangsan/expenses/1563-1.xlsx` | `sheet1: missing required roles` | 이 이슈 밖 |
| `gwangju-gwangsan/expenses/1550-1.xlsx` | `no_candidates` | 이 이슈 밖 |
| `gwangju-seo/expenses-department/4639-1.xlsx` | `no_candidates` | 이 이슈 밖 |
| `gwangju-buk/expenses/1156-1.pdf` | `no_table` | 이 이슈 밖 |

## 검증 — 저장소 산출물을 건드리지 않고 `parse`를 돌렸다

`parse`는 저장할 때 대조 기록의 후보 수를 원본별 보고와 맞춰 보고, 다르거나 이미 통과한 원본을
가리키면 실행을 세운다(`storage._validate_source_reviews`). 15줄이 그 검사를 지나는지 보려고
[#106](issue-106.md)의 선례대로 `data/`를 임시 폴더에 복사해 그쪽에서만 돌렸다.

**이 검사가 보는 것은 둘뿐이다** — 가리킨 원본이 이번 보고에서도 미해결인지, 그리고
`candidates`가 보고와 같은지다. `rows`·`finding`·`organization`은 읽지 않으므로 종료 코드 0이
그 셋까지 보증하지 않는다. 그 셋은 위 "줄마다 무엇이 달라졌나" 절처럼 `parse.json`·`fetch.json`과
따로 맞춰 보았다.

양쪽 공통(저장소 루트):

```text
uv run python -m deliciousmap parse --city gwangju --data-root <임시>/data-check
```

`--org` 없이 한 번 돌리면 `Paths.city_dir`가 `data/<city>`를 써서 시청과 다섯 구의 원본 635개를
모두 덮는다. 결과는 **종료 코드 0**이고, 임시 폴더의 `gwangju/parse.json`은 저장소의 것과
**바이트까지 같다**(`78dbc615d993db0c04ba39ea6a9c4974346aa78926beb343d9d506e31ce74377`).
미해결은 그대로 24개다. 저장소의 `data/gwangju/`는 한 파일도 바뀌지 않았다.

검사가 실제로 도는지도 확인했다. 임시 폴더에서 마지막 줄의 `candidates`를 35에서 34로 바꾸고
같은 명령을 돌리면 `parse city=gwangju org=* cause=invalid-artifact`로 **종료 코드 1**이다.
확인 뒤 되돌렸다.

### 화면의 자료 범위가 어떻게 갈리는가

같은 임시 폴더에서 `build`를 두 번 돌려 대조 전후를 비교했다. 지도 SDK 키는 화면 문구와
무관하므로 검증용 값을 넣었고, 출력도 임시 폴더로 보냈다.

양쪽 공통(저장소 루트):

```text
uv run python -m deliciousmap build --city gwangju --data-root <임시>/data-check --output-root <임시>/dist-check
```

대조 전(`develop`의 9줄, `confirmed_by` 빈칸):

```text
사람이 원본과 대조해 원본 자체의 결함으로 확정한 원본은 아직 없습니다. 아직 확정하지 못해
미해결로 남은 원본 24개: 검증 실패 20개(지출 후보 수 알 수 없음) · 후보 없음 2개(지출 후보
0건) · 모델 미설정 1개(지출 후보 수 알 수 없음) · 표 없음 1개(지출 후보 수 알 수 없음).
```

대조 뒤(이 PR의 15줄):

```text
사람이 원본과 대조해 원본 자체의 결함으로 확정한 원본 15개는 레코드를 내지 않습니다: 합계
불일치 11개(지출 후보 271건) · 상호 빈칸 4개(지출 후보 115건). 아직 확정하지 못해 미해결로
남은 원본 9개: 검증 실패 5개(지출 후보 수 알 수 없음) · 후보 없음 2개(지출 후보 0건) · 모델
미설정 1개(지출 후보 수 알 수 없음) · 표 없음 1개(지출 후보 수 알 수 없음).
```

271 + 115 = 386으로 위 표의 후보 합과 같고, 미해결 원본은 24개에서 9개로 옮겨 갔을 뿐 사라지지
않았다. 두 빌드의 `records.json`·`markers.json`은 바이트까지 같고 레코드 9,825건 · 마커 33곳으로
저장소의 `data/gwangju/build.json`과 같다. **`confirmed_by`는 레코드를 한 건도 바꾸지 않는다.**

임시 폴더는 검증 뒤 지웠다.

## 검증 명령과 결과

양쪽 공통(저장소 루트):

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
node --test tests/*.test.js
git diff --check
```

`ruff check` 통과, `ruff format --check` 162개 파일 통과, `mypy src` 55개 파일 통과,
`pytest` 810건 통과, `node --test` 92건 통과, `git diff --check` 지적 없음이다. 이 PR은 코드를
바꾸지 않으므로 테스트를 더하지 않았다(AGENTS.md: 문서·데이터만 바뀌면 의미 없는 실행 테스트를
넣지 않는다). `tests/` 아래 파일은 하나도 바뀌지 않았다.

gitleaks는 `gitleaks detect -c .gitleaks.toml`로 돌렸고 268개 커밋에서 탐지가 없다.

## 남은 제한

- **사람이 원본을 열어 대조하지는 않았다.** 근거는 코드 전수 훑기(#62·#99)의 전재와 PR 검토다.
  폴백 정책 59줄·`CONTEXT.md`·`SourceReview` 주석의 문구와 이 관례의 간극은 그대로 남는다.
- **`confirmed_by`가 적은 `PR 검토`는 아직 일어나지 않은 일이다.** 값은 커밋 시점에 들어갔고
  검토는 이 PR에서 이루어진다. AGENTS.md는 승인 0·셀프 머지를 허용하므로, 아무도 보지 않고
  머지하면 15줄이 적은 근거가 글자 그대로 거짓이 된다. 이 PR은 사람이 읽고 머지해야 한다.
- 다섯 구 6줄의 `evidence`에는 금액이 없다. 시청 9줄과 자세함이 다르다.
- 이 PR은 미해결 24개를 줄이지 않는다. 15개가 원본 결함 확정으로 갈릴 뿐이고, 남은 9개는
  #112·#113과 이 이슈 밖 4개다.
- 제출 기준의 "미해결 0개"는 이 PR로 채워지지 않는다. 제출 시점 기준이 요구하는 공개는
  위 화면 문구와 이 문서가 맡는다.
