# 다섯 구의 재추출을 기관·도시 산출물과 지도까지 반영 (#129)

## 결론부터

- 다섯 기관과 도시 산출물을 다시 만들었다. 도시 레코드가 **9,720 → 9,825(+105)**가 되어
  [#113](https://github.com/snowjaewon/OfficialDeliciousMap/issues/113)·[#116](https://github.com/snowjaewon/OfficialDeliciousMap/issues/116)의
  재추출이 공개 장부에 올랐다.
- 기존 확정 33곳은 하나도 바뀌지 않았다. 늘어난 105건 중 좌표까지 확정된 것은 3건이고 모두 기존 업소에 붙었다.
  **새 마커는 0개다.**
- 새 조회는 네이버·인허가뿐이고 **LLM 호출은 0건**이다(`data/_shared/llm-budget.jsonl` 바이트 불변).
- 이슈가 적은 범위가 세 곳에서 달랐다. 아래 [범위가 달랐던 세 가지](#범위가-달랐던-세-가지).

## 범위가 달랐던 세 가지

### 1. 기관 재생성은 classify가 아니라 parse부터다

이슈는 기관 산출물을 `classify`부터 `build`까지 다시 만든다고 적었다. 실제로는 다섯 기관 모두
`parse.json`이 스키마 v4인데 현재 계약이 v5, `build.json`이 v7인데 v9였다. `classify`만 돌리면
`parse.json`을 읽는 자리에서 `RegenerationRequired`가 나고 종료 1이다(`src/deliciousmap/storage.py:614`).

```text
다섯 기관 모두  fetch:4 headermap:2 parse:4≠5 classify:1 geocode:5 closure:4 build:7≠9
도시 gwangju    fetch:4 headermap:2 parse:5  classify:1 geocode:5 closure:4 build:9
```

### 2. 도시도 parse가 아니라 headermap부터다

도시를 `parse`부터 돌렸더니 종료 0인데도 레코드가 9,720 그대로였다. 종료 코드도 `check-data`도 이 낡음을
잡지 못한다.

까닭은 헤더 판정이 도시에 전달되지 않은 것이었다. #113이 서구 원본 하나의 헤더를 **사람이** 판정해
기관 답변 이력에만 적었다.

```text
기관 data/gwangju/orgs/gwangju-seo/headermap-answers-v1.jsonl
  human/issue-113 3cd9fc86b0994b12 sheet1  연도 근거 2026. 게시글 제목이 2026년 2분기 …   (revision 2)

도시 data/gwangju/headermap-answers-v1.jsonl
  claude-opus-5/claude-read-1 3cd9fc86b0994b12 sheet1                                   (revision 1)
```

그래서 도시 `headermap`은 그 원본을 `unresolved`로 두고, 도시 `parse`가 건너뛰었다.

**이 판정은 답변 이력에만 있고 공통 캐시에는 없었다.** 같은 열 배치를 `data/_shared/headermap.jsonl`
428줄에서 찾으면 0건이고, 그 파일은 이 작업 내내 바이트 그대로다.

`answers_key`는 `digest({policy, source_hash, table.name})`이라 기관에 무관하다(`headermap.py:224`).
같은 원본·같은 표의 판정이므로 도시에도 그대로 해당한다. 그래서 기관 답변을 도시 이력에 **덧붙였다**
(덮어쓰지 않고 다음 revision으로, evidence 그대로). 8건이 옮겨졌다.

| 옮긴 판정 | 건수 | 근거 |
| --- | ---: | --- |
| 서구 | 1 | `human/issue-113` — 사람 판정 |
| 광산구 | 7 | `gemini-3.6-flash/header-map-1` — 모델 판정 |

다시 실행하면 0건이 옮겨진다(멱등).

### 3. 기관도 headermap부터 돌려야 도시와 맞는다

도시를 고친 뒤 남구만 기관(1,074) < 도시(1,079)로 어긋났다. 남구 `headermap.json`이 커밋본 그대로라
공통 캐시로 풀 수 있는 원본 셋을 `unsupported_format`으로 두고 있었다. 다섯 기관을 `headermap`부터
다시 돌리자 남구 `headermap.json`만 바뀌고 나머지 넷은 같은 결과였다(멱등).

## 게시일 범위

재추출 범위는 게시일 2026년이다. `period.py`의 `START = 2026-01-01`·`END = 2026-06-30`이 기준이고
`collects()`가 게시일의 해로 자른다. 게시일을 밝히지 않는 게시판은 받는다 — 근거 없음을 0건으로
바꾸지 않는다는 그 함수의 규칙이다.

수집 원본 11,724개 중 이번 제출의 대상은 **635개(5.4%)**다. `period.targets()`가 `parse` 앞에서 거른다.

| 기관 | 대상 | 제외 | 전체 |
| --- | ---: | ---: | ---: |
| gwangju-city | 173 | 10,862 | 11,035 |
| 광산구 | 120 | 70 | 190 |
| 동구 | 99 | 45 | 144 |
| 북구 | 98 | 49 | 147 |
| 서구 | 78 | 39 | 117 |
| 남구 | 67 | 24 | 91 |

제외 사유는 `posted_out_of_range` 10,786(게시일이 2026년 밖)과 `declared_out_of_range` 303(제목이 밝힌
지출 기간이 대상 밖)이다. 수집 단계에서도 2026년 밖 게시글 5,471건은 본문을 열지 않았다
(`fetch.json`의 `uncollected_postings`).

## 실행

저장소 루트, Git Bash. 모델 키(`GEMINI_*`)는 환경에서 뺐다 — 이슈가 정한 기본 경로다. 네이버 검색·
인허가·지도 키는 넣었다. 커밋된 산출물이 두 제공자를 모두 쓰기 때문이다(기준선 도시 `geocode.json`에
naver 1,709 · license 1,709).

```text
uv run python -m deliciousmap <단계> --city gwangju [--org <기관>] --raw-root <fetch.json이 기록한 경로>
```

단계는 기관·도시 모두 `headermap` → `parse` → `classify` → `geocode` → `closure` → `build`다.

### 조회를 먼저 끝낸 이유

`geocode`의 조회는 응답 지연이 병목이라(요청당 약 5초) 다섯 기관을 한 프로세스로 돌리면 네 시간이
넘었다. [#122](issue-122.md)와 같이 조회를 먼저 하는 스크립트를 썼다. 그 스크립트는 저장소에 두지 않았다.

기관마다 미적중 질의를 뽑아 샤드로 나눠 조회하고, 샤드 결과를 그 기관 캐시에 **순차로** 합쳤다.
같은 캐시 파일에 동시에 쓰면 `cannot overwrite cache history`로 멈추기 때문이다(`storage.py:513`).

**실패한 조회는 합치지 않았다.** 캐시에 실패로 굳으면 뒤의 `geocode`가 `retry_failed` 없이 그 실패를
재사용한다(`lookup.py:149`). 빼 두면 `geocode`가 그 질의만 다시 묻는다.

### 산출물을 쓰는 동안 그 파일을 읽지 않는다

파이프라인은 산출물을 `os.replace`로 갈아치운다(`storage.py:158`). Windows에서는 다른 프로세스가 그
파일을 열고 있으면 `PermissionError(WinError 5)`가 나고 단계 전체가 `io-error`로 죽는다. 진행 확인을
하려고 조회 캐시를 20초마다 읽다가 동구 `geocode`를 1,475초 지점에서 죽였다. 그 뒤로는 진행 확인에
저장소 파일을 읽지 않았다.

### 단계 소요 (도시)

| 단계 | 초 |
| --- | ---: |
| headermap | 149 |
| parse | 171 |
| classify | 53 |
| geocode | 240 |
| closure | 185 |
| build | 292 |

기관은 단계마다 5~15초다(조회가 캐시에 있을 때).

## 전후 레코드 수

| 기관 | 전 | 후 | 차 | 기관 `records.csv` |
| --- | ---: | ---: | ---: | ---: |
| 시청 | 3,250 | 3,250 | 0 | — |
| 북구 | 1,859 | 1,859 | 0 | 1,859 |
| 광산구 | 1,439 | 1,439 | 0 | 1,439 |
| 서구 | 1,158 | **1,188** | +30 | 1,188 |
| 남구 | 1,022 | **1,079** | +57 | 1,079 |
| 동구 | 992 | **1,010** | +18 | 1,010 |
| **도시 합계** | **9,720** | **9,825** | **+105** | — |

도시와 기관의 구별 레코드 수가 모두 같다. 사라진 레코드는 0건이다.

기준선에서는 방향이 반대였다. 같은 커밋에서 도시는 동 992 / 남 1,022 / 서 1,158인데 기관은
1,010 / 1,074 / 1,188이었다. 이번에 도시가 기관을 따라잡았고, 남구는 기관도 함께 1,079로 올라갔다.

### 건수가 같고 내용이 바뀐 레코드

**0건.** 기준선과 현재에 다 있는 도시 레코드 9,720건은 12개 칸 값이 완전히 같다. 변경은 105건 추가뿐이다.

이슈는 광산구를 건수는 같고 내용이 다르다고 적었으나, 도시 산출물 기준으로는 광산구 레코드가
한 건도 바뀌지 않았다.

기관 `records.csv`는 스키마가 10칸에서 12칸으로 올라갔다(`expense_id`·`expense_amount_krw` 추가).
도시는 이미 12칸이었다. 새 두 칸은 여섯 타깃 모두 채워진 행이 0건이고, 공통 10칸의 값 차이도 0건이다.

## 새 조회와 LLM

| 제공자 | 건수 |
| --- | ---: |
| 네이버 지역검색 | 461 |
| 인허가(data.go.kr) | 2,828 |
| **LLM** | **0** |

`data/_shared/llm-budget.jsonl`은 747줄 그대로이고 `data/_shared/classify.jsonl`·`headermap.jsonl`도
바이트 그대로다. 예산 장부에 더할 것이 없다.

인허가 제공자는 일시 실패(`unavailable`)를 이따금 돌려준다. 선조회 2,430건 중 72건(3.0%)이 그랬다.
그 72건은 캐시에 넣지 않고 `geocode` 실행이 다시 물었다.

`geocode`는 `lookup_error`가 하나라도 있으면 단계 전체를 실패로 알린다(`pipeline.py:294`). 그래서
남은 실패는 그 질의만 다시 조회해(재시도 3회·backoff 2초) 해소했다. 최종 산출물의 `lookup_error`는
기관·도시 모두 0건이다.

### 남구 인허가 캐시는 커밋 상태에서 이미 실패였다

남구 `geocode-lookup-v1.jsonl`은 HEAD에서 인허가 조회 379건이 **전부 실패**였다. 이번 실행이 453건을
새로 성공시켰다. 나머지 네 기관은 HEAD에 인허가 조회가 아예 없었고 이번에 처음 채워졌다.

| 기관 | HEAD 인허가 | 현재 인허가 |
| --- | --- | --- |
| 남구 | 0 성공 / 379 실패 | 453 성공 / 381 실패 |
| 동구 | 항목 없음 | 351 성공 / 9 실패 |
| 광산구 | 항목 없음 | 675 성공 / 2 실패 |
| 북구 | 항목 없음 | 870 성공 / 1 실패 |

## 기존 확정 33곳

**하나도 바뀌지 않았다.** `business_id`마다 맞댄 결과 유지 33 / 사라짐 0 / 새로 생김 0이고, 33곳 전부
좌표·확정 상호가 같다. 확정 레코드 836건도 `business_id`·좌표·상호·`reason`·`status` 여섯 값이
한 건도 바뀌지 않았다.

방문 수만 세 곳에서 늘었다. 새 레코드가 기존 업소에 붙은 것이다.

| 업소 | 방문 | 합계 금액 |
| --- | --- | --- |
| 신청담한우 | 75 → 76 | 14,477,000 → 14,754,500원 |
| 해남성내식당 | 23 → 24 | 3,782,500 → 4,058,500원 |
| 여수서대회집 | 14 → 15 | 1,290,000 → 1,410,000원 |

나머지 30곳은 방문 수도 그대로다.

## 늘어난 105건의 행방

```text
새 레코드 105  (남구 57 · 서구 30 · 동구 18 · 북구 0 · 광산구 0)
├─ 판단 보류 69
│  ├─ 모델 미설정(model_not_configured) 47
│  └─ LLM 업종 불분명 22
├─ 비식당 2
└─ 식당 34
   ├─ 좌표 실패 31  (주소 없음 29 · 후보 없음 2)
   └─ 좌표 확정  3  → 전부 기존 업소에 합류. 새 업소 0곳
```

**보류를 0건으로 적지 않는다.** 105건 중 지도에 새 마커로 오른 것은 0건이고, 확정으로 간 것은
3건(2.9%)뿐이다.

`model_not_configured` 47건은 기준선에 0건이던 사유다. 이슈가 모델 키를 넣지 않으면 새 상호는
`unclassified: model_not_configured`로 남으며 그 경로를 기본으로 한다고 정한 대로 돌린 결과다.
다만 이것은 **판단해 보니 보류가 아니라 판단을 시도하지 않은 것**이다. 그 구분을 그대로 남긴다.

`no_candidates` 2건은 남구 `부자네가든`, 서구 `임마중추어팅`이다.

## 파일 건수와 크기

기준선은 `origin/develop`(8234ec7)을 별도 worktree에 두고 그대로 build해서 쟀다. 이 작업 공간의
`dist/`는 이전 브랜치(마커 12개)의 잔재여서 기준선으로 쓸 수 없었다.

| 파일 | 전 건수 | 후 건수 | 전 크기 | 후 크기 |
| --- | ---: | ---: | ---: | ---: |
| `markers.json` | 33 | 33 | 14,417 B | 14,417 B |
| `records.json` | 9,720 | **9,825** | 4,042,760 B | **4,084,750 B** |

`markers.json`은 크기가 같지만 바이트는 다르다. 위 세 업소의 `visit_count`·`total_amount_krw`가 바뀐
것이 전부다. 합계로는 방문 836 → 839, 금액 114,331,030 → 115,004,530원이다.

## 의존성 해시

여섯 타깃(도시 + 다섯 기관)의 `classify`·`geocode`·`closure`·`build`가 모두 현재 입력과 맞는다.
`parse`까지 포함해 `dependencies`와 `schema_version`을 직접 대조했고 6 × 5 전부 일치했다.

여섯 타깃 모두 `records.csv` 행 수 == `classify` 결정 수 == `build.record_count`다.

## 남은 제한

- **남구 `.hwpx`는 반영되지 않았다.** 원본은 이슈가 적은 14건이 아니라 **6건**이고, 그중 4건이
  `unsupported_format`으로 남았다(나머지 2건은 `declared_out_of_range`). `.hwpx`에서 나온 레코드는 0건이다.
  현재 코드의 `grid.read_tables`로 여섯 파일을 직접 읽으면 모두 파싱되므로 파서 문제는 아니고,
  헤더 판정을 답변 이력에 넣는 일이 먼저다([#112](https://github.com/snowjaewon/OfficialDeliciousMap/issues/112)).
  이슈의 제외 범위에 해당한다.
- **새 업소 확인(사람 판단)은 하지 않았다.** 좌표 확정에 사람 확인이 필요한 건은 확정하지 않고 후보와
  사유만 남겼다. `missing_address` 29건·`no_candidates` 2건이 그것이다.
  [#135](https://github.com/snowjaewon/OfficialDeliciousMap/issues/135)·[#136](https://github.com/snowjaewon/OfficialDeliciousMap/issues/136)·[#123](https://github.com/snowjaewon/OfficialDeliciousMap/issues/123)·[#128](https://github.com/snowjaewon/OfficialDeliciousMap/issues/128)의 경로로 따로 처리한다.
- **`check-data`는 이 낡음을 잡지 못한다.** 도시를 `parse`부터만 돌렸을 때 종료 0에 `check-data` 통과인데도
  재추출이 반영되지 않았다. 기관 산출물의 낡음을 잡는 일은 이 이슈의 제외 범위다.
- **[#135](https://github.com/snowjaewon/OfficialDeliciousMap/issues/135)·[#136](https://github.com/snowjaewon/OfficialDeliciousMap/issues/136)·[#137](https://github.com/snowjaewon/OfficialDeliciousMap/issues/137)·[#128](https://github.com/snowjaewon/OfficialDeliciousMap/issues/128)의 수치(161·14·61·483)는 다시 세어야 한다.** 이전 도시 산출물을 전제로 적혀 있다.
- `dist/gwangju/orgs/*`가 새로 생겼다(기관별 마커 18개). 기관 `build`를 처음 돌린 결과이며 `dist/`는
  커밋하지 않으므로 저장소에는 영향이 없다.

## 검사

| 명령 | 결과 |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 139 files already formatted |
| `uv run mypy src` | Success: no issues found in 50 source files |
| `uv run pytest` | 644 passed (160초) |
| `git diff --check` | 통과 |
| `uv run python -m deliciousmap.ci check-data` | 종료 0 |
| `gitleaks detect` | no leaks found (608 MB, 2분 58초) |

### 최종 장부

| 항목 | 값 |
| --- | ---: |
| 도시 `records.csv` | 9,825 |
| `classify` | 식당 7,021 · 비식당 618 · 판단 보류 2,186 |
| `geocode` | 확정 839 · `missing_address` 5,291 · `merged_merchant` 549 · `no_candidates` 342 · `lookup_error` 0 |
| `build` | 마커 33 · 레코드 9,825 |
