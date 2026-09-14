status: verified

# 도시·기관 산출물 재생성 범위와 대조

도시 산출물과 기관 산출물은 `classify`의 같은 레코드 판정을 공유한다. `check-data`는 기관
`classify.json`의 각 `record_id`가 도시 판정에 있고 두 판정 객체가 같은지 대조한다. 기관 파일이
없는 수집 전용 대상은 비교하지 않는다. 지오코딩은 기관 범위가 판정 키에 들어가므로 이 대조의
대상이 아니다.

## 대조가 지금의 어긋남을 잡는다

대조를 넣은 커밋(`c501ecc`)에서 산출물을 고치기 전에 저장소 루트에서 실행했다(양쪽 공통).

```text
uv run python -m deliciousmap.ci check-data --data-root data
```

```text
check-data: city/organization classify mismatch: ulsan/ulsan-bukgu/6fffeb8d806f3c4a-table1-R3
```

종료 코드는 1이다. 이슈가 적은 울산 1건이며 광주는 걸리지 않는다.

## 울산 북구 재생성

`data/ulsan/orgs/ulsan-bukgu/`를 `classify`·`geocode`·`closure`·`build` 순서로 다시 냈다.
`.env`에서 `NAVER_SEARCH_*`·`NAVER_MAP_*`·`DATA_GO_KR_KEY`만 싣고 `GEMINI_*`는 뺐다. 모델
호출은 막았고, `classify`는 공통 캐시(`data/_shared/classify.jsonl`)만 읽었다.

| 산출물 | 이전(`HEAD`) | 재생성 |
| --- | --- | --- |
| `classify.json` 판정 58건 | `restaurant` 1 / `pending` 57 | `restaurant` 2 / `pending` 56 |
| `6fffeb8d806f3c4a-table1-R3` | `pending` (`unclassified: model_not_configured`) | `restaurant` (도시와 같은 캐시 판정) |
| `geocode.json` 결과 | 1건, `lookup_error`(`not_supplied`) | 2건, 둘 다 `missing_address` |
| `closure.json`·`build.json` | — | `dependencies`만 바뀜 |

판정이 바뀐 레코드는 R3 1건뿐이다. 이전 기관 `geocode`는 조회 키 없이 돌아 `파리바게트`가
`not_supplied`였다. 이번에는 키를 실어 R3와 `파리바게트`를 조회했다(Naver 2회, 식품 인허가 2회,
`geocode-lookup-v1.jsonl` 4줄). 둘 다 주소를 하나로 좁히지 못해 `missing_address`로 남으며,
도시 산출물의 R3도 `missing_address`다. 표의 수는 재생성 전 `git show HEAD:<파일>`과 재생성 후
파일을 `record_id`로 대조해 셌다.

## 확인

재생성 뒤 저장소 루트에서 실행했다(양쪽 공통).

```text
uv run python -m deliciousmap.ci check-data --data-root data
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest
git diff --check
```

`check-data`는 `gwangju`·`ulsan`을 내고 종료 0이다. pytest는 804개가 통과했다. 대조 로직의
불일치·기관 전용 레코드 테스트는 `tests/test_ci.py`에 있다.

## 재생성 계약

`classify` 판정 코드 또는 그 입력(레코드·파싱·사람 보정·복원)이 바뀌면 도시와 모든 기관의
`classify`부터 후속 `geocode`·`closure`·`build`까지 한 변경 범위에서 다시 생성한다. 도시만
다시 생성한 커밋은 기관 산출물을 낡게 만들며, `check-data`의 도시·기관 판정 대조를 통과하지
못한다.

## 남은 제한

- 대조는 판정 결과만 본다. 판정 코드가 바뀌었는데 결과가 같으면 잡지 않는다.
- 울산 남구·울주의 `geocode.json`은 이 이슈 전부터 `dependencies`가 현재 사람 확인·상호 정책과
  다르다. 기관 `classify` 대조와 무관해 이번 범위에서 다시 내지 않았다.
