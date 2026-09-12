# 이슈 #59 제외 원본 집계 검증 기록

2026-09-12, Windows 11 · Git Bash · Python 3.12.10. 도시는 광주, 기관은 광주광역시청 하나다.
범위는 [#51 3부](issue-51.md)가 남긴 "기간 미표기로 빠진 수를 산출물에 남길지"의 구현이다.

## 결정

사용자 결정(2026-09-12): **요약 집계만 남긴다.** 원본별 전량 기록은 `fetch.json`의 게시일·제목으로
재계산 가능한 것을 10,862줄로 중복 저장하고 파일이 약 1MB 늘어 택하지 않았다. 아무것도 남기지
않는 안은 아래 감시 지점을 잃어 택하지 않았다.

## 실측 — 광주광역시청 원본 11,035개

| 갈래 | 원본 수 |
| --- | --- |
| 대상 | **173** |
| `posted_out_of_range` — 게시일이 대상 연도 밖이거나 없다 | 10,786 |
| `declared_out_of_range` — 게시일은 2026인데 제목의 기간이 대상 밖이다 | 76 |
| `undeclared_in_year` — 게시일은 2026인데 제목이 기간을 밝히지 않았다 | **0** |

마지막 줄이 감시 지점이다. 0이 아니게 되면 읽지 못한 표기 때문에 대상이 조용히 빠졌다는 뜻이고,
그때는 그 표기를 실측해 `period.DECLARATION`에 더해야 한다.

집계는 대상을 고르는 쪽(`ArtifactStore.excluded_sources`)이 수집 장부에서 센다. 어댑터는 대상만
받으므로 이 수를 알지 못한다. **수집 장부는 줄지 않는다** — `fetch.json`은 11,035개를 그대로 싣는다.

## 실행

`parse` 산출물 스키마를 1에서 2로 올렸으므로 뒤 단계를 모두 다시 만들었다.

```text
uv run --env-file .env python -m deliciousmap <단계> --city gwangju --raw-root ../deliciousmap-raw
```

| 단계 | 결과 |
| --- | --- |
| parse | 종료 코드 0. 원본 173개 보고, 집계 10,786 / 76 / 0 |
| classify | 종료 코드 0. **모델 호출 0회** |
| geocode | 종료 코드 0. 네이버 조회 0회(`geocode-lookup-v1.jsonl` 변화 없음) |
| closure | 종료 코드 0 |
| build | 종료 코드 0. **레코드 2,921 · 마커 0** |

`records.csv`·`fetch.json`·`headermap.json`은 바뀌지 않았다. 공개 파일도 바이트까지 같다
(`records.json` 1,140,080바이트 · `markers.json` 69바이트). 공통 LLM 예산은 **USD 0.653 그대로**다.

## 화면

자료 범위 다이얼로그에 한 줄이 늘었다.

```text
게시글 원본 11,035개 중 대상 173개 (기간 미표기 제외 0개)
```

원본을 세지 않은 산출물에는 이 줄을 내지 않는다. 0개라고 적으면 없는 사실을 지어내는 것이다.

## 찾은 것 — 지오코딩 이력이 재실행마다 통째로 늘어난다

`geocode-history-v2.jsonl`이 **9.84MB에서 14.76MB로 늘었다**(2,325줄 추가, +4.92MB).

`geocode_dependency_key`는 `records.csv`·`parse.json`·`classify.json`의 해시를 묶어 만든다
(`storage.py`). 이번에 `parse.json`이 바뀌자 그 키가 바뀌었고, 모든 레코드의 `lookup_key`가 새
키가 되어 판정 2,921건 중 식당 2,325건이 전부 `revision: 1`로 다시 쌓였다. **값은 같고 키만 새것이다.**

그리고 `append_cache_entries`는 `require_size`를 부르지 않는다. 이 파일에는 ADR-0001의 20MB
상한이 걸려 있지 않아 조용히 넘을 수 있다. 지금 여유는 5.24MB이고, 같은 성격의 상류 변경 한 번이
약 4.9MB를 더한다.

사용자 결정(2026-09-12): 이번에는 이력을 그대로 싣는다. 이력은 "이 입력으로 이렇게 판정했다"는
장부이고, 파일을 작게 만들려고 되돌리면 판정 기록과 산출물이 어긋난다. 분할 기준과 의존성 키는
[#29](https://github.com/snowjaewon/OfficialDeliciousMap/issues/29)와 별도 이슈로 다룬다.

## 자동 검사

| 검사 | 결과 |
| --- | --- |
| `uv run ruff check .` | 통과 |
| `uv run ruff format --check .` | 83개 파일 통과 |
| `uv run mypy src` | 통과, 39개 소스 파일 |
| `uv run pytest` | **348 passed** (#51 시점 331에서 17개 추가) |
| `git diff --check` | 통과 |
| gitleaks 8.30.1 | pre-commit 훅으로 실행 |

## 남은 일

- 지오코딩 이력의 분할 기준과 의존성 키 — 20MB 상한에 걸리기 전에 정해야 한다
- 제목이 기간을 밝히지 않은 게시글의 표기를 더 실측할지는 `undeclared_in_year`가 0이 아니게 될 때 정한다
- #51이 남긴 나머지(미해결 원본 19개, 마커 0, 자치구 5곳, 누적 재게시 118묶음)는 그대로다
