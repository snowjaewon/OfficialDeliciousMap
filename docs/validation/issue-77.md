# 이슈 #77 재방문 셸 캐시와 실데이터 성능 재측정

검증일: 2026-09-13. 범위: [이슈 #77](https://github.com/snowjaewon/OfficialDeliciousMap/issues/77).
초기 성능 목표와 20회 판정은 [이슈 #22 결정 댓글](https://github.com/snowjaewon/OfficialDeliciousMap/issues/22#issuecomment-5614661364)을 따른다.

## 서비스 워커 결정과 구현

- 셸 요청(도시 HTML 탐색, `assets/app.js`, `assets/styles.css`, `manifest.webmanifest`)은
  stale-while-revalidate로 처리한다. 캐시가 있으면 즉시 반환하고 네트워크 응답은 뒤에서
  캐시에 덮어쓴다. 캐시가 없으면 네트워크 응답을 기다린다.
- `markers.json`과 `records.json`은 네트워크 우선이다. 성공한 응답만 캐시에 저장하고,
  네트워크가 실패할 때 마지막 성공 응답을 반환한다. 따라서 검색·집계에 쓰는 마커는
  재방문 때 오래된 캐시를 먼저 확정하지 않는다.
- 셸 캐시는 `deliciousmap-shell-v1`에서 `deliciousmap-shell-v2`로 올렸고 데이터는
  별도 `deliciousmap-data-v1`에 둔다. 새 워커가 활성화되면 이전 셸 버전만 삭제하고
  `clients.claim()`으로 열린 페이지를 제어한다. 셸 계약을 바꾸는 배포는 셸 이름을
  다시 올려 셸 캐시를 비운다. 같은 버전의 자산 배포는 한 번 오래된 셸이 보일 수 있지만,
  백그라운드 갱신 뒤 다음 탐색부터 새 셸을 사용한다.
- 설치 중에는 공통 루트 셸만 미리 받는다. 도시별 HTML은 첫 방문 응답을 캐시하므로
  7개 도시의 셸을 합성 입력으로 만들거나 장부를 캐시 셸에 섞지 않는다.

이 정책은 셸의 재검증 지연을 줄이면서 `markers.json`의 신선도 규칙을 보존한다. 셸과
데이터의 캐시를 분리해, 오프라인 폴백이 지도 집계의 새 응답을 가리는 일이 없도록 했다.

## 자동 검증

실제 서비스 워커 스크립트를 가짜 Service Worker 전역에서 실행해 다음 공개 경계를 확인했다.

| 검사 | 결과 |
| --- | --- |
| 캐시된 도시 셸 즉시 응답 및 백그라운드 갱신 | 통과 |
| 마커 네트워크 우선 및 성공 응답 오프라인 폴백 | 통과 |
| 설치 셸 프리캐시 | 통과 |
| 활성화 시 구버전 캐시 제거·열린 페이지 제어 | 통과 |
| `node --test tests/service_worker.test.js` | 7 passed |

## 실측 상태

광주만 정제 산출물이 준비돼 있다. 2,799 레코드·12 마커의 SHA-256과 파일 크기는
[`issue-77-gwangju-2026-09-13.json`](issue-77-gwangju-2026-09-13.json)에 고정했다. 서울·부산·
대구·인천·대전·울산은 [#75](https://github.com/snowjaewon/OfficialDeliciousMap/issues/75)이 열려 있고
정제 산출물이 없어 미측정이다. 광주 마커 12개도 한 1.5km 상자에 모여 있어 [#73](https://github.com/snowjaewon/OfficialDeliciousMap/issues/73)
이후 마커 밀집 부하를 재기에는 부족하다.

모의 모바일 20회 실행은 `node scripts/measure_map.js`로 시도했지만, 이 호스트의
Chrome 152 GPU 프로세스가 `GPU process isn't usable`로 종료돼 CDP 페이지 세션을 만들지
못했다. 따라서 9개 시나리오와 서비스 워커 개선 전후의 **유효한 20회 결과는 미측정**이며,
성공·미달 판정을 기록하지 않았다. 측정 직전 유휴 CPU 샘플은 31.1834%, 7.6734%, 11.5088%
(평균 16.7885%)였고, 이 값과 실패 단계는 결과 JSON에 남겼다. 기존 [#29 광주 결과](issue-29.md)는
다른 코드와 상주 프로그램 조건에서 잰 값이므로 개선 전후 비교의 기준으로 재사용하지 않았다.

Chrome GPU 오류가 해결된 조용한 호스트에서 아래 명령을 같은 코드 커밋에 다시 실행해야 한다.
원본 trace는 저장소 밖에 두고, 셸 전략 적용 전후를 같은 호스트에서 번갈아 20회씩 기록한다.

```text
node scripts/measure_map.js --city gwangju --out <결과.json> --trace-dir <저장소 밖 경로>
```

유효한 전후 수치가 생기기 전에는 [#22](https://github.com/snowjaewon/OfficialDeliciousMap/issues/22)의
목표나 개선 순서를 수정하지 않는다.

## 완료 기준 점검

| 기준 | 상태 |
| --- | --- |
| 조용한 호스트 조건·광주 9개 시나리오 20회 결과 | 미측정: Chrome GPU 세션 오류, 실패 JSON 기록 |
| 서비스 워커 전략·이유·캐시 무효화 | 구현·자동 검증 완료 |
| 서비스 워커 적용 전후 번갈아 20회 비교 | 미측정: 유효한 Chrome 세션 필요 |
| 준비된 도시별 측정 | 광주만 준비됐으나 실측 미측정, 나머지 6개는 산출물 없음 |
| #73 이후 마커 밀집 구간 | 미측정: 광주 12개 마커로 밀집 부하 부족 |
| #22 기준 변경 | 변경 없음: 비교 수치 부족 |
