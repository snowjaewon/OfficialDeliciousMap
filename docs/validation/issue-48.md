# 이슈 #48 정적 사이트 빌드 검증

2026-09-11, Windows 11 · Git Bash · Python 3.12.10 · Node.js v24.14.1.
범위: [정제 산출물로 정적 사이트 빌드 구현 #48](https://github.com/snowjaewon/OfficialDeliciousMap/issues/48).
사용법과 공개 파일 계약은 [README의 정적 지도 화면](../../README.md#정적-지도-화면)에 있다.

## 선행 상태

[도시별 정적 지도와 장부 로딩 구현(PR #47)](https://github.com/snowjaewon/OfficialDeliciousMap/pull/47)이
이미 `markers.json`·`records.json` 분리, 도시 랜딩·진입 페이지, 지도 화면, manifest·service worker,
`City.map_bounds`를 develop에 넣었다. 이 작업은 그 위에서 #48의 남은 범위만 구현한다.

## 결정의 출처

- 필수 기능 목록과 수집 상태 공개: [화면 기능 범위 #12](https://github.com/snowjaewon/OfficialDeliciousMap/issues/12#issuecomment-5611428144).
- 도시별 파일 분리, 도시 전체 결과와 현재 지도 영역 구분: [로딩 전략 #22](https://github.com/snowjaewon/OfficialDeliciousMap/issues/22#issuecomment-5614661364).
- CI는 커밋된 정제 산출물로 `build`만 실행하고 지도 키는 Variables로 주입:
  [CI 빌드·배포 흐름 #15](https://github.com/snowjaewon/OfficialDeliciousMap/issues/15#issuecomment-5611503849).
- 수집 보류 사유 네 가지와 장부 보존 범위: [CONTEXT.md](../../CONTEXT.md).

## 이번에 구현한 것

| 범위 | 결과 |
| --- | --- |
| 좌표 출처 | `PublishedMarker.coordinate_source`(`local`·`naver`·`license`)를 마커 상세에 표시 |
| 장부 사유 | 장부 레코드에 `geocode_reason`과 묶인 `business_id` 보존, 화면에 사유 표시 |
| 공개 범위 | 장부에서 `source_hash`·`source_location` 제거, `build` 계약 v5 → v6 |
| 기관 실행 | `--org`는 데이터 파일만 내고 도시 셸·랜딩·PWA를 만들지 않음 |
| 수집 상태 | `Organization.hold_reason` 추가, 자료 범위에 기간·기관별 상태·보류 사유 표시 |
| 지도 위 안내 | 수집 보류 기관이 있을 때만 표시 |
| 기관 이름 | 진입 페이지가 slug→이름 대응을 실어 장부가 이름으로 표시 |
| 지도 키 | `build`·`run`만 `NAVER_MAP_CLIENT_ID`를 요구하고 없으면 종료 코드 2 |
| 랜딩 | 7개 도시 카드를 유지하되 build한 도시만 링크, 나머지는 `준비 중` |
| 지도 불가 | 인증 실패를 공식 훅으로 받아 안내를 띄우고 검색·집계·장부는 유지 |

## 구현과 TDD

주 테스트 경계는 기존 공개 CLI(`cli.main`)와 그 산출물이다. 브라우저 로직은
`tests/site_behavior.test.js`가 Node 내장 러너로 `app.js`의 공개 함수에 직접 건다.
네트워크는 pytest에서 차단하고 임시 디렉터리와 합성 선행 산출물만 쓴다. 실제 키는 없다.

실패 → 최소 구현 → 통과를 확인한 동작(`tests/test_site_build.py` 14건):

- `build`·`run`이 지도 키 없이 종료 코드 2와 `configuration: NAVER_MAP_CLIENT_ID`로 거부하고
  출력 디렉터리를 만들지 않음: 최초 CLI 확인 부재로 실패.
- `geocode` 등 다른 명령은 같은 상황에서 영향받지 않음.
- 알 수 없는 `NAVER_MAP_KEY_PARAM` 거부와 키 값 미출력: 최초 검증 부재로 실패.
- `--org` 실행이 `orgs/<org>/`에 `markers.json`·`records.json`만 내고 도시 셸을 만들지 않음:
  최초 모든 실행이 셸을 써서 실패.
- 마커의 좌표 출처가 사람 확인 전에는 좌표가 일치하는 후보의 제공자, 확인 뒤에는 확인한 후보의
  제공자임: 최초 필드 부재로 실패.
- 장부가 비식당·판단 보류·지오코딩 실패 레코드를 사유·업소 식별자와 함께 보존:
  최초 `geocode_reason` 부재로 실패.
- 공개 파일 전체에 `source_hash`·`source_location`·`lookup_key`·`dependency_key`·원본 해시 값·
  근거 URL·근거 문구가 없음: 최초 장부가 `Record`를 그대로 실어 실패.
- 자료 범위에 기간과 기관별 수집 상태·보류 사유가 실리고, 보류가 없으면 지도 위 안내가 없음:
  최초 고정 문구만 있어 실패.
- 랜딩이 7개 도시 카드를 유지하면서 build한 도시만 링크: 최초 모두 링크해 실패.

브라우저 로직(`tests/site_behavior.test.js` 9건) 중 이번에 추가한 3건:

- 선택한 식당 상세에 좌표 출처 표시.
- 장부가 지도에 오르지 못한 사유를 상태와 함께 표시.
- 지도가 현재 영역을 알려 주지 못해도 도시 전체 집계가 유지됨.

## 자동 검사

| 검사 | 결과 |
| --- | --- |
| `uv sync --locked` | 통과, 19개 패키지 확인 |
| `uv run ruff check .` | 통과 |
| `uv run ruff format --check .` | 통과, 62개 파일 |
| `uv run mypy src` | 통과, 29개 소스 파일 |
| `uv run pytest` | 174 passed |
| `node --test tests/site_behavior.test.js` | 9 passed |
| `uv run python -m deliciousmap --help` | 종료 0 |
| `git diff --check` | 통과 |
| gitleaks | PR #49의 workflow에서 통과. 로컬 실행은 아래 참고 |

gitleaks 바이너리가 이 개발 환경에 없고 `core.hooksPath`도 설정돼 있지 않아 로컬 검사를 돌리지
못했다. 대신 `.gitleaks.toml`의 `project-secret-env-assignment` 패턴을 추적 파일 전체에
`git grep`으로 적용해 `.env.example`·`.gitleaks.toml` 밖에서 값이 들어간 비밀 변수가 없음을
확인했다. 이것은 gitleaks 전체 규칙의 대체가 아니므로 PR의 `gitleaks` workflow로 확인했고,
[PR #49](https://github.com/snowjaewon/OfficialDeliciousMap/pull/49)의 두 실행이 모두 통과했다.
새 변수 `NAVER_MAP_CLIENT_ID`는 공개되는 지도 키이므로 `.gitleaks.toml`의 비밀 변수 목록에
추가하지 않았고, `.env.example`에는 이미 빈 값으로 등록돼 있다.

## 브라우저 확인

합성 산출물로 `dist/`를 만들고 `python -m http.server`로 띄운 뒤 Chrome에서 직접 조작했다.
생성 스크립트는 검증용 임시 파일이며 저장소에 커밋하지 않았다. 입력은 식당 4곳(방문 23·14·7·3회),
비식당 1건, 판단 보류 1건, 후보 없음으로 지오코딩에 실패한 식당 1건, 총 50개 레코드다.
기관은 서울특별시청(수집), 중구청(수집 보류·봇 차단), 마포구청(레코드 없음)으로 선언했고
폐업 확인은 `closure.json`을 손으로 고쳐 한 곳에 넣었다.

```text
uv run python -m deliciousmap build --city seoul
uv run python -m http.server 8765 --directory dist --bind 127.0.0.1
```

| 필수 기능 | 확인한 방법 | 결과 |
| --- | --- | --- |
| 도시 카드 랜딩 | `http://127.0.0.1:8765/` 열기 | 7개 카드, 서울만 링크, 나머지 `준비 중` |
| 도시별 진입·OG 메타 | `/seoul/` 열기, 페이지 소스 확인 | `og:title`·`og:description`에 도시 이름 |
| 식당명 검색 | 검색창에 `바다`, `해뜰` 입력 | 결과 1건, 전체 결과 수 1로 갱신 |
| 방문 횟수 구간 필터 | `5–9` 버튼 클릭 | `aria-pressed` 이동, 전체 결과 1곳(7회 식당) |
| 전체/현재 영역 결과 수 | 결과 줄 확인 | `1곳 전체 · —곳 현재 지도 영역` |
| 마커 선택 상세 | 검색 결과 클릭 | 상호·방문 23회·`폐업 확인`·좌표 출처·네이버 링크 |
| 폐업 표시 | 같은 상세 | 마커를 지우지 않고 `폐업 확인` 배지 표시 |
| 좌표 출처 | 두 식당 상세 비교 | `담당자 준비 자료`와 `네이버 지역검색`으로 구분 |
| 네이버 지도 연결 | 상세의 링크 `href` | `https://map.naver.com/p/search/해뜰%20식당` |
| 장부 탭 지연 로드 | 탭 열기 전후 `performance` 리소스 목록 | 열기 전 `markers.json`만, 연 뒤 `records.json` 추가 |
| 장부 보존 | 장부 목록의 상태 배지 | `지도 표시`·`비식당`·`판단 보류`·`지오코딩 실패 · 후보 없음` |
| 기관 이름 | 장부 행의 기관 표기 | slug가 아닌 `서울특별시청` |
| 자료 범위 | `자료 범위` 버튼 | 대상 기간 2026년 상반기, 3개 기관의 상태·보류 사유 표 |
| 수집 보류 안내 | 지도 화면 | 보류 1곳 안내 표시 |
| 모바일 바텀시트 | 397px 폭 프레임에서 상세 열기 | `position: fixed`, 폭 전체, 화면 하단 고정 |
| PWA | `navigator.serviceWorker.getRegistrations()` | `sw.js`가 `/` 범위에서 active, manifest 연결됨 |

### 확인하지 못한 것

이 세션에는 유효한 네이버 지도 클라이언트 키가 없다. `demo-key`로 build하면 SDK는 내려받아지지만
인증이 실패하므로(`500 / Internal Server Error`, Client ID `demo-key`) **지도 타일·마커 그리기·
`fitBounds`·`minZoom`·`maxBounds`·현재 지도 영역 결과 수는 브라우저에서 확인하지 못했다.**
이 작업에서 그 실패를 숨기지 않도록 공식 `navermap_authFailure` 훅을 붙여 안내를 띄우고, 현재
지도 영역 수를 `0곳`이 아니라 `—곳`으로 적게 했다. 지도 자체의 확인은 유효한 키를 넣고 다시
해야 하며, 실기기·실데이터 성능은 [#29](https://github.com/snowjaewon/OfficialDeliciousMap/issues/29)의 범위다.

## 코드 리뷰

Standards·Spec 두 축으로 리뷰했고 다음을 반영했다.

- `site.py`가 dist에 내보내는 것 전부(마커·장부 데이터와 화면)를 소유하도록 마커·장부 파일
  조립을 `local.py`에서 옮기고 docstring을 고쳤다. `local.build`는 단계 실행과 파일 목록만 맡는다.
- 지도 키 없이 `build` 어댑터에 닿는 경로가 산출물 오류로 보고되던 것을 원인 코드
  `missing-configuration`으로 바꿨다. CLI가 먼저 막으므로 실행 경로에서는 도달하지 않는다.
- `coverage`/`OrganizationCoverage`를 `collection_status`/`CollectionStatus`로 고쳐 화면 문구
  "기관별 수집 상태"와 이름을 맞췄다.
- 도달할 수 없고 스펙에도 없는 "기관 미선언" 지도 안내와, `held` 상태의 사유 미기재 분기를 지웠다.
- 자료 범위 표는 기관 이름, 장부 행은 기관 slug를 보여 주던 불일치를 고쳤다.
- `contracts.py`의 리터럴과 `app.js`의 표기 표가 따로 늘어나는 것을 막는 테스트를 더했다.
- README가 좌표 출처를 실제보다 넓게 적은 부분(마커는 첫 레코드의 판정에서 고른다)을 고쳤다.

스펙 리뷰가 짚은 범위 밖 추가 세 가지는 그대로 두고 PR에 밝힌다: 빌드하지 않은 도시의
`준비 중` 카드(죽은 링크 방지), 지도 인증 실패 처리, 지도 호출의 방어적 예외 처리.
`City.bounds`라는 스펙의 이름 대신 #47이 이미 넣은 `City.map_bounds`를 쓴다.

## 실제 도시 산출물

현재 checkout에는 `data/`가 없고 7개 도시 레지스트리에 확인된 기관·게시판 선언도 없다.
`fetch`·`headermap`·`parse`·`classify` 운영 어댑터도 `not-implemented`다. 따라서 실제 도시
정제 산출물로 `build`를 돌린 결과는 **미확인**이다. 위 브라우저 확인은 모두 합성 입력의 결과이며
어떤 도시도 완료로 판정하지 않는다.
