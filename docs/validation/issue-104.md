# 이슈 #104 지도 조작·목록 시트 검증

2026-09-13, Windows 11 · Python 3.12 · Node.js v24 · headless Chrome 모바일 에뮬레이션.
범위: [실기기 지적에 따라 목록 시트·지도 조작·방문 횟수 필터를 고친다 #104](https://github.com/snowjaewon/OfficialDeliciousMap/issues/104).

## 구현 확인

| 요구 | 확인 |
| --- | --- |
| 시트 머리의 빈 곳으로 끌기 | `the empty space in the sheet header drags without remeasuring during movement` |
| 끄는 동안 높이를 다시 읽지 않기 | 같은 테스트에서 pointerdown 뒤 pointermove·pointerup의 `offsetHeight` 읽기 수가 증가하지 않음 |
| `+ −` 컨트롤 제거 | `the map does not create a plus-minus zoom control`; Naver Maps 옵션 `zoomControl: false` |
| 방문 구간 복수 선택·전체 | `several visit bands can be selected together, and an empty selection means all`; 각 버튼의 `aria-pressed`를 집합 상태로 갱신 |
| 마커 선택 즉시 상세·선택 표시 | 기존 목록/마커 상세 테스트와 `selecting a map marker highlights it...`; 상세를 다시 그릴 때 스크롤을 0으로 초기화 |
| 지도 빈 곳에서 해제 | 같은 마커 선택 테스트; 지도 `click`에서 상세·선택 표시를 해제하고 선택 전 시트 상태로 복귀 |

전체 행동 테스트는 `node --test tests/site_behavior.test.js`로 46개 모두 통과했다.
측정 하네스는 1번과 5번 구간을 연속으로 켠 뒤 `전체`로 되돌려 복수 선택 경로를 포함한다.

## 랜딩 390×844 캡처

동일한 390×844 모바일 에뮬레이션과 숨겨진 설치 안내 조건에서 전후를 캡처했다.

| 이전 | 변경 후 |
| --- | --- |
| [landing-before.png](issue-104/landing-before.png) | [landing-after.png](issue-104/landing-after.png) |

변경 후 측정값은 CSS viewport `390×844`, document `scrollWidth=390`,
`scrollHeight=844`, 도시 카드 2열(열 너비 약 174.6px), 카드 7개다.
따라서 일곱 도시 카드가 가로 넘침·세로 스크롤 없이 한 화면에 들어온다.
이 캡처는 headless Chrome 에뮬레이션이며 iPhone Safari 실기기 캡처가 아니다.

## 실기기 상태

| 기기 | 결과 |
| --- | --- |
| iPhone Safari (iPhone 13) | 미확인 — 사용자가 6개 항목을 직접 확인해야 함 |
| Android Chrome | 미확인 |

실기기 확인 전에는 이 이슈를 데이터 품질·성능·접근성 완료로 간주하지 않는다.

## 실행한 검사

최종 검증에서 다음 결과를 확인했다.

- `.tools\\uv\\bin\\uv.exe run pytest`: 485 passed
- `.tools\\uv\\bin\\uv.exe run ruff check .`: 통과
- `.tools\\uv\\bin\\uv.exe run ruff format --check .`: 116 files already formatted
- `.tools\\uv\\bin\\uv.exe run mypy src`: 47 source files, issues 없음
- `node --test tests/site_behavior.test.js`: 46 passed
- `node --test tests/*.test.js`: 86 passed
- `git diff --check`: 통과
- `gitleaks git --pre-commit --staged --no-banner --redact`: no leaks found
