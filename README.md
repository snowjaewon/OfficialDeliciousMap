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

**현재 운영 명령은 `cause=not-implemented`를 출력하고 종료 코드 1을 반환한다.**
가짜 성공 어댑터는 `tests/fakes.py`에만 있으며 운영 CLI에는 연결하지 않는다.
실제 게시판 수집·파일 변환·파싱·LLM·검색 API·인허가·사이트 생성·배포는 후속 작업이다.

| 옵션 | 의미·기본값 |
| --- | --- |
| `--city` | 필수 도시 slug: `seoul`, `busan`, `daegu`, `incheon`, `gwangju`, `daejeon`, `ulsan` |
| `--org` | 도시 안의 기관 slug. 생략하면 등록된 기관 전체 |
| `--raw-root` | 저장소 외부 원본 루트. 기본 `../deliciousmap-raw`; 인허가 자료 참조는 그 아래 `licenses/` |
| `--data-root` | 정제 산출물 루트. 기본 `data/` |
| `--output-root` | build 출력 루트. 기본 `dist/` |
| `--retry-failed` | geocode 입력에서 기존 실패의 재시도를 허용. 기본은 성공·실패 모두 재사용; 실제 호출 정책은 어댑터가 구현 |

상대 경로는 실행한 저장소 루트 기준이다. 원본 루트가 저장소 내부이면 거부한다.
도시별 `registry/<city>.py`는 dataclass 선언이며, 확인되지 않은 기관·게시판은 현재 비어 있다.
기관을 추가할 때 `Organization`과 `Board`에 검증된 주소와 실제 스크래퍼 클래스를 등록한다.
존재하지 않는 도시·기관 및 잘못된 경로는 실행 전에 종료 코드 2로 거부한다.

단계 실패는 `단계 city=도시 org=기관 cause=원인코드`와 종료 코드 1로 전달하고 후속 실행을 중단한다.
`org=*`는 도시 전체다. 원인 코드는 `not-implemented`, `invalid-artifact`, `io-error`,
`adapter-failed`, `unsupported-format`, `service-unavailable`이다. 예외 원문·서비스 응답은 출력하지 않는다.
판단 보류와 지오코딩 실패는 유효한 판정 상태이므로 장부용 레코드를 보존하고 build까지 전달한다.

## 단계 계약과 후속 구현 접점

`contracts.py`의 입출력 모델, `pipeline.py`의 `Adapters` Protocol이 공개 경계다.
`execute(command, ExecutionContext(target, paths), adapters)`에 어댑터를 주입한다.
CLI를 포함한 통합 테스트에는 `cli.main(argv, cities=..., adapters=...)`를 사용한다.
기본 어댑터는 없으며 각 도시 스크래퍼와 외부 서비스 구현은 이후에 연결한다.

| 단계 | 입력 → 출력 |
| --- | --- |
| fetch | `FetchInput.target` → 외부 `SourceRef`(경로·SHA-256·기관·게시판·출처 URL) |
| headermap | 원본 참조 → 표별 `HeaderMap`과 공통 캐시 참조 |
| parse | 원본 참조 + 매핑 → `ParseOutput.records` |
| classify | 레코드·고유 상호(`merchants`)·도시별 사람 보정 → 레코드별 최종 판정과 근거 |
| geocode | 식당 판정 상호·이전 성공/실패·재시도 여부 → 좌표 또는 실패와 근거 |
| closure | 좌표가 있는 마커 후보·외부 인허가 루트 참조 → `open` / `closed` / `unknown` |
| build | 레코드·판정·좌표·폐업 결과·마커 후보 → 출력 파일 경로와 레코드/후보 수 |

각 단계는 동일한 저장소 인터페이스로 이전 정제 산출물을 읽고 검증한 뒤 실행한다.
단일 단계는 필요한 선행 산출물이 없으면 `io-error`로 실패한다. `run`은 산출물을 차례로 만든다.
입출력 타입, 기관·원본 관계, 판정 대상의 완전성과 중복을 검사하며 설명 없는 0건은 실패다.
확인된 집행 없음은 fetch/parse의 `empty_reason`에 근거를 명시해야 한다.
classify 이후에는 입력 파일 SHA-256도 기록해 이전 입력의 판정을 재사용하지 못하게 한다.
레코드나 사람 보정을 바꾸면 classify부터 후속 단계를 다시 실행한다.

build는 `records.csv`, `parse.json`, `classify.json`, `geocode.json`, `closure.json`과
적용한 사람 보정만으로 입력을 만들며 원본·수집 메타데이터·API에 접근하지 않는다.
테스트의 `synthetic.txt`는 전달 검증용이다. 실제 지도 JSON, 마커 집계 알고리즘, HTML/PWA는 구현하지 않았다.
현재 마커 후보 키는 정규화된 상호(도시는 실행 범위)이며 동일 상호의 실제 업소 식별·별칭 병합은 후속 구현 책임이다.
폐업으로 확인된 후보도 제거하지 않는다.

## 저장 형식 v1

정제 산출물은 `data/<city>/`에 두며, `--org` 실행은 도시 전체 출력을 덮어쓰지 않도록
`data/<city>/orgs/<org>/`에 분리한다. 기관별 산출물을 도시 전체로 합치는 기능은 후속 작업이다.
공통 캐시는 `data/_shared/`, 사람 보정은 `data/manual/<city>/classify.jsonl`이다.
단계 메타데이터 파일은 `<stage>.json`이며 `schema_version=1`, `city`, `org`, 입력 해시인
`dependencies`, 실제 출력인 `payload`를 가진다. `parse.json`에는 레코드를 중복 저장하지 않는다.
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

`geocode.json`은 현 실행의 결과이고 `geocode-history.jsonl`은 같은 이력 형식으로
`상호|도시` 키의 성공·실패를 추가 보존한다. 변경 없는 재실행은 이력을 중복 추가하지 않는다.
직렬화 도구는 단일 작성자용이다. 동시 쓰기 잠금·실제 LLM/검색 캐시 엔진은 후속 범위다.
정제 산출물의 파일당 20MB 상한과 원본·인허가 원본·`dist/` 커밋 금지는
[ADR-0001](docs/adr/0001-commit-refined-artifacts.md)을 따른다. 상한 CI는 후속 작업이다.

사람 보정의 각 줄은 `schema_version=1`, `city`, `merchant`, `status`
(`restaurant` / `non_restaurant`), `evidence`, 선택적 `organization`·`source_hash`를 가진다.
해당 도시 파일을 읽고 기관 선택 범위를 적용해 classify 입력에 전달한다. 실제 판정 우선순위의
적용은 classify 어댑터 책임이며 공통 LLM 캐시를 사람 보정으로 덮어쓰지 않는다.

## 라이선스

- **코드·문서**: [MIT](LICENSE).
- **데이터 라이선스** (`data/` 아래 정제 산출물): 각 기관이 법령에 따라 공개한 업무추진비 집행내역을 수집·정제한 것이다. 산출물은 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ko) 으로 배포한다. 다만 원 자료에 [공공누리](https://www.kogl.or.kr/) 유형이 표시된 경우 그 조건이 우선하며, 이용 시 원 기관(도시·기관 이름)을 출처로 밝힌다. 인허가 자료의 원본은 저장소에 두지 않고, 대조 결과만 남긴다.
