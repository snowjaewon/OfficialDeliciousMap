# Issue #154 검증 — 중랑구 게시판 목록 순회 재개

## 원인

중랑구 목록은 853쪽을 1쪽부터 차례로 요청한다(쪽 수는 `docs/validation/issue-141.md`의
"실패한 게시판"). 한 쪽 요청이 재시도 4회를 다 쓰고도 끊기면(`service-unavailable`) 그 실행의
순회는 거기서 끝나고, 다음 실행은 늘 1쪽부터 다시 훑었다. 원본을 함께 받는 실제 수집은 열세 번
모두 끝 쪽에 닿지 못했고(#154 본문 실측 표 "13회 모두 순회 미완주". `issue-141.md`는 당시까지의
열두 번으로 적었다), 그래서 `uncollected_postings`·`filtered_postings`가 "셀 수 없음"을 0으로 적었다.

## 고른 방법 — 순회를 이어서 한다

이슈의 세 갈래 중 1번(순회 재개)을 골랐다. 목록만 훑은 측정이 853쪽을 완주했다는 것은 호스트가
끝까지 응답한다는 뜻이고, 문제는 한 번의 실행이 끝까지 버티지 못하면 앞서 훑은 쪽이 모두
버려진다는 것이었다. 재개하면 실행마다 한 쪽이라도 넘기는 한, 실행을 거듭해 순회가 끝난다.

- 2번(목록과 원본 분리)은 명령 계약(`fetch` 한 단계)과 장부 흐름을 바꾸고, 3번(호스트별 재시도
  확대)은 끊김이 몰리면 여전히 1쪽부터다. 둘 다 고르지 않았다.
- **재시도 횟수·백오프·호스트 간격은 바꾸지 않았다**(`boards.REQUEST_ATTEMPTS`·
  `REQUEST_BACKOFF`·`HOST_INTERVALS` 그대로). 그래서 그 효과를 측정할 값이 없다.

### 동작

- 수집(`collection._walk`)이 게시판 디렉터리의 `listing-progress.json`에 다음 쪽 번호·그때까지
  걸러 낸 수·게시판 주소를 남긴다. 원본과 같이 저장소 밖(`--raw-root`)에 있다.
- 서울 목록 게시판(`scrapers.seoul.ListingBoard`와 그 계열 전부)은 한 쪽의 마지막 게시글을
  호출자가 처리한 뒤, 다음 쪽을 요청하기 **전에** 그 쪽 번호를 알린다
  (`boards.ResumesListing.resume`의 `settle`). 마지막 게시글의 첨부를 받다 끊기면 그 쪽을
  끝냈다고 알리지 않았으므로 다음 실행이 그 쪽부터 다시 훑는다. 수집 기록(`collected.jsonl`)이
  게시글 단위라 다시 훑어도 두 번 받지 않는다. 다른 도시의 스크래퍼는 `resume`이 없어 그대로다.
- 쪽을 넘길 때마다 목록 색인(`listing.jsonl`)을 먼저 쓰고 진행 기록을 쓴다. 프로세스가 통째로
  죽으면(강제 종료·메모리 부족) `finally`가 돌지 않으므로, 진행 기록이 색인보다 앞서 가지 않게
  하는 순서다.
- 사람이 봐야 하는 첨부(실측하지 않은 형식·원본이 아닌 응답)를 만난 뒤로는 진행 기록을 넘기지
  않는다. 그 목록은 끝에 한 번에 알리고 기록하지 않으므로, 넘겼다고 쓰면 이어 간 실행이 그 첨부를
  다시 보지 않아 서울이 받아들이지 않는 형식이 성공으로 숨는다.
- 마지막 쪽까지 훑으면 진행 기록을 지운다. 다음 실행은 새로 올라온 게시글을 보도록 1쪽부터다.
- 스크래퍼는 파일을 쓰지 않는다(`boards.BoardScraper`는 저장하지 않는다는 계약). 게시판 주소가
  레지스트리에서 바뀌었거나, 기록을 읽지 못하거나, 목록 색인이 없으면 1쪽부터 훑는다.

### `uncollected_postings`의 단위

- 1쪽부터 훑은 실행은 전과 같이 이번 순회에서 본 게시글 중 끝내지 않았고 게시일이 대상 연도
  밖인 게시글을 센다. 이 경로는 바뀌지 않았다 — 다른 도시·기관의 값은 그대로다.
- 이어 간 실행은 앞선 실행이 넘긴 쪽을 다시 읽지 않는다. 그 쪽의 게시글은 목록 색인에 있으므로
  색인 전체에서 **같은 판정**(수집 기록에 없고 `period.collects`가 거짓)으로 센다. 단위는
  게시글 하나이고, 이미 받은 게시글은 세지 않는다.
- `filtered_postings`는 진행 기록에 남긴 수에서 이어서 센다.

### 한계

- 이어 간 실행은 끊긴 사이에 1쪽에 새로 올라온 게시글을 보지 않는다. 그 게시글은 순회를 마친 뒤의
  다음 실행(1쪽부터)이 받는다. 끊긴 사이에 게시글이 지워져 줄이 앞 쪽으로 밀리면 넘긴 쪽으로
  들어간 줄을 그 실행이 놓칠 수 있다 — 이것도 다음 1쪽 실행이 본다.
- 이어 간 실행의 수는 색인에 남은 옛 게시글(그 뒤 게시판에서 지워진 것)도 센다. 1쪽부터 훑은
  실행은 세지 않는다.
- 쪽을 넘길 때마다 색인 전체를 다시 쓴다. 아래 실측의 색인은 1,269,785바이트(`ls -la`)이고 853쪽이면
  그만큼을 쪽마다 쓴다. 853쪽 순회 시간(약 47분, #154 본문)에 비하면 작다고 보고 두었다.

## 자동 검증

합성 중랑 목록 두 쪽(대상 연도 게시글 1건, 그 밖 게시글 1쪽·2쪽 각 1건)으로
`tests/test_seoul.py`에 고정했다.

| 테스트 | 고정한 것 |
| --- | --- |
| `test_an_interrupted_jungnang_walk_resumes_where_it_stopped` | 2쪽에서 끊긴 첫 실행은 `service-unavailable`과 1건, 이어 간 실행은 2쪽만 요청하고 경고 없이 2건, 그다음 실행은 1쪽부터 다시 2건 |
| `test_a_jungnang_walk_keeps_the_pages_it_passed_before_asking_the_next` | 2쪽을 요청하는 순간 1쪽 게시글이 이미 목록 색인에 있다 |
| `test_a_resumed_walk_still_reports_an_original_it_could_not_accept` | 원본이 아닌 응답을 만난 쪽을 넘긴 것으로 쓰지 않아, 다음 실행도 `unsupported-format`으로 멈춘다 |
| `test_a_walk_starts_over_when_the_progress_record_is_not_this_listings` | 다른 주소·`next_page` 1·음수나 `true`인 걸러 낸 수·빠진 키·깨진 JSON이면 1쪽부터 |
| `test_a_walk_starts_over_when_the_listing_index_is_gone` | 진행 기록이 있어도 색인이 없으면 1쪽부터 훑고 수를 온전히 센다 |
| `test_listing_resumes_at_the_page_it_is_given` | 주어진 쪽부터 요청하고 걸러 낸 수를 이어서 센다 |
| `test_listing_settles_a_page_only_after_its_rows_are_consumed` | 쪽의 마지막 게시글을 넘겨준 직후에는 그 쪽을 끝냈다고 하지 않는다 |

기존 `tests/test_gwangju_fetch.py::test_fetch_keeps_originals_collected_before_the_reporting_years`
(이미 받은 게시글은 받지 않은 게시글로 세지 않는다)가 그대로 통과한다.

```text
uv run pytest            # 양쪽 공통
uv run ruff check .
uv run ruff format --check .
uv run mypy src
git diff --check
```

결과는 PR 본문에 적는다.

## 실측 — 설재원 PC의 한 번 실행 (커밋하지 않음)

2026-09-15 Codex 세션이 빈 원본 루트로 한 번 실행했다.

```powershell
.venv\Scripts\python.exe -m deliciousmap fetch --city seoul --org seoul-jungnang --raw-root 'C:\Temp\odm-raw-154' --data-root data --output-root dist
```

| 값 | 측정 | 출처 |
| --- | --- | --- |
| 시작·끝 | 첫 원본 13:37:52, 목록 색인 마지막 쓰기 14:30:47 (약 53분) | 원본·`listing.jsonl`의 수정 시각 |
| 원본 받기 | `collected.jsonl` 마지막 쓰기 13:49 | 같은 디렉터리 수정 시각 |
| `empty_reason` | 없음 — `collection failures` 없이 끝났다 | 그 실행이 쓴 `fetch.json` |
| `sources` | 574건, `source_hash`가 커밋본 574건과 전부 같다 | 두 `fetch.json`의 해시 집합 비교 |
| `uncollected_postings` | 7,981 | 그 실행이 쓴 `fetch.json` |
| `filtered_postings` | 0 | 같음 |
| 목록 색인 | 8,523줄. 그중 게시일이 2026년 밖 7,981줄, 그 7,981줄 중 수집 기록에 있는 게시글 0건 | `wc -l`, 색인·`collected.jsonl` 대조 |
| 수집 기록 | 540줄(게시글) | `wc -l collected.jsonl` |
| 진행 기록 | 끝난 뒤 남지 않았다 | `listing-progress.json` 없음 |

- **이 실행은 끊기지 않고 한 번에 끝났다. 재개 경로를 거치지 않았으므로 재개가 완주를 만들었다는
  증거가 아니다.** 원본을 함께 받는 실행도 끝까지 갈 수 있다는 것까지만 보여 준다.
- 이 실행은 이 PR의 최종 코드가 아니라 Codex의 첫 구현(`4617a5b` 무렵)으로 돌았다. 그 구현은
  색인 전체에서 기간 밖 게시글을 셌다. 수집 기록에 있는 게시글 중 기간 밖이 0건이라 이 PR의 판정으로
  세어도 7,981이다(위 색인 대조). 이 수는 게시글 단위이며 `issue-141.md` 표의 다른 기관 값과 같은
  단위다.
- 이 `fetch.json`은 `sources` 경로가 `C:\Temp\odm-raw-154` 아래라서 커밋하지 않았다(2026-09-15 사용자
  결정). 원본은 그 경로에 그대로 있다.

## 서울 담당 PC의 재수집 — 2026-09-17 실측 (커밋한 실행)

위 실측은 재개 경로를 거치지 않은 한 번의 실행이었고, 커밋한 `fetch.json`도 아니었다. 2026-09-17에
서울 담당 PC에서 이 저장소의 원본 루트로 다시 받았다. **이 실행이 재개 경로를 실제로 거쳤고, 그
결과가 커밋된 `fetch.json`이다.**

```powershell
uv run python -m deliciousmap fetch --city seoul --org seoul-jungnang --raw-root "C:\Users\pc\orca\workspaces\OfficialDeliciousMap\deliciousmap-raw"
```

| 값 | 측정 | 출처 |
| --- | --- | --- |
| 실행 횟수 | 2회. 1회차가 264쪽에서 `service-unavailable`로 끊기고, 2회차가 265쪽부터 이어 853쪽까지 | 1회차 뒤 `listing-progress.json`의 `next_page` 265 |
| 1회차 | 264쪽까지, 17:10:04 종료. 그때 목록 색인 2,640줄, `uncollected_postings` 2,091, `empty_reason`에 `collection failures` | 1회차가 쓴 `fetch.json`·`listing.jsonl`, 진행 기록 |
| 2회차 | 남은 589쪽을 17:10~17:39:40에 약 29분(쪽당 약 3.0초)만에 마쳤다 | 1회차 종료 시각과 `listing.jsonl` 마지막 쓰기 시각 |
| 전체 쪽 수 | 853쪽 | `issue-141.md`의 "실패한 게시판". 이 실행이 따로 센 값이 아니다 |
| `empty_reason` | 없음 — `collection failures`가 남지 않았다 | 커밋한 `fetch.json` |
| `uncollected_postings` | 7,981 | 같음 |
| `filtered_postings` | 0 | 같음 |
| `sources` | 581건 (`ole2 10 · ooxml 31 · pdf 540`) | 같음 |
| `missing` | 0건 | 같음 |
| 수집 기록 | 547줄(게시글) | `wc -l collected.jsonl` |
| 진행 기록 | 끝난 뒤 남지 않았다 | `listing-progress.json` 없음 |

- **재개가 완주를 만들었다.** 1회차 혼자서는 264쪽에서 끝났고, 이어 간 2회차가 남은 589쪽을 마쳤다.
  전에는 이 지점에서 다음 실행이 1쪽부터 다시 훑었다.
- `uncollected_postings` 7,981은 위 Codex PC 실측과 같은 값이고 게시글 단위다. `issue-141.md`
  수집 장부 표의 중랑 줄과 합계에 반영했다.
- 원본이 574건에서 **원본** 581건으로 늘었다. 두 `fetch.json`의 `source_hash` 집합을 비교하면
  574건은 전부 그대로 있고 **원본 7건**이 더해졌다. 그 원본 7건은 **게시글 7건**에 하나씩 달린
  것이고(수집 기록도 540줄에서 547줄로 늘었다), 게시일이 2026-09-15~17인 새 게시글
  (`167689`·`167698`·`167701`·`167702`·`167703`·`167705`·`167706`)이다. `period.collects`가
  게시일의 해로 자르므로 2026년 게시글은 받는다. 제목이 밝힌 지출 기간이 대상 기간 밖인지는
  `parse` 이후가 가른다.
- **재시도 횟수·백오프·호스트 간격은 이 재수집에서도 바꾸지 않았다.** 그래서 그 값의 효과를
  측정한 수는 여전히 없다.
- **1회차의 증거는 지금 다시 볼 수 없다.** 진행 기록은 순회를 마칠 때 지워지고 `fetch.json`은
  2회차가 덮어쓰므로, 위 표의 1회차 줄(264쪽·`next_page` 265·2,091)은 그 실행 중에 읽은 값이고
  커밋된 산출물로 되짚을 수 없다. 지금 커밋본에서 확인되는 것은 완주의 결과뿐이다 —
  `empty_reason` 없음, `listing.jsonl` 8,530줄, `collected.jsonl` 547줄, 진행 기록 없음.
  재개 경로 자체는 `tests/test_seoul.py`의 위 테스트들이 고정한다.
