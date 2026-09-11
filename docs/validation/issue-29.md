# 이슈 #29 지도 구현·성능 검증 기록

검증일: 2026-09-11. 범위: [이슈 #29](https://github.com/snowjaewon/OfficialDeliciousMap/issues/29).
초기 성능 기준은 [이슈 #22 결정 댓글](https://github.com/snowjaewon/OfficialDeliciousMap/issues/22#issuecomment-5614661364)을 따른다.

## 구현 결과

- `build` v5는 선택 도시의 축약 마커를 `markers.json`, 전체 장부를 `ledger.json`으로 분리한다.
  장부에는 비식당·판단 보류·지오코딩 실패 레코드와 지도 포함 상태를 함께 남긴다.
- build는 7개 도시 랜딩, 도시별 정적 진입 페이지, 공유 CSS·JavaScript, manifest와 service
  worker를 만든다. 도시별 `MapBounds`를 네이버 지도의 초기 `fitBounds`, `minZoom`,
  `maxBounds`에 사용한다.
- 지도 화면은 선택 도시 전체 마커를 대상으로 식당명 검색과 방문 횟수 구간 필터를 적용하고,
  전체 결과와 현재 지도 영역 결과를 따로 표시한다. 마커 상세에서 방문 횟수·폐업 표시와
  네이버 지도 링크를 제공한다.
- 장부 파일은 장부 탭을 처음 열 때만 요청하며 100건씩 표시한다. 모바일 너비에서는 마커
  상세가 화면 하단 시트로 배치된다.
- `window.deliciousmapMetrics`에 `marker-data`, `first-ready`, `filter-result`,
  `marker-selection`, `ledger-first-list`의 최근 200개 시간을 밀리초 단위로 남긴다.
  같은 이름의 `deliciousmap:metric` 이벤트도 발생시켜 측정 자동화가 값을 수집할 수 있다.

## 자동 검사

아래 결과는 합성 소규모 fixture의 기능 계약 검증이며 실제 도시 성능 측정이 아니다.

| 검사 | 결과 |
| --- | --- |
| `uv sync --locked` | 통과, 19개 패키지 확인 |
| `uv run ruff check .` | 통과 |
| `uv run ruff format --check .` | 통과, 62개 파일 |
| `uv run mypy src` | 통과, 29개 소스 파일 |
| `uv run pytest` | 162 passed, 15.42초 |
| `node --test tests/site_behavior.test.js` | 3 passed |
| `uv run python -m deliciousmap --help` | 종료 0 |
| `uv build --wheel` | 통과, wheel에 4개 정적 자산 포함 |
| `git diff --check` | 통과 |
| `gitleaks git --no-banner --redact` | 33개 커밋 검사, 비밀 탐지 없음 |

## 실제 데이터·브라우저 측정 상태

현재 checkout에는 `data/`가 없고 7개 도시 레지스트리에 검증된 기관·게시판 선언도 없다.
`fetch`·`headermap`·`parse`·`classify` 운영 어댑터 역시 아직 `not-implemented`다. 따라서 실제
도시별 정제 산출물의 규모·버전과 전송·파싱·렌더링 성능을 측정할 입력이 없다. 합성 대규모
입력으로 대신하지 않는다는 결정에 따라 아래 항목은 모두 **미측정**이며 합격으로 판정하지 않는다.

| 도시 | 레코드 | 마커 | markers 크기 | ledger 크기 | 입력 버전 | 상태 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 서울 | — | — | — | — | — | 정제 산출물 없음 |
| 부산 | — | — | — | — | — | 정제 산출물 없음 |
| 대구 | — | — | — | — | — | 정제 산출물 없음 |
| 인천 | — | — | — | — | — | 정제 산출물 없음 |
| 광주 | — | — | — | — | — | 정제 산출물 없음 |
| 대전 | — | — | — | — | — | 정제 산출물 없음 |
| 울산 | — | — | — | — | — | 정제 산출물 없음 |

이 세션의 Computer Use에는 사용할 수 있는 브라우저가 없어 생성 화면의 브라우저 자동화도
실행하지 못했다. 실제 Android Chrome과 iPhone Safari 기기가 제공되지 않아 기기 사용감,
OS·브라우저 버전·화면 크기·주사율 역시 미측정이다.

## 실데이터 준비 후 측정 절차

1. 같은 코드 커밋에서 7개 도시를 각각 build하고 위 표에 입력 커밋 또는 산출물 해시,
   레코드·마커 수, 두 JSON 파일의 바이트 크기를 기록한다.
2. 데스크톱 Chrome과 다운로드 10Mbps·업로드 1Mbps·지연 100ms·CPU 4배 감속의 고정 모바일
   모의 환경에서 첫 방문, 재방문, 장부 첫 목록, 입력·선택 피드백, 검색·필터 결과를 도시·환경·
   시나리오별 20회 측정한다. 느린 순 두 번째 값과 최대값을 모두 기록한다.
3. 첫 방문은 서비스 워커를 포함한 캐시를 초기화하고, 재방문은 캐시가 채워진 새 탐색에서 잰다.
   `window.deliciousmapMetrics`와 브라우저 Performance 기록을 함께 보존한다.
4. 드래그·줌·장부 스크롤은 별도 Performance 기록에서 긴 프레임과 연속 조작 중 멈춤을 확인한다.
   실제 Android Chrome·iPhone Safari에서도 같은 조작을 수행하고 기기·OS·브라우저·화면·
   주사율을 고정해 기록한다.
5. 전송·파싱이 병목이면 필드를 축약하거나 파일을 더 나누고, 마커 렌더링이 병목이면 현재 지도
   영역만 그리는 모드를 적용한다. 변경 전후를 같은 조건으로 재측정하고 이 문서와 결정 티켓에
   근거를 연결한다.

현재 결과로 확인된 것은 합성 입력에서의 공개 동작뿐이다. 이슈 #29의 실데이터 성능·실기기 완료
기준은 위 선행 입력과 장비가 준비된 뒤에만 판정할 수 있다.
