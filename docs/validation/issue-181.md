# 이슈 #181 조회 캐시 쓰기 실측

2026-09-16, Windows 11 · Git Bash · Python 3.12 · uv(`.tools/uv/bin`).
범위: [조회 캐시를 추가마다 통째로 다시 써 조회 수의 제곱으로 느려진다 #181](https://github.com/snowjaewon/OfficialDeliciousMap/issues/181).
대상은 `LookupCache`의 쓰기 경로다. 제공자 호출은 재지 않았다.

## 1. 무엇을 쟀나

커밋된 울산 조회 캐시 `data/ulsan/geocode-lookup-v1.jsonl`(2,403줄 / 10,666,842바이트,
`wc -lc data/ulsan/geocode-lookup-v1*.jsonl`)를 임시 폴더로 복사하고, 그 사본에 새 조회 200건을
`LookupCache.remember_candidates()`로 담았다. 값은 같은 캐시 앞 200줄의 `value`를 새 키로 다시 썼다.
실제 조회 한 건과 같은 크기다.

- 쓰기 바이트: `storage.write_bytes`를 감싸 넘긴 바이트를 더하고, 대기 파일
  `geocode-lookup-v1.pending.jsonl`은 합치기 직전 크기를 더했다.
- 시간: `time.perf_counter()`로 열기·조회 200건·합치기를 따로 쟀다.
- 변경 전은 `git worktree add <scratch>/before de77cf4`로 꺼낸 `src`를 `PYTHONPATH` 앞에 두어 같은
  스크립트를 돌렸다. 변경 전 코드에는 `with`가 없어 조회마다 캐시에 바로 쓴다.

```text
uv run --no-sync python <scratch>/bench.py 200 data/ulsan/geocode-lookup-v1.jsonl
PYTHONPATH=<scratch>/before/src uv run --no-sync python <scratch>/bench.py 200 data/ulsan/geocode-lookup-v1.jsonl
```

스크립트는 측정용이라 커밋하지 않았다.

## 2. 결과

| 값 | 변경 전 (`de77cf4`) | 변경 후 |
| --- | --- | --- |
| 캐시 교체(`os.replace`) 바이트 | 2,238,964,706 | 11,602,161 (합치기 1회) |
| 대기 파일 덧붙이기 바이트 | 0 | 935,319 |
| 조회 한 건당 쓰기 바이트 | 11,194,824 | 4,677 (덧붙이기) + 실행당 합치기 1회 |
| 조회 200건 시간 | 130.90초 | 0.16–0.18초 |
| 합치기 시간 | — | 1.00–1.07초 |
| 전체 시간 | 131.06초 | 1.45–1.52초 |
| 캐시 교체 횟수 | 200 | 1 |
| 결과 캐시 줄 수 | 2,603 | 2,603 |

변경 전은 1회, 변경 후는 3회 잰 값이다. 변경 후 한 건당 덧붙이기(935,319 ÷ 200)는 캐시 크기와
무관하다. 캐시 크기에 비례하는 비용은 실행 끝 합치기 한 번만 남는다.

## 3. 완료 기준 대조

| 기준 | 근거 |
| --- | --- |
| 조회 한 건 추가가 캐시 전체 크기에 비례하지 않는다 | 2절. `tests/test_storage.py`의 `test_lookup_cache_does_not_rewrite_the_cache_per_lookup`가 조회 중 캐시 바이트가 그대로인 것을 고정한다 |
| 실행이 끊겨도 받은 조회가 캐시에 남는다 | `test_lookup_cache_keeps_lookups_of_an_interrupted_run`(닫지 못한 실행, 쓰다 끊긴 끝 줄), `test_lookup_cache_merges_its_own_lookups_even_if_another_run_took_the_journal`, `test_lookup_cache_keeps_the_original_failure_when_merging_also_fails` |
| 기존 커밋된 캐시를 그대로 읽고 이어 쓴다 | 캐시 형식·키·정렬은 그대로다. 2절이 커밋된 울산 캐시에 이어 써 2,603줄을 다시 읽었다 |
| `pytest`·`ruff check`·`ruff format --check` | 904 passed, All checks passed, 174 files already formatted |

## 4. 남은 제한

- 실제 `geocode` 실행의 벽시계 시간은 재지 않았다. 제공자 호출이 필요해 이 측정에서 뺐다.
- `os.replace` 재시도는 넣지 않았다. 한 실행의 캐시 교체가 조회 수만큼에서 캐시당 한 번으로 줄었다.
  그래도 합치기 한 번이 `WinError 5`를 만나면 실행은 실패한다. 대기 파일은 남으므로 다시 돌리면 이어서 합친다.
- 같은 도시를 두 실행이 동시에 돌리는 것은 여전히 지원하지 않는다. 같은 revision이 다른 값으로 겹치면
  합치기가 `cannot overwrite cache history`로 멈추고 대기 파일을 남긴다.
