# 부산 열다섯 기관 파이프라인 실측 (#142)

검증일 2026-09-17. 원본은 저장소 밖 `C:\Users\pc\orca\workspaces\OfficialDeliciousMap\deliciousmap-raw`
(기본 `--raw-root`)에서 읽었고 저장소로 복사하지 않았다. `.env`는 실행 프로세스에만 실었다.

**이 문서는 `develop`(`e7fd2ef`)에 리베이스한 뒤 다시 낸 값이다.** 리베이스 전 이 브랜치는 열세
기관을 돌려 레코드 9,831건·마커 1,530개를 냈다. 그 사이 `develop`이 다섯 가지를 바꿨고 전제가
달라져 전 단계를 다시 돌렸다.

| `develop`에 들어온 것 | 이 실행에 미친 영향 |
| --- | --- |
| [#140](https://github.com/snowjaewon/OfficialDeliciousMap/issues/140) 후속 — 남구·강서구 수집 | 보류 넷 중 둘이 풀려 기관이 13 → **15**, 원본 3,519 → **4,049** |
| [#198](https://github.com/snowjaewon/OfficialDeliciousMap/issues/198) 기장군 HTML 표 파서 | 기장군 원본 0 → 1(HTML), `headermap`·`parse`는 `develop` 쪽을 그대로 받았다 |
| [#195](https://github.com/snowjaewon/OfficialDeliciousMap/issues/195) 첨부 묶음 ZIP 파서 | 미해결로 남던 원본 일부가 읽힌다 |
| [#197](https://github.com/snowjaewon/OfficialDeliciousMap/issues/197) 사상구 재수집 장부 | 사상구 원본 266 → 265 |
| [#175](https://github.com/snowjaewon/OfficialDeliciousMap/issues/175) 대전 — 답변 이력을 도시 하나로, 연도 근거를 제목에서 보충 | 미해결 975 → **947**, 레코드 11,123 → **11,402**. 기관 합계와 도시 실행이 처음으로 정확히 같아졌다(5절) |

리베이스는 두 번 했다. 처음 `f3522ca`(#204) 위에 올려 한 번 돌렸고, 그 실행 중에 `develop`에
#207(대전)이 들어와 다시 `e7fd2ef` 위로 올린 뒤 한 번 더 돌렸다. 아래는 두 번째 실행의 값이다.

## 0. 이번 실행이 따른 사용자 결정 셋

모두 이슈 본문의 구현 범위에 없던 일이고, 실행 중에 실측을 보고 사용자가 정했다. 범위를 넘은
자리를 감추지 않으려고 여기 먼저 적는다.

1. **후보 조회를 네이버 우선으로 바꾼다** (2026-09-17). 인허가 조회가 네이버보다 약 13배 느려
   도시 실행 시간을 지배했다. 앞 제공자가 후보를 낸 레코드는 뒤 제공자에게 묻지 않는다. 결정과
   잃는 것은 [ADR-0011](../adr/0011-ask-providers-in-order.md)에 적었다(6절).
2. **부산 주소 접두와 청사를 실측해 선언한다** (2026-09-17). 접두가 없으면 채택이 서지 않아
   마커가 0개다. 리베이스 전에 열셋을 쟀고, 보류가 풀린 남구·강서구를 같은 방법으로 더해
   **열다섯**이 됐다(7절). 레지스트리 데이터만 더하고 판정 규칙과 `identity.POLICY_VERSION`은
   건드리지 않았다.
3. **공용 서명 캐시가 연도 근거를 잃던 버그를 고친다** (2026-09-17). 기관 실행과 도시 실행이
   같은 원본을 다르게 판정해 `geocode --org busan-nam`이 종료 코드 1로 끝났다(8절 3번).
   고치고 보니 같은 시각 `develop`에 들어온 #175가 `extract._year_hint`로 같은 일을 더 넓게
   하고 있었다. 한 규칙에 두 자리를 두지 않으려고 우리 코드는 걷고 develop 것을 쓴다. 사상구로
   대조해 매핑 39개·미해결 143건으로 값이 같았다. 회귀 테스트만 남겼다.

## 1. 원본 대조 — 4,049건 전부 일치

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

출력: `ok 4049 mismatch 0 absent 0`. 원본 해시는 4,042개가 고유하고, 같은 해시가 한 기관 안에서
거듭 나온 것이 7건이다.

## 2. fetch — 받은 것과 받지 않은 것

수집은 #140 계열이 한 것이고 이 이슈는 그 산출물을 입력으로 삼았다. 아래는 이번에 다시 읽은
값이다.

| 기관 | 원본 | 받지 못함 | 받지 않은 게시글 | 컨테이너 |
| --- | ---: | ---: | ---: | --- |
| `busan-busanjin` | 480 | 16 | 4,338 | ooxml 446 · pdf 34 |
| `busan-city` | 409 | 105 | 10,198 | ooxml 406 · hwpx 3 |
| `busan-jung` | 405 | 0 | 10,406 | ooxml 226 · ole2 170 · pdf 9 |
| `busan-geumjeong` | 402 | 15 | 5,949 | hwpx 241 · ole2 111 · pdf 50 |
| `busan-nam` | 347 | 73 | 5,870 | ooxml 347 |
| `busan-suyeong` | 326 | 0 | 8,593 | ooxml 296 · ole2 30 |
| `busan-buk` | 298 | 31 | 2,942 | hwpx 140 · ole2 128 · pdf 21 · ooxml 9 |
| `busan-haeundae` | 289 | 51 | 4,163 | ooxml 218 · ole2 62 · pdf 9 |
| `busan-yeonje` | 280 | 0 | 3,645 | ooxml 241 · hwpx 39 |
| `busan-sasang` | 265 | 17 | 407 | ole2 215 · pdf 26 · hwpx 15 · ooxml 9 |
| `busan-gangseo` | 182 | 22 | 3,512 | ooxml 162 · ole2 20 |
| `busan-seo` | 128 | 0 | 937 | ooxml 101 · ole2 27 |
| `busan-dongnae` | 119 | 0 | 2,538 | ole2 41 · hwpx 40 · pdf 27 · ooxml 11 |
| `busan-dong` | 118 | 0 | 682 | pdf 86 · hwpml 28 · ole2 2 · ooxml 1 · hwpx 1 |
| `busan-gijang` | 1 | 0 | 0 | html 1 |
| **합계** | **4,049** | **330** | **64,180** | |

- `busan-sasang`의 `empty_reason`은 `collection failures: busan-sasang/expenses=service-unavailable`
  이다. 훑기가 끊겼고 받지 않은 게시글 407은 그 게시판의 바닥값이지 전체가 아니다.
- `busan-gijang`은 #198이 HTML 표를 원본 하나로 받게 하면서 원본 0 → 1이 됐다. 그래도 대상
  기간의 레코드는 0건이다(5절).
- 보류는 둘이다: `busan-yeongdo`(`bot_blocked`) · `busan-saha`(`board_lost`). 도시 `fetch.json`의
  `empty_reason`이 이 둘을 이름과 사유로 싣는다.

**받지 못한 원본 330건의 사유**는 기관 `fetch.json`의 `missing[].reason`이 밝힌다 — DRM 329건과
`not_an_original` 1건(부산진구)이다. DRM은 기관별로 `busan-city` 105 · `busan-nam` 73 ·
`busan-haeundae` 51 · `busan-buk` 31 · `busan-gangseo` 22 · `busan-sasang` 17 ·
`busan-busanjin` 15 · `busan-geumjeong` 15이고, 나머지 일곱 기관은 0이다. 같은 수가 저장소 밖
수집 장부(`<raw-root>/busan/*/*/collected.jsonl`의 `drm`)와도 맞는다.

## 3. 미해결 원본 — 0건으로 숨기지 않았다

도시 `headermap`의 미해결 947건과 그 사유다. `parse`는 같은 947건에 `no_candidates` 104건을
더해 **1,051건**을 미해결로 남겼다.

| 사유 | 건수 | 뜻 |
| --- | ---: | --- |
| `unsupported_format` | 504 | OLE2 컨테이너인데 엑셀 통합문서가 아니다. HWP 5.0이며 현재 추출 경로가 없다 |
| `validation_failed` | 433 | 표는 읽었으나 매핑이 코드 검증을 통과하지 못했다 |
| `no_candidates` | 104 | 표는 읽었으나 지출 후보 줄이 0이다. 집행 없음으로 통과시키지 않았다 |
| `unreadable` | 7 | 통합문서를 열지 못했다 |
| `no_table` | 3 | 표를 하나도 찾지 못했다 |

`unsupported_format` 504건은 기관별로 `busan-sasang` 137 · `busan-jung` 104 · `busan-buk` 94 ·
`busan-geumjeong` 85 · `busan-dongnae` 27 · `busan-seo` 20 · `busan-dong` 20 · `busan-haeundae` 17
이다. 사상구가 가장 많은 것은 그 기관 원본 265건 중 215건이 OLE2이기 때문이다. 새로 들어온
남구(ooxml 347)·강서구(ooxml 162 · ole2 20)는 `unsupported_format`이 0이다.

`validation_failed`는 리베이스 전 369건에서 433건이 됐다. 새 원본 529건이 들어와 늘었다가,
#175의 연도 근거 보충이 13건을 풀어 다시 줄어든 값이다.

## 4. 도시 산출물 병합

기관 `fetch.json` 15개를 도시 `fetch.json` 하나로 합쳤다. 원본을 바꾸거나 레코드를 만들지
않았고, `empty_reason`은 기관별 사유를 `;`로 이어 붙인 뒤 보류 기관을 덧붙였다. 합친 결과는
2절의 합계와 같다(원본 4,049 · 받지 못함 330 · 받지 않은 게시글 64,180 · 걸러 낸 게시글 0).

```text
collection failures: busan-sasang/expenses=service-unavailable;
held organizations: busan-yeongdo=bot_blocked, busan-saha=board_lost
```

`fetch --city busan`을 다시 돌리지 않은 것은 그 명령이 게시판을 다시 훑기 때문이다. 받지 않은
게시글이 64,180건 남아 있어 다시 훑으면 이 이슈의 범위 밖인 수집을 새로 하게 된다.

## 5. parse·classify — 레코드 11,402건

대상 기간은 `2026-01-01/2026-06-30`이다. 도시 실행 기준으로 `parse`가 대상 원본 2,724건을 살펴
1,673건을 읽었고 지출 후보 17,371줄에서 레코드 11,402건을 냈다. 기간 밖으로 뺀 원본은
`declared_out_of_range` 1,316 · `posted_out_of_range` 0 · `undeclared_in_year` 3이다.
누적 재게시(ADR-0004)로 합쳐 본 지출은 67건(레코드 91), 합치지 않은 것이 26건이다.

| 기관 | 레코드 | 식당 | 비식당 | 판단 보류 |
| --- | ---: | ---: | ---: | ---: |
| `busan-city` | 4,382 | 3,157 | 647 | 578 |
| `busan-suyeong` | 833 | 595 | 184 | 54 |
| `busan-gangseo` | 761 | 428 | 185 | 148 |
| `busan-busanjin` | 751 | 394 | 285 | 72 |
| `busan-jung` | 711 | 519 | 90 | 102 |
| `busan-haeundae` | 676 | 367 | 262 | 47 |
| `busan-nam` | 534 | 233 | 272 | 29 |
| `busan-dongnae` | 465 | 284 | 129 | 52 |
| `busan-seo` | 464 | 331 | 73 | 60 |
| `busan-geumjeong` | 430 | 246 | 93 | 91 |
| `busan-yeonje` | 421 | 277 | 104 | 40 |
| `busan-dong` | 401 | 306 | 44 | 51 |
| `busan-buk` | 357 | 210 | 94 | 53 |
| `busan-sasang` | 216 | 150 | 27 | 39 |
| `busan-gijang` | 0 | 0 | 0 | 0 |
| **합계** | **11,402** | **7,497** | **2,489** | **1,416** |

**기관 합계와 도시 실행이 네 칸 모두 정확히 같다.** 리베이스 전에는 레코드가 74건 어긋났고
식당·비식당·판단 보류도 갈렸다. #175가 헤더 매핑 답변 이력을 기관별 파일에서 도시 파일
하나로 옮겨, 기관 실행과 도시 실행이 같은 답을 읽게 된 결과다. 도시 `records.csv`를 기관별로
세도 위 표와 같다 — 사이트의 `자료 범위`가 적는 건수도 이 수다(12절).

## 6. 조회 — 네이버 우선으로 바꾼 자리

### 무엇을 재고 바꿨나

리베이스 전 첫 도시 `geocode`는 옛 순서(레코드마다 두 제공자를 모두 물음)로 돌았고 **1시간
37분 동안 조회 1,811건(목표 6,760건의 27%)** 을 받았다. 두 제공자의 응답 시간을 같은 질의
다섯 개로 쟀다. 저장소 루트, Git Bash:

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
약 13배 차이다. 사용자 결정으로 [ADR-0011](../adr/0011-ask-providers-in-order.md)의 순서를 넣었다.

### 조회 수

과금은 없다. 네이버 지역검색은 무료 한도(하루 25,000건) 안이고 인허가 조회서비스도 무료다.
도시 `geocode.json`이 레코드마다 남긴 질의를 셌다.

| 제공자 | 질의 | 고유 질의 | 실패 |
| --- | ---: | ---: | ---: |
| 네이버 | 7,497 | 3,588 | 0 |
| 인허가 | 982 | 651 | 0 |
| **합계** | **8,479** | **4,239** | **0** |

네이버가 확정 식당 7,497건 모두에 서고, 인허가는 네이버가 후보를 못 낸 982건에만 섰다. 곧
**뒤 제공자에게 묻는 비율이 13.1%** 다. 실제로 제공자에게 나간 요청은 이보다 훨씬 적다 —
`geocode-lookup-v1.jsonl`이 같은 상호의 답을 재사용한다.

여기에 청사 좌표 실측으로 네이버 지역검색을 15번 더 불렀다(7절).

## 7. 지오코딩 — 접두와 청사

### 원본의 장소 칸은 대개 상호다 — 남구만 주소 칸을 가진다

도시 `headermap`이 매핑한 표 2,600개의 머리글을 실측했다. 장소류 열(`장소`·`가맹점`·`거래처`·
`집행처`·`업체`·`상호`)은 **2,279개 표(87.7%)** 가 가졌으나 그 칸은 대개 주소가 아니라 상호다.

| 기관 | 매핑한 표 | 장소류 열 | 가장 흔한 머리글 |
| --- | ---: | ---: | --- |
| `busan-busanjin` | 594 | 564 | 사용장소 301 · 사용 장소 251 |
| `busan-city` | 292 | 283 | 장소 240 · 사용장소 26 |
| `busan-nam` | 260 | 260 | 업체명 192 · 업체주소 (동까지 기재) 105 |
| `busan-geumjeong` | 213 | 186 | 집행처 79 · 집행장소 38 |
| `busan-suyeong` | 205 | 168 | 사용장소 107 · 장소 28 |
| `busan-haeundae` | 184 | 47 | 사용장소 18 · 장소 18 |
| `busan-buk` | 181 | 181 | 사용장소(가맹점명) 132 · 사용장소 (가맹점명) 20 |
| `busan-yeonje` | 163 | 150 | 장소 86 · 사용장소 22 |
| `busan-gangseo` | 144 | 131 | 사용장소(가맹점명) 54 · 장소 45 |
| `busan-jung` | 143 | 143 | 사용장소 87 · 장소 41 |
| `busan-dong` | 67 | 62 | 집행장소 51 · 장소 8 |
| `busan-seo` | 60 | 12 | 장소 10 · 거래처명 2 |
| `busan-dongnae` | 55 | 53 | 장소 49 · 사용장소 (가맹점명) 2 |
| `busan-sasang` | 39 | 39 | 사용장소 (가맹점명) 11 · 사용장소 10 |
| **합계** | **2,600** | **2,279** | |

**리베이스 전 이 문서는 "원본에는 주소 칸이 없다"고 적었다. 이제 그 말은 틀렸다.** `develop`이
연 남구 원본에는 주소 열이 있다 — 머리글에 `주소`·`소재지`·`위치`가 든 표가 **220개**이고
(`업체주소 (동까지 기재)` 105 · `업체주소(동까지 기재)` 103 · `업체주소` 12) **모두 남구**다.
나머지 열네 기관은 0이다.

그래도 파이프라인은 그 칸을 읽지 않는다. 헤더 매핑이 판정하는 열 역할은 여덟 가지
(`spent_on`·`merchant`·`purpose`·`department`·`amount_krw`·`month`·`day`·`time`,
`src/deliciousmap/contracts.py`의 `ColumnRole`)이고 주소·소재지 역할이 없다. 남구의 주소 열을
독립 근거(`facts`)로 쓰는 일은 이 이슈에서 하지 않았다(14절).

### 접두·청사가 없으면 마커가 0개다

`identity.city_places`는 "접두가 없는 도시는 채택하지 않는다"이다. 리베이스 전 실행에서 접두를
선언하기 전의 도시 `geocode`는 확정 식당 6,643건이 전부 실패로 남았고 마커가 0개였다. 접두를
선언한 뒤 1,530개가 섰고, 이번 재실행에서 **1,754개**가 섰다.

| 사유 | 리베이스 전 | 이번 실행 |
| --- | ---: | ---: |
| `matched` | 3,864 | **4,318** |
| `insufficient_evidence` | 2,079 | 2,433 |
| `no_candidates` | 368 | 399 |
| `merged_merchant` | 332 | 347 |
| **확정 식당** | **6,643** | **7,497** |
| **마커(업소)** | **1,530** | **1,754** |

### 청사 열다섯은 이렇게 쟀다

네이버 지역검색으로 기관 이름을 하나씩 조회해, **상호 칸이 그 청사 이름이고 주소가
`부산광역시`로 시작하는 후보**만 받았다.

| 기관 | 청사 주소 | 좌표 |
| --- | --- | --- |
| `busan-city` | 연제구 중앙대로 1001 | 35.1798159, 129.0750223 |
| `busan-jung` | 중구 중구로 120 | 35.1062139, 129.032352 |
| `busan-seo` | 서구 구덕로 120 | 35.097932, 129.0244125 |
| `busan-dong` | 동구 구청로 1 | 35.1292745, 129.0453253 |
| `busan-busanjin` | 부산진구 시민공원로 30 | 35.1629129, 129.053157 |
| `busan-dongnae` | 동래구 충렬대로237번길 93 | 35.2051554, 129.0836898 |
| `busan-nam` | 남구 못골로 19 | 35.1365769, 129.084163 |
| `busan-buk` | 북구 낙동대로1570번길 33 | 35.1972644, 128.990181 |
| `busan-haeundae` | 해운대구 중동2로 11 | 35.1631769, 129.163634 |
| `busan-geumjeong` | 금정구 중앙대로 1777 | 35.2430679, 129.0920999 |
| `busan-gangseo` | 강서구 낙동북로 477 | 35.2122178, 128.98045 |
| `busan-yeonje` | 연제구 연제로 2 | 35.1762419, 129.079764 |
| `busan-suyeong` | 수영구 남천동로 100 | 35.1456939, 129.113186 |
| `busan-sasang` | 사상구 학감대로 242 | 35.1526239, 128.99125 |
| `busan-gijang` | 기장군 기장읍 기장대로 560 | 35.2444979, 129.2223119 |

셋은 지역검색 표기가 청사 이름과 정확히 같지 않아 주소·좌표로 확인하고 받았다 —
`부산동구청`·`부산광역시남구청`·`부산광역시 강서구청`. 강서구는 이름만 물으면 서울 강서구청만
나와 `부산강서구청`으로 물었다. 보류 두 기관(영도·사하)은 수집이 없어 청사를 적지 않았다
(ADR-0010의 "실측한 기관에만 적는다").

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

출력: 주소를 밝힌 후보 34,663건 가운데 `부산광역시` 6,720건이고 두 제공자가 함께 쓴다
(인허가 3,402 · 네이버 3,318). 다른 부산 표기는 없다. 나머지는 다른 시·도의 동명 업소다
(서울특별시 7,690 · 경기도 5,881 · 경상남도 2,735 · 전남광주통합특별시 1,656).

이 수는 캐시가 자라면 함께 자란다. 위 값은 이 문서를 쓴 시점의 것이다.

### 폐업 대조

`closure`는 확정 업소 1,754곳을 모두 `unknown`으로 남겼다. 지금 단계는 후보를 그대로 미확인으로
두며 이 이슈에서 바꾸지 않았다.

## 8. 기관별 종료 상태 (완료 기준 1)

**기관 열다섯 곳 × 여섯 단계와 도시 여섯 단계, 아흔여섯 개 실행이 모두 종료 코드 0**이다.
마지막 실행은 재시도 없이 한 번에 끝났다.

| 기관 | 레코드 | 마커 | `matched` | `insufficient_evidence` | `no_candidates` | `merged_merchant` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `busan-city` | 4,382 | 631 | 1,732 | 1,052 | 208 | 165 |
| `busan-suyeong` | 833 | 158 | 399 | 158 | 20 | 18 |
| `busan-jung` | 711 | 154 | 292 | 215 | 9 | 3 |
| `busan-gangseo` | 761 | 120 | 194 | 211 | 19 | 4 |
| `busan-dongnae` | 465 | 115 | 185 | 84 | 8 | 7 |
| `busan-haeundae` | 676 | 113 | 216 | 120 | 15 | 16 |
| `busan-dong` | 401 | 110 | 228 | 54 | 13 | 11 |
| `busan-busanjin` | 751 | 104 | 216 | 130 | 35 | 13 |
| `busan-nam` | 534 | 102 | 149 | 64 | 10 | 10 |
| `busan-seo` | 464 | 100 | 206 | 93 | 9 | 23 |
| `busan-yeonje` | 421 | 93 | 158 | 90 | 22 | 7 |
| `busan-buk` | 357 | 72 | 142 | 62 | 3 | 3 |
| `busan-geumjeong` | 430 | 70 | 116 | 37 | 27 | 66 |
| `busan-sasang` | 216 | 43 | 85 | 63 | 1 | 1 |
| `busan-gijang` | 0 | 0 | 0 | 0 | 0 | 0 |
| **합계** | **11,402** | **1,985** | | | | |

기관 마커 합계 1,985가 도시 1,754보다 많은 것은 같은 업소를 여러 기관이 각각 세기 때문이다.
도시 실행은 기관을 가로질러 업소를 하나로 합친다. 사이트는 도시 산출물로 빌드한다.

### 도중에 실패한 네 자리

0으로 끝난 상태만 적고 그 앞을 지우지 않는다.

1. **`headermap --org busan-nam` 1차 — `PermissionError EACCES`.** 원인은 원본도 모델도 아니고
   `data/_shared/llm-budget.jsonl`을 다른 프로세스(진행 확인용 읽기)가 열고 있어 원자적 교체가
   막힌 것이다. 다시 돌려 0으로 끝냈다. 리베이스 전 실행의 `busan-buk`도 같은 자리였다.
2. **`geocode --city busan` — `lookup_error` 1건.** 남구의 `(주)해강에프앤비 해강서울깍두기`
   한 건에서 인허가가 `unavailable`을 돌려줬다. 판정은 저장된 뒤 단계가 실패로 끝난다.
   `--retry-failed`로 다시 물어 `no_candidates`로 확정했고 0으로 끝냈다.
3. **`geocode --org busan-nam` — `invalid-artifact`.** 남구 식당 레코드 216건 중 3건이 도시
   판정에 없었다. 같은 원본(`0b901a54…`)을 기관 실행은 레코드 3건으로 읽고 도시 실행은
   `validation_failed`로 남겼기 때문이다.

   원인은 공용 서명 캐시가 **연도 근거를 싣지 않는 것**이었다. 그 원본의 날짜 칸은
   `3. 23.(월)`처럼 연도가 없어 `year_hint` 없이는 어떤 매핑도 검증을 통과하지 못한다.
   기관 실행이 모델에게 받아 캐시에 남긴 정답을 도시 실행이 되살릴 때 `year_hint`가 `None`이
   되어 검증에 걸렸고, 캐시를 못 쓴 도시는 모델에 새로 두 번 물어 두 답 모두 검증에 걸렸다.

   ```text
   NAM 채택 매핑(year_hint=2026)으로 검증 → None(통과)
   같은 매핑에서 year_hint만 빼고 검증 → sheet1:R4 spent_on(실패)
   ```

   사용자 결정으로 고쳤고, 고친 뒤 도시 `headermap`이 **10분 59초에서 2분 44초로** 줄었다.
   캐시가 실제로 쓰이기 시작한 것이다. 다만 같은 시각 `develop`에 들어온 #175가 같은 문제를
   `extract._year_hint`로 더 넓게 고치고 있었다 — 매핑이 연도를 안 밝히면 **읽는 자리에서**
   게시글 제목의 해로 보충하므로 캐시에서 온 판정도 함께 풀린다. 한 규칙에 두 자리를 두지
   않으려고 우리 코드는 걷고 develop 것을 남겼다. 사상구로 대조해 매핑 39개·미해결 143건으로
   값이 같다. 회귀 테스트는 남겼고 develop의 수정 위에서도 통과한다.
4. **`geocode --org busan-nam` — `lookup-failed`.** 3번을 고친 뒤 남은 실패다. 판정이 아니라
   확정 업소의 업종 조회가 실패했다. `--retry-failed`로 다시 돌려 0으로 끝냈다.

위 네 자리는 모두 **첫 리베이스(`f3522ca`) 위 실행**의 것이다. `e7fd2ef`로 다시 올린 뒤의
마지막 실행은 아흔여섯 개가 재시도 없이 0으로 끝났다.

## 9. LLM 예산 (완료 기준 4)

누적은 **$8.7502 / 한도 $15**다. 이 값은 네 몫으로 나뉜다.

| 구간 | 더한 것 | 누적 |
| --- | ---: | ---: |
| 리베이스 전 이 브랜치 | — | $6.5597 |
| 1차 재실행 (`f3522ca` 위, 기관 15곳 + 도시) | $1.2724 | $7.8321 |
| `develop` 병합분 (#207 대전) | $0.8948 | $8.7269 |
| 2차 재실행 (`e7fd2ef` 위, 마지막 값을 낸 실행) | **$0.0234** | **$8.7502** |

`develop` 병합분은 리베이스로 장부에 합쳐진 것이고 우리 실행이 쓴 것이 아니다. 1차 재실행의
$1.2724는 새로 들어온 남구·강서구 원본 529건의 헤더 매핑(정산 528건 $1.0798)과 비식당 판별
17건($0.1811)이다.

2차 재실행이 $0.0234밖에 쓰지 않은 것은 1차가 답변 이력과 서명 캐시를 이미 채웠기 때문이다.
헤더 매핑 호출은 **0건**이고, 새로 나온 상호 4건만 판별에 물었다. 확인 명령(저장소 루트,
양쪽 공통):

```text
uv run python -c "from pathlib import Path; from deliciousmap.budget import Budget, LIMIT_USD; c=Budget(Path('data/_shared/llm-budget.jsonl')).committed(); print(c, LIMIT_USD)"
```

모델은 `GEMINI_MODEL`에 선언된 `gemini-3.6-flash`다.

## 10. 산출물 크기와 개인정보 (완료 기준 5)

`data/busan/` 아래 파일당 20MB 상한(ADR-0001)을 넘는 파일은 없다. 가장 큰 것은
`geocode-history-v2.002.jsonl` 15.8MB, `geocode.json` 14.9MB, `geocode-history-v2.jsonl` 13.9MB,
`geocode-lookup-v1.jsonl` 13.1MB다. 이력은 상한에 닿아 `.002`에 이어 `.003`(7.3MB)으로 한 조각
더 갈렸다.

개인정보는 `privacy` 규칙이 추출 시점에 가린다. 조회 캐시의 `evidence`는 제공자·해석 버전·
결과 수만 적는다.

## 11. 완료 기준 대조

| 완료 기준 | 결과 |
| --- | --- |
| 보류가 아닌 기관마다 `parse`부터 `build`까지 끝나고 종료 상태를 기록 | 충족. 15기관 × 6단계 모두 종료 코드 0 (8절). 도중 실패 네 자리도 8절에 남겼다 |
| 기관·게시판별 원본 해시·레코드·비식당·보류·좌표 실패 수와 사유 | 충족. 1·2·5·8절 |
| 미지원 형식·미해결 원본·받지 않은 게시글·DRM 첨부를 기관별 수와 근거로 기록 | 충족. 2·3절. DRM 329건도 기관별로 적었다. 0건이나 성공으로 숨기지 않았다 |
| LLM 호출 수·누적 비용이 장부와 일치하고 USD 15 이내, 네이버 조회 수 기록 | 충족. $8.7502/15, 질의 8,479건 (6·9절) |
| `data/busan/` 산출물과 `dist/busan/`의 건수·크기, 파일 크기 상한·개인정보 검사 | 충족. 10절 |
| `build --city busan` 성공, 부산 페이지에서 장부·마커·보류 사유 확인 | 충족. 마커 1,754 · 장부 11,402건 · 보류 2곳 사유 · 기관별 건수를 모두 화면에서 봤다. 지도 타일만 지도 키의 출처 등록 문제로 뜨지 않는다 (12절) |
| 다른 도시 산출물과 확정 업소를 바꾸지 않음 | 충족. 변경 경로는 `data/busan/`, `data/_shared/` 캐시, 코드·문서·테스트뿐이다 |
| `pytest`·`ruff`·`mypy`·`git diff --check`·gitleaks | 충족. 13절 |

## 12. 부산 페이지 로컬 확인 (완료 기준 6)

`dist`를 로컬에 띄우고 브라우저로 열었다. 저장소 루트, 양쪽 공통:

```text
python -m http.server 8765 --bind 127.0.0.1
```

`http://localhost:8765/busan/`에서 화면으로 확인한 것.

- **마커·목록.** 목록 머리말이 `1,754곳 전체`이고 방문 횟수 순으로 `부자회관` 79회,
  `우나기만` 64회, `만성횟집`·`취원` 57회, `함양가` 42회가 이어진다. 빌드 산출물의
  `marker_count` 1,754와 같다.
- **보류 안내.** 지도 위 안내가 `수집 보류 기관 2곳이 있어 비어 있는 지역이 집행 없음을 뜻하지
  않습니다.`를 띄운다. 보류가 넷에서 둘로 준 것이 화면에 그대로 반영된다.
- **`자료 범위`.** 기관 표가 `부산광역시 영도구 · 수집 보류 · 봇 차단`, `부산광역시 사하구 ·
  수집 보류 · 게시판 유실`을 적고, 보류가 풀린 둘을 `부산광역시 남구 · 수집 완료 · 레코드
  534건`, `부산광역시 강서구 · 수집 완료 · 레코드 761건`으로 적는다. 나머지 열셋의 건수도
  5절 표와 같다.
- **장부.** `장부` 탭이 `마커가 없는 레코드도 포함 / 전체 장부 / 전체 11,402건 · 100건 표시`를
  띄우고, 레코드마다 `판단 보류`·`지도 표시` 같은 표지를 단다. 확정되지 않은 레코드가 장부에서
  사라지지 않는다.
- **지도 타일은 뜨지 않았다.** 콘솔에 `Naver Maps authentication failed`가 남고 페이지가
  `네이버 지도 설정을 확인해 주세요. 검색 집계와 장부는 계속 볼 수 있습니다.`로 바꿔 보여 준다.
  이것은 `NAVER_MAP_CLIENT_ID`의 서비스 환경에 이 출처가 등록되지 않은 것이며, 파이프라인
  산출물과는 무관하다.

**첫 로드는 옛 화면이었다.** 서비스 워커가 캐시한 이전 빌드가 떠서 보류를 넷으로 적고 건수도
옛 값이었다. 강제 새로고침(`Ctrl+Shift+R`) 뒤 위의 값으로 바뀌었다. 배포 뒤 이용자 화면에도
같은 일이 생길 수 있다(14절).

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

- **남구의 주소 열을 읽지 않는다.** 표 220개가 `업체주소(동까지 기재)`를 가졌는데 `ColumnRole`에
  주소 역할이 없어 독립 근거로 쓰지 못한다(7절). 그 열을 읽으면 남구의
  `insufficient_evidence` 64건 중 일부가 사람 없이 확정될 수 있다. 이 이슈에서 하지 않았다.
- **서비스 워커가 옛 화면을 준다.** 다시 빌드한 뒤 첫 로드가 캐시된 이전 화면(보류 4곳)을 띄웠고
  강제 새로고침으로만 새 값이 나왔다(12절). 배포 뒤 이용자 화면에도 같은 일이 생길 수 있다.
- **HWP 5.0(OLE2) 504건.** 추출 경로가 없어 미해결로 남았다. 이슈의 작업 분류표가 다른 세션
  몫으로 나눈 일이다.
- **`validation_failed` 433건.** 표는 읽었으나 매핑이 코드 검증을 통과하지 못했다. 사유별로 더
  갈라 보지 않았다.
- **`insufficient_evidence` 2,433건.** 도시 안에서 상호가 맞는 후보를 찾지 못했거나 여러 곳이라
  고르지 못한 레코드다. 사람이 확정하는 대량 작업은 이슈의 제외 범위다.
- **`busan-sasang` 훑기 중단과 보류 두 기관.** #140 계열이며 이 이슈에서 다시 시도하지 않았다.
- **폐업 대조.** 확정 업소 1,754곳이 모두 `unknown`이다.
- **지도 키의 출처 등록.** `NAVER_MAP_CLIENT_ID`가 `localhost:8765`·`127.0.0.1:8765`에서
  인증에 실패한다. 파이프라인 밖의 콘솔 설정 문제이며 이 이슈에서 고치지 않았다.
