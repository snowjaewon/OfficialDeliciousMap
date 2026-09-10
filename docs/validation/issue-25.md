# 이슈 #25 뼈대 구현 검증

검증일: 2026-09-10. 범위: [이슈 #25](https://github.com/snowjaewon/OfficialDeliciousMap/issues/25).
Windows, Python 3.12.10, PowerShell, Git for Windows의 `C:/Program Files/Git/bin/bash.exe`에서 확인했다.
WSL을 사용하지 않았으며 Linux에서 pytest를 실행한 결과는 아니다.

## 설치와 최종 검사

이 환경에는 uv가 PATH에 없어 `.tools/uv/bin/uv.exe`(0.12.12)를 로컬 설치했다.
아래 `uv` 검사는 모두 그 실행 파일로 수행했다. `.tools/`와 가상환경은 커밋하지 않는다.

기존 `.venv`와 별개로 비어 있는 `.tools/clean-env`를 `UV_PROJECT_ENVIRONMENT`에 지정하고
`uv sync --locked`를 실행했다. 17개 패키지 설치, `python -m deliciousmap --help`,
`mypy src`가 통과했다. 검사 후 해당 환경변수는 제거했다.

| 검사 | 최종 결과 |
| --- | --- |
| `uv sync --locked` | 통과, 잠금 파일 변경 없음 |
| `uv run ruff check .` | 통과 |
| `uv run ruff format --check .` | 통과 |
| `uv run mypy src` | 16개 소스 파일 통과 |
| `uv run pytest` | **54 passed**, 6.64초 |
| `uv run python -m deliciousmap --help` | 종료 0 |
| `git diff --check` | 통과 |
| gitleaks 기능 브랜치 검사·커밋 훅 | 비밀 탐지 없음 |

공개 CLI와 단계 계약에서 실패 테스트를 먼저 확인한 뒤 구현했다. 주요 검증은
8개 명령 help, 선택 검증, 산출물 전달, 단일 단계와 run의 일치, 모든 단계의 실패 중단,
잘못된 산출물·오래된 판정 거부, CSV/JSONL round-trip, 캐시 재사용·실패 재시도,
도시·기관 경로 분리, 비식당·판단 보류·좌표 실패 레코드의 장부 입력 보존이다.
합성 CSV는 `tests/fixtures/seoul/records.csv`에 있으며 외부 원본에서 가져오지 않았다.

## PowerShell·Git Bash smoke

저장소 루트에서 양쪽 셸로 아래 동일한 인자를 실행했다. `uv` 대신 위 로컬 실행 파일 경로를 사용했다.
Git Bash는 `--noprofile --norc`로 실행한 UTF-8 스크립트 파일에서 명령을 호출했다.

```text
uv run python -m deliciousmap fetch --city seoul --raw-root "../원본 보관" --data-root "./정제 산출물" --output-root "./빌드 출력"
```

두 셸 모두 출력은 `fetch city=seoul org=* cause=not-implemented`, 종료 코드는 **1**이었다.
한글·공백 경로가 인자로 정상 전달되고 미구현 실제 어댑터에서 실패하는 예상 동작이다.
`정제 산출물/`, `빌드 출력/`이 만들어지지 않았음도 두 셸에서 확인했다.
가짜 어댑터의 성공 경로는 pytest 임시 디렉터리의 한글·공백 경로에서 별도로 검증했다.

## Standards

비교 기준은 `26133fee088b3e8c0cc28a0bf1624b544c7bdebe`(분기 시 develop)이며,
최초 구현 커밋 `2d27b30`을 독립된 Standards 에이전트가 검토했다.

1. **문서 정책 충돌**: SECURITY.md의 옛 보존 목록에는 목적이 없었지만 CONTEXT.md와
   #25는 목적·원본 해시·출처 위치를 요구했다. 최신 계약과 일치하도록 보존 필드를 명시하고
   목적의 개인정보 제거 책임과 실제 파서 미구현 상태를 적었다. 합성 fixture에서 개인정보 유출은 없었다.
2. **가능한 Duplicated Code (판단 사항)**: `execute()`와 `_execute_one()`에 단계 순서 루프가 중복됐다.
   단계 순서는 `execute()`만 담당하도록 수정했다.

수정 후 독립 재검토: 최초 2건 모두 해결, 새 Standards 문제 없음.

## Spec

같은 기준으로 별도 Spec 에이전트가 이슈 #25와 대조했다.

1. **P2 — 저장소 내부 원본 참조 허용**: 원본 루트를 저장소 상위 디렉터리로 지정하면
   저장소 내부 원본 참조가 통과했다. 개별 원본의 해석된 경로에도 저장소 내부 금지를 적용했다.
   회귀 테스트의 실패→통과를 확인했고, 공개 `Target`에서도 경로 우회가 불가능하도록 검증했다.

수정 후 독립 재검토: P2 해결, 새 Spec 문제 없음. 실제 수집·외부 API·파싱 알고리즘·사이트 구현 제외는
이슈 범위와 일치함을 확인했다.

최초 발견: Standards 2건(문서 충돌·낮은 우선순위 중복), Spec 1건(P2). 수정 후 남은 발견: 각 0건.

## 남은 구현 범위

운영 CLI는 명시적으로 실패한다. 실제 스크래퍼·변환기·파서·개인정보 제거·헤더 매핑·분류·공통 LLM
예산·지오코딩·인허가·마커 집계·지도·장부 화면·PWA·배포는 구현하지 않았다.
기존 gitleaks workflow 외의 Python CI, 20MB 상한 CI, 실제 캐시 엔진과 동시 쓰기 제어도 후속 작업이다.
본 결과는 실제 수집 성공·데이터 품질·사이트 배포 완료의 증거가 아니다.
