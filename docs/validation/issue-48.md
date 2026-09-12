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

#48 세션에는 유효한 네이버 지도 클라이언트 키가 없었다. `demo-key`로 build하면 SDK는 내려받아지지만
인증이 실패했다(`500 / Internal Server Error`). 그래서 지도 타일·마커 그리기·`fitBounds`·
`minZoom`·`maxBounds`·현재 지도 영역 결과 수를 확인하지 못했고, 그 실패를 숨기지 않도록 공식
`navermap_authFailure` 훅으로 안내를 띄우고 현재 지도 영역 수를 `0곳`이 아니라 `—곳`으로 적게 했다.
이 다섯 항목은 아래 [유효한 지도 키로 확인(#50)](#유효한-지도-키로-확인50)에서 확인했다.

아직 확인하지 않은 것:

- (확인함) 운영 도메인 `officialdeliciousmap.pages.dev`와 PR 미리보기 주소의 실제 지도 인증은
  [#53](https://github.com/snowjaewon/OfficialDeliciousMap/issues/53)에서 확인했다(아래 표).
- 실기기·실데이터 성능: [#29](https://github.com/snowjaewon/OfficialDeliciousMap/issues/29)의 범위다.
- 화면 크기에 따른 축소 한계: `minZoom`은 첫 화면의 줌으로 한 번 고정하며, 한 창 크기(851×841)에서만
  확인했다. 창 크기를 바꾸거나 모바일 폭으로 열었을 때 도시 전체가 보이는지는 #29에서 실기기와 함께 본다.
- 실제 도시 산출물의 build·정적 서빙: 아래 [실제 도시 산출물](#실제-도시-산출물) 참고.

### 유효한 지도 키로 확인(#50)

2026-09-11, Windows 11 · Chrome 152(창 크기 851×841) ·
[유효한 지도 키로 타일·마커·경계 제한 브라우저 확인 #50](https://github.com/snowjaewon/OfficialDeliciousMap/issues/50).

**허용 도메인과 인증.** 사용자가 네이버 클라우드 콘솔의 Maps 애플리케이션에 Web 서비스 URL로
`http://127.0.0.1:8765`, `http://localhost:8765`, 운영 도메인 `officialdeliciousmap.pages.dev`를
등록했고 `pages.dev` 전체는 넣지 않았다(사용자 보고, 콘솔 화면은 보지 않음).

| 주소 | 등록 | 실제 인증 |
| --- | --- | --- |
| `http://127.0.0.1:8765` | 사용자 보고 | 성공(이 세션에서 관찰) |
| `http://localhost:8765` | 사용자 보고 | 성공(이 세션에서 관찰) |
| `officialdeliciousmap.pages.dev` | 사용자 보고, `pages.dev` 전체 미등록 | 성공(2026-09-12 운영 첫 배포 뒤 관찰, #53) |
| `pr-80.officialdeliciousmap.pages.dev`(PR alias) | 사용자 보고: `http://*.officialdeliciousmap.pages.dev`와 이 주소 추가 | 성공(2026-09-12 관찰, #53) |

2026-09-12 미리보기 주소에서 처음 본 인증 실패는 도메인 때문이 아니었다. CI가 build에 쓰는
GitHub Variable `NAVER_MAP_CLIENT_ID`에 위 경과의 **예전 키**가 남아 있었다. 사용자가 `.env`만 새 키로
바꿨기 때문이다. Variable을 새 키로 바꾸고 다시 배포하자 `pr-80` alias에서 인증이 성공했다.
경과와 판정은 [#53 검증](issue-53.md#지도-인증)에 있다. 그 사이 사용자가 하위 도메인 두 줄을 추가했으므로,
운영 도메인 한 줄만으로 하위 도메인이 허용되는지는 가르지 못했다.

로컬 두 주소에서는 실제 인증이 성공했다. SDK의 인증 오류 콘솔 메시지가 없었고 `navermap_authFailure`가
호출되지 않아 지도 불가 안내도 뜨지 않았다. 따라서 실제 키로 인증 실패 안내가 오탐하지 않는다.
처음 `.env`에 있던 키는 신규 파라미터 `ncpKeyId`로 `500 / Internal Server Error`(가짜 키와 같은
응답), 구형 `ncpClientId`로 `200 / Authentication Failed`를 받았다. URL을 등록한 뒤에도 같았고,
사용자가 `.env`의 키를 바꾼 뒤 `ncpKeyId`로 성공했다. 여기서 `500`이 URL 문제가 아니라 Maps
애플리케이션 키로 인식되지 않는 값이라는 뜻이라는 것은 이 경과에서 끌어낸 추론이며, SDK 문서로
확인한 사실은 아니다. 운영 도메인은 위 "확인하지 못한 것"에 남긴다.
키 값은 이 문서·저장소·산출물 메타데이터 어디에도 남기지 않았다.

**입력.** 검증용 임시 스크립트로 서울 레지스트리의 실제 `map_bounds`를 쓴 합성 산출물을 만들었다.
스크립트는 커밋하지 않았다. 식당은 서울 시내 5곳(방문 23·14·7·3·1회), 도시 밖 부산 1곳,
그리고 도시 경계 네 모서리에서 안쪽으로 0.003도 들어간 확인용 4곳이다. 비식당·판단 보류 레코드도
1건씩 넣었다. `.env`에서는 `NAVER_MAP_*` 두 변수만 불러와 외부 조회를 막고, 스크립트가
`cli.main`으로 `geocode`→`closure`→`build`를 차례로 실행해 임시 디렉터리의 `dist/`를 만들었다.

```text
PowerShell: Get-Content -Encoding utf8 .env | ForEach-Object { if ($_ -match '^(NAVER_MAP_\w+)=(.*)$') { Set-Item "env:$($Matches[1])" $Matches[2] } }
            uv run python <임시 스크립트> <임시 디렉터리>
            uv run python -m http.server 8765 --directory "<임시 디렉터리>\dist" --bind 127.0.0.1
```

| 항목 | 확인한 방법 | 결과 |
| --- | --- | --- |
| 지도 타일·마커 | `/seoul/` 열기 | 타일과 마커 10개가 그려짐 |
| 도시 전체 초기 영역(`fitBounds`) | 움직이기 전 결과 줄 | `10곳 전체 · 9곳 현재 지도 영역`. 네 모서리 4곳과 시내 5곳이 모두 화면 안, 부산만 밖 |
| 최소 축소 수준(`minZoom`) | 줌 컨트롤 `−` 3회, 휠 축소 10칸 | 축척 5km와 화면이 그대로이고 줌 핸들이 맨 아래 |
| 이동 제한(`maxBounds`) | 남동쪽(부산 방향)·북서쪽으로 각각 큰 드래그 3회 | 각각 남동·북서 모서리 마커 부근에서 멈추고 더 나가지 않음 |
| 현재 지도 영역 수 M | 드래그·마커 선택·검색 | 9 → 4(드래그) → 1(강남 마커 선택). 검색 `잠실` 선택 시 `1곳 전체 · 1곳` |
| 마커 클릭 → 상세 | 지도에서 `14` 마커 클릭 | 강남 한정식 상세가 열리고 지도가 그 마커 위 줌 16으로 이동 |
| 도시 밖 식당 | 검색 `해운대` 결과 선택 | 상세에 `도시 지도 범위 밖의 식당입니다.`, 지도는 움직이지 않고 M은 0 |
| 첫 준비 지표 | `window.deliciousmapMetrics` | 움직이기 전에 `first-ready` 기록(140–176ms) |

**확인하면서 찾아 고친 결함 두 가지.** 둘 다 가짜 키로는 드러나지 않았고, 실제 SDK에서
관찰한 동작을 `tests/site_behavior.test.js`의 가짜 `naver.maps`로 재현해 실패를 먼저 확인한 뒤 고쳤다.

- 네이버 지도 v3는 첫 화면에서 `idle` 없이 `init`만 보낸다(옵션 네 가지로 새 지도를 만들어 확인).
  화면이 첫 `idle`을 기다렸기 때문에 사용자가 지도를 처음 움직이기 전까지 세 가지가 일어나지 않았다.
  현재 지도 영역 수는 `—`로 남았고, `minZoom`이 고정되지 않았으며, `first-ready` 지표에는 사용자가
  움직이기까지의 시간이 섞였다. 첫 동작이 축소라면 그 축소된 수준이 한계로 굳을 수도 있었다.
  이제 `init`에서 도시 전체 수준으로 `minZoom`을 고정하고 현재 영역을 보고하며, `idle`은 현재 영역만 갱신한다.
- 마커를 고르면 `panTo` 뒤에 곧바로 `setZoom`을 불렀다. 그러면 이동 애니메이션이 끊겨 원래 중심에서
  확대되고, 선택한 식당은 화면 밖에 남았다(현재 영역 0곳). 좌표와 줌을 한 번에 옮기는 `morph`로 바꿨다.

**확인 환경 주의.** Chrome 창이 최소화되거나 다른 창에 완전히 가려지면 탭이
`visibilityState: hidden`이 되어 `requestAnimationFrame`이 멈춘다. 이때는 지도 SDK의 이벤트와
화면의 지표 기록이 진행되지 않으므로, 브라우저 확인과 #29의 성능 측정은 창이 보이는 상태에서 한다.

검색창 패널이 지도 왼쪽 위를 덮어 북서 모서리 마커가 가려진다. 마커는 현재 영역 수에 포함되고
검색으로도 열 수 있어 이번 범위에서는 바꾸지 않았다.

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

### 광주 정제 산출물 확인 (2026-09-12)

`develop` 기준 커밋 `4356d20`의 실제 광주광역시청 정제 산출물로, 지도 키는 저장하지 않는
검증용 값만 환경 변수에 넣어 `build`를 실행했다. 출력은 저장소의 `dist/`가 아닌 임시 디렉터리에
냈고, 실행이 끝난 뒤 생성된 `data/gwangju/build.json`의 출력 경로는 기존 값으로 되돌렸다.

```text
PowerShell: $env:NAVER_MAP_CLIENT_ID = '<검증용 공개 키>'
            $env:NAVER_MAP_KEY_PARAM = 'ncpKeyId'
            uv run python -m deliciousmap build --city gwangju --output-root '<임시 출력 디렉터리>'
            uv run python -m http.server 8765 --directory '<임시 출력 디렉터리>' --bind 127.0.0.1
```

| 항목 | 결과 |
| --- | --- |
| 입력 | 광주 정제 레코드 2,799건, 확정 마커 12곳 |
| 생성 파일 | `gwangju/markers.json`, `gwangju/records.json`, `gwangju/index.html`, 랜딩, `assets/app.js`, `assets/styles.css`, `manifest.webmanifest`, `sw.js` (8개) |
| `BuildOutput` | `record_count=2799`, `marker_count=12`, `files` 8개 |
| 정적 서버 `/` | HTTP 200, 랜딩 1,592바이트 |
| 정적 서버 `/gwangju/` | HTTP 200, 도시 진입 페이지 4,437바이트 |
| 장부·마커 | `records.json` 1,108,102바이트, `markers.json` 2,839바이트 |
| 키 보존 | 검증용 키는 커밋·소스·산출물 메타데이터에 기록하지 않음 |

따라서 실제 도시 산출물로 `build`가 완료되고 두 정적 진입 페이지가 로컬 서버에서 응답하는 것을
확인했다. 지도 SDK의 타일·인증·마커 상호작용은 유효한 키를 사용한 합성 서울 산출물의
[#50 검증](https://github.com/snowjaewon/OfficialDeliciousMap/issues/50)에서 확인했으며, 이
확인은 광주 산출물의 파일 생성·정적 서빙 범위를 검증한다.

## 최신 develop 회귀 검사 (2026-09-12)

실제 산출물 확인과 함께 현재 `develop` 기준으로 전체 회귀 검사를 다시 실행했다.

| 검사 | 결과 |
| --- | --- |
| `uv sync --locked` | 통과, 31개 패키지 확인 |
| `uv run ruff check .` | 통과 |
| `uv run ruff format --check .` | 통과, 91개 파일 |
| `uv run mypy src` | 통과, 39개 소스 파일 |
| `uv run pytest` | 375 passed |
| `node --test tests/site_behavior.test.js` | 11 passed |
| `uv run python -m deliciousmap --help` | 종료 0 |
| `git diff --check` | 통과 |
| `gitleaks git --staged` | 통과, no leaks found |
