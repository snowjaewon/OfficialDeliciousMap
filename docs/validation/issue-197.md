# 이슈 #197 사상구 `expenses` 끊김 장부 검증 기록

2026-09-17, Windows 11 · Git Bash · Python 3.12.10. 도시는 부산, 기관은 `busan-sasang`
하나다. 그 기관의 게시판은 `expenses` 하나뿐이므로 아래 기관 수치가 곧 게시판 수치다.

범위는 [#197](https://github.com/snowjaewon/OfficialDeliciousMap/issues/197)이 짚은 것 —
끊김이 남긴 265/17/407을 해시까지 포함해 확정하고, `fetch`를 다시 한 번 돌려 서버가
안정됐는지 확인하는 것 — 이다. 수집 코드는 건드리지 않았다.

기관·게시판별 수, DRM 비율, 2026년 게시글이 빠짐없다는 확인은 이미
[`issue-140.md`](issue-140.md)에 있다. 이 문서는 거기 없던 **원본 해시**와 **끊김·재시도
실측**만 더하고, 나머지는 #140을 가리킨다.

## 장부가 담은 것

출처는 `data/busan/orgs/busan-sasang/fetch.json` 한 파일이고, 인용하는 값은
`FetchOutput`의 `sources`·`missing`·`uncollected_postings`·`empty_reason` 넷뿐이다.

| 항목 | 값 | 도출 |
| --- | --- | --- |
| 원본 | 265 | `payload.sources` 길이 |
| 받지 못한 원본 | 17 (전부 `drm`) | `payload.missing` 길이 · `reason` 집계 |
| 받지 않은 게시글 | 407 | `payload.uncollected_postings` 정수 |
| 끊김 사유 | `collection failures: busan-sasang/expenses=service-unavailable` | `payload.empty_reason` |
| DRM 첨부 확장자 | `.hwp` 11 · `.xls` 6 | `missing[].filename` 확장자 집계 |
| 게시일 범위 | 2026-01-01 ~ 2026-09-08 | `sources[].posted` 최소·최대 |
| 게시판 | `expenses` 하나 | `sources[].board` 고유값 |

컨테이너별 내역(ole2·pdf·hwpx·ooxml)과 DRM 비율은 [`issue-140.md`](issue-140.md)의 기관별
표에 이미 있으므로 여기 다시 적지 않는다. 아래 명령은 그 값도 함께 낸다 — 같은 장부 한 파일을
읽으므로 두 문서가 어긋날 자리는 없다.

양쪽 공통(Git Bash·PowerShell)으로 저장소 루트에서 위 표를 그대로 다시 내는 명령:

```bash
uv run python -c "import json, collections, pathlib; d = json.loads(pathlib.Path('data/busan/orgs/busan-sasang/fetch.json').read_bytes()); pl = d['payload']; s = pl['sources']; print('sources', len(s)); print('missing', len(pl['missing']), dict(collections.Counter(r['reason'] for r in pl['missing']))); print('uncollected', pl['uncollected_postings']); print('empty_reason', pl['empty_reason']); print('containers', dict(sorted(collections.Counter(r['container'] for r in s).items()))); print('posted', min(r['posted'] for r in s), max(r['posted'] for r in s)); print('boards', sorted({r['board'] for r in s}))"
```

## 원본 해시

`source_hash`는 내려받은 원본 바이트의 SHA-256(`collection.py`의
`hashlib.sha256(body).hexdigest()`)이다. 265건이 서로 다른 해시를 가지며 — 중복 없음 —
저장소 밖 원본 파일을 다시 읽어 265건 모두 장부의 해시와 같다는 것을 확인했다.

| 항목 | 값 | 도출 |
| --- | --- | --- |
| 고유 `source_hash` | 265 (= 레코드 수, 중복 0) | `len(set(sources[].source_hash))` |
| 파일 바이트와 일치 | 265 / 265 (불일치 0, 없는 파일 0) | 각 `sources[].path`를 다시 SHA-256 |
| 해시 묶음 SHA-256 | `f235e6776f57b8caeee3dba6f678fc1790f96ae222b5d303bf9e7a73fe2bad4a` | 265개 해시를 정렬해 줄바꿈으로 이은 문자열의 SHA-256 |
| 장부 파일 SHA-256 | `d5b344f8834e92e4cd549850779683d454574ceea32fb9e8ad3f0016b6f7417b` | `fetch.json` 파일 바이트 (140,525 B) |

양쪽 공통(Git Bash·PowerShell), 저장소 루트:

```bash
uv run python -c "import json, hashlib, pathlib; p = pathlib.Path('data/busan/orgs/busan-sasang/fetch.json'); b = p.read_bytes(); s = json.loads(b)['payload']['sources']; ok = sum(pathlib.Path(r['path']).exists() and hashlib.sha256(pathlib.Path(r['path']).read_bytes()).hexdigest() == r['source_hash'] for r in s); print('match', ok, '/', len(s), 'unique', len({r['source_hash'] for r in s})); print('rollup', hashlib.sha256(chr(10).join(sorted(r['source_hash'] for r in s)).encode()).hexdigest()); print('ledger', hashlib.sha256(b).hexdigest(), len(b))"
```

원본 파일 자체는 저장소 밖(`--raw-root`, 기본 `../deliciousmap-raw`)에 있고 커밋하지 않는다.
해시만 장부와 이 문서에 남는다.

## 재실행 — 서버는 여전히 끊는다

Git Bash, 저장소 루트. 시각과 걸린 시간을 함께 남기려고 감싸 돌렸다.

```bash
date -Iseconds && start=$(date +%s) \
  && uv run python -m deliciousmap fetch --city busan --org busan-sasang; \
  echo "exit=$? elapsed=$(( $(date +%s) - start ))s"
# 2026-09-17T11:14:52+09:00
# exit=0 elapsed=77s
```

표준 출력·표준 오류에 찍힌 것은 없다. 끊김은 `empty_reason`으로만 남으므로 종료 코드 0이
성공을 뜻하지 않는다 — 결과는 **`service-unavailable` 그대로**다.

| | 재실행 전 | 재실행 후 |
| --- | --- | --- |
| 원본 | 265 | 265 (변화 없음) |
| 받지 못한 원본 | 17 (`drm`) | 17 (`drm`) (변화 없음) |
| 받지 않은 게시글 | 407 | 407 (변화 없음) |
| 사유 | `busan-sasang/expenses=service-unavailable` | 같음 |
| 장부 SHA-256 | `fd03400f6dc438ad36fc1a6dcc18d0707dad69e8e4e9e20bf45d10ffdd69189e` | `d5b344f8834e92e4cd549850779683d454574ceea32fb9e8ad3f0016b6f7417b` |

새로 받은 원본은 한 건도 없다 — 저장소 밖 게시글 장부(`collected.jsonl` 282줄)와 원본 파일
265개가 2026-09-14 수집 때 그대로다.

**장부 파일은 그래도 바뀌어 커밋한다.** 바뀐 것은 수가 아니라 **빈 자리 둘**이다. 재실행 전
장부는 지금 코드보다 앞선 실행이 쓴 것이라 그 뒤에 생긴 필드를 담고 있지 않았다.

| 새로 붙은 자리 | 값 | 왜 비어 있나 |
| --- | --- | --- |
| `payload.filtered_postings` | `0` | 업무추진비가 아닌 줄을 걸러 내는 수(`contracts.py`). 사상구 게시판은 섞인 게시판이 아니라 거를 줄이 없다 |
| `payload.sources[].spent_on` (265건 전부) | `null` | ADR-0008의 상세 키 집행일. 사상구는 `Rfc3Board`라 상세 키가 집행일을 밝히지 않는다 |

나머지는 모두 같다 — `sources`의 순서와 `source_hash` 집합, `missing`,
`uncollected_postings`, `empty_reason`, `schema_version`(4), 그리고 `city`·`org`·
`dependencies`. 아래 명령은 **키 집합까지** 비교하므로 새로 붙은 자리도 잡아낸다(값만
비교하면 새 키는 옛 장부에 없어서 눈에 띄지 않는다). 양쪽 공통(Git Bash·PowerShell),
저장소 루트:

```bash
uv run python -c "import json, pathlib, subprocess; old = json.loads(subprocess.run(['git','show','15e2d87:data/busan/orgs/busan-sasang/fetch.json'], capture_output=True).stdout); new = json.loads(pathlib.Path('data/busan/orgs/busan-sasang/fetch.json').read_bytes()); a, b = old['payload'], new['payload']; print('top added', set(new) - set(old), 'removed', set(old) - set(new)); print('payload added', set(b) - set(a), 'removed', set(a) - set(b)); print({k: a[k] == b[k] for k in sorted(set(a) & set(b))}); print('record added', set(b['sources'][0]) - set(a['sources'][0]))"
```

`15e2d87`(이 브랜치의 분기점, 재실행 전 장부)에 대고 돌리면 이렇게 나온다. `develop`이
앞으로 나아가도 이 SHA는 그대로라 나중에도 같은 값이 나온다.

```text
top added set() removed set()
payload added {'filtered_postings'} removed set()
{'empty_reason': True, 'missing': True, 'sources': False, 'uncollected_postings': True}
record added {'spent_on'}
```

## 끊김과 재시도 실측

프로젝트 UA(`OfficialDeliciousMap/0.1 (+https://github.com/snowjaewon/OfficialDeliciousMap)`)로
순차 요청했고, 브라우저 UA나 우회는 쓰지 않았다. 설정은 `boards.py`가 고정한 값 그대로다 —
`REQUEST_ATTEMPTS = 4`, `REQUEST_BACKOFF = 2.0`(2·4·8초), `REQUEST_TIMEOUT = 30.0`,
`REQUEST_INTERVAL = 0.2`. 이 값들은 #197의 범위 밖이라 바꾸지 않았다.

아래 여섯 줄을 시간 순서대로 한 번씩 돌렸다. 도출 명령은 표 다음에 같은 순서로 둔다.

| # | 실측 | 결과 |
| --- | --- | --- |
| 1 | 목록 1쪽을 20회 반복 (0.2초 간격) | 20/20 http 200, 22,499 B |
| 2 | 흩어진 깊은 쪽 13개 (1·2·100·200·300·355·358~362·365·370) | 13/13 http 200 |
| 3 | 1~120쪽 순차 (0.2초 간격) | 120/120 http 200, 실패 0 |
| 4 | 1쪽부터 순차, 재시도 없이(`attempts=1`) | **241쪽에서 끊김**, 216.6초 지점 |
| 5 | 그 직후 1쪽, 프로젝트 설정(4회·2/4/8초) | **4회 모두 끊김**, 15.9초 소모 후 실패 |
| 6 | 그 직후 1쪽 단발 → 30초 뒤 1쪽 단발 | 1회차 끊김 → 2회차 http 200 (31.4초 지점) |

끊김의 밑바닥 예외는 `http.client.RemoteDisconnected: Remote end closed connection without
response`이고, 이것이 `BoardUnavailable` → `FailureCause.SERVICE_UNAVAILABLE`로 올라온다.

**그래서 재시도가 모자란다.** 4회 시도가 기다리는 시간은 2+4+8 = 14초인데, 위 실측에서
호스트가 다시 200을 준 것은 14초와 31초 사이다. 한 번 끊기면 남은 재시도가 전부 같은 끊김을
맞고 게시판이 `service-unavailable`로 끝난다. UA 차단도 속도 제한도 아니다 — 쉬었다 보내면
같은 주소가 200을 준다. 재시도 값을 바꾸는 일은 이 이슈의 범위 밖이라 여기서는 재지 않았고
고치지도 않았다.

끊기는 자리는 실행마다 다르다. 이번 `fetch` 재실행이 본 게시글은 689건(= 장부 282건 + 미수집
407건, 단위는 게시글)이고, 재시도 없는 4번 실측은 241쪽까지 갔다(단위는 목록 쪽). 세는 단위가
달라 두 값을 빼지 않는다 — 둘 다 "끝까지 가지 못했다"는 사실만 말한다. `issue-140.md:427`이
적은 "at a different page each run"이 그대로다.

### 도출 명령

1~3은 `curl`로, 4~6은 프로젝트 전송기로 쟀다. 모두 Git Bash · 저장소 루트다. 기관 서버에
부담을 주는 요청이므로 필요한 만큼만 돌렸다.

**1~3** — `$UA`는 `boards.USER_AGENT`와 같은 문자열이고, `$PAGES`만 바꿔 세 번 돌렸다
(`$(seq 1 20)`로 1쪽 20회 · `1 2 100 200 300 355 358 359 360 361 362 365 370` · `$(seq 1 120)`).

```bash
UA="OfficialDeliciousMap/0.1 (+https://github.com/snowjaewon/OfficialDeliciousMap)"
for p in $PAGES; do
  curl -s -o /dev/null -w "$p %{http_code} %{size_download}\n" -A "$UA" --max-time 30 \
    "https://www.sasang.go.kr/board/list.sasang?boardId=BBS_0000175&startPage=$p"
  sleep 0.2
done
```

**4~5** — 끊기는 쪽과 재시도가 그것을 넘기는지. `attempts`만 바꿔 두 번 돌렸다
(4는 `attempts=1`, 5는 `attempts=boards.REQUEST_ATTEMPTS, backoff=boards.REQUEST_BACKOFF`).

```bash
uv run python -c "
import time
from deliciousmap import boards

transport = boards.HttpTransport(
    timeout=boards.REQUEST_TIMEOUT,
    interval=boards.REQUEST_INTERVAL,
    attempts=1,
)
start = time.time()
for page in range(1, 401):
    try:
        boards.request(
            transport,
            'https://www.sasang.go.kr/board/list.sasang',
            {'boardId': 'BBS_0000175', 'startPage': str(page)},
        )
    except Exception as err:
        cause = err.__cause__ or err.__context__
        print(f'break page={page} {time.time() - start:.1f}s {type(err).__name__} {type(cause).__name__}')
        break
"
# break page=241 216.6s BoardUnavailable RemoteDisconnected   (attempts=1)
# break page=1    15.9s BoardUnavailable RemoteDisconnected   (attempts=4, backoff=2.0)
```

**6** — 끊긴 뒤 호스트가 언제 돌아오는지. 재시도 없이 30초 간격으로 다시 물었다.

```bash
uv run python -c "
import time, urllib.request
from deliciousmap import boards

url = 'https://www.sasang.go.kr/board/list.sasang?boardId=BBS_0000175&startPage=1'
start = time.time()
for i in range(1, 21):
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=boards.HEADERS), timeout=30
        ) as response:
            print(f'{time.time() - start:6.1f}s try={i} 200 {len(response.read())} bytes')
            break
    except Exception as err:
        print(f'{time.time() - start:6.1f}s try={i} {type(err).__name__}')
    time.sleep(30)
"
#    0.3s try=1 RemoteDisconnected
#   31.4s try=2 200 22499 bytes
```

## 407은 총량이 아니라 하한이다

`uncollected_postings`는 **이번 훑기가 본** 게시글 중 장부에 없고 대상 기간(2026년) 밖인 것의
수다(`collection.py`의 `uncollected += 1`). 끊김이 훑기의 꼬리를 자르므로 그 수는 게시판이
가진 기간 밖 게시글의 총량이 아니라 **끊긴 지점까지의 하한**이다.

재실행마다 그 수가 튀는 것이 같은 말이다. [#197 본문](https://github.com/snowjaewon/OfficialDeliciousMap/issues/197)이
`fetch --org busan-sasang`를 45초 간격으로 15회 돌려 잰 폭이 407~3,317이고, 그때도 `sources`는
265건으로 고정이었다 — 훑은 깊이만 다르다. (그 폭은 #197이 잰 값이고 `issue-140.md`에는 없다.
#140이 적은 것은 끊기는 쪽이 실행마다 다르다는 것까지다: `issue-140.md:427`
"at a different page each run".)

게시판이 실제로 가진 게시글은 그보다 많다. 목록 색인(`listing.jsonl`, 저장소 밖)에는 여러
실행이 쌓은 3,600건이 있고 그중 2026년 게시글은 283건, 장부에 든 게시글은 282건이다.
**283 대 282의 뜻 — 남는 한 건이 첨부를 아예 내지 않는 글이라는 것 — 은 #140이 이미 밝혔고
(`dataSid=565106`), 여기서는 그 판단을 다시 내리지 않고 오늘 날짜로 세 수가 그대로임만
확인한다.**

즉 **2026년 원본은 빠짐없고(#140), 끊김이 앗아 가는 것은 기간 밖 꼬리의 계수뿐**이다.
장부는 그것을 0건이나 성공으로 숨기지 않고 `empty_reason`에 사유를 적는다.

양쪽 공통(Git Bash·PowerShell), 저장소 루트. 읽는 파일은 저장소 밖이다:

```bash
uv run python -c "import json, collections, pathlib; p = pathlib.Path('../deliciousmap-raw/busan/busan-sasang/expenses'); lines = (p / 'listing.jsonl').read_text(encoding='utf-8').splitlines(); print('listing', len(lines), '2026', collections.Counter(json.loads(l).get('posted', '')[:4] for l in lines)['2026']); print('collected', len((p / 'collected.jsonl').read_text(encoding='utf-8').splitlines()))"
```

## 검사

양쪽 공통(Git Bash·PowerShell), 저장소 루트. 모두 통과했다.

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
git diff --check
```
