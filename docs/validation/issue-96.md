# 이슈 #96 업종 필터 검증

2026-09-15, Windows 11 · Git Bash · Python 3.12.10 · Node.js v24.17.0.
범위: [feat(map): 업종 자료를 받아 지도에서 업종으로 거른다 #96](https://github.com/snowjaewon/OfficialDeliciousMap/issues/96).
조회 규칙은 [지오코딩 문서의 업종 조회](../geocoding.md#업종-조회), 공개 파일은
[README의 공개 데이터 파일](../../README.md#공개-데이터-파일)에 있다.

## 결정

2026-09-15 사용자가 착수 때 정할 세 가지를 정했다. 선행 조건인
[#73](https://github.com/snowjaewon/OfficialDeliciousMap/issues/73)은 2026-09-13에 닫혔다.

| 정할 것 | 결정 | 근거 |
| --- | --- | --- |
| 업종 출처 | 마커를 확정한 후보의 제공자 값. 네이버는 `category`, 인허가는 업태구분명(`BZSTAT_SE_NM`) | 마커마다 출처가 하나라 두 값이 다를 때 고를 일이 없다 |
| 화면 분류 | 필터는 한식·중식·일식·양식·분식·카페·주점·기타·미상으로 묶고, 상세는 원문을 보인다 | 업종을 아는 마커 32개의 원문이 19종이라 버튼으로 늘어놓기 어렵다 |
| 재조회 범위 | 확정 업소만 | 표시에 쓰는 값만 조회한다. 뒤에 확정되는 업소는 그때 그 업소만 더 조회한다 |

업종은 표시용이다([docs/geocoding.md](../geocoding.md)). `PlaceCandidate`와 조회 캐시에 칸을 더하지
않았다. `lookup`은 판정 키에 통째로 들어가므로([ADR-0005](../adr/0005-key-only-what-the-decision-reads.md))
칸 하나가 모든 레코드의 키를 바꾸고, 네이버 후보의 `source_id`는 해석 버전을 담으므로 버전을 올리면
사람 확인이 가리키는 후보를 찾지 못한다. 대신 별도 캐시 `category-lookup-v1.jsonl`에 쌓고 build만 읽는다.

### 이슈에 없던 판단

| 판단 | 이유 |
| --- | --- |
| 업소를 찾은 조회를 같은 질의로 다시 묻고, 확정한 후보와 출처(`source_id`)가 같은 항목만 쓴다 | 같은 응답의 다른 후보 업종으로 채우지 않는다 |
| 같은 실행에서 방금 받은 응답은 다시 요청하지 않는다 | 새로 조회해 규칙으로 확정한 업소는 응답에 이미 업종이 있다 |
| 업종 조회 실패는 `lookup-failed`로 종료하고, `--retry-failed` 전까지 다시 묻지 않는다 | 후보 조회 실패와 같은 규칙이다. 실패를 `미상`으로 숨기지 않는다 |
| 갈래에 없는 원문은 `기타`, 모르는 업종은 `미상` | 업종을 아는 마커와 모르는 마커를 섞지 않는다 |
| 도시 화면은 마커가 있는 갈래만 버튼으로 낸다 | 누르면 0곳인 버튼을 두지 않는다 |
| `markers.json` `schema_version` 10 → 11 | 마커에 `category`·`category_group`이 생겼다. `records.json`은 그대로 10이다 |

## 구현과 TDD

사전에 합의한 두 경계에서만 테스트했다. 네트워크·실제 키는 쓰지 않는다.

| 행동 | 테스트 |
| --- | --- |
| 네이버로 확정한 마커가 그 후보의 업종을 싣고, 같은 요청을 다시 보내지 않는다 | `test_a_naver_marker_carries_the_category_of_the_candidate_that_confirmed_it` |
| 인허가로 확정한 마커가 그 행의 업태를 싣는다 | `test_a_license_marker_carries_the_business_type_of_its_licence` |
| 캐시된 조회로 뒤에 확정한 업소는 그 질의를 한 번 다시 묻고 결과를 재사용한다 | `test_a_business_confirmed_from_a_cached_lookup_asks_its_query_again` |
| 다시 물었을 때 확정한 후보가 없으면 다른 후보로 채우지 않고 `미상` | `test_a_marker_whose_candidate_is_no_longer_found_stays_unknown` |
| 담당자가 준 후보는 물을 조회가 없어 요청 없이 `미상` | `test_a_candidate_supplied_without_a_lookup_is_not_asked_and_stays_unknown` |
| 실패는 종료 코드 1로 알리고 재시도 전까지 재사용 | `test_a_failed_category_lookup_is_reported_and_reused_until_an_explicit_retry` |
| 업종을 얻든 못 얻든 판정 결과·판정 키·이력이 같다 | `test_categories_never_reach_the_identity_decision_or_its_key` |
| 원문을 갈래로 묶고 원문은 그대로 둔다 | `test_a_marker_is_filed_under_a_group_while_keeping_the_original_category` |
| 도시 화면이 마커가 있는 갈래만 버튼으로 낸다 | `test_the_city_page_offers_only_the_groups_its_markers_fall_under` |
| 업종 필터가 검색·방문 구간과 함께 거르고 `미상`도 고를 수 있다 | `category groups narrow the result together with search and visit bands` |
| 업종 버튼은 여럿을 함께 고르고 빈 선택을 `전체`로 표시한다 | `category filter buttons toggle independently and mark the empty state as all` |
| 상세가 업종 원문을 보인다 | `a selected restaurant shows where its coordinate came from` |

앞 아홉은 `tests/test_category_cli.py`, 뒤 셋은 `tests/site_behavior.test.js`다. 기존 테스트 가운데
마커 전체를 비교하던 네 곳은 `category`·`category_group`을 더하거나 따로 확인하도록 고쳤다.

## 실제 키 실행

`.env`에서 `NAVER_SEARCH_*`·`DATA_GO_KR_KEY`·`NAVER_MAP_*`만 읽고 `GEMINI_*`는 뺐다. 전송 경계는
커밋된 `geocode.json`에서 `category.requests`로 고른 확정 업소의 질의만 실제로 보내고, 그 밖의 요청은
`BaseException`으로 거부해 캐시에 실패로 남지 않게 했다. 실행 순서는 도시마다 `geocode` → `closure` →
`build`다(광주는 커밋된 `fetch.json`의 원본 경로에 맞춰 `--raw-root`를 그 경로로 준다).

| 값 | 광주 | 울산 | 출처 |
| --- | ---: | ---: | --- |
| 공개 마커(업소) | 33 | 1 | `data/<city>/build.json`의 `marker_count` |
| 확정한 제공자 | 네이버 33 | 인허가 1 | `category.requests`가 고른 `Request.provider` |
| 다시 물을 조회가 없는 업소 | 1 | 0 | 같은 곳에서 `None`인 업소 수 |
| 실제 HTTP 요청 | 네이버 32 | 인허가 3 | 전송 경계의 요청 수(인허가는 질의 1개 × 업종 3종) |
| 업종을 얻은 마커 | 31 | 1 | `dist/<city>/markers.json`에서 `category`가 `미상`이 아닌 마커 수 |
| `category-lookup-v1.jsonl` | 32줄 · 16,418바이트 | 1줄 · 12,336바이트 | `wc -l`, `wc -c` |
| 실행 시간 | geocode 3분 18초 · closure 3분 50초 · build 4분 38초 | 10초 미만(geocode) | `time` |

`미상` 두 곳의 사유는 이렇다.

- `옥과한우촌`: 후보를 담당자가 `geocode-input.json`으로 주었다. 제공자 조회가 없어 다시 물을 질의가 없다.
- `더커볶`: 같은 질의를 다시 물었지만 응답에 확정한 후보와 출처가 같은 항목이 없었다.
  응답이 바뀌었는지는 원문을 남기지 않으므로 이 실행으로 가리지 않는다.

`dist/<city>/markers.json`의 갈래는 광주 한식 25 · 일식 4 · 미상 2 · 양식 1 · 분식 1, 울산 한식 1이다.
`기타`는 0이다. 업종을 아는 마커 32개(광주 31 + 울산 1)의 원문은 19종(광주 18 + 울산 1)이다.
인허가 응답에는 `BZSTAT_SE_NM`이 실제로 있었다(울산 질의 1개의 세 업종 응답에서 145행).

### 판정이 바뀌지 않았다

`geocode`를 다시 돌린 뒤 `git status`에서 `geocode.json`·`geocode.00N.json`·`geocode-history-v2*.jsonl`·
`geocode-lookup-v1*.jsonl`·`closure.json`은 두 도시 모두 바뀌지 않았다. 새 파일은
`category-lookup-v1.jsonl` 두 개이고, `build.json`은 `dependencies`에 `categories` 한 칸만 늘었다.

## 검증 명령

저장소 루트, 양쪽 공통:

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
node --test tests/site_behavior.test.js tests/measure_map.test.js tests/service_worker.test.js
uv run python -m deliciousmap.ci check-data --data-root data
uv run python -m deliciousmap.ci check-dist --dist dist --commit <커밋> --city gwangju --city ulsan
git diff --check
```

## 남은 제한

- 기관(`--org`) 산출물의 업종 캐시는 만들지 않았다. 기관 `geocode`를 다시 돌리기 전까지 기관별
  `markers.json`의 마커는 모두 `미상`이다. 공개 사이트는 도시 전체 산출물만 쓴다.
- 갈래 규칙은 실측 원문과 인허가 업태 이름을 담았다. 새 원문이 갈래 이름과 맞지 않으면 `기타`로 간다.
- 실제 브라우저에서 필터를 눌러 본 확인은 하지 않았다. 필터 동작은 `node --test`로만 확인했다.
