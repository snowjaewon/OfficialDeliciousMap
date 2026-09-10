# 이슈 #38 구현 검증

2026-09-10, Windows PowerShell·Git Bash, Python 3.12.10.
범위: [사람 확인에 따른 상호 복원과 재실행 #38](https://github.com/snowjaewon/OfficialDeliciousMap/issues/38).
사용법과 직렬화 계약은 [상호 복원](../restoration.md)에 있다.

## 구현과 TDD

부모 #36에서 사용자가 확정한 공개 CLI 경계에 합성 선행 산출물·후보·검토 입력·네트워크 차단·
임시 디렉터리를 사용했다. 새 테스트는 실제 범위 판단·업소 판정·저장·마커 연결을 실행하고,
`run` 경로에서는 범위 밖 수집·파싱·분류만 합성 어댑터로 제공한다.

실패→최소 구현→통과를 확인한 동작:

- 확정 복원명으로 근거를 대조하고 원본 표기를 유지한 채 마커까지 연결: 최초 `restoration` 키 부재 실패.
- 복원 검토를 분류 입력에 연결하고 원본을 다시 파싱하지 않음: 최초 합성 분류 입력에 복원 결과 부재 실패.
- 어느 줄도 더 좁지 않은 확인 두 줄: 최초 해시 순서로 조용히 하나를 고르는 종료 0 실패.
- 판단 보류 레코드의 복원·업소 확인 충돌: 최초 마커 대상이 아니라는 이유로 넘어가는 종료 0 실패.

추가 검증은 범위를 벗어난 동일 표기 업소로 번지지 않음, 확인 전 후보·유사 이름·후보 0건이
복원명이 되지 않음, 짧지만 정상인 상호의 무복원 채택, 복원명 확정 후 좌표 근거 부족 시 마커 보류,
좁은 범위 줄의 근거 채택, 확인 추가·수정·철회 시 의존 결과 갱신과 무관 레코드 결과·이력 보존,
다른 도시 줄 거부, 근거 발췌 상한 초과 거부, v2 산출물 보존과 재생성을 포함한다.

## 최종 검사

이 환경의 uv는 PATH에 없어 저장소 로컬 `.tools/uv/bin/uv.exe`로 실행했다.
다음 명령은 저장소 루트 기준 PowerShell·Git Bash 공통이며, 실제 검사는 Git Bash에서 수행했다.

| 명령 | 결과 |
| --- | --- |
| `uv sync --locked` | 통과, 17개 잠금 패키지 확인 |
| `uv run pytest` | **95 passed** |
| `uv run ruff check .` | 통과 |
| `uv run ruff format --check .` | 43개 파일 통과 |
| `uv run mypy src` | 소스 19개 통과 |
| `uv run python -m deliciousmap --help` | 종료 0, 기존 8개 명령 유지 |
| `git diff --check` | 통과 |
| gitleaks 스테이지 검사·커밋 훅 | 비밀 탐지 없음 |

## Standards

분기 기준 `917ceca785499740f5b194f10d1e89d3e32d339c`부터 구현 커밋 `9683566`까지
별도 Standards 에이전트가 검토했다.

문서화된 기준 위반 1건: `docs/restoration.md`의 명령 블록에 실행 환경 표시가 없었다.
AGENTS.md 명령어 규칙에 따라 "저장소 루트에서 PowerShell·Git Bash 공통"을 추가했다.

판단 사항에서 반영한 것: `markers.json`의 스키마 버전 상수 중복을 `storage.schema_version`으로
합쳤고, `paths.manual`의 기본값을 없애 호출부가 검토 입력을 명시하게 했으며,
`deliciousmap.restoration` 모듈을 가리던 테스트 도우미 이름을 `restore_entry`로 바꿨다.

반영하지 않은 것과 이유: `ManualCorrection`을 `RestorationScope`로 묶으면 문서화된 `classify.jsonl`
형식이 바뀌므로 이 티켓 범위 밖이다. `NameRestoration`과 `RestoredName`은 파일 입력과 레코드별
적용 결과로 역할이 다르므로 합치지 않았다. `PreparedPredecessors`의 상속 형태는 #37이 세운 선례다.
`restoration.applies`의 범위 판정과 저장 모듈의 기관 선택 필터는 모양만 같고 묻는 질문이 다르다.

## Spec

같은 변경을 별도 Spec 에이전트가 #38·부모 #36과 대조했다.

구현이 잘못된 지적 2건을 반영했다.

- 적용되는 확인이 여럿일 때 확정 복원명만 비교하고 근거·범위는 해시 순서로 골랐다.
  한 줄이 다른 모든 줄의 선언 항목을 포함할 때만 그 줄을 쓰고, 아니면 `conflicting-review`로 알린다.
- 복원명과 업소 확인의 충돌을 식당 레코드에서만 검사했다. 판단 보류·비식당 레코드의 어긋난 확인도
  검사하도록 `geocode` 단계의 검토 대상을 전체 레코드로 넓혔다.

누락 지적 2건은 반영하지 않았다. 확인 전 복원 후보는 조회 결과 그대로 `GeocodeResult.lookup`에
보존되며 별도 후보 계약을 만들면 부모 #36이 금지한 추측성 일반화가 된다. 마커의 복원 연결은
`record_ids`와 같은 `markers.json`의 geocode 판정으로 이미 이어진다. 두 가지 모두
`docs/restoration.md`에 명시했다.

범위 초과 지적 2건 중 `markers.json`의 v3 승격은 유지했다. `BuildOutput` 자체는 그대로지만
`markers.json`이 싣는 geocode 판정에 복원 결과가 들어가므로 형태가 실제로 바뀐다. 문서의
표현을 그 근거에 맞게 고쳤다. 저장 모듈 정리는 이 티켓이 추가한 세 번째 검토 입력의 중복을
없애기 위한 것으로, Standards 검토도 기존 중복 제거로 평가했다.

`applies`가 `scope.city`를 다시 비교하지 않는 점은 의도한 것이다. 도시 검사는 저장 모듈이 하며
다른 도시 줄은 `invalid-artifact`로 거부된다. `resolve`의 docstring에 전제를 적었다.

최초 발견: Standards 하드 1건·판단 8건, Spec 5건. 반영 후 남은 발견: 위에 근거를 적은
Standards 판단 4건과 Spec 4건이며 모두 의도한 설계다.

## 제한

실제 수집·파서·분류기·네이버/인허가 HTTP·LLM·유료 호출·HTML/PWA·배포는 수행하지 않았다.
담당자 지정 건의 LLM 후보 비교와 별도 검토 화면은 이 티켓 범위가 아니다.
저장은 단일 작성자용이며 자동 파일 분할은 없다. Windows 검사 결과로 Linux 실행 완료를 주장하지 않는다.
합성 테스트와 중간 JSON 빌드는 실데이터 상호 복원 품질 또는 제출 전 미해결 0건 검증이 아니다.
