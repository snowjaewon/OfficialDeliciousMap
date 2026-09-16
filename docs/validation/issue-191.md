# 이슈 #191 geocode 재실행 비용 검증 기록

2026-09-17, Windows 11 · Git Bash · Python 3.12.10. 도시는 광주, 기관은 도시 전체다.
범위는 [#191](https://github.com/snowjaewon/OfficialDeliciousMap/issues/191)이 짚은 세 가지
되풀이 읽기 — `ArtifactStore.load`의 상류 재검증, `_validate(FetchOutput)`의 루프 불변
`resolve()`, 업소 판정 이력의 세 번 읽기 — 를 고치기 전과 후의 비교다.

## 잰 방법

저장소 `data/`를 직접 돌리지 않는다. `data/gwangju`·`data/manual`·`data/_shared`를 scratchpad로
복사하고 `--data-root`를 그 사본에 건다. `--raw-root`는 커밋된 `fetch.json`이 가리키는 원본 루트
그대로다(geocode는 원본 파일을 열지 않고 경로만 검사한다). Git Bash에서:

```bash
cp -r data/gwangju data/manual data/_shared "$SCRATCH/data/"
set -a && . ./.env && set +a
uv run python "$SCRATCH/measure.py" geocode --city gwangju \
  --data-root "$SCRATCH/data" --raw-root ".../deliciousmap-raw"
```

`measure.py`는 `deliciousmap.cli.main`을 `cProfile`과 `time.monotonic()`으로 감싼 열 줄짜리
래퍼다. 산출물에 남지 않는 일회용 측정 도구라 저장소에 두지 않았다.

두 수치는 **같은 PC·같은 사본·같은 수렴 상태**에서 잇달아 잰 쌍이다. 사본은 이미 한 번 돌려
새 조회가 0건이므로 조회 대기가 없다. 두 실행 모두 `cause=lookup-failed`로 끝나는데, 이력에 남은
`lookup_error` 때문이며 저장은 그 전에 끝난다. 이슈 본문의 첫 실행 4:59·warm 80.3s와는 새 조회
건수와 디스크 상태가 달라 직접 빼지 않는다.

## 실측 — 광주 도시 geocode warm 재실행

| 비용 | 고치기 전 | 고친 뒤 |
| --- | --- | --- |
| 전체 시간 | 102.2s | **52.2s** |
| 함수 호출 수 | 55,499,918 | **17,618,772** |
| `ArtifactStore._validate` (cumtime) | 46.21s (13/4회) | **6.32s** (4/3회) |
| └ `_validate_reports` | 43.10s (5회) | **4.87s** (1회) |
| `Path.resolve` | 27.50s (175,864회) | **2.03s** (11,730회) |
| `read_cache` | 12.90s (4회 / 조각 38개 읽기) | **6.46s** (3회 / 조각 21개 읽기) |
| `previous_geocodes` | 16.50s | 15.62s |
| `ProviderQuery.consistent_query` (범위 밖) | 16.82s (209,574회) | 14.94s (209,574회) |

`_validate_reports` 5회 → 1회가 "parse를 다섯 번 읽던 것"이다. 그때마다 원본 11,724건을 다시
검증했고, 그 검증이 원본마다 `resolve()`를 세 번 불러 175,864회가 됐다. 조각 읽기 38 → 21이
"이력을 한 번만 읽는다"다 — 남은 21개는 업소 판정 이력 17 + 조회 캐시 3 + 업종 캐시 1이며,
전에는 판정 이력 17개를 두 번 읽었다.

**아끼는 것과 아끼지 못하는 것.** 산출물 재사용은 파일을 읽지 않게 하지 않는다 — `_signature`가
산출물·장부·`dependencies`의 지문을 내느라 그 바이트는 여전히 읽는다. 없어지는 것은 JSON 파싱과
pydantic 계약 검증이고, `_validate_reports` 43.10s → 4.87s가 그 몫이다. 업소 판정 이력
(258,022,809바이트, `ls -l data/gwangju/geocode-history-v2*.jsonl`)은 지문값이 아낀 읽기를 도로
먹으므로 지문으로 무효화하지 않고, 이 파일을 쓰는 `save` 한 곳에서 든 값을 버린다. 처음에는
이력도 지문으로 무효화했는데 그때는 59.5s였다 — 지문 두 벌이 7.3s를 도로 먹었다.

## 입력 규모

| 값 | 수 | 도출 |
| --- | --- | --- |
| 원본 | 11,724 | `data/gwangju/fetch.json`의 `payload.sources` 길이 |
| 이력 조각 | 17 | `ls data/gwangju/geocode-history-v2*.jsonl \| wc -l` |
| 이력 줄 | 46,192 | `cat data/gwangju/geocode-history-v2*.jsonl \| wc -l` |
| 이력 바이트 | 258,022,809 | `ls -l data/gwangju/geocode-history-v2*.jsonl` 합 |
| 도시 geocode 산출물 | 77.6MB | `data/gwangju/geocode*.json` 합 |

## 산출물이 바뀌지 않았다는 확인

고치기 전·후 실행을 마친 뒤 사본의 `geocode*.json`(4조각)·`geocode-history-v2*.jsonl`(17조각)·
`geocode-lookup-v1*.jsonl`(3조각) 24개 파일의 SHA-256이 저장소의 것과 모두 같다.

```bash
cd "$SCRATCH/data/gwangju" && sha256sum geocode*.json geocode-history-v2*.jsonl \
  geocode-lookup-v1*.jsonl | diff "$SCRATCH/repo.sha" -   # 차이 없음
```

저장소 작업 트리의 `data/`는 이번 실행이 손대지 않았다.

## 남은 것

`ProviderQuery.consistent_query`(209,574회, 14.9s)와 `previous_geocodes`(15.6s)의 pydantic 검증은
이슈가 범위 밖으로 둔 그대로다. 지금 warm 52.2s의 가장 큰 덩어리는 그쪽이다.
