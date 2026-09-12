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
출처를 기록한다. 매직 바이트로 원본 컨테이너를 판정해 `SourceRef.container`에 남기므로 후속 단계는
게시판이 붙인 확장자가 아니라 이 값을 본다. 어떤 컨테이너도 아닌 응답(200으로 온 HTML 등)은
저장하지 않고 `unsupported-format`으로 실패한다.
받아들일 확장자는 게시판마다 실측한 것만 선언한다. 실측하지 않은 형식은 게시판을 끝까지 훑은 뒤
저장소 밖 `unmeasured.jsonl`에 모아 적고 한 번에 `unsupported-format`으로 알린다.
실측한 구조와 다르거나 통째로 읽을 수 없는 크기의 응답은 `adapter-failed`, 게시판에 닿지 못하면
`service-unavailable`로 구별해 알린다. 기관이 더는 내주지 않는 원본(404·410)과 200으로 온 빈
첨부는 서비스 장애와 구별해 수집을 멈추지 않고 `fetch.json`의 `missing`에 사유(`gone`·`empty`)와
함께 남긴다. 일시적 실패(연결 끊김·타임아웃·
5xx·429)만 4회까지 2초 배수로 다시 시도하고, 그래도 안 되면 `service-unavailable`로 실패한다. 한 기관에 연달아 보내는 요청에는 간격을 둔다.
이미 받은 원본은 다시 내려받지 않는다. 목록은 매번 다시 훑어 이미 받아 둔 게시글의 게시일·제목도
저장소 밖 `listing.jsonl`에 채운다. 게시판을 아직 선언하지 않은 도시는 0건 성공이 아니라
`not-implemented`로 실패한다. 현재 선언된 게시판은 광주광역시청 하나뿐이고
근거와 첫 실행 규모는 [정찰 기록](docs/validation/issue-51.md)에 있다.

`headermap`·`parse`·`classify`도 광주광역시청(`gwangju-city`) 게시판 하나에 대해
구현했다([이슈 #51](https://github.com/snowjaewon/OfficialDeliciousMap/issues/51)).

`headermap` 이후 단계는 받아 둔 원본 전체가 아니라 **이번 제출의 대상 원본**만 다룬다.
게시판은 22년치를 한 곳에 쌓아 두고 지출 기간은 게시글 제목에만 있으므로, 게시일의 해와
제목이 밝힌 기간(`period.targets`)이 모두 대상 기간과 맞는 게시글의 원본만 고른다. 고르는 일은
원본을 열기 전에 끝나 대상 밖 원본은 헤더 매핑에 가지 않는다. 수집 장부인 `fetch.json`은
줄이지 않으므로 무엇을 받아 두었는지는 그대로 남는다. 제목이 실측한 기간 표기를 쓰지 않으면
짐작하지 않고 대상에서 뺀다. 게시일도 제목도 없는 원본은 가를 근거가 없어 대상으로 둔다.

- `headermap`: 표마다 공통 헤더 서명 캐시 → 원본별 답변 이력 → Gemini 순으로 매핑을 찾고,
  코드 검증을 통과한 매핑만 쓴다. 표마다 호출은 최초 1회와 실패 사유를 담은 재호출 1회뿐이다.
  잘리거나 해석할 수 없는 응답과 카드형 표는 다시 묻지 않고 미해결로 남긴다.
- `parse`: xls·xlsx(ISO Strict 포함)를 읽는다. 모든 표가 통과한 원본만 레코드를 낸다. 원본마다
  후보·범위 밖 건수, 분모에서 뺀 행의 위치·종류, 0원·음수 레코드의 위치, 미해결 사유를
  `parse.json`의 `sources`에 남긴다. 목적·상호의 개인정보를 지우고, 경조사 수령인처럼 상호 칸에
  사람 이름이 적힌 경우 `개인(성명 비공개)`로 가린다. 부서가 누적 파일·정정본으로 다시 올려
  여러 원본에 반복된 지출은 [ADR-0004](docs/adr/0004-merge-repeated-reposts.md)의 기준으로 합치고,
  가를 근거가 없는 묶음은 남긴 뒤 그 수를 `parse.json`의 `repeated_expenses`에 싣는다. 사람이
  원본을 대조해 확정한 묶음은 그 확정을 기준보다 먼저 적용하며([ADR-0006](
  docs/adr/0006-human-confirmed-reposts.md)), 확정으로 합치거나 남긴 수를 자동 판정과 구별해
  같은 집계에 싣는다.
- `classify`: 사람 보정 → 도시 무관 LLM 캐시 → Gemini 순. 호출 실패는 판단 보류로 두고 캐시에 남기지 않는다.

PDF·HWP·원본 묶음 ZIP과 전량 추출 폴백은 파일 단위 미해결로 남으며 후속 작업이다.
다른 도시·기관, 인허가 전량 수집·폐업 대조, 실데이터 지도 성능 검증도 후속 작업이다.
배포는 [CI·배포](#ci배포)에 있다.

조회 키는 `.env`에서 읽는다. 네이버 지역검색은 `NAVER_SEARCH_CLIENT_ID`·`NAVER_SEARCH_CLIENT_SECRET`,
인허가 조회서비스는 `DATA_GO_KR_KEY`다. 키가 없는 제공자는 조회하지 않고, 모두 없으면 준비된 후보
파일만 쓴다. 네이버 키가 한쪽만 있으면 실행 전에 `configuration:`과 종료 코드 2로 거부한다.
`build`·`run`은 공개 가능한 지도 키 `NAVER_MAP_CLIENT_ID`도 요구한다.
헤더 매핑·비식당 판별은 `GEMINI_API_KEY`·`GEMINI_MODEL`과 요금 페이지에서 확인한 단가
`GEMINI_INPUT_USD_PER_MTOK`·`GEMINI_OUTPUT_USD_PER_MTOK`를 쓴다. 키가 있는데 단가가 없으면
종료 코드 2다. 모든 호출은 `data/_shared/llm-budget.jsonl`의 공통 예산(누적 USD 15)을 예약·정산하며
장부에 확인한 기존 사용액(`prior_usage`)이 없으면 호출하지 않는다.
값은 출력·산출물에 남기지 않는다. 셸에 `.env`를 불러온 뒤 실행한다.

```text
양쪽 공통: uv run --env-file .env python -m deliciousmap run --city gwangju
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
같은 대화상자에 누적 재게시로 장부에서 뺀 묶음·건수와 가를 근거가 없어 남긴 수를 적고, 사람이
확정해 뺀 수와 별개 지출로 확정해 남긴 수가 있으면 그것도 함께 적는다. 밝히지 않으면 장부 건수가
조용히 줄어든 것으로 보인다.

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
node --test tests/site_behavior.test.js tests/measure_map.test.js
```

#### 지도 성능 측정

`scripts/measure_map.js`는 [#22 결정](https://github.com/snowjaewon/OfficialDeliciousMap/issues/22#issuecomment-5614661364)의
절차를 설치된 Chrome으로 반복한다. Node.js 22 이상과 build한 `dist/<city>/`, 허용 주소가
`http://127.0.0.1:8765`인 지도 키가 필요하다. 스크립트가 `dist/`를 8765 포트로 직접 띄우므로
다른 서버를 먼저 띄우지 않는다.

```text
양쪽 공통: node scripts/measure_map.js --city gwangju --out <결과.json>
```

데스크톱과 모의 모바일(다운로드 10Mbps·업로드 1Mbps·지연 100ms·CPU 4배 감속)에서 각 20회
재어 표를 출력한다. 첫 방문은 매번 새 브라우저 컨텍스트(캐시·서비스 워커 없음)에서, 재방문은
캐시와 서비스 워커를 채운 컨텍스트의 새 탭에서 잰다. 입력·선택 피드백은 Event Timing(16ms
미만은 16ms로 적음), 결과·상세·장부 첫 목록은 앱의 `window.deliciousmapMetrics`로 잰다.
식당 선택은 검색 결과 첫 항목을 누르며 지도 마커를 누르는 경로와 실제 터치 입력은 재지 않는다.
드래그·줌·장부 스크롤은 각 조작 구간에 CDP `Tracing`을 붙여 브라우저 성능 기록을 남긴다.
`PipelineReporter`의 표시 프레임과 프레임 간격, Long Animation Frame·긴 작업을 요약하며,
판정에 쓰지 않은 원본 기록은 저장소 밖의 trace 디렉터리에 gzip 파일로 둔다. 결과 JSON에는
원본 이벤트가 아니라 요약만 들어간다. 60Hz 기준 한 프레임(16.7ms)의 두 배인 33.3ms
이상 간격을 끊김, 100ms 이상 간격이나 100ms 이상 Long Animation Frame·긴 작업을 멈춤으로
판정한다. 20회 모두 끊김·멈춤이 없어야 `충족`이고, 20회를 채우지 못하면 `미측정`이다.
URL이 `naver.com`이면 네이버 SDK, 로컬 주소이면 애플리케이션, 나머지는 미분류로 긴 작업
원인을 요약한다. trace 디렉터리는 기본적으로 임시 폴더에 만들며 `--trace-dir`로 저장 위치를
지정할 수 있지만 저장소 안은 거부한다. Chrome 경로는 `--chrome` 또는 `CHROME_PATH`로 바꾼다.

## 단계 계약과 후속 구현 접점

`contracts.py`의 입출력 모델, `pipeline.py`의 `Adapters` Protocol이 공개 경계다.
`execute(command, ExecutionContext(target, paths), adapters)`에 어댑터를 주입한다.
CLI를 포함한 통합 테스트에는 `cli.main(argv, cities=..., adapters=...)`를 사용한다.
기본 `LocalAdapters`가 운영 단계다. 게시판 수집·업소 판정과 후속 정제 출력에 연결한다.
게시판 해석기는 `src/deliciousmap/scrapers/`의 클래스이며 레지스트리의 `Board.scraper`가 가리킨다.
후보 조회는 `lookup.CandidateProvider`(현재 네이버 지역검색·인허가 조회서비스), 모델은
`headermap.HeaderMapper`·`classify.Classifier`·`comparison.ComparisonModel`로 분리한다.
통합 테스트는 `cli.main(argv, board_transport=..., model_transport=..., naver_transport=...,
license_transport=...)`로 외부 응답만 대신한다. 게시판 요청도 같은 `Transport` 경계를 쓴다.
선언되지 않은 도시의 스크래퍼는 후속 작업이다.

| 단계 | 입력 → 출력 |
| --- | --- |
| fetch | `FetchInput.target` → 외부 `SourceRef`(경로·SHA-256·기관·게시판·출처 URL·컨테이너)와 받지 못한 원본 |
| headermap | 원본 참조 → 표별 `HeaderMap`과 공통 캐시 참조 |
| parse | 원본 참조 + 매핑 + 도시별 재게시 확정 → `ParseOutput.records` |
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
`geocode.jsonl`(업소 확인), `compare.jsonl`(후보 비교 지정), `sources.jsonl`(미해결 원본 대조),
`repeats.jsonl`(재게시 확정)에 둔다. 자세한 내용은 [상호 복원](docs/restoration.md)에 있다.
각 줄은 계약 하나이며 없는 파일은 검토가 없는 것과 같다. 도시가 맞지 않는 줄은 그 단계가 거부하고,
`--org` 실행은 그 기관에 해당하는 줄만 읽는다(기관을 적지 않은 줄은 도시 전체에 걸린다).
범위를 선언하는 `restore`·`geocode`·`compare`·`repeats`는 같은 범위를 두 번 선언한 줄을,
`sources`는 한 원본을 두 번 적은 줄을 거부한다. `classify.jsonl`은 상호 범위가 겹칠 수 있어,
한 레코드에 서로 다른 판정이 걸릴 때 `classify`가 거부한다.
커밋된 광주 산출물은 아직 PDF 읽기와 미해결 원본 16개의 사람 최종 확인
이전이다([#66](https://github.com/snowjaewon/OfficialDeliciousMap/issues/66)). 그 둘을 갖춘
실행에서 `run --city gwangju`로 다시 만든다.

`repeats.jsonl`은 지출 하나(`기관·부서·집행일·상호·금액`)와 그 지출을 실은 원본 해시를 범위로
선언하고 `same_expense`/`separate_expenses` 중 하나를 근거와 함께 적는다. 장부에 없는 묶음이나
그 지출을 싣지 않은 원본을 가리키면 `parse`가 거부한다. 입력을 고치면 `parse`부터 다시 돌린다.

단계 메타데이터 파일은 `<stage>.json`이며 `schema_version`(fetch는 3, parse는 4, geocode는 5,
closure는 4, build는 6, 나머지는 1), `city`, `org`, 입력 해시인
`dependencies`, 실제 출력인 `payload`를 가진다. `fetch.json`은 받은 원본의 `sources` 외에
게시판이 링크했지만 받지 못한 원본을 `missing`(기관·게시판·게시글 주소·파일 이름·사유)에 남긴다.
`sources`·`missing`의 각 줄은 게시판 목록이 밝힌 `posted`(게시일)와 `title`(제목)도 싣고,
`sources`는 목록이 밝힌 작성 부서를 `department`에 싣는다. 원본 표에 부서 열이 없을 때 이 값이
부서가 된다. 목록 구조를 읽지 않는 스크래퍼는 이 셋을 채우지 않는다. `parse.json`에는 레코드를 중복 저장하지 않는다.
원본의 내용·개인정보를 메타데이터에 넣지 않는다. fetch 메타데이터의 외부 경로는 수집 PC 기준이다.

레코드 CSV의 열 순서(`storage.RECORD_FIELDS`)는 다음과 같다. UTF-8 BOM 없음, LF 줄바꿈,
표준 CSV 인용을 사용하며 레코드 순서를 유지한다.

```text
record_id,spent_on,organization,department,merchant,purpose,amount_krw,source_hash,source_location,repeats
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
| `source_location` | 공백 없는 표/행·카드 위치(예: `sheet1:R2`) |
| `repeats` | 누적 재게시로 합친 레코드가 겹친 원본들. `<해시>:<위치>`를 공백으로 나열하며 합치지 않았으면 빈 값 |

헤더 매핑은 `layout`, 1부터 시작하는 `header_rows`·`data_start_row`, `year_hint`,
0부터 시작하는 열 번호인 `columns`, 원 단위 변환 배수 `amount_multiplier`를 가진다.
열 역할은 `spent_on`, `merchant`, `purpose`, `department`, `amount_krw`, `month`, `day`, `time`이다.
정책·검증의 상세는 [ADR-0002](docs/adr/0002-ai-header-mapping.md)와
[폴백 정책](docs/specs/header-mapping-fallback.md)을 따른다. 코드 검증은 표의 지출 후보 전부가
날짜·금액·상호를 갖추고, 합계 행이 있으면 그 구역 또는 표 전체의 합과 정확히 같아야 통과한다.
빈 행·반복 헤더·소계·합계·`이하 빈칸` 같은 행은 분모에서 뺀다. 합계 행의 `N건`은 대조하지 않는다.
`누계`·`N월 합계`처럼 범위를 확정할 수 없는 합계는 대조하지 않고 `total_check=ambiguous`로 남긴다.

공통 캐시는 `headermap.jsonl`(키: 정책 버전과 정규화한 헤더 행 글자의 SHA-256. 행 길이가 열 수다.
값은 헤더 행·첫 지출 행까지의 거리·열 역할·금액 배수·모델)과 `classify.jsonl`(키: 정규화 상호)이다.
원본·표마다 받은 헤더 매핑 답은 `data/<city>/headermap-answers-v1.jsonl`에 쌓아, 코드가 바뀌어도
같은 표를 다시 묻지 않고 기록된 답을 다시 검증한다. 잘리거나 해석할 수 없던 응답도 과금된 시도로
남긴다. 표마다 호출 한도는 모델·지시문이 바뀌어도 이 이력으로 센다. 다시 물으려면 담당자가 그 파일을 지운다.
각 줄은 `schema_version=1`, `key`, 양의 정수 `revision`, `valid`, `evidence`, `value`를 가진다.
JSON 객체의 키와 줄의 `(key, revision)`을 정렬하며, 이력의 기존 값은 수정하거나 삭제하지 않는다.
같은 키·revision의 동일 항목 재추가는 무동작이고 다른 값이면 실패한다.
유효 판정은 `valid=true`인 가장 큰 revision이다. 검증 실패 이력은 이전 유효 판정을 삭제하지 않는다.
캐시에서 찾은 매핑이 검증에 실패하면 그 원본에서는 캐시를 쓰지 않고 한 번만 다시 묻는다.

`geocode.json`은 현 실행의 결과이고 `geocode-history-v2.jsonl`은 판정이 레코드에서 읽는 값·범위·
후보·근거·사람 확인·확정 복원명·판정 정책 버전의 해시 키로 성공·미확정을 추가 보존한다. 선행
산출물과 검토 파일의 해시는 이 키에 넣지 않으며([ADR-0003](docs/adr/0003-narrow-geocode-history-key.md)),
레코드도 통째로 넣지 않고 판정이 읽는 `record_id`·`merchant`만 넣는다
([ADR-0005](docs/adr/0005-key-only-what-the-decision-reads.md)).
`geocode-lookup-v1.jsonl`은 제공자·요청 맥락·응답 해석 버전의 해시 키로 조회 결과만 따로 보존한다.
조회 캐시 적중은 동일 업소 확정이나 사람 확인이 아니며 판정 이력과 섞지 않는다.
변경 없는 재실행은 이력을 중복 추가하지 않는다. 옛 `geocode-history.jsonl`은 보존만 하며
동일 업소의 근거로 재사용하지 않는다. 이전 버전 산출물은 재생성 전 `history/`에 보관한다.
직렬화 도구는 단일 작성자용이다. 동시 쓰기 잠금·실제 LLM/검색 캐시 엔진은 후속 범위다.
정제 산출물의 파일당 20MB 상한과 원본·인허가 원본·`dist/` 커밋 금지는
[ADR-0001](docs/adr/0001-commit-refined-artifacts.md)을 따른다. 파일 쓰기는 20,000,000바이트를 초과하면
분할을 요구하며 실패한다. 추가형 이력만 예외로, 이번 배치가 마지막 조각에 들어가지 않으면 그
조각을 그대로 닫고 `<이름>.002.<확장자>`부터 세 자리 번호를 붙인 다음 조각을 연다. 앞 조각은 다시
쓰지 않고 마지막 조각만 정렬을 지켜 다시 쓴다. 읽는 쪽은 번호 순으로 이어 읽고, 번호가 비었거나
같은 `(key, revision)`이 두 조각에 있으면 실패한다. CI는 build 전에 커밋된 파일마다 이 상한을
다시 검사한다([CI·배포](#ci배포)).

사람 보정의 각 줄은 `schema_version=1`, `city`, `merchant`, `status`
(`restaurant` / `non_restaurant`), `evidence`, 선택적 `organization`·`source_hash`를 가진다.
해당 도시 파일을 읽고 기관 선택 범위를 적용해 classify 입력에 전달한다. 실제 판정 우선순위의
적용은 classify 어댑터 책임이며 공통 LLM 캐시를 사람 보정으로 덮어쓰지 않는다.

상호 복원의 각 줄은 `schema_version=1`, 적용 범위인 `scope`, 확정 복원명 `restored_merchant`,
`evidence`, 선택적 `references`를 가진다. 식당 포함·제외를 정하는 사람 보정과 의미가 다르며
원본 표기를 덮어쓰지 않는다. 형식과 적용 규칙은 [상호 복원](docs/restoration.md)에 있다.

## CI·배포

[#15 결정](https://github.com/snowjaewon/OfficialDeliciousMap/issues/15#issuecomment-5611503849)을
[#53](https://github.com/snowjaewon/OfficialDeliciousMap/issues/53)이 구현했다. GitHub Actions가
커밋된 정제 산출물로 사이트를 build하고 Cloudflare Pages 프로젝트에 Wrangler Direct Upload로 올린다.
CI는 `build`만 호출하며 수집·파싱·지오코딩·LLM과 검색·Gemini 키를 쓰지 않는다.
workflow는 `.github/workflows/ci.yml`(`ci-build`·`preview`·`production`)과 기존 `gitleaks.yml`이다.

| 실행 | ci-build | 배포 |
| --- | --- | --- |
| `develop`·`main` 대상 PR | 실행 | 같은 저장소 PR만 미리보기(`pr-<번호>` branch). fork PR은 배포하지 않음 |
| `develop` push | 실행 | 없음 |
| `main` push | 실행 | 동결 전이면 운영. 동결 뒤에는 검사만 |
| `main`에서 수동 실행(사유 입력) | 실행 | 동결과 무관하게 같은 절차로 운영 |

`ci-build`는 두 필수 체크(`gitleaks`·`ci-build`) 중 하나라 경로 필터를 두지 않는다. 순서는 위의
설치·검증 명령과 `node --test tests/site_behavior.test.js` → 정제 산출물 검사 → 도시별 `build` →
`dist/` 검사와 manifest → artifact(`site-<SHA>`)다. 배포 job은 이 artifact를 받아 올릴 뿐 다시
build하지 않는다. 판정은 모두 `python -m deliciousmap.ci`가 하고 테스트는 `tests/test_ci.py`·
`tests/test_deploy.py`가 가짜 Pages·응답으로 네트워크 없이 검증한다.

| 명령 | 판정 |
| --- | --- |
| `check-data` | 정제 산출물 파일당 20,000,000바이트 초과, 등록되지 않은 도시 디렉터리, build할 도시 0곳을 실패로 본다. 통과하면 `data/<city>/`가 있는 도시를 레지스트리 순서로 낸다 |
| `check-dist` | Pages 한도(파일당 25MiB, 20,000개), `site.public_paths`의 화면용 파일 외 파일, 빠진 화면 파일, HTML·`sw.js`·`manifest.webmanifest`의 끊긴 참조를 실패로 본다. 통과하면 `dist/deploy-manifest.json`(상대 경로·SHA256·바이트·commit)을 쓴다 |
| `preview` | 올린 뒤 배포 고유 URL과 PR alias를 검증하고 결과를 Actions summary에 쓴다. build한 커밋은 PR의 임시 merge commit이므로 PR head SHA도 함께 적는다. 롤백하지 않는다 |
| `production` | 아래 운영 절차 |
| `wait-check` | 같은 커밋의 다른 workflow 체크(`gitleaks`)가 `success`로 끝날 때까지 기다린다. 실패·취소·건너뜀·15분 초과는 실패다 |

배포 검증은 배포 주소에서 manifest를 받아 빌드한 것과 같은지 보고, manifest의 파일을 모두 내려받아
압축을 푼 본문의 SHA256을 대조한다. 첫 화면은 build한 도시만 링크해야 하고, 7개 도시 진입 주소는
build한 도시만 도시 화면이어야 하며, `markers.json`·`records.json`은 `application/json`이면서 그
도시의 목록을 담아야 한다. Pages는 없는 경로에 첫 화면 HTML을 200으로 주므로 상태 코드만 보지 않는다.
alias는 전파가 늦을 수 있어 10초 간격으로 6번까지 본다.

운영 절차는 다음 순서다. 운영 job은 한 동시 실행 그룹에서 직렬화하고 진행 중인 실행을 취소하지 않는다.

1. 같은 커밋의 `gitleaks` 성공을 기다린다(`ci-build`는 같은 workflow의 선행 job이다).
2. 실행 자격과 동결을 본다. `main`이 아닌 ref, 사유 없는 수동 실행, 시간대 없는 동결 시각은
   종료 코드 2로 거부한다. 동결 뒤의 `main` push는 올리지 않고 성공으로 끝낸다.
3. Pages API로 지금 운영 배포를 찾고, 그 배포가 자기 manifest와 다시 대조되어 통과할 때만 롤백 대상으로
   보존하고 기록에 먼저 쓴다. manifest가 없는 배포(프로젝트를 만들 때 올린 빈 배포 등)는 대상이 아니다.
4. 업로드 직전에 원격 `main`을 다시 본다. 이 커밋보다 앞서 있으면 올리지 않는다. 동결 전에는 더 최신
   push가 배포하므로 성공이고, 동결 중에는 배포할 실행이 없으므로 실패로 남겨 최신 `main`에서 다시
   수동 실행하게 한다.
5. 올린 뒤 고유 URL → 운영 alias 순으로 검증한다.
6. 검증이 실패하거나 Wrangler가 배포를 확인해 주지 못하면 Pages API의 지금 운영 배포를 다시 본다.
   보존한 배포가 아니면 그 배포로 롤백하고, 어느 쪽이든 운영 alias를 보존한 manifest와 다시 대조한다.
   복구가 되어도 실행은 실패로 남는다. 롤백 대상이 없거나 재검증도 실패하면 사람이 대응한다.

대기 중인 운영 job은 같은 그룹의 더 새 job이 오면 GitHub가 취소한다. 취소는 성공으로 보고되지 않으며,
동결 중에 수동 실행이 이렇게 취소되면 다시 실행한다.

직전 배포 ID·manifest, 새 배포 ID·URL, 검증 결과는 summary와 artifact `release-<SHA>-<시도>`의
`release.json`에 남는다. 지도 키(`vars.NAVER_MAP_CLIENT_ID`·`vars.NAVER_MAP_KEY_PARAM`)는 build 단계에만,
Cloudflare 비밀값(`CLOUDFLARE_API_TOKEN`·`CLOUDFLARE_ACCOUNT_ID`)은 배포 단계에만 넘긴다. 배포 대상은
`vars.CLOUDFLARE_PAGES_PROJECT`, 운영 branch와 alias 주소는 Pages 프로젝트 설정에서 읽는다.

제출 동결은 `vars.DEPLOY_FREEZE_AT`에 실제 제출 시각을 `2026-09-20T18:00:00+09:00`처럼 시간대와 함께
넣어 켠다. 그 뒤 `main` push는 검사만 한다. 링크 장애·치명적 오류는 PR로 `main`에 합친 뒤 Actions의
`ci` workflow를 `main`에서 수동 실행하고 사유를 적는다. 동결은 `main` 잠금이 아니며 태그를 남기는
것만으로 배포가 멈추지 않는다. 실제 실행 결과는 [#53 검증](docs/validation/issue-53.md)에 있다.

## 라이선스

- **코드·문서**: [MIT](LICENSE).
- **데이터 라이선스** (`data/` 아래 정제 산출물): 각 기관이 법령에 따라 공개한 업무추진비 집행내역을 수집·정제한 것이다. 산출물은 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ko) 으로 배포한다. 다만 원 자료에 [공공누리](https://www.kogl.or.kr/) 유형이 표시된 경우 그 조건이 우선하며, 이용 시 원 기관(도시·기관 이름)을 출처로 밝힌다. 인허가 자료의 원본은 저장소에 두지 않고, 대조 결과만 남긴다.
