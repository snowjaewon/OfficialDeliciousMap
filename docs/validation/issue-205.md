# 기장군 선언 표의 상호·금액 실패 행 단위 제외 재실측 (#205)

[#205](https://github.com/snowjaewon/OfficialDeliciousMap/issues/205)의 결정(선언 표의 행 단위 제외를
`merchant`·`amount_krw`까지 넓히고 `amount_unit`과 모델 매핑 표는 넓히지 않는다)을 구현한 뒤
2026-09-17에 기장군 원본을 다시 흘렸다. 원본은 [#198 실측](issue-198.md)이 받아 둔 `.html` 1건
(`expenses-1.html`, 2,959,657 B, `source_hash` `9aaaf9ee…`)이며 다시 받지 않았다. 구현 전 값은
[issue-198.md](issue-198.md) 4절에 그대로 있다.

## 1. 다시 흘린 결과 — 레코드 421건

`headermap`부터 다시 흘렸다. #198 시점의 `headermap.json`은 선언 매핑을 코드 검증까지 돌려 본 뒤
`unresolved_mappings`에 두었으므로(`table1:R365 merchant`), `parse`만 다시 돌리면 그 판정을 그대로
읽어 값이 바뀌지 않는다.

```text
uv run python -m deliciousmap headermap --city busan --org busan-gijang
uv run python -m deliciousmap parse --city busan --org busan-gijang
```

| 항목 | #198 시점 | #205 뒤 |
| --- | --- | --- |
| `headermap` 매핑 | `mappings` 0 · `unresolved_mappings` 1 | `mappings` 1 · `unresolved_mappings` 0 |
| `parse` 상태 | `unresolved` · `validation_failed` · `table1:R365 merchant` | `parsed` |
| `candidates` | 3,248 | 3,248 |
| `records` | 0 | **421** |
| `out_of_range` | 0 | 2,798 |
| 제외 목록 `blank` | 49 | 49 |
| 제외 목록 `spent_on` | 0 (미해결 원본은 값을 읽지 않는다) | 18 |
| 제외 목록 `merchant` | 0 | 5 |
| 제외 목록 `amount_krw` | 0 | 6 |
| `review` | — | 0 |
| `total_check` | — | `absent` |

분모 식이 맞는다: `421 + 2,798 + 29 = 3,248`. 행 단위로 빠진 29줄의 자리는 #198 실측이 미리 센
것과 같다 — 상호 `R365`·`R2372`·`R2844`·`R2849`·`R2859`, 금액 `R3071`~`R3076`, 집행일 18줄.
`records.csv`는 헤더 포함 422줄, 94,780 B다.

값은 `data/busan/orgs/busan-gijang/parse.json`의 `sources[0]`을 사유별로 센 것이다
(`excluded`의 마지막 낱말로 묶었다).

## 2. 다른 도시의 선언 표 — 울산 동구 원본 2개가 영향을 받는다

이 결정은 선언 표 전부에 미치므로 커밋된 `parse.json` 전부에서 `detail`이 행 단위 실패로 끝나는
원본을 찾아 매핑이 선언(`declared=true`)인지 보았다.

| 기관 | 원본 | 실패 | 매핑 | #205 뒤 다시 흘리면 |
| --- | --- | --- | --- | --- |
| `ulsan-city` | 34 | `amount_unit` | 선언 | 그대로 미해결(넓히지 않는다) |
| `ulsan-donggu` | 2 (2026-01-28 후보 4 · 2026-02-09 후보 5) | `amount_krw` | 선언 | 그 한 줄씩만 빠지고 3 + 4 = 7건이 레코드가 된다 |
| 그 밖의 `merchant`·`amount_krw`·`spent_on` 실패 (부산 시청·중구·동래, 대전, 광주) | — | — | 모델 매핑 | 그대로 미해결 |

동구 원본 2개는 [#145 실측](issue-145.md)의 "동구 금액 빈 행"(금액 칸이 빈 채 첨부만 단 행)이다.
이슈 #205는 시청·중구·동구 산출물이 바뀌지 않기를 기대했는데, 시청·중구는 그대로이고 **동구는
바뀐다**. 울산 원본은 이 작업 PC에 남아 있지 않아 이번에 다시 흘리지 못했고, 커밋된 동구 산출물은
#145 시점 그대로다(`records=0`, `table1:R5 amount_krw`·`table1:R6 amount_krw`). 울산을 다음에
흘릴 때 이 두 원본이 위 값이 되는지 본다. 같은 꼴을 합성한 종단 테스트
(`tests/test_html_tables.py`의 `test_a_detail_row_without_an_amount_is_not_filled_in`)는 이 계약으로
갱신했다 — 후보 2줄 가운데 금액 빈 줄 하나만 `table1:R3 amount_krw`로 빠지고 나머지 한 줄이
레코드가 된다.

## 3. 아직 흘리지 않은 것

`parse` 뒤의 `classify`·`geocode`·`closure`·`build`는 다시 흘리지 않았다. 레코드 421건의 비식당
판별과 지오코딩은 모델·네이버 호출이라 [#142](https://github.com/snowjaewon/OfficialDeliciousMap/issues/142)의
실행 절차와 예산에서 한다. 그때까지 기장군의 뒤 단계 산출물은 `parse.json`보다 낡았다고
파이프라인이 알린다(`stale artifact; rerun its producing stage`).
