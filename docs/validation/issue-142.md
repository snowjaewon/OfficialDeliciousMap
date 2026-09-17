# 부산 열세 기관 파이프라인 실측 (#142)

검증일 2026-09-17. 원본은 저장소 밖 `C:\Users\pc\orca\workspaces\OfficialDeliciousMap\deliciousmap-raw`
(기본 `--raw-root`)에서 읽었고 저장소로 복사하지 않았다. `.env`는 실행 프로세스에만 실었다.

[2026-09-15 중단 기록](https://github.com/snowjaewon/OfficialDeliciousMap/issues/142#issuecomment)은
원본 3,519건 가운데 존재하는 파일이 0건이라 착수하지 못했다고 적었다. 이번 환경에서는 그 경로가
그대로 있어 3,519건 전부를 읽었다(아래 1절). 이슈의 두 번째 댓글은 `data/busan/fetch.json`만 있고
기관별 산출물이 없다고 적었으나 실제 상태는 반대였다 — `data/busan/orgs/*/fetch.json` 13개가 있었고
도시 `fetch.json`이 없었다. 도시 산출물은 이번에 기관 것을 합쳐 만들었다(4절).

## 0. 이번 실행이 따른 사용자 결정 둘

둘 다 이슈 본문의 구현 범위에 없던 일이고, 실행 중에 실측을 보고 사용자가 정했다. 범위를 넘은
자리를 감추지 않으려고 여기 먼저 적는다.

1. **후보 조회를 네이버 우선으로 바꾼다** (2026-09-17 결정). 인허가 조회가 네이버보다 약 13배
   느려 도시 실행 시간을 지배했다. 앞 제공자가 후보를 낸 레코드는 뒤 제공자에게 묻지 않는다.
   이것은 코드 변경이며 부산만이 아니라 모든 도시의 다음 실행에 걸린다. 결정과 잃는 것
   (제공자 합의가 운영 조회로 서지 않음)은 [ADR-0011](../adr/0011-ask-providers-in-order.md)에
   적었다(6절).
2. **부산 주소 접두와 청사 열셋을 실측해 선언한다** (2026-09-17 결정). 접두가 없으면 채택이 서지
   않아 마커가 0개다. 이슈의 완료 기준은 "마커가 0개면 그 사유를 적었다"도 허용하지만, 사용자가
   실측해 선언하는 쪽을 골랐다. 선언 뒤 마커 1,530개가 나왔다(7절). 레지스트리 데이터만 더하고
   판정 규칙과 `identity.POLICY_VERSION`은 건드리지 않았다.

## 1. 원본 대조 — 3,519건 전부 일치

`data/busan/orgs/*/fetch.json`의 `source_hash`와 `--raw-root` 아래 실제 파일의 SHA-256을 맞댔다.
불일치 0건, 없는 파일 0건이다. 저장소 루트, Git Bash:

```bash
uv run python -c "
import json,pathlib,hashlib
ps=sorted(pathlib.Path('data/busan/orgs').glob('*/fetch.json'))
ok=bad=gone=0
for p in ps:
    for s in json.loads(p.read_text(encoding='utf-8'))['payload']['sources']:
        f=pathlib.Path(s['path'])
        if not f.exists(): gone+=1; continue
        ok+= hashlib.sha256(f.read_bytes()).hexdigest()==s['source_hash']
        bad+= hashlib.sha256(f.read_bytes()).hexdigest()!=s['source_hash']
print('ok',ok,'mismatch',bad,'absent',gone)"
```

출력: `ok 3519 mismatch 0 absent 0`. 원본 해시는 3,513개가 고유하고, 같은 해시가 한 기관 안에서
거듭 나온 것이 6건이다(시청 2·동구 1·금정 3).

## 2. fetch — 받은 것과 받지 않은 것

수집은 #140이 한 것이고 이 이슈는 그 산출물을 입력으로 삼았다. 아래는 이번에 다시 읽은 값이다.

| 기관 | 원본 | 받지 못함 | 받지 않은 게시글 | 컨테이너 |
| --- | ---: | ---: | ---: | --- |
| `busan-city` | 409 | 105 | 10,198 | ooxml 406 · hwpx 3 |
| `busan-jung` | 405 | 0 | 10,406 | ooxml 226 · ole2 170 · pdf 9 |
| `busan-seo` | 128 | 0 | 937 | ooxml 101 · ole2 27 |
| `busan-dong` | 118 | 0 | 682 | pdf 86 · hwpml 28 · ole2 2 · hwpx 1 · ooxml 1 |
| `busan-busanjin` | 480 | 16 | 4,338 | ooxml 446 · pdf 34 |
| `busan-dongnae` | 119 | 0 | 2,538 | ole2 41 · hwpx 40 · pdf 27 · ooxml 11 |
| `busan-buk` | 298 | 31 | 2,942 | hwpx 140 · ole2 128 · pdf 21 · ooxml 9 |
| `busan-haeundae` | 289 | 51 | 4,163 | ooxml 218 · ole2 62 · pdf 9 |
| `busan-geumjeong` | 402 | 15 | 5,949 | hwpx 241 · ole2 111 · pdf 50 |
| `busan-yeonje` | 280 | 0 | 3,645 | ooxml 241 · hwpx 39 |
| `busan-suyeong` | 326 | 0 | 8,593 | ooxml 296 · ole2 30 |
| `busan-sasang` | 265 | 17 | 407 | ole2 215 · pdf 26 · hwpx 15 · ooxml 9 |
| `busan-gijang` | 0 | 0 | 2,690 | (없음) |
| **합계** | **3,519** | **235** | **57,488** | |

두 기관의 `empty_reason`은 그대로 남아 있다.

- `busan-sasang`: `collection failures: busan-sasang/expenses=service-unavailable`. 훑기가 끊겼고
  받지 않은 게시글 407은 그 게시판의 바닥값이지 전체가 아니다([#140 기록](issue-140.md)).
- `busan-gijang`: `no attachment published on busan-gijang/expenses`. 게시판의 `<tr>` 하나가 지출
  한 줄이고 첨부가 없다. 이 이슈에서 추출 경로를 더하지 않았으므로 원본은 0건이고 지출 후보도
  0건이다. 받지 않은 게시글 2,690이 그 게시판에 남아 있다는 사실을 대신 싣는다.

보류 네 기관은 수집 자체가 없다: `busan-yeongdo`·`busan-nam`·`busan-gangseo`는 `bot_blocked`,
`busan-saha`는 `board_lost`다. 도시 `fetch.json`의 `empty_reason`이 이 넷을 이름과 사유로 싣는다.

## 3. 미지원 형식 — 0건으로 숨기지 않았다

도시 `headermap`의 미해결 883건과 그 사유다. `parse`는 같은 883건에 `no_candidates` 72건을 더해
955건을 미해결로 남겼다.

| 사유 | 건수 | 뜻 |
| --- | ---: | --- |
| `unsupported_format` | 504 | OLE2 컨테이너인데 엑셀 통합문서가 아니다. HWP 5.0이며 현재 추출 경로가 없다 |
| `validation_failed` | 369 | 표는 읽었으나 매핑이 코드 검증을 통과하지 못했다 |
| `unreadable` | 7 | 통합문서를 열지 못했다 |
| `no_table` | 3 | 표를 하나도 찾지 못했다 |
| `no_candidates` | 72 | 표는 읽었으나 지출 후보 줄이 0이다. 집행 없음으로 통과시키지 않았다 |

`unsupported_format` 504건은 기관별로 `busan-sasang` 137 · `busan-jung` 104 · `busan-buk` 94 ·
`busan-geumjeong` 85 · `busan-dongnae` 27 · `busan-seo` 20 · `busan-dong` 20 · `busan-haeundae` 17이다.
사상구가 가장 많은 것은 그 기관 원본 265건 중 215건이 OLE2이기 때문이다.

이 이슈는 HWP 5.0 파서도 기장군 HTML 표 파서도 더하지 않았다. 이슈 본문의 작업 분류표가 그 둘을
다른 세션 몫으로 나눴고, 여기서는 "미지원 형식으로 원본 수·지출 후보 수를 장부에 남긴다"는 쪽을
골랐다. 근거는 위 표와 산출물의 `sources[].reason`이다.

## 4. 도시 산출물 병합

기관 `fetch.json` 13개를 도시 `fetch.json` 하나로 합쳤다. 원본을 바꾸거나 레코드를 만들지 않았고,
`empty_reason`은 기관별 사유를 `;`로 이어 붙인 뒤 보류 네 기관을 덧붙였다. 합친 결과는 2절의
합계와 같다(원본 3,519 · 받지 못함 235 · 받지 않은 게시글 57,488).

`fetch --city busan`을 다시 돌리지 않은 것은 그 명령이 게시판을 다시 훑기 때문이다. 받지 않은
게시글이 57,488건 남아 있어 다시 훑으면 이 이슈의 범위 밖인 수집을 새로 하게 된다.

## 5. parse·classify — 레코드 9,831건

대상 기간은 `2026-01-01/2026-06-30`이다. 도시 실행 기준으로 `parse`가 원본 2,368건을 살펴
1,413건을 읽었고 지출 후보 12,409줄에서 레코드 9,831건을 냈다. 기간 밖으로 뺀 원본은
`declared_out_of_range` 1,143 · `posted_out_of_range` 0 · `undeclared_in_year` 3이다.
누적 재게시(ADR-0004)로 합쳐 본 지출은 8건이다.

| 기관 | 레코드 | 식당 | 비식당 | 판단 보류 |
| --- | ---: | ---: | ---: | ---: |
| `busan-city` | 4,382 | 3,034 | 623 | 725 |
| `busan-suyeong` | 833 | 514 | 181 | 138 |
| `busan-busanjin` | 749 | 394 | 283 | 72 |
| `busan-jung` | 711 | 519 | 90 | 102 |
| `busan-haeundae` | 676 | 360 | 255 | 61 |
| `busan-seo` | 464 | 331 | 73 | 60 |
| `busan-yeonje` | 421 | 277 | 104 | 40 |
| `busan-dong` | 401 | 306 | 44 | 51 |
| `busan-dongnae` | 387 | 208 | 100 | 79 |
| `busan-geumjeong` | 382 | 223 | 76 | 83 |
| `busan-buk` | 357 | 210 | 94 | 53 |
| `busan-sasang` | 65 | 33 | 26 | 6 |
| `busan-gijang` | 0 | 0 | 0 | 0 |
| **기관 합계** | **9,828** | **6,409** | **1,949** | **1,470** |
| **도시 실행** | **9,831** | **6,643** | **1,995** | **1,193** |

기관 합계와 도시가 레코드 3건 다른 것은 같은 원본이 두 기관의 수집 장부에 함께 들어 있어
도시에서 한 번만 세어지기 때문이 아니라, 도시 `parse`가 기관 경계를 넘어 재게시를 합쳐 보기
때문이다. 식당·비식당·판단 보류가 갈리는 것은 비식당 판별이 상호 단위 캐시를 쓰기 때문이며,
도시 실행이 기관 실행 뒤에 돌아 캐시가 더 차 있었다.

## 6. 조회 — 네이버 우선으로 바꾼 자리

### 무엇을 재고 바꿨나

처음 도시 `geocode`는 옛 순서(레코드마다 두 제공자를 모두 물음)로 돌았고 **1시간 37분 동안
조회 1,811건(목표 6,760건의 27%)** 을 받았다. 두 제공자의 응답 시간을 같은 질의 다섯 개로 쟀다.
저장소 루트, Git Bash:

```bash
uv run python -c "
import os,pathlib,time,statistics
for line in pathlib.Path('.env').read_text(encoding='utf-8').splitlines():
    line=line.strip()
    if line and not line.startswith('#') and '=' in line:
        k,v=line.split('=',1)
        if v.strip(): os.environ[k.strip()]=v.strip()
from deliciousmap import naver, licenses
for name, p in (('naver', naver.from_environment(None)), ('license', licenses.from_environment(None))):
    t=[]
    for q in ['할매국밥','부산밀면','동래파전','돼지국밥집','해운대횟집']:
        s=time.perf_counter(); p.search(q); t.append(time.perf_counter()-s)
    print(name, f'median={statistics.median(t):.2f}s min={min(t):.2f}s max={max(t):.2f}s')"
```

출력: `naver median=0.27s min=0.23s max=0.50s`, `license median=3.43s min=2.40s max=5.55s`.
약 13배 차이다. 사용자 결정으로 [ADR-0011](../adr/0011-ask-providers-in-order.md)의 순서를 넣었고,
인허가에 물을 상호가 **3,380건에서 655건으로 80.6% 줄었다**. 네이버 조회 3,490건 가운데 2,835건
(81.2%)이 후보를 냈고 655건이 비었다.

바꾸기 전 받아 둔 조회는 버리지 않았다. 끊긴 실행이 남긴 `geocode-lookup-v1.pending.jsonl`을
다음 실행이 그대로 합쳤다(`storage.LookupCache`).

### 조회 수

과금은 없다. 네이버 지역검색은 무료 한도(하루 25,000건) 안이고 인허가 조회서비스도 무료다.

| 캐시 | 네이버 | 인허가 | 합계 |
| --- | ---: | ---: | ---: |
| `data/busan/geocode-lookup-v1.jsonl` | 3,490 | 1,667 | 5,157 |
| `data/busan/category-lookup-v1.jsonl` | 1,440 | 55 | 1,495 |
| **합계** | **4,930** | **1,722** | **6,652** |

인허가 1,667건에는 순서를 바꾸기 전 첫 실행이 받은 905건이 들어 있다. 그 905건은 지금 순서라면
묻지 않았을 상호까지 포함하지만, 이미 받은 조회라 지우지 않고 캐시에 남겼다.

여기에 청사 좌표 실측으로 네이버 지역검색을 13번 더 불렀다(7절).

## 7. 지오코딩 — 접두와 청사를 선언하기 전과 후

### 원본에는 주소 칸이 없다

이슈가 물은 "사용장소·주소 칸"을 매핑한 표 2,968개의 머리글에서 기관별로 실측했다. 장소류 열은
**있고 많다** — 2,388개 표(80.5%)가 가졌다. 그러나 그 칸은 **주소가 아니라 상호**다.

| 기관 | 매핑한 표 | 장소류 열이 있는 표 | 가장 흔한 머리글 |
| --- | ---: | ---: | --- |
| `busan-busanjin` | 925 | 855 | 사용장소 831 · 사용장소(가맹점명) 24 |
| `busan-geumjeong` | 432 | 262 | 장소 127 · 집행장소 38 · 장소3) 38 |
| `busan-city` | 319 | 310 | 장소 267 · 사용장소 29 |
| `busan-buk` | 246 | 222 | 사용장소(가맹점명) 178 · 사용장소 33 |
| `busan-suyeong` | 222 | 187 | 사용장소 114 · 장소 39 · 3)장소 19 |
| `busan-haeundae` | 201 | 49 | 사용장소 25 · 장소 18 |
| `busan-yeonje` | 193 | 151 | 장소 97 · 사용장소(가맹점명) 28 |
| `busan-jung` | 186 | 179 | 사용장소 119 · 장소 45 |
| `busan-seo` | 73 | 10 | 장소 10 |
| `busan-dong` | 70 | 64 | 집행장소 56 · 장소 8 |
| `busan-dongnae` | 57 | 55 | 장소 51 |
| `busan-sasang` | 44 | 44 | 사용장소(가맹점명) 20 · 장소 14 |
| `busan-gijang` | 0 | 0 | (원본 없음) |
| **합계** | **2,968** | **2,388** | |

머리글 자신이 그렇게 말한다 — `사용장소(가맹점명)`·`장소(가맹점명)`·`사용장소(집행처)`·
`장소/거래처`. 값도 그렇다. 서구 원본을 열어 보면 그 칸은 `남해낙지`, `텐퍼센트(서구청점)`,
`돈풍각, 셀럽스커피(연제구)`이고, 헤더 매핑은 그것을 `merchant`로 읽는다.

구조로도 주소를 받을 자리가 없다. 헤더 매핑이 판정하는 열 역할은 여덟 가지
(`spent_on`·`merchant`·`purpose`·`department`·`amount_krw`·`month`·`day`·`time`,
`src/deliciousmap/contracts.py`의 `ColumnRole`)이고 주소·소재지 역할이 없다. 따라서 독립 근거
(`facts`)를 원본에서 얻는 길은 부산에도, 다른 어느 도시에도 없다. 부산 마커가 사람 확인 없이
서는 것은 ADR-0010의 단일 제공자 채택 덕이다.

### 접두·청사가 없으면 마커가 0개다

`identity.city_places`는 "접두가 없는 도시는 채택하지 않는다"이다. 접두를 선언하기 전의 도시
`geocode`는 확정 식당 6,643건이 전부 실패로 남았다.

| 사유 | 선언 전 | 선언 후 |
| --- | ---: | ---: |
| `matched` | 0 | 3,864 |
| `insufficient_evidence` | 5,933 | 2,079 |
| `no_candidates` | 366 | 368 |
| `merged_merchant` | 333 | 332 |
| `lookup_error` | 11 | 0 |
| **마커(업소)** | **0** | **1,530** |

`lookup_error` 11건은 인허가 응답을 받지 못한 것(`unavailable`)이며 `--retry-failed`로 다시
돌려 풀었다. 선언 전 실행은 이 11건 때문에 종료 코드 1로 끝났고, 실패를 0건으로 숨기지 않았다.

### 청사 열셋은 이렇게 쟀다

2026-09-17에 네이버 지역검색으로 기관 이름을 하나씩 조회해, **상호 칸이 그 청사 이름이고 주소가
`부산광역시`로 시작하는 후보**만 받았다. 열둘은 이름이 정확히 같았고, 동구청만 지역검색 표기가
`부산동구청`이라 이름이 정확히 같지 않아 주소(`부산광역시 동구 구청로 1`)와 좌표로 확인했다.

| 기관 | 청사 주소 | 좌표 |
| --- | --- | --- |
| `busan-city` | 연제구 중앙대로 1001 | 35.1798159, 129.0750223 |
| `busan-jung` | 중구 중구로 120 | 35.1062139, 129.032352 |
| `busan-seo` | 서구 구덕로 120 | 35.097932, 129.0244125 |
| `busan-dong` | 동구 구청로 1 | 35.1292745, 129.0453253 |
| `busan-busanjin` | 부산진구 시민공원로 30 | 35.1629129, 129.053157 |
| `busan-dongnae` | 동래구 충렬대로237번길 93 | 35.2051554, 129.0836898 |
| `busan-buk` | 북구 낙동대로1570번길 33 | 35.1972644, 128.990181 |
| `busan-haeundae` | 해운대구 중동2로 11 | 35.1631769, 129.163634 |
| `busan-geumjeong` | 금정구 중앙대로 1777 | 35.2430679, 129.0920999 |
| `busan-yeonje` | 연제구 연제로 2 | 35.1762419, 129.079764 |
| `busan-suyeong` | 수영구 남천동로 100 | 35.1456939, 129.113186 |
| `busan-sasang` | 사상구 학감대로 242 | 35.1526239, 128.99125 |
| `busan-gijang` | 기장군 기장읍 기장대로 560 | 35.2444979, 129.2223119 |

보류 네 기관은 수집이 없어 청사를 적지 않았다(ADR-0010의 "실측한 기관에만 적는다").

접두는 조회 캐시에서 골랐다. 저장소 루트, Git Bash:

```bash
uv run python -c "
import collections,json,pathlib
p=collections.Counter(); prov=collections.Counter(); total=0
for line in pathlib.Path('data/busan/geocode-lookup-v1.jsonl').open(encoding='utf-8'):
    for c in json.loads(line).get('value',{}).get('candidates',[]):
        a=c.get('address')
        if not a: continue
        total+=1; p[a.split()[0]]+=1
        if a.startswith('부산광역시'): prov[c['source']['provider']]+=1
print(total, p.most_common(5), dict(prov))"
```

출력: 주소를 밝힌 후보 32,943건 가운데 `부산광역시` 6,226건이고 두 제공자가 함께 쓴다
(인허가 3,293 · 네이버 2,933). 다른 부산 표기는 없다. 나머지는 다른 시·도의 동명 업소다
(서울특별시 7,297 · 경기도 5,581 · 경상남도 2,591 · 전남광주통합특별시 1,599).

이 수는 캐시가 자라면 함께 자란다. 위 값은 이 문서를 쓴 시점(업종 조회까지 끝난 뒤)의 것이다.

### 폐업 대조

`closure`는 확정 업소 1,530곳을 모두 `unknown`으로 남겼다. 지금 단계는 후보를 그대로 미확인으로
두며 이 이슈에서 바꾸지 않았다.

## 8. 기관별 종료 상태 (완료 기준 1)

열세 기관 × 세 단계(`geocode`·`closure`·`build`) **서른아홉 개 실행이 모두 종료 코드 0**이다.
앞선 `headermap`·`parse`·`classify`도 열세 기관 모두 0으로 끝났다.

| 기관 | 레코드 | 마커 | `matched` | `insufficient_evidence` | `no_candidates` | `merged_merchant` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `busan-city` | 4,382 | 593 | 1,674 | 1,010 | 195 | 155 |
| `busan-jung` | 711 | 154 | 292 | 215 | 9 | 3 |
| `busan-suyeong` | 833 | 138 | 337 | 144 | 18 | 15 |
| `busan-dong` | 401 | 110 | 228 | 54 | 13 | 11 |
| `busan-haeundae` | 676 | 110 | 213 | 119 | 14 | 14 |
| `busan-busanjin` | 749 | 104 | 216 | 130 | 35 | 13 |
| `busan-seo` | 464 | 100 | 206 | 93 | 9 | 23 |
| `busan-yeonje` | 421 | 93 | 158 | 90 | 22 | 7 |
| `busan-dongnae` | 387 | 87 | 145 | 54 | 5 | 4 |
| `busan-buk` | 357 | 72 | 142 | 62 | 3 | 3 |
| `busan-geumjeong` | 382 | 62 | 103 | 29 | 26 | 65 |
| `busan-sasang` | 65 | 13 | 16 | 15 | 1 | 1 |
| `busan-gijang` | 0 | 0 | 0 | 0 | 0 | 0 |
| **합계** | **9,828** | **1,636** | | | | |

기관 마커 합계 1,636이 도시 1,530보다 많은 것은 같은 업소를 여러 기관이 각각 세기 때문이다.
도시 실행은 기관을 가로질러 업소를 하나로 합친다. 사이트는 도시 산출물로 빌드한다.

`busan-buk`은 첫 배치에서 `headermap`이 종료 코드 1로 끝났다. 사유는 원본이나 모델이 아니라
`data/_shared/llm-budget.jsonl`을 다른 프로세스(진행 확인용 읽기)가 열고 있어 원자적 교체가
`PermissionError EACCES`로 막힌 것이다. 실행이 끝난 뒤 같은 명령을 다시 돌려 0으로 끝냈고,
답변 캐시가 이미 차 있어 새 모델 호출은 거의 없었다.

## 9. LLM 예산 (완료 기준 4)

이번 실행이 `data/_shared/llm-budget.jsonl`에 더한 줄은 4,360이고, 정산 2,175건 · 예약 2,180건 ·
해제 5건이다. 해제 5건은 응답을 받지 못한 호출이다.

| 용도 | 호출(정산) | 이번 실행 지출 |
| --- | ---: | ---: |
| 헤더 매핑 | 2,066 | $4.0240 |
| 비식당 판별 | 109 | $1.2538 |
| **이번 실행 합계** | **2,175** | **$5.2778** |

누적은 **$6.5597 / 한도 $15**다. 실행 전 누적은 $1.2819였다. 확인 명령(저장소 루트, 양쪽 공통):

```text
uv run python -c "from pathlib import Path; from deliciousmap.budget import Budget, LIMIT_USD; c=Budget(Path('data/_shared/llm-budget.jsonl')).committed(); print(c, LIMIT_USD)"
```

모델은 `GEMINI_MODEL`에 선언된 `gemini-3.6-flash`이며 `geocode`·`closure`·`build`는 `GEMINI_*`를
싣지 않고 돌렸다. 울산 #132처럼 헤더 매핑 0건으로 레코드가 0이 되는 상태는 없었다 —
매핑 2,150개가 섰다.

## 10. 산출물 크기와 개인정보 (완료 기준 5)

`data/busan/` 아래 파일당 20MB 상한(ADR-0001)을 넘는 파일은 없다. 가장 큰 것은
`geocode-history-v2.002.jsonl` 15.0MB, `geocode.json` 13.8MB, `geocode-lookup-v1.jsonl` 13.1MB다.
이력은 상한에 닿아 `geocode-history-v2.002.jsonl`로 한 조각 갈렸다.

`dist/busan/`은 커밋하지 않는다(`.gitignore`). 이번 빌드의 크기는 아래와 같다.

| 파일 | 크기 | 건수 |
| --- | ---: | ---: |
| `records.json` | 4,219,241 B | 레코드 9,831 |
| `markers.json` | 756,150 B | 마커 1,530 |
| `index.html` | 11,307 B | |

gitleaks 8.30.1으로 저장소를 훑어 `no leaks found`를 받았다. 산출물에 키·응답 원문은 없다 —
조회 캐시의 `evidence`는 제공자·해석 버전·결과 수만 적는다.

## 11. 완료 기준 대조

| 완료 기준 | 결과 |
| --- | --- |
| 보류가 아닌 기관마다 `parse`부터 `build`까지 끝나고 종료 상태를 기록 | 충족. 13기관 × 6단계 모두 종료 코드 0 (8절) |
| 기관·게시판별 원본 해시·레코드·비식당·보류·좌표 실패 수와 사유 | 충족. 1·2·5·8절 |
| 미지원 형식·미해결 원본·받지 않은 게시글을 기관별 수와 근거로 기록 | 충족. 2·3절. 0건이나 성공으로 숨기지 않았다 |
| LLM 호출 수·누적 비용이 장부와 일치하고 USD 15 이내, 네이버 조회 수 기록 | 충족. $6.5597/15, 조회 6,652건 (6·9절) |
| `data/busan/` 산출물과 `dist/busan/`의 건수·크기, 파일 크기 상한·개인정보 검사 | 충족. 10절 |
| `build --city busan` 성공, 부산 페이지에서 장부·마커·보류 사유 확인 | 충족. 마커 1,530·장부 9,831건·보류 4곳 사유를 화면에서 봤다. 지도 타일만 지도 키의 출처 등록 문제로 뜨지 않았다 (12절) |
| 다른 도시 산출물과 확정 업소를 바꾸지 않음 | 충족. 변경 경로는 `data/busan/`, `data/_shared/` 캐시, 코드·문서·테스트뿐이다 |
| `pytest`·`ruff`·`mypy`·`git diff --check`·gitleaks | 충족. 13절 |

## 12. 부산 페이지 로컬 확인 (완료 기준 6)

`dist`를 로컬에 띄우고 브라우저로 열었다. 저장소 루트, 양쪽 공통:

```text
python -m http.server 8765 --bind 127.0.0.1
```

`http://localhost:8765/busan/`에서 확인한 것.

- **마커·목록.** 머리말이 `1,530곳 전체 · 1,518곳 현재 지도 영역`이고 방문 횟수 순으로
  `부자회관` 78회, `우나기만` 62회, `만성횟집` 57회가 이어진다. 빌드 산출물의 마커 수와 같다.
- **보류 사유.** 지도 위 안내가 `수집 보류 기관 4곳이 있어 비어 있는 지역이 집행 없음을 뜻하지
  않습니다.`를 띄운다. `자료 범위`를 열면 기관별 표가 `부산광역시 영도구 · 수집 보류 · 봇 차단`,
  `부산광역시 남구 · 수집 보류 · 봇 차단`, `부산광역시 사하구 · 수집 보류 · 게시판 유실`로
  사유를 적는다. 수집한 기관은 `수집 완료 · 레코드 4,382건`처럼 건수를 적는다.
- **장부.** `장부` 탭이 `마커가 없는 레코드도 포함 / 전체 9,831건`을 띄우고, 레코드마다
  `판단 보류`·`지오코딩 실패 · 근거 부족`·`비식당`·`지도 표시` 표지를 단다. 확정되지 않은
  레코드가 장부에서 사라지지 않는다.

**지도 타일은 뜨지 않았다.** 콘솔에 `Naver Maps authentication failed`가 남고 페이지가
`네이버 지도 설정을 확인해 주세요. 검색 집계와 장부는 계속 볼 수 있습니다.`로 바꿔 보여 준다.
`127.0.0.1:8765`와 `localhost:8765` 둘 다 같았다. 이것은 `NAVER_MAP_CLIENT_ID`의 서비스 환경에
이 출처가 등록되지 않은 것이며, 파이프라인 산출물과는 무관하다. 마커 수·장부·보류 사유는 타일
없이도 그대로 보인다.

## 13. 검사

저장소 루트, 양쪽 공통.

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
git diff --check
gitleaks detect --no-banner --redact --source .
```

## 14. 남은 문제

- **HWP 5.0(OLE2) 504건과 기장군 HTML 표.** 추출 경로가 없어 미해결로 남았다. 이슈의 작업
  분류표가 다른 세션 몫으로 나눈 일이다.
- **`validation_failed` 369건.** 표는 읽었으나 매핑이 코드 검증을 통과하지 못했다. 사유별로 더
  갈라 보지 않았다.
- **`insufficient_evidence` 2,079건.** 도시 안에서 상호가 맞는 후보를 찾지 못했거나 여러 곳이라
  고르지 못한 레코드다. 사람이 확정하는 대량 작업은 이슈의 제외 범위다.
- **`busan-sasang` 훑기 중단과 보류 네 기관.** #140 계열이며 이 이슈에서 다시 시도하지 않았다.
- **폐업 대조.** 확정 업소 1,530곳이 모두 `unknown`이다.
- **지도 키의 출처 등록.** `NAVER_MAP_CLIENT_ID`가 `localhost:8765`·`127.0.0.1:8765`에서
  인증에 실패한다. 파이프라인 밖의 콘솔 설정 문제이며 이 이슈에서 고치지 않았다.
- **DRM 첨부 수.** 이 실행은 기관별 DRM 건수를 따로 세지 않았다. #140이 기관별로 이미
  실측해 [그 기록](issue-140.md)에 남겼고, 여기서는 그 수를 옮겨 적지 않았다.
