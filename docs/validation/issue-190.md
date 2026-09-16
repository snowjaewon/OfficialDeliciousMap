# 이슈 #190 manual 파일 판정 필드 키 전환 실측

2026-09-17, Windows 11 · Git Bash · Python 3.12 · uv. 기준 커밋 `248bf50`(`feature/128-merchant-reviews`).
범위: [산출물 의존성 키가 manual 파일 4종의 판정 필드만 읽게 한다 #190](https://github.com/snowjaewon/OfficialDeliciousMap/issues/190).
키 값 형식이 바뀌어 광주 시·구 5개의 parse~build를 1회 다시 냈고, 그 산출물이 재실행 전과 같은지 적는다.
울산 시·구 6개는 이 실행에서 다시 내지 않았다 — 담당자가 다음에 만질 때 재실행한다.

## 1. 무엇을 바꿨나

`storage._dependencies`의 `merchants`(parse)·`manual`(classify)·`restorations`(classify·geocode)·
`confirmations`(geocode) 네 키가 `file_digest`(파일 통째 SHA-256) 대신 `review_digest`를 쓴다.
`review_digest`는 manual 파일을 해당 모델로 읽어 `contracts.REVIEW_EVIDENCE_FIELDS`(`evidence`·`references`)를
뺀 `model_dump(mode="json")`을 정렬해 `identity.digest`로 묶는다. 정책 버전 문자열 4종은 그대로다.

## 2. 재실행 — 도시 1 + 구 5, parse → classify → geocode → closure → build

`.env`를 읽은 Git Bash에서 단계 명령을 차례로 실행했다(`uv run python -m deliciousmap <단계> --city gwangju [--org <구>]`).

| 대상 | parse | classify | geocode | closure | build |
| --- | --- | --- | --- | --- | --- |
| gwangju(시) | 45초 | 12초 | 190초 안팎 (`lookup-failed`, 아래) | 43초 | 71초 |
| gwangju-buk | 4초 | 2초 | 21초 (`lookup-failed`, 아래) | 4초 | 24초 |
| gwangju-dong | 2초 | 2초 | 18초 | 2초 | 19초 |
| gwangju-gwangsan | 4초 | 1초 | 19초 | 4초 | 22초 |
| gwangju-nam | 3초 | 1초 | 18초 | 2초 | 19초 |
| gwangju-seo | 3초 | 1초 | 19초 | 3초 | 20초 |

시간은 셸에서 `date +%s` 차이로 잰 것이다. 시 geocode는 첫 실행 로그가 `tail`로 잘려 정확한 초를 남기지
못했고, 이슈의 실측(190초)과 같은 자리다.

시 geocode와 북구 geocode는 판정을 저장한 뒤 종료 코드 1로 `cause=lookup-failed`를 냈다. 원인은 판정이
아니라 업종 조회 캐시 `data/gwangju/category-lookup-v1.jsonl`에 기준 커밋부터 있던 `status == "error"`
12줄이다(`--retry-failed` 없이는 실패로 남는다). 아래 명령으로 기준 커밋과 재실행 후가 같은 12줄임을
확인했고, `lookup_error` 판정은 0건이다.

```text
uv run python -c "import json,collections; print(collections.Counter(json.loads(l)['value'].get('status') for l in open('data/gwangju/category-lookup-v1.jsonl',encoding='utf-8')))"
# Counter({'ok': 2172, 'error': 12}) — 기준 커밋(git show 248bf50:...)도 같다
```

geocode.json은 그 실패보다 먼저 저장되므로 closure·build는 새 geocode를 읽었다(`dependencies` 검사 통과).

## 3. 결과 — build 수는 같고, payload는 33개 파일 전부 같다

`build.json`의 `record_count` / `marker_count`(재실행 전은 `git show 248bf50:<경로>`, 후는 작업 트리):

| 대상 | 재실행 전 | 재실행 후 |
| --- | --- | --- |
| gwangju(시) | 10,335 / 2,266 | 10,335 / 2,266 |
| gwangju-buk | 2,057 / 509 | 2,057 / 509 |
| gwangju-dong | 1,033 / 242 | 1,033 / 242 |
| gwangju-gwangsan | 1,545 / 441 | 1,545 / 441 |
| gwangju-nam | 1,151 / 301 | 1,151 / 301 |
| gwangju-seo | 1,212 / 350 | 1,212 / 350 |

바뀐 파일은 `git status --short data/gwangju` 기준 33개(시 `parse`·`classify`·`geocode`×4조각·`closure`·`build`
8개, 구 5개 × 5단계 25개)다. 33개 모두 `schema_version`과 `payload`가 기준 커밋과 같고 `dependencies`만 다르다.
달라진 키는 manual 키 4종(`merchants`·`manual`·`restorations`·`confirmations`)과 그 연쇄인 선행 산출물
해시(`parse.json`·`classify.json`·`geocode.json`·`closure.json`·`city_geocode`)뿐이다. geocode 판정 7,396건은
`record_id` 순서까지 기준 커밋과 같다.

바뀌지 않은 것: `records.csv` 6개, `geocode-history-v2*.jsonl`(새 줄 0), `geocode-lookup-v1*.jsonl`(새 조회 0),
`category-lookup-v1.jsonl`, `data/_shared/classify.jsonl`·`llm-budget.jsonl`(모델 호출 0). 네이버·인허가·Gemini
호출은 이 재실행에서 0회다.

## 4. 근거 편집이 산출물을 낡게 하지 않는다 — 실제 광주 파일로

재실행 뒤 `data/manual/gwangju/`의 네 파일 각각에 대해 첫 줄의 `evidence`에 문구를 덧붙이고 줄 순서를
뒤집은 뒤, 그 파일을 읽는 단계의 산출물을 `ArtifactStore.load`로 열었다(끝나면 원본 바이트로 되돌렸다).

| 파일 | 줄 수 | 파일 해시(옛 키) | `review_digest`(새 키) | `load` |
| --- | --- | --- | --- | --- |
| merchants.jsonl | 448 | 바뀜 | 같음 | parse 통과 |
| classify.jsonl | 10 | 바뀜 | 같음 | classify 통과 |
| restore.jsonl | 6 | 바뀜 | 같음 | classify 통과 |
| geocode.jsonl | 33 | 바뀜 | 같음 | geocode 통과 |

옛 키였다면 네 경우 모두 `stale artifact`로 parse 또는 classify부터 다시 돌아야 했다(2절의 시 단위 합계
약 6분, 구 5개까지 약 10분). 판정 필드를 바꾼 줄이 낡음을 내는 것은 `tests/test_review_dependency_key.py`가
합성 데이터로 고정한다.

## 5. 검사

`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest`, `git diff --check`를
같은 작업 트리에서 실행해 모두 통과했다(`uv run pytest -q`: 932 passed).
