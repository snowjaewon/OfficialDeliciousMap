# 공무원 맛집 지도

지자체가 공개하는 업무추진비 집행내역을 모아, 공무원이 자주 찾는 식당을 지도로 보여준다. 용어는 [CONTEXT.md](CONTEXT.md), 결정은 [docs/adr/](docs/adr/), 진행 상황은 [Wayfinder 지도](https://github.com/snowjaewon/OfficialDeliciousMap/issues/1)에 있다.

## 협업 시작

public 저장소다. 클론한 뒤 [SECURITY.md](SECURITY.md) 의 "협업자가 지킬 것" 을 먼저 따른다.

## 설치·검증

저장소 루트에서 실행한다. Python **3.12.10**, `uv`가 필요하다. 의존성과 개발 도구의
정확한 버전은 `uv.lock`에 고정한다. PowerShell·Git Bash 모두 다음 명령을 사용한다.
uv가 없다면 `python -m pip install uv`로 설치한 뒤 터미널을 다시 연다.

```text
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv run python -m deliciousmap --help
git diff --check
```

pytest는 네트워크 연결을 차단하고 합성 레지스트리·원본 참조·가짜 어댑터와 임시 디렉터리를
사용한다. API 키·실제 원본은 필요 없다. 개발 도구 설치 때에는 패키지 다운로드가 필요하다.
실제 실행 결과와 셸별 smoke 기록은 [이슈 #25 검증](docs/validation/issue-25.md)에 있다.

## CLI

[이슈 #25](https://github.com/snowjaewon/OfficialDeliciousMap/issues/25)의 뼈대다.
공개 명령은 `fetch`, `headermap`, `parse`, `classify`, `geocode`, `closure`, `build`, `run`이며,
`run`은 앞의 일곱 단계를 순서대로 실행한다. 루트와 각 명령의 `--help`는 오프라인에서 동작한다.

PowerShell·Git Bash 공통:

```text
uv run python -m deliciousmap run --help
uv run python -m deliciousmap fetch --city seoul --raw-root "../원본 보관" --data-root "./정제 산출물" --output-root "./빌드 출력"
uv run python -m deliciousmap geocode --city seoul --retry-failed
```

`geocode`는 담당자가 준비한 정제 레코드·후보·근거로 업소를 판정한다. 후보가 없는 레코드는
키가 있는 제공자(네이버 지역검색·인허가 조회서비스)로 후보를 조회한다. `closure`는 현재
폐업 대조 연결 전이므로 확인된 업소마다 `unknown`을 저장한다. `build`는 지도용 축약 정보를
`dist/<city>/markers.json`, 전체 장부를 `dist/<city>/records.json`으로 나누고 도시 카드 랜딩과
정적 지도 화면·PWA 기본 구성을 함께 만든다. 기관 실행은 데이터 파일만 `orgs/<org>/`에 분리한다.
[지오코딩 사용법과 계약](docs/geocoding.md)을 따른다.
`fetch`는 레지스트리에 선언된 게시판을 실제로 훑어 원본을 `--raw-root` 아래에 내려받고
출처를 기록한다. 매직 바이트로 원본 컨테이너를 확인하고 게시판이 밝힌 확장자와 대조하므로,
200으로 온 HTML이나 확장자와 어긋나는 첨부는 저장하지 않고 `unsupported-format`으로 실패한다.
받아들일 확장자는 게시판마다 실측한 것만 선언한다. 실측하지 않은 형식은 게시판을 끝까지 훑은 뒤
저장소 밖 `unmeasured.jsonl`에 모아 적고 한 번에 `unsupported-format`으로 알린다.
실측한 구조와 다르거나 통째로 읽을 수 없는 크기의 응답은 `adapter-failed`, 게시판에 닿지 못하면
`service-unavailable`로 구별해 알린다. 기관이 더는 내주지 않는 원본(404·410)과 200으로 온 빈
첨부는 서비스 장애와 구별해 수집을 멈추지 않고 `fetch.json`의 `missing`에 사유(`gone`·`empty`)와
함께 남긴다. 일시적 실패(연결 끊김·타임아웃·
5xx·429)만 4회까지 2초 배수로 다시 시도하고, 그래도 안 되면 `service-unavailable`로 실패한다. 한 기관에 연달아 보내는 요청에는 간격을 둔다.
이미 받은 원본은 다시 내려받지 않으며, 게시판을 아직 선언하지 않은 도시는 0건 성공이 아니라
`not-implemented`로 실패한다. 현재 선언된 게시판은 광주광역시청 하나뿐이고
근거와 첫 실행 규모는 [정찰 기록](docs/validation/issue-51.md)에 있다.
`headermap`·`parse`·`classify`의 실제 어댑터는 미구현이므로 운영 `run`은 아직 매핑 단계에서 실패한다.
파일 변환·파싱·LLM·인허가 전량 수집·폐업 대조·실데이터 지도 성능 검증·배포는 후속 작업이다.

조회 키는 `.env`에서 읽는다. 네이버 지역검색은 `NAVER_SEARCH_CLIENT_ID`·`NAVER_SEARCH_CLIENT_SECRET`,
인허가 조회서비스는 `DATA_GO_KR_KEY`다. 키가 없는 제공자는 조회하지 않고, 모두 없으면 준비된 후보
파일만 쓴다. 네이버 키가 한쪽만 있으면 실행 전에 `configuration:`과 종료 코드 2로 거부한다.
`build`·`run`은 공개 가능한 지도 키 `NAVER_MAP_CLIENT_ID`도 요구한다.
값은 출력·산출물에 남기지 않는다. 셸에 `.env`를 불러온 뒤 실행한다.

```text
Git Bash:   set -a; . ./.env; set +a; uv run python -m deliciousmap geocode --city seoul
PowerShell: Get-Content .env | ForEach-Object { if ($_ -match '^(\w+)=(.*)$') { Set-Item "env:$($Matches[1])" $Matches[2] } }
```

| 옵션 | 의미·기본값 |
| --- | --- |
| `--city` | 필수 도시 slug: `seoul`, `busan`, `daegu`, `incheon`, `gwangju`, `daejeon`, `ulsan` |
| `--org` | 도시 안의 기관 slug. 생략하면 등록된 기관 전체 |
| `--raw-root` | 저장소 외부 원본 루트. 기본 `../deliciousmap-raw`; 인허가 자료 참조는 그 아래 `licenses/` |
| `--data-root` | 정제 산출물 루트. 기본 `data/` |
| `--output-root` | build 출력 루트. 기본 `dist/`. `dist/`는 커밋하지 않는다 |
| `--retry-failed` | 변경 없는 미확정 결과도 다시 판정하고 실패 재시도 revision을 보존. 실패한 조회만 다시 요청하며 성공한 조회·판정은 재사용 |

상대 경로는 실행한 저장소 루트 기준이다. 원본 루트가 저장소 내부이면 거부한다.
도시별 `registry/<city>.py`는 dataclass 선언이며, 광주를 뺀 나머지 도시의 기관·게시판은 아직 비어 있다.
기관을 추가할 때 `Organization`과 `Board`에 **직접 확인한** 주소와 실제 스크래퍼 클래스를 등록하고,
확인 방법과 값을 `docs/validation/`에 남긴다. 스크래퍼는 `src/deliciousmap/scrapers/`에 두며
`boards.BoardScraper`의 계약(첨부 참조만 내고 저장·형식 판정은 하지 않음)을 따른다.
존재하지 않는 도시·기관 및 잘못된 경로는 실행 전에 종료 코드 2로 거부한다.

단계 실패는 `단계 city=도시 org=기관 cause=원인코드`와 종료 코드 1로 전달하고 후속 실행을 중단한다.
`org=*`는 도시 전체다. 원인 코드는 `not-implemented`, `invalid-artifact`, `io-error`,
`adapter-failed`, `unsupported-format`, `service-unavailable`, `lookup-failed`,
`regeneration-required`, `conflicting-review`, `missing-configuration`이다.
예외 원문·서비스 응답·비밀값은 출력하지 않는다.
조회 오류는 레코드별 결과를 저장한 뒤 `lookup-failed`로 실패한다. 후속 단계를 따로 실행하면
그 레코드를 보존한 중간 빌드가 가능하다. 이전 버전은 `geocode`→`closure`→`build`를 재실행한다.
판단 보류와 지오코딩 실패는 유효한 판정 상태이므로 장부용 레코드를 보존하고 build까지 전달한다.

### 정적 지도 화면

도시 전체 build를 실행하면 `dist/index.html`에 7개 도시 랜딩이, `dist/<city>/index.html`에
선택 도시 화면이 생긴다. 랜딩은 7개 도시 카드를 모두 두되 이미 build한 도시만 링크하고
나머지는 `준비 중`으로 남겨 미수집 도시를 열 수 있는 것처럼 보이지 않게 한다. 화면은
`markers.json`을 먼저 받아 식당명 검색, 20+ / 10~19 / 5~9 / 1~4 방문 횟수 필터, 전체 결과와
현재 지도 영역 결과 수, 마커 상세와 네이버 지도 연결을 제공한다. `records.json`은 장부 탭을
처음 열 때만 받으며 비식당·판단 보류·지오코딩 실패 레코드도 상태와 사유를 함께 표시한다.
한 번에 100건씩 그려 긴 장부의 첫 목록 렌더링을 제한한다.

`--org` 실행은 `dist/<city>/orgs/<org>/`에 두 데이터 파일만 낸다. 도시 셸·랜딩·PWA 파일은
도시 전체 실행에서만 만들며 기관 실행이 이를 덮어쓰지 않는다.

자료 범위 대화상자에 대상 기간(`site.REPORTING_PERIOD`, 현재 2026년 상반기)과 레지스트리에
선언한 기관별 수집 상태를 적는다. 상태는 `수집 완료`(이번 빌드에 레코드 있음), `레코드 없음`,
`수집 보류`(`Organization.hold_reason`: 봇 차단·DRM·게시판 유실·공개 기준 미달)이며 어느 쪽도
집행이 없었다는 뜻이 아니다. 수집 보류 기관이 있을 때만 지도 위에도 짧은 안내를 둔다.
기관의 수집 보류는 상호의 판단 보류와 다른 상태다. 장부는 레코드의 기관 slug를 담으므로
진입 페이지가 slug와 기관 이름의 대응을 함께 실어 화면에서 이름으로 보여 준다.

#### 공개 데이터 파일

| 파일 | 내용 |
| --- | --- |
| `markers.json` | `schema_version`(6), `city`, `org`, `markers` |
| `records.json` | `schema_version`(6), `city`, `org`, `records` |

마커 하나는 `business_id`, 확정 상호 `merchant`, `visit_count`(묶인 레코드 수), `latitude`,
`longitude`, `closed`, `coordinate_source`를 가진다. `coordinate_source`는 좌표를 준 제공자
(`local`·`naver`·`license`)다. 마커에 묶인 레코드는 좌표가 같으므로 첫 레코드의 판정에서 고르며,
그 판정이 사람 확인이면 확인한 후보의 제공자, 아니면 결과 좌표와 일치하는 후보의 제공자다.
여러 제공자의 근거가 같은 좌표로 겹치면 이름 순으로 하나를 밝힌다.
폐업으로 확인된 마커도 파일에서 빼지 않는다.

장부 레코드 하나는 `record_id`, `spent_on`, `organization`, `department`, `merchant`, `purpose`,
`amount_krw`와 `classification`(식당·비식당·판단 보류), `map_status`(`mapped`·`geocode_failed`·
`non_restaurant`·`pending`), 판정한 레코드의 `geocode_reason`, 마커로 묶인 레코드의
`business_id`를 가진다. 마커 수와 장부 레코드 수는 다를 수 있으며 `BuildOutput`에 그대로 남는다.
공개 파일에는 화면에 필요한 값만 넣는다. `source_hash`·`source_location`·`lookup_key`·
`dependency_key`·조회 원문·근거 발췌·사람 확인 파일은 넣지 않는다.

#### 지도 키와 로컬 확인

`build`와 `run`은 공개 가능한 `NAVER_MAP_CLIENT_ID`를 요구하고, 비어 있으면 실행 전에
`configuration:`과 종료 코드 2로 거부한다. 다른 명령은 이 변수를 요구하지 않는다. 신규 키의
기본 파라미터는 `ncpKeyId`이며 구형 키만 `NAVER_MAP_KEY_PARAM=ncpClientId`로 바꾼다. 그 밖의
값은 종료 코드 2로 거부한다. 키는 페이지 설정에만 들어가고 저장소 파일·로그·산출물
메타데이터에는 남기지 않는다. 키가 잘못되어 지도 인증이 실패하면 지도 자리에 설정 안내를
띄우고 검색 집계·구간 필터·장부는 계속 제공한다. 도시별 `MapBounds`는 초기 `fitBounds`,
최소 축소 수준, 지도 중심 이동 제한에 함께 사용한다.

build한 결과는 정적 파일이므로 로컬 서버로 확인한다. 기본 `--output-root`인 `dist/`를 쓴 경우다.

```text
Git Bash:   set -a; . ./.env; set +a; uv run python -m deliciousmap build --city seoul
PowerShell: Get-Content .env | ForEach-Object { if ($_ -match '^(\w+)=(.*)$') { Set-Item "env:$($Matches[1])" $Matches[2] } }
            uv run python -m deliciousmap build --city seoul
```

```text
양쪽 공통: uv run python -m http.server 8765 --directory dist --bind 127.0.0.1
```

브라우저에서 `http://127.0.0.1:8765/`를 열면 도시 카드 랜딩이, `http://127.0.0.1:8765/<city>/`가
선택 도시 화면이다. `file://`로 열면 `fetch`와 service worker가 동작하지 않으므로 쓰지 않는다.
확인한 결과는 [이슈 #48 검증](docs/validation/issue-48.md)에 있다.

브라우저 로직 테스트에는 Node.js 20 이상이 필요하며 아래 명령은 외부 패키지를 설치하지 않는다.

```text
node --test tests/site_behavior.test.js
```

## 단계 계약과 후속 구현 접점

`contracts.py`의 입출력 모델, `pipeline.py`의 `Adapters` Protocol이 공개 경계다.
`execute(command, ExecutionContext(target, paths), adapters)`에 어댑터를 주입한다.
CLI를 포함한 통합 테스트에는 `cli.main(argv, cities=..., adapters=...)`를 사용한다.
기본 `LocalAdapters`는 게시판 수집·업소 판정과 후속 정제 출력에 연결한다. 후보 조회는
`lookup.CandidateProvider`(현재 네이버 지역검색·인허가 조회서비스)로 분리하며, 통합 테스트는
`cli.main(argv, naver_transport=..., license_transport=..., board_transport=...)`로 외부 응답만 대신한다.
게시판 요청도 같은 `Transport` 경계를 쓴다. 선언되지 않은 도시의 스크래퍼는 후속 작업이다.

| 단계 | 입력 → 출력 |
| --- | --- |
| fetch | `FetchInput.target` → 외부 `SourceRef`(경로·SHA-256·기관·게시판·출처 URL) |
| headermap | 원본 참조 → 표별 `HeaderMap`과 공통 캐시 참조 |
| parse | 원본 참조 + 매핑 → `ParseOutput.records` |
| classify | 레코드·고유 상호(`merchants`)·도시별 사람 보정 → 레코드별 최종 판정과 근거 |
| geocode | 식당 판정 레코드·범위가 명시된 후보/근거·조회한 후보·사람 확인·이전 결과 → 레코드별 동일 업소·좌표 또는 미확정 이유 |
| closure | 좌표가 있는 마커 후보·외부 인허가 루트 참조 → `open` / `closed` / `unknown` |
| build | 레코드·판정·좌표·폐업 결과·마커 후보 → 출력 파일 경로와 레코드/후보 수 |

각 단계는 동일한 저장소 인터페이스로 이전 정제 산출물을 읽고 검증한 뒤 실행한다.
단일 단계는 필요한 선행 산출물이 없으면 `io-error`로 실패한다. `run`은 산출물을 차례로 만든다.
입출력 타입, 기관·원본 관계, 판정 대상의 완전성과 중복을 검사하며 설명 없는 0건은 실패다.
확인된 집행 없음은 fetch/parse의 `empty_reason`에 근거를 명시해야 한다.
classify 이후에는 입력 파일 SHA-256도 기록해 이전 입력의 판정을 재사용하지 못하게 한다.
레코드·사람 보정·확정 복원명을 바꾸면 classify부터 후속 단계를 다시 실행한다.

build는 `records.csv`, `parse.json`, `classify.json`, `geocode-input.json`, `geocode.json`,
`closure.json`과 적용한 사람 보정·상호 복원·업소 확인 파일로 재현하며 원본·수집 메타데이터·API에 접근하지 않는다.
마커는 확인된 업소 식별자로 묶는다. 동일 상호라도 지점·주소가 다르면 분리하고,
미확정 레코드는 전체 장부에만 남긴다. 패키지 안의 정적 자산을 렌더링·복사해 화면을 만들며
Node 기반 빌드 도구를 쓰지 않는다. 폐업으로 확인된 후보도 제거하지 않는다.

## 저장 형식

정제 산출물은 `data/<city>/`에 두며, `--org` 실행은 도시 전체 출력을 덮어쓰지 않도록
`data/<city>/orgs/<org>/`에 분리한다. 기관별 산출물을 도시 전체로 합치는 기능은 후속 작업이다.
공통 캐시는 `data/_shared/`에 둔다. 사람 검토 입력은 의미별로 나누어
`data/manual/<city>/`의 `classify.jsonl`(사람 보정), `restore.jsonl`(상호 복원),
`geocode.jsonl`(업소 확인)에 둔다. 자세한 내용은 [상호 복원](docs/restoration.md)에 있다.
단계 메타데이터 파일은 `<stage>.json`이며 `schema_version`(fetch는 2, geocode·closure는 4,
build는 6, 나머지는 1), `city`, `org`, 입력 해시인
`dependencies`, 실제 출력인 `payload`를 가진다. `fetch.json`은 받은 원본의 `sources` 외에
게시판이 링크했지만 받지 못한 원본을 `missing`(기관·게시판·게시글 주소·파일 이름·사유)에 남긴다. `parse.json`에는 레코드를 중복 저장하지 않는다.
원본의 내용·개인정보를 메타데이터에 넣지 않는다. fetch 메타데이터의 외부 경로는 수집 PC 기준이다.

레코드 CSV의 열 순서(`storage.RECORD_FIELDS`)는 다음과 같다. UTF-8 BOM 없음, LF 줄바꿈,
표준 CSV 인용을 사용하며 레코드 순서를 유지한다.

```text
record_id,spent_on,organization,department,merchant,purpose,amount_krw,source_hash,source_location
```

| 필드 | 표현 |
| --- | --- |
| `record_id` | 실행 범위 안에서 유일한 비어 있지 않은 안정적 레코드 식별자. 생성은 파서 책임 |
| `spent_on` | 실제 날짜 `YYYY-MM-DD` |
| `organization` | 레지스트리의 기관 slug, 항상 보존 |
| `department`, `purpose` | 문자열, 빈 값 허용. 개인정보는 실제 파서가 제거해야 함 |
| `merchant` | 정규화된 비어 있지 않은 상호 |
| `amount_krw` | 원 단위 유한 Decimal 문자열. 0·음수 허용; 부동소수점으로 합산하지 않음 |
| `source_hash` | 원본 SHA-256 소문자 16진수 64자 |
| `source_location` | 비어 있지 않은 표/행·카드 위치(예: `sheet1:R2`) |

헤더 매핑은 `layout`, 1부터 시작하는 `header_rows`·`data_start_row`, `year_hint`,
0부터 시작하는 열 번호인 `columns`, 원 단위 변환 배수 `amount_multiplier`를 가진다.
열 역할은 `spent_on`, `merchant`, `purpose`, `department`, `amount_krw`, `month`, `day`, `time`이다.
정책·검증의 상세는 [ADR-0002](docs/adr/0002-ai-header-mapping.md)와
[폴백 정책](docs/specs/header-mapping-fallback.md)을 따른다. 매핑·파싱 알고리즘과 예산 집행은 아직 없다.

공통 캐시는 `headermap.jsonl`(키: 정규화 헤더 텍스트와 열 수의 SHA-256),
`classify.jsonl`(키: 정규화 상호)이다. 키 생성은 후속 어댑터의 책임이다.
각 줄은 `schema_version=1`, `key`, 양의 정수 `revision`, `valid`, `evidence`, `value`를 가진다.
JSON 객체의 키와 줄의 `(key, revision)`을 정렬하며, 이력의 기존 값은 수정하거나 삭제하지 않는다.
같은 키·revision의 동일 항목 재추가는 무동작이고 다른 값이면 실패한다.
유효 판정은 `valid=true`인 가장 큰 revision이다. 검증 실패 이력은 이전 유효 판정을 삭제하지 않는다.
헤더 검증 실패 시 해당 원본에서 캐시를 우회하는 정책은 실제 headermap 어댑터가 구현한다.

`geocode.json`은 현 실행의 결과이고 `geocode-history-v2.jsonl`은 레코드·범위·후보·근거·
사람 확인·입력 의존성·정책 버전의 해시 키로 성공·미확정을 추가 보존한다.
`geocode-lookup-v1.jsonl`은 제공자·요청 맥락·응답 해석 버전의 해시 키로 조회 결과만 따로 보존한다.
조회 캐시 적중은 동일 업소 확정이나 사람 확인이 아니며 판정 이력과 섞지 않는다.
변경 없는 재실행은 이력을 중복 추가하지 않는다. 옛 `geocode-history.jsonl`은 보존만 하며
동일 업소의 근거로 재사용하지 않는다. 이전 버전 산출물은 재생성 전 `history/`에 보관한다.
직렬화 도구는 단일 작성자용이다. 동시 쓰기 잠금·실제 LLM/검색 캐시 엔진은 후속 범위다.
정제 산출물의 파일당 20MB 상한과 원본·인허가 원본·`dist/` 커밋 금지는
[ADR-0001](docs/adr/0001-commit-refined-artifacts.md)을 따른다. 파일 쓰기는 20,000,000바이트를 초과하면
분할을 요구하며 실패한다. 상한 CI는 후속 작업이다.

사람 보정의 각 줄은 `schema_version=1`, `city`, `merchant`, `status`
(`restaurant` / `non_restaurant`), `evidence`, 선택적 `organization`·`source_hash`를 가진다.
해당 도시 파일을 읽고 기관 선택 범위를 적용해 classify 입력에 전달한다. 실제 판정 우선순위의
적용은 classify 어댑터 책임이며 공통 LLM 캐시를 사람 보정으로 덮어쓰지 않는다.

상호 복원의 각 줄은 `schema_version=1`, 적용 범위인 `scope`, 확정 복원명 `restored_merchant`,
`evidence`, 선택적 `references`를 가진다. 식당 포함·제외를 정하는 사람 보정과 의미가 다르며
원본 표기를 덮어쓰지 않는다. 형식과 적용 규칙은 [상호 복원](docs/restoration.md)에 있다.

## 라이선스

- **코드·문서**: [MIT](LICENSE).
- **데이터 라이선스** (`data/` 아래 정제 산출물): 각 기관이 법령에 따라 공개한 업무추진비 집행내역을 수집·정제한 것이다. 산출물은 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ko) 으로 배포한다. 다만 원 자료에 [공공누리](https://www.kogl.or.kr/) 유형이 표시된 경우 그 조건이 우선하며, 이용 시 원 기관(도시·기관 이름)을 출처로 밝힌다. 인허가 자료의 원본은 저장소에 두지 않고, 대조 결과만 남긴다.
