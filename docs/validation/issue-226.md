# 이슈 #226 부산 parse~build 검증 기록

2026-09-18, Windows 11 · Git Bash · Python 3.12.10. 도시는 부산, 기관은 산출물이 있는 15곳이다.
헤더 매핑은 [#235](issue-235.md)가 다시 낸 것을 그대로 썼다.

## 막혀 있던 것

#217의 재수집이 대상 기간 원본 7개를 새로 가져왔는데 `parse.json`이 그 원본을 덮지 못했다.
`storage._validate_reports`는 원본별 보고가 대상 기간 원본을 한 번씩 **모두** 덮기를 요구하므로
`build --city busan`이 `invalid-artifact`(`ValueError`)로 거부됐고, PR #225의 `ci-build`가
`build city=busan org=* cause=invalid-artifact error=ValueError`로 빨간채였다.

지금은 대상 기간 원본 2,731개를 보고 2,731개가 한 번씩 덮는다.

## 전후

전 값은 `git show c9f072c~1:<경로>`, 후 값은 커밋된 작업 트리다. 모두 도시 산출물 기준이다.

| 항목 | 전 | 후 | 단위 | 도출 |
| --- | ---: | ---: | --- | --- |
| 원본 보고 | 2,724 | 2,731 | 원본 파일 | `parse.json`의 `payload.sources` 길이 |
| ├ 읽어 낸 원본 | 1,673 | 1,812 | 원본 파일 | 같은 목록의 `status == "parsed"` |
| └ 미해결 원본 | 1,051 | 919 | 원본 파일 | 같은 목록의 `status == "unresolved"` |
| 레코드 | 11,402 | 12,283 | 레코드 | `records.csv`의 줄 수(머리글 제외) |
| 식당 판정 | 7,497 | 8,100 | 레코드 | `classify.json`의 `status == "restaurant"` |
| 비식당 판정 | 2,489 | 2,620 | 레코드 | 같은 곳의 `non_restaurant` |
| 판단 보류 | 1,416 | 1,563 | 레코드 | 같은 곳의 `pending` |
| 좌표 성공 | 4,318 | 4,665 | 레코드 | `geocode.json`의 `status == "success"` |
| 좌표 실패 | 3,179 | 3,435 | 레코드 | 같은 곳의 `failed` |
| 마커 | 1,754 | 1,895 | 마커 | `closure.json`의 `payload.results` 길이 |

`build.json`의 `record_count` 12,283 · `marker_count` 1,895가 위 레코드·마커 수와 같다.

미해결 원본 919개의 사유는 `unsupported_format` 504 · `validation_failed` 257 ·
`no_candidates` 148 · `unreadable` 7 · `no_table` 3이다. 앞의 넷은 헤더 매핑이 남긴 것이고
`no_candidates`는 매핑은 있으나 지출 후보가 한 건도 없던 원본이다.

## 나간 모델 호출

`classify`에서만 나갔다. `parse`·`closure`·`build`는 모델을 쓰지 않고, `geocode`는 네이버 지역검색
·인허가 조회만 쓰므로 [폴백 정책](../specs/header-mapping-fallback.md)의 LLM 예산에 들지 않는다.

| 항목 | 값 | 도출 |
| --- | ---: | --- |
| 호출 | 15건 | `data/_shared/llm-budget.jsonl` 7,852 → 7,882줄, 예약·정산 각 15줄 |
| 예약 | USD 0.4916655 | 같은 줄의 `kind: reservation` 합 |
| 정산 | USD 0.1416930 | 같은 줄의 `kind: settlement` 합 |
| 누적 정산 | USD 9.60408825 | 장부 전체의 `settlement` 합 (한도 15, 잔여 5.39591175) |

이슈 #226의 실측은 「`classify`가 모델에 물을 상호 20 · 그로 인한 모델 호출 1」이었다. 실제는
15건이다. 그 실측은 `headermap`을 그대로 두고 새 원본 7개만 더했을 때의 수이고, 이 작업은
[#235](issue-235.md)가 헤더 매핑을 다시 내 레코드가 881건 더 늘어난 위에서 돌았다. 이슈의
추정치는 이 실행에 해당하지 않는다.

호출은 모두 `purpose: classification`이고 모델은 `gemini-3.6-flash`다. 15건은 첫 차례
(도시 → 기관 열다섯)에서 나갔다. 그 뒤 헤더 매핑 고정점에 맞춰 다시 돌린 도시·기관 실행은
공통 캐시(`data/_shared/classify.jsonl`)에서만 읽어 호출이 0건이었다 — 장부가 7,882줄에서
움직이지 않았다.

첫 차례의 도시 실행은 `unclassified: invalid_response`로 60건을 판단 보류에 남겼다. 응답이
해석되지 않은 상호는 캐시에 들어가지 않으므로 기관 실행이 다른 묶음으로 다시 물어 답을 받았고,
다시 돌린 도시 실행이 그 답을 캐시에서 읽었다. 마지막 도시 산출물의 `unclassified` 보류는 0건이다.

이 60건은 **실행 중에 본 중간값**이다. 그 산출물은 덮여 커밋되지 않았으므로 저장소의 파일로는
다시 셀 수 없고, 마지막 값 0건만 `data/busan/classify.json`에서 확인된다.

## 되살아난 부산진구 원본 두 건

#226이 짚은 `8b277a58…`·`61ebcfbc…`는 이제 `status: parsed`다. 다만 **레코드는 0건**이다.

| 항목 | 값 | 도출 |
| --- | ---: | --- |
| 지출 후보 | 각 1 | 두 원본의 `SourceReport.candidates` |
| 대상 기간 밖 | 각 1 | 같은 보고의 `out_of_range` |
| 레코드 | 각 0 | 같은 보고의 `records` |

`sheet1`·`sheet2`의 6행은 `해 | 당 | 없 | 음`이라 `note`로, 7행은 `소 계 | 0`이라 `subtotal`로
후보에서 빠진다(`excluded`). 남은 후보 하나는 `sheet3`의 2024년 2월 지출이라 2026년 상반기 밖이다.
#226의 실측이 적은 「부산진 새 원본이 만드는 레코드 0」은 사유가 달라졌을 뿐 값은 같다.

## 도시와 기관이 어긋나지 않는가

`--org` 산출물은 도시 산출물과 같은 레코드를 담아야 한다(README의 재생성 범위, `check-data`).

| 검사 | 결과 |
| --- | --- |
| 기관 `records.csv`의 `record_id`가 도시에 없는 것 | 15곳 모두 0건 |
| 기관 `classify.json`의 판정이 도시와 다르거나 없는 것 | 15곳 모두 0건 |
| 기관 `headermap.json`의 매핑이 도시와 다르거나 없는 것 | 15곳 모두 0건 |

## CI와 같은 검사

저장소 루트에서 `.github/workflows/ci.yml`의 `ci-build` 단계를 그대로 돌렸다.

| 명령 | 결과 |
| --- | --- |
| `uv run ruff check .` | 통과 |
| `uv run ruff format --check .` | 208 files already formatted |
| `uv run mypy src` | no issues in 59 source files |
| `uv run pytest` | 1,095 passed |
| `node --test tests/site_behavior.test.js tests/measure_map.test.js tests/service_worker.test.js` | 94 pass / 0 fail |
| `uv run python -m deliciousmap.ci check-data --data-root data` | 종료 코드 0, 도시 5곳 |
| `uv run python -m deliciousmap build --city <5곳>` | 모두 종료 코드 0 |
| `uv run python -m deliciousmap.ci check-dist --dist dist` | `sealed 24 files` |
| `git diff --check` | 통과 |
| gitleaks | no leaks found |

## 남은 제한

- `data/busan/geocode.json`이 16,932,805바이트다. ADR-0001의 파일당 20,000,000바이트 상한까지
  3.07MB 남았고, 이 파일은 이력과 달리 조각으로 나뉘지 않는다. 부산 식당 레코드가 지금의 1.18배가
  되면 `storage.write_bytes`가 `artifact exceeds 20MB`로 막는다.
- 좌표 실패 3,435건과 판단 보류 1,563건은 그대로 남는다. 이 작업은 수를 줄이지 않고 늘어난
  레코드만큼 함께 늘렸다.
- `data/manual/busan/`은 없다. 사람 보정·전수 대조를 거친 원본이 없으므로 미해결 919개는 모두
  코드 훑기까지이고 「원본 결함 확정」은 0개다.
