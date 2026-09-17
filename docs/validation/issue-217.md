# 이슈 #217 부산 재수집 검증 기록

2026-09-18, Windows 11 · Git Bash · Python 3.12.10. 도시는 부산, 기관은 레지스트리의 17곳에서
수집 보류 2곳(`busan-yeongdo` `bot_blocked` · `busan-saha` `board_lost`)을 뺀 15곳이다.

범위는 [#217](https://github.com/snowjaewon/OfficialDeliciousMap/issues/217)이 짚은 것 —
[#212](https://github.com/snowjaewon/OfficialDeliciousMap/issues/212)가 더한
`FetchOutput.unattached_postings`를 부산 산출물에 실제 수로 채우고, 그 게시글을 수집 장부에
남겨 다음 실행이 본문을 다시 열지 않게 하는 것 — 이다. 수집 코드는 건드리지 않았다.

기관·게시판별 원본 수와 DRM 비율은 이미 [`issue-140.md`](issue-140.md)에 있다. 이 문서는 거기
없던 **재수집 전후 차이**와 **모델 API 판정이 나간 사유**만 더한다.

## 장부가 담은 것

출처는 `data/busan/fetch.json`과 `data/busan/orgs/*/fetch.json` 열여섯 파일이다.

| 항목 | 전 | 후 | 단위 | 도출 |
| --- | ---: | ---: | --- | --- |
| 첨부 없는 게시글 | 0 | 140 | 게시글 | `payload.unattached_postings` (전에는 칸 자체가 없어 기본값 0) |
| 받아 둔 원본 | 4,049 | 4,072 | 원본 파일 | `payload.sources` 길이 |
| 받지 못한 원본 | 330 | 337 | 원본 파일 | `payload.missing` 길이 |
| 받지 않은 게시글 | 64,180 | 64,180 | 게시글 | `payload.uncollected_postings` 정수 |
| 걸러 낸 줄 | 0 | 0 | 줄 | `payload.filtered_postings` 정수 |

전 값은 `git show origin/develop:data/busan/fetch.json`, 후 값은 작업 트리의 같은 파일이다.

기관별 첨부 없는 게시글. `장부`는 원본 루트 `<기관>/<게시판>/collected.jsonl`에서 `files`도
유실 목록도 비어 있는 줄 수이고, `산출물`은 그 기관 `fetch.json`의 `unattached_postings`다.

| 기관 | 장부 | 산출물 |
| --- | ---: | ---: |
| busan-gangseo | 74 | 74 |
| busan-yeonje | 17 | 17 |
| busan-haeundae | 14 | 14 |
| busan-busanjin | 13 | 13 |
| busan-jung | 5 | 5 |
| busan-dongnae | 5 | 5 |
| busan-geumjeong | 4 | 4 |
| busan-suyeong | 3 | 3 |
| busan-buk | 2 | 2 |
| busan-dong · busan-nam · busan-sasang | 각 1 | 각 1 |
| busan-city · busan-seo · busan-gijang | 0 | 0 |
| **합계** | **140** | **140** |

`busan-sasang`의 1건은 완주한 수가 아니다. 그 게시판은 이번에도 끊겨(`service-unavailable`)
끝까지 훑지 못했으므로 그 기관의 값은 끊긴 지점까지의 수다.

## 게시글 회계

이슈는 「장부에 없는 게시글」을 389건으로 적었다. 그 수는 `period.targets`(게시일의 해 + 제목이
밝힌 지출 기간) 기준이고, 수집이 실제로 쓰는 판정은 `period.collects`(게시일의 해)다.
`collects` 기준으로 세면 아래와 같이 맞아떨어진다. 단위는 모두 게시글이다.

| 항목 | 수 | 도출 |
| --- | ---: | --- |
| 재수집 직전 장부에 없던 게시글 | 753 | `listing.jsonl`의 게시일이 2026년이고 `collected.jsonl`에 `post_id`가 없는 줄 |
| 재수집 중 목록에 새로 올라온 대상 게시글 | 32 | 같은 판정의 게시글 수 5,060 → 5,092 |
| **합계(이번 실행이 마주한 게시글)** | **785** | 위 둘의 합 |
| ├ 제목 조건에서 걸려 본문을 열지 않음 | 616 | 재수집 뒤에도 장부에 없는 게시글 전량 |
| ├ 본문을 열었고 첨부가 하나도 없음 | 140 | `unattached_postings` |
| └ 본문을 열었고 원본·유실이 있음 | 29 | 새 원본 23개·새 유실 7개가 달린 게시글의 고유 수 |

616건은 전부 `scrapers/busan.MixedRfc3Board.title_filter`(`추진비`)에 걸린 게시글이다 — 중구
201 · 수영 405 · 해운대 10. 이 세 기관은 정보공개 통합 게시판이라 업무추진비 아닌 글이 섞여
있고, 스크래퍼가 제목에서 가려 본문을 아예 열지 않는다. `MixedRfc3Board`는
`boards.FiltersRows`가 아니므로 이 616건은 `filtered_postings`에도 들지 않는다.

## 본문을 다시 열지 않는가

**전 기관 0건이다.** 판정은 네트워크 없이 `src/deliciousmap/collection.py`의 `_ledger().done`과
`_walk`의 `skip`으로 했다. 장부에 들어간 140건은 `done`에 들어 `skip`이 참이 되므로 본문 요청이
없고, 남은 616건은 `title_filter`에서 먼저 걸려 `_attachments`가 불리지 않는다.

## 재수집 중 있었던 실패·장애

| 항목 | 값 | 도출 |
| --- | --- | --- |
| 기관 수집 실패 | 0곳 | 15곳 모두 종료 코드 0 |
| 끊긴 게시판 | `busan-sasang/expenses` | `payload.empty_reason`의 `service-unavailable` |
| 새로 받지 못한 원본 | 7개 (전부 `drm`) | 시청 6 · 부산진 1, `missing[].reason` |
| 수집 보류 | 2곳 | 영도 `bot_blocked` · 사하 `board_lost` |

끊김은 [#197](https://github.com/snowjaewon/OfficialDeliciousMap/issues/197)에서 본 것과 같은
장애다. 이번 실행에서도 상반기 원본을 끝까지 받지 못했고, 사유는 산출물에 그대로 남는다.

## 모델 API 판정 4건과 그 사유

[폴백 정책](../specs/header-mapping-fallback.md)의 「헤더 매핑 판정 경로」는 2026-09-17 결정
이후의 판정을 에이전트 CLI가 착수하고, 모델 API 직접 호출은 CLI로 처리할 수 없는 건에만 쓰며
그 사유를 이 문서에 남기도록 한다. **이번 실행의 API 호출 4건은 그 예외에 해당하지 않는다.**
`headermap`을 `uv run --env-file .env`로 돌려 모델을 구성한 채 실행했고, 그래서 CLI가 착수하기
전에 API 경로가 먼저 판정했다. 경로 선택의 실수이며 2026-09-18 사용자 결정으로 되돌리지 않고
여기 기록한다.

| 항목 | 값 | 도출 |
| --- | --- | --- |
| 호출 | 4건 | `data/_shared/llm-budget.jsonl`에 예약·정산 각 4줄. 2026-09-18 `develop` 리베이스 뒤 7,844 → 7,852줄 |
| 예약 | USD 0.044820 | 같은 줄의 `kind: reservation` 합 |
| 정산 | USD 0.006894 | 같은 줄의 `kind: settlement` 합 |
| 누적 정산 | USD 9.462395 | 리베이스 뒤 장부 전체의 `settlement` 합 (한도 15). 리베이스 전에는 8.613713이었고, 늘어난 0.848682는 인천(#218)의 `classification` 288줄이다 |
| 새 답변 | 4건 | `data/busan/headermap-answers-v1.jsonl` 1,062 → 1,066줄, 모두 `gemini-3.6-flash` |

호출이 난 자리는 재수집이 새로 가져온 부산진구 원본 2건이다.

| 원본 | 표 | 캐시 후보 | 재검증 | 호출 |
| --- | --- | ---: | --- | ---: |
| `3977708-195196.xlsx` (`8b277a58bb3f811f`) | sheet1 | 1 | 실패 `sheet1:R6 spent_on` | 1 |
| | sheet2 | 1 | 실패 `sheet2:R6 spent_on` | 1 |
| | sheet3 | 1 | 통과 | 0 |
| `3977707-195195.xlsx` (`61ebcfbcbb212b43`) | sheet1 | 1 | 실패 `sheet1:R6 spent_on` | 1 |
| | sheet2 | 1 | 실패 `sheet2:R6 spent_on` | 1 |
| | sheet3 | 1 | 통과 | 0 |

**헤더 서명이 캐시에 없어서 부른 것이 아니다.** 여섯 표 모두 공통 캐시
(`data/_shared/headermap.jsonl`)에 후보가 하나씩 있었고, 그중 넷이 `headermap._failure`의
재검증에서 6행의 집행일 칸으로 걸렸다. `_map_table`은 캐시 후보가 있으면 재호출을 한 번만
허용하므로(`1 if cached else 2`) 표당 1회씩 넷이 나갔다. 새로 채택된 매핑은 캐시에 이미 있는
값과 같아 캐시는 938줄 그대로다.

재현(양쪽 공통, 저장소 루트):

```bash
uv run python -c "import json, pathlib; from deliciousmap import grid, headermap; from deliciousmap.contracts import SourceRef; from deliciousmap.paths import Paths; p = Paths(pathlib.Path.cwd(), pathlib.Path.cwd().parent / 'deliciousmap-raw', pathlib.Path('data'), pathlib.Path('dist')); pl = json.loads(pathlib.Path('data/busan/orgs/busan-busanjin/fetch.json').read_text(encoding='utf-8'))['payload']; [print(s['source_hash'][:16], t.name, len(headermap._cached(SourceRef.model_validate(s), t, p.shared('headermap'))), [headermap._failure(SourceRef.model_validate(s), t, c) for c in headermap._cached(SourceRef.model_validate(s), t, p.shared('headermap'))]) for s in pl['sources'] if s['source_hash'].startswith(('8b277a58bb3f811f', '61ebcfbcbb212b43')) for t in grid.read_tables(p.raw_root / SourceRef.model_validate(s).path)]"
```

멈춘 뒤의 도시 단위 `headermap`은 모델 자격증명 없이 돌려 추가 호출이 생길 수 없게 했다. 그
실행 뒤 예산 장부·답변 장부(1,066줄)·공통 캐시(938줄)의 줄 수가 모두 그대로였다.

## `headermap` 낡음

열여섯 `headermap.json` 모두 `dependencies["fetch.json"]`이 짝이 되는 `fetch.json`의
`storage.artifact_digest`와 같다. 낡음 0이다.

```bash
uv run python -c "import json, pathlib; from deliciousmap import storage; rows = [pathlib.Path('data/busan')] + sorted(p for p in pathlib.Path('data/busan/orgs').iterdir() if (p / 'headermap.json').exists()); bad = [d.name for d in rows if json.loads((d / 'headermap.json').read_text(encoding='utf-8'))['dependencies']['fetch.json'] != storage.artifact_digest(d / 'fetch.json')]; print('checked', len(rows), 'stale', bad)"
```

도시 산출물의 헤더 매핑은 2,600 → 2,609건, 판단 보류는 947건 그대로, 보류 매핑은 917 → 919건이다.

## 남은 제한

- 대상 기간 원본이 7개 늘어(`시청` 5 · `부산진` 2) `parse.json`이 그 원본을 덮지 못한다.
  `storage._validate_reports`는 보고가 대상 기간 원본을 한 번씩 모두 덮기를 요구하므로
  `build --city busan`이 `invalid-artifact`로 거부된다. `parse` 이후 단계의 재실행 여부는
  이슈의 「제외 범위」대로 사람이 정한다.
- 제목 조건에서 걸린 616건은 `unattached_postings`에도 `filtered_postings`에도 들지 않는다.
  어느 수로도 세지 않는 게시글이 남는다는 사실만 여기 적는다.
