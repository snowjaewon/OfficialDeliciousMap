# AGENTS.md

## Agent skills

### Issue tracker

이 레포의 이슈는 GitHub Issues(snowjaewon/OfficialDeliciousMap)에서 관리한다 — `gh` CLI 사용. See `docs/agents/issue-tracker.md`.

### Triage labels

기본 라벨 5종을 그대로 사용 (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

single-context — 루트 `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.

## Git & PR 규칙

### 브랜치 (Git Flow)

- `main`은 운영 릴리스, `develop`은 다음 릴리스의 통합 브랜치다. `develop`이 아직 없으면 최신 `main`에서 최초 분기한다.
- 일반 코드·문서 작업은 최신 `develop`에서 `feature/<issue>-<slug>`로 분기하고 `develop` 대상 PR로 합친다.
- 릴리스 준비는 `develop`에서 `release/<version>`으로 분기한다. 검증 후 `main`에 PR로 합쳐 버전 태그를 남기고, 릴리스 수정도 `develop`에 PR로 반영한다.
- 운영 긴급 수정은 `main`에서 `hotfix/<issue>-<slug>`로 분기한다. `main`과 `develop` 모두에 PR로 반영하며, 진행 중인 release에도 필요한 수정을 반영한다.
- 파이프라인 실행 전 최신 `main`을 가져오고 작업 브랜치에도 반영한다. 작업 브랜치의 기반인 `develop`도 동기화한다. 미커밋 변경을 먼저 보존하고 강제 덮어쓰기를 하지 않는다.
- 이 흐름은 [두 사람의 분담과 작업 규칙](https://github.com/snowjaewon/OfficialDeliciousMap/issues/8)의 브랜치 흐름을 2026-09-10 사용자 결정으로 구체화한다. 모든 변경의 PR 필수·승인 0·셀프 머지 허용은 유지한다. 상대 담당 영역 변경 시 리뷰를 요청한다.

### 커밋·PR

- 커밋과 PR 제목은 `<type>(<scope>): <요약>` 형식의 Conventional Commits를 사용한다. scope는 선택이며 type은 `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `build`, `perf`, `revert`를 쓴다. 예: `feat(cli): 파이프라인 단계 명령 추가`.
- 커밋은 하나의 목적과 검증 가능한 변경 단위로 나눈다. PR 본문에는 해결할 문제, 변경 후 동작, 관련 이슈, 검증 명령·결과, 남은 제한을 적는다.
- 구현 이슈를 `develop` PR로 처리할 때는 관련 이슈를 링크하고, 실제 완료 기준을 검증한 뒤 닫는다. 기본 브랜치가 아닌 대상 PR의 `Closes` 문구만으로 자동 종료를 기대하지 않는다.
- 머지 전 변경에 필요한 검사와 gitleaks를 통과한다. CI 도입 시 `develop`·`main` 대상 PR 모두 검사하며, 운영 배포는 `main` 기준이다. 상세 배포 계약은 [CI 빌드·배포 흐름](https://github.com/snowjaewon/OfficialDeliciousMap/issues/15)을 따른다. 이 문서 작성이 원격 브랜치 보호·workflow 적용 완료를 뜻하지는 않는다.

## 파이프라인

- mattpocock/skills의 개별 스킬을 사용한다. 결정 탐색은 `wayfinder`, 구현은 `implement` → `tdd` → `code-review` 흐름이다. 이슈의 범위·완료 기준을 먼저 읽고, 현재 세션에서 사용 가능한 실제 스킬 이름과 `SKILL.md`를 확인한다.
- Codex에서는 `$wayfinder`, `$tdd`, `$code-review`처럼 실제 이름으로 호출한다. slash 명령을 지원하는 환경에서는 해당 환경에 등록된 개별 스킬 명령을 쓴다. `matt-pocock`을 공통 실행 명령으로 가정하지 않는다. 필요한 스킬이 세션에서 보이지 않으면 그 사실과 설치 경로를 보고한다.
- 명령 계약은 `python -m deliciousmap <단계> --city <도시> [--org <기관>]`이며, 명령은 `fetch`, `headermap`, `parse`, `classify`, `geocode`, `closure`, `build`, `run`이다. `run`은 앞의 일곱 단계를 순서대로 연결한다.
- 단계별 입력·출력과 배치는 [파이프라인 모듈 경계와 저장소 구조](https://github.com/snowjaewon/OfficialDeliciousMap/issues/2)를 따른다. [파이프라인 뼈대 구현](https://github.com/snowjaewon/OfficialDeliciousMap/issues/25)은 CLI·계약·단계 연결·테스트까지이며 실제 수집·외부 API·사이트·배포 구현은 후속 작업이다.

## 명령어

- 명령은 저장소 루트에서 실행하는 기준으로 적고 PowerShell, Git Bash, 양쪽 공통 중 실행 환경을 표시한다. 공백·한글이 있는 경로를 인용하고, 셸별 환경변수·줄 연결·리다이렉션 문법을 섞지 않는다.
- Python 도구는 가상환경 활성화에 의존하지 않고 `uv run`으로 실행한다. 아래 명령은 뼈대 이슈가 패키지·도구 설정을 추가한 뒤 사용하는 양쪽 공통 검증 명령이다.

```text
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python -m deliciousmap --help
git diff --check
```

- `.sh`는 Git Bash의 Bash로 실행한다. PowerShell에서는 Git for Windows의 Bash를 명시해 호출하고 WSL Bash와 혼동하지 않는다. UTF-8 문서를 PowerShell로 읽을 때는 `Get-Content -Encoding utf8`을 사용한다.
- GitHub 이슈·PR의 여러 줄 본문은 UTF-8 파일에 쓰고 `gh ... --body-file <경로>`로 전달한다.

## 코드스타일

- Python 이름은 함수·변수·모듈에 `snake_case`, 클래스에 `PascalCase`, 상수에 `UPPER_SNAKE_CASE`를 쓴다. 도메인 이름은 `CONTEXT.md`와 일치시킨다.
- 공개 함수와 단계 입출력에 타입 힌트를 둔다. 레지스트리는 도시별 Python 모듈의 dataclass로 선언하고, 도시·기관·게시판별 값은 레지스트리에서 가져온다.
- Ruff로 lint·import 정렬·format을 관리한다. 세부 설정과 Python 지원 버전은 뼈대 구현에서 `pyproject.toml`에 명시하고 이후 그 파일을 단일 기준으로 삼는다.
- CLI는 인자·입출력·종료 코드 변환을 담당한다. 단계 로직과 외부 통신은 분리하고 파일 경로는 `pathlib`로 처리한다. 예외에 단계·대상·실패 사유를 남기되 비밀값과 원본 내용을 로그에 노출하지 않는다.

## 테스트

- 실제 동작을 추가·수정할 때 TDD로 실패하는 행동 테스트 → 최소 구현 → 리팩터링 순서를 따른다. pytest로 공개 CLI와 단계 계약을 검증한다.
- 기본 테스트는 네트워크·실제 API 키·유료 호출 없이 실행한다. 외부 서비스는 주입 가능한 가짜 어댑터, 파일 출력은 임시 디렉터리를 사용한다.
- 정상 연결뿐 아니라 잘못된 도시·기관, 단계 실패 전달, 잘못된 산출물, 캐시 재사용·재실행, 비식당·판단 보류·좌표 실패 레코드의 장부 보존을 해당 구현 범위에서 검증한다.
- 합성 fixture를 우선 사용한다. 원본에서 만든 fixture는 익명화한 상위 5행·파일당 100KB 이내로 `tests/fixtures/<city>/`에 둔다. 원본 파일 자체는 커밋하지 않는다.
- 작업 중 관련 테스트를 실행하고 완료 시 전체 테스트와 Ruff 검사를 실행한다. 문서만 변경하면 링크·내용·`git diff --check`를 확인하며 의미 없는 실행 테스트를 추가하지 않는다.

## 아키텍처

- 정식 패키지는 `src/deliciousmap/`, 테스트는 `tests/`에 둔다. Python 파이프라인과 정적 HTML/PWA를 유지한다. 원본 수집·파싱·LLM·지오코딩은 개발자 PC에서, CI 사이트 빌드는 커밋된 입력으로 수행한다.
- 원본·정제 산출물·캐시를 다룰 때 [ADR-0001](docs/adr/0001-commit-refined-artifacts.md), 헤더 매핑·추출을 다룰 때 [ADR-0002](docs/adr/0002-ai-header-mapping.md)와 [폴백 정책](docs/specs/header-mapping-fallback.md)을 읽는다.
- `data/<city>/`는 도시 담당자가 갱신한다. 공통 캐시의 키 정렬 JSONL·추가형 이력은 [협업 결정](https://github.com/snowjaewon/OfficialDeliciousMap/issues/8)을 따른다. 초기 모듈 결정의 `.json` 예시보다 이후의 JSONL 합의를 우선한다. 사람 보정은 `data/manual/<city>/`에 분리한다.
- 기존 결정과 충돌하면 충돌 근거를 밝힌다. 도메인 용어는 `CONTEXT.md`, 결정의 이유는 해당 이슈·ADR에 기록하고 중복 스펙을 만들지 않는다.

## 개발 환경

- Windows PowerShell·Git Bash를 지원하고 CI의 Linux에서도 경로·인코딩이 같게 동작하도록 한다. `.gitattributes`의 줄바꿈 규칙을 따른다.
- 의존성은 uv로 관리한다. 뼈대 구현에서 `pyproject.toml`, `uv.lock`, `.python-version`을 추가하고 커밋한다. `.venv`는 로컬에만 둔다. Python 버전은 구현 시 의존성 호환성을 확인해 고정한다.
- 클론 직후 훅·키 설정은 [SECURITY.md](SECURITY.md)를 따른다. 현재 main에는 패키지·테스트 설정이 없으므로 위 개발 명령이 이미 동작한다고 보고하지 않는다. 뼈대 머지 후 이 전환 안내를 제거한다.

## 주의 사항

- 비밀값·개인정보·유출 대응은 [SECURITY.md](SECURITY.md)를 따른다. 원본·인허가 원본·`dist/`는 커밋하지 않는다. 정제 산출물의 파일당 20MB 상한은 ADR-0001을 따른다.
- LLM 호출·재시도·예산 집행은 [폴백 정책](docs/specs/header-mapping-fallback.md)이 기준이다. 프로젝트 합산 USD 15 한도를 실행마다 초기화하거나 옛 비용 추정으로 대체하지 않는다.
- 목업 저장소와 헤더 매핑 프로토타입은 지식·검증 경험만 참고하고 정식 코드·데이터로 이식하지 않는다.
- 미지원 형식·실패·판단 보류를 성공이나 0건으로 숨기지 않는다. 뼈대의 가짜 어댑터 통과를 실제 수집·데이터 품질·배포 완료로 보고하지 않는다.
