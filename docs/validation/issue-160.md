# 울산 남구·울주 산출물 재생성 (#160)

2026-09-15 실행. 기준점은 `HEAD` `1110d5ec2f5b709f06ff3188bd865f357b4b6223`이다.
원본은 저장소 밖 `C:\Users\설재원\deliciousmap-raw`에서 읽었고, `.env`는 실행 프로세스에만
로드했다.

## 재생성

- `ulsan-namgu`: `geocode`(실패 재시도) → `closure` → `build`
- `ulsan-ulju`: `parse` → `classify` → `geocode` → `closure` → `build`

울주 `parse.json`은 schema 4에서 현재 schema 5로 올라갔다. 대상 원본 6개에서 레코드는
0건이며, 기간 밖 원본 2개(`declared_out_of_range`)는 장부에 남겼다. 남구는 레코드 66건과
식당 판정 1건을 유지했고, `build`는 레코드 66건·마커 1건을 냈다. 울주는 레코드·마커가
각각 0건이다.

## Naver·식품 인허가 조회

남구 식당 레코드 `116b614e978728d0-table1-R3`의 조회 캐시를 새로 만들었다.

| 제공자 | 요청 수 | 후보 수 | 근거 |
| --- | ---: | ---: | --- |
| Naver 지역검색 | 1 | 5 | `data/ulsan/orgs/ulsan-namgu/geocode-lookup-v1.jsonl`의 `naver` 캐시 1줄 |
| 식품 인허가 조회서비스 | 3 (일반음식점·휴게음식점·제과점) | 145 (100·42·3) | 같은 파일의 `license` 캐시 1줄과 서비스별 `source_id` |

응답 원문·키는 커밋하지 않고 후보 사실과 캐시 참조만 남겼다. 인허가 후보에는 울산 남구
산업로 595의 영업 중 `경복궁` 1건이 포함된다.

## 판정 전·후

| 기관/산출물 | 재생성 전 | 재생성 후 |
| --- | --- | --- |
| 남구 `geocode` | 1건 `failed / lookup_error` | 1건 `success / human_confirmed` |
| 남구 `closure` | 결과 0건 | `unknown` 1건 (`license-evidence-not-supplied`) |
| 남구 `build` | 레코드 66건·마커 0건 | 레코드 66건·마커 1건 |
| 남구 `classify` | restaurant 1·non-restaurant 1·pending 64 | restaurant 1·non-restaurant 1·pending 64 |
| 울주 `parse` | schema 4 | schema 5, 레코드 0건 |
| 울주 `classify`·`geocode`·`closure`·`build` | 현재 코드로 로드 불가 또는 낡은 의존성 | 현재 schema·의존성으로 로드 가능, 모두 0건 |

남구의 `classify` 판정 자체는 전후 동일(restaurant 1, non-restaurant 1, pending 64)이며,
울주의 분류 대상 레코드는 0건이다. 남구 사람 확인은 기존 #132 승인 범위를 그대로 사용했고,
새로운 업소 추정은 하지 않았다.

## 확인 명령과 결과

저장소 루트에서 다음을 실행했다.

```text
uv run python -m deliciousmap.ci check-data --data-root data
# gwangju
# ulsan

uv run python -m deliciousmap build --city ulsan
# exit 0

uv run pytest tests/test_storage.py tests/test_ci.py tests/test_pipeline.py
# 66 passed

uv run pytest
# 810 passed in 46.96s

uv run ruff check src tests
uv run ruff format --check src tests
git diff --check
# all passed
```

The repository-standard commands above were executed with `uv run` after granting the
test process access to its external temporary directory. No source code or test changes
were made to bypass the `Paths.validate` safety check.

두 기관의 `fetch`, `headermap`, `parse`, `classify`, `geocode`, `closure`, `build`를
`ArtifactStore.load`로 각각 읽었고 모두 성공했다. `dist/`는 로컬 빌드 산출물이며 커밋하지
않는다. 실기기·지도 타일 검증은 이 이슈 범위에 포함하지 않는다.

로드 확인에 사용한 간단한 스크립트와 출력은 다음과 같다.

```text
@'
from pathlib import Path
from deliciousmap.contracts import BuildOutput, ClassifyOutput, ClosureOutput, FetchOutput, GeocodeOutput, HeaderMapOutput, ParseOutput
from deliciousmap.paths import Paths
from deliciousmap.registry import CITIES, select_target
from deliciousmap.storage import ArtifactStore
models = {"fetch": FetchOutput, "headermap": HeaderMapOutput, "parse": ParseOutput, "classify": ClassifyOutput, "geocode": GeocodeOutput, "closure": ClosureOutput, "build": BuildOutput}
paths = Paths(Path.cwd(), Path.cwd().parent / "deliciousmap-raw", Path("data"), Path("dist"))
for org in ("ulsan-namgu", "ulsan-ulju"):
    store = ArtifactStore(paths, select_target(CITIES, "ulsan", org))
    for stage, model in models.items():
        store.load(stage, model)
        print(f"{org} {stage}: loaded")
'@ | uv run python -
# each organization printed loaded for all seven stages
```

status: verified
