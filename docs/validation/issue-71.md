# 이슈 #71 판정 키가 담는 레코드 값 검증 기록

2026-09-13, Windows 11 · Git Bash · Python 3.12.10. 도시는 광주, 기관은 광주광역시청 하나다.
기준은 [ADR-0005](../adr/0005-key-only-what-the-decision-reads.md)이며, 그 앞의 결정은
[ADR-0003](../adr/0003-narrow-geocode-history-key.md)이다. 작업 브랜치의 기반은 `develop`
`e08c0b1`이다.

## 고친 것

- `lookup_key`가 레코드에서 담는 값을 `record_id`·`merchant`로 좁혔다. 목록은
  `identity.KEYED_RECORD_FIELDS` 한곳에 있고 `lookup_key`는 그 목록으로만 레코드를 담는다.
  `record_id`는 `lookup.scope`에도 있어 키에 두 번 들어가지만, 목록이 말하는 것은 판정이 레코드에서
  읽는 값이므로 조각에 남겼다(ADR-0005).
- `decide_identity`를 읽어 확정한 목록이다. 레코드에서 읽는 곳은 두 군데뿐이다 —
  `common`에 싣는 `record_id`·`merchant`와, 확정 복원명이 없을 때 근거와 맞춰 볼
  `expected_name`(= `record.merchant`)이다. `confirmation.record_id != record.record_id`는 범위가
  어긋난 입력을 막는 검사이며 `record_id`를 읽는 같은 자리다.
- `spent_on`·`department`·`purpose`·`amount_krw`·`source_location`·`repeats`는 키에서 빠졌다.
  `organization`·`source_hash`는 레코드에서는 빠지고, 그 조회가 어느 범위에 답한 것인지로서
  `lookup.scope`에 남아 키에 들어간다.
- 문서는 `docs/geocoding.md`의 식별자 표와 "의존성·이력·교체 경계" 절을 고쳤다.

## 실측 — 광주광역시청 재생성

`geocode` → `closure` → `build`를 다시 돌렸다. **외부 호출은 0회**다. 실행 전에 커밋된
`geocode.json`이 적은 조회 캐시 키 1,069개가 모두 `geocode-lookup-v1.jsonl`에 있고 revision까지
같으며 실패로 기록된 조회가 0건임을 확인했고, 실행 중에는 `socket.create_connection`·
`socket.getaddrinfo`를 막아 두었다. 네이버 검색 키 자리에는 값이 필요 없어 자리표시 문자열을 넣었고,
실행 뒤 `geocode-lookup-v1.jsonl`의 MD5가 그대로인 것으로 조회가 일어나지 않았음을 확인했다.

| 파일 | 전 | 후 |
| --- | --- | --- |
| `geocode-history-v2.jsonl` | 15,477,093바이트 · 6,975줄 | **바이트·MD5 그대로** |
| `geocode-history-v2.002.jsonl` | 10,993,975바이트 · 4,550줄 | **16,828,919바이트 · 6,775줄** |
| 이력 합계 | 26,471,068바이트 · 11,525줄 | 32,306,012바이트 · 13,750줄 |
| 늘어난 줄 | — | **2,225 (5,834,944바이트)** |
| `geocode.json` | 5,251,449바이트 | 5,251,449바이트(`lookup_key` 값만 다름) |
| `geocode-lookup-v1.jsonl` | 1,252,591바이트 · 1,069줄 | **MD5 그대로** |

늘어난 2,225줄은 판정 대상 전부다. 키 식이 바뀌었으므로 **이번 한 번은** 모두 새 키로 쌓인다
(ADR-0003이 같은 대가를 이미 치렀다). 조각 2는 상한까지 **3,171,081바이트**를 남긴다. 조각 1은
다시 쓰지 않았고 조각 3은 열리지 않았다. 두 조각 모두 20MB 아래다.

**판정은 하나도 바뀌지 않았다.** 2,225건을 옛 판과 칸별로 맞춰 본 결과 다른 칸은 `lookup_key`
하나뿐이고 나머지 열세 칸은 전부 같다. `status`는 성공 296 · 미확정 1,929이고 `reason`은
`missing_address` 1,673 · `human_confirmed` 296 · `no_candidates` 256으로 전과 같다. 새 키
2,225개는 모두 서로 다르다. `closure.json`은 payload가 같고 `geocode.json` 해시 한 칸만 바뀌었으며,
`build.json`도 payload(레코드 2,799 · 마커 12)가 같고 의존성 해시만 바뀌었다.

### 변경 없는 재실행

같은 명령을 한 번 더 돌렸다. 두 조각 모두 **MD5까지 같다**. 이력에 줄이 늘지 않는다.

### 판정에 쓰이지 않는 칸만 바꾼 재실행 (#63 상황 재현)

커밋된 `data/`를 복사해 레코드 100건에 겹친 출처(`repeats`)를 새로 달고 — #63의 병합이 한 것과 같은
성질의 변경이다 — `classify.json`의 `records.csv` 해시를 맞춘 뒤 geocode를 다시 돌렸다. 100건 중
판정 대상(식당)은 65건이다. 옛 키와 새 키를 같은 입력으로 각각 쟀다.

| | 옛 키(레코드 전체) | 새 키(`record_id`·`merchant`) |
| --- | --- | --- |
| 더해진 줄 | **65** | **0** |
| `geocode-history-v2.002.jsonl` | 10,993,975 → 11,180,899바이트 | **MD5 그대로** |

옛 키의 기준선도 함께 확인했다. 레코드를 건드리지 않고 옛 키로 돌리면 0줄이 는다. 곧 위의 65줄은
겹친 출처를 단 것만으로 늘어난 줄이다.

이 65줄이 이 이슈가 겨냥한 것이다. #63의 실제 실행에서는 `repeats` 칸이 **처음 생겼기** 때문에
겹친 출처를 얻지 않은 레코드의 `model_dump`까지 모두 달라져 2,225건 전부가 다시 쌓였다
([#64 검증](issue-64.md)). 이번 실측은 칸이 이미 있는 상태에서 값만 달라진 경우이며, 두 경우 모두
새 키에서는 0줄이다.

## 비용과 얻는 것

한 번에 5,834,944바이트를 더 쌓고, 레코드 계약이 늘거나 판정에 쓰이지 않는 값이 바뀔 때마다 내던
같은 성격의 비용을 그만 낸다. 2026-09에만 두 번 냈다 — [#59](issue-59.md)의 집계 세 칸이 2,325줄
(+4.92MB), [#63](issue-63.md)의 `repeats` 칸이 2,225줄(5,834,944바이트)이다. 뒤의 재생성은
`POLICY_VERSION`을 `identity-2`로 올린 실행이기도 해서 그 5.8MB 가운데 `repeats` 몫을 가릴 수는
없다. 다만 값이 빈 `repeats`도 키를 바꾸므로 그 칸 하나로도 전량이 다시 쌓인다는 것은 확실하다.
좁히지 않으면 `Record`에 칸이 하나 늘 때마다 같은 값을 다시 낸다.

## 남은 제한

- **원본의 행 번호가 밀리면 키는 여전히 바뀐다.** `source_location`을 뺐지만 `record_id`가
  `<원본 해시 앞 16자>-<표>-R<행>`이라 행 번호와 원본 해시를 이미 담고 있다. 이슈가 든 "행 번호가 한
  칸 밀리면 상호가 같아도 새 판정이 된다"는 이 변경으로 풀리지 않는다. 레코드의 이름을 무엇으로 할지는
  별개 결정이므로 이 기록에 남긴다.
- `lookup`·`confirmation`·`restoration`은 여전히 통째로 키에 들어간다. `CandidateLookup`에 칸이 하나
  늘면 `repeats`와 같은 일이 그대로 일어난다. 같은 논리를 그 계약들에도 적용할지는 후속 결정이며,
  `lookup.queries`(어느 제공자에게 물었고 어느 캐시 revision을 썼는지)를 키에서 뺄지가 핵심이다.
- `GeocodeResult.dependency_key`의 이름은 그대로 두었다. 계약이 `extra="forbid"`라 이름을 바꾸면
  쌓인 이력을 읽지 못한다. ADR-0003이 남긴 판단이며 이 이슈의 제외 범위다.
- `reconcile_coordinates`의 보류가 상대 레코드 변경으로 풀리지 않는 문제는 그대로다. 이 변경은 그
  규칙을 건드리지 않는다.
- 이슈의 병렬 메모는 [#66](https://github.com/snowjaewon/OfficialDeliciousMap/issues/66)의 재생성과
  같은 실행에서 처리하면 이력이 두 번 늘지 않는다고 적었다. #66은 `ready-for-human`이고 모델 키와
  담당자의 원본 대조를 기다리고 있어 함께 돌리지 못했다. 이 변경은 커밋된 `geocode.json`을
  `invalid-artifact`로 만들어 CI의 사이트 build를 멈추므로 재생성을 미룰 수 없다. #66이 레코드
  13건을 더할 때 이력은 그 몫만큼 다시 는다.
- 판정 대상 2,225건 가운데 확정은 296건(마커 12개)이고 나머지는 미확정이다. 이 실행은 그 분포를
  바꾸지 않는다.

## 자동 검사

| 검사 | 결과 |
| --- | --- |
| `uv sync --locked` | 통과 |
| `uv run ruff check .` | 통과 |
| `uv run ruff format --check .` | 102개 파일 통과 |
| `uv run mypy src` | 통과, 44개 소스 파일 |
| `uv run pytest` | **435 passed** |
| `node --test tests/site_behavior.test.js` | 통과 |
| `uv run python -m deliciousmap.ci check-data --data-root data` | `gwangju` |
| `git diff --check` | 통과 |
| gitleaks | pre-commit 훅으로 실행 |

이 이슈가 더한 테스트는 함수 6개(경우 13개)다. 다섯은 `tests/test_identity.py`의 판정 키 계약이다 —
레코드 계약의 모든 칸이 "키에 담는다/담지 않는다" 중 하나로 선언되었는지, 담지 않는 칸 8개를 바꿔도
**판정 결과 전체**가 같은지(판정이 그 칸을 읽기 시작하면 여기서 깨진다), 담는 칸은 키를 바꾸는지,
조회가 답한 범위는 여전히 키를 바꾸는지, 레코드 계약에 칸이 늘어도 키가 같은지를 본다. 하나는
`tests/test_geocoding_cli.py`에서 공개 CLI로 레코드의 다른 칸만 바꿔 재실행해도 판정을 재사용하고
이력이 바이트까지 그대로인 것을 본다.
