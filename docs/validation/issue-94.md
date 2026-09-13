# 이슈 #94 지도·식당 순위 목록 화면 검증

2026-09-13, Windows 11 · Git Bash · Python 3.12.10 · Node.js v24.17.0 · Chrome(헤드리스).
범위: [지도와 식당 순위 목록을 함께 보여 주고 상세·마커를 강화한다 #94](https://github.com/snowjaewon/OfficialDeliciousMap/issues/94).
화면과 공개 파일의 설명은 [README의 정적 지도 화면](../../README.md#정적-지도-화면)에 있다.

## 결정의 출처

- 실기기 지적(목업보다 완성도가 떨어져 보임, 초기 화면이 너무 축소됨):
  [#76 중간 기록](https://github.com/snowjaewon/OfficialDeliciousMap/issues/76#issuecomment-5646384874).
- 2026-09-13 사용자 결정: 지도 + 순위 목록(목업식), 모바일은 끌어올리는 목록 시트, 색·분위기 유지,
  기관 필터 제외, 업종 필터는 [#96](https://github.com/snowjaewon/OfficialDeliciousMap/issues/96)으로,
  PWA 설치 안내는 [#95](https://github.com/snowjaewon/OfficialDeliciousMap/issues/95)로 나눔.
- 필수 기능과 지도 위 수집 보류 안내: [#12 결정](https://github.com/snowjaewon/OfficialDeliciousMap/issues/12#issuecomment-5611428144).
- 마커 먼저·장부 지연 로드: [#22 결정](https://github.com/snowjaewon/OfficialDeliciousMap/issues/22#issuecomment-5614661364).

### 기존 결정과 달라진 것

#22·#29는 "도시 링크 진입 시 도시 전체를 보여준다"고 적었다. #76의 지적에 따라 **첫 화면은 식당이 모인
영역**으로 바꾸고 **축소 한계와 이동 범위는 도시 전체**로 둔다. 한 번 축소하면 도시 전체가 그대로 보인다.

## 이번에 구현한 것

| 범위 | 결과 |
| --- | --- |
| `markers.json` v7 | 마커에 `address`, `last_visited_on`, `total_amount_krw`, `organizations`. build 계약 v6 → v7 |
| 주소 | 좌표를 준 근거의 주소. 업소 확인이 주소가 일치한 후보만 채택하므로 확정 마커에는 언제나 있다 |
| 배치 | 데스크톱은 지도 오른쪽 목록 패널, 폭 720px 이하는 접힘·중간·펼침 세 단계 시트 |
| 순위 목록 | 검색·방문 구간 결과를 방문 횟수 순으로 50곳씩. 방문 횟수가 같으면 같은 순위 |
| 상세 | 목록·마커가 같은 상세를 열고 닫기로 목록에 돌아간다. 목록의 스크롤 위치를 되돌린다 |
| 마커 | 방문 구간 4색과 폐업 회색, 범례, 방문이 많은 마커를 위에 |
| 첫 화면 | 도시 안 식당의 영역(20곳 이상이면 양끝 5% 제외)에 맞추고 14단계 상한 |
| 수집 보류 안내 | 범례와 함께 지도 왼쪽 위에 둔다(#12의 "지도 위에도") |
| 화면 높이 | 도시 화면을 창 높이에 맞추고 장부 탭은 그 안에서 스크롤한다 |
| 측정 하네스 | 사라진 검색 결과 상자 대신 검색으로 거른 목록의 첫 항목을 누른다 |

`records.json`은 모양이 그대로지만 build 계약 버전을 함께 쓰므로 v7로 올랐다.

## 구현과 TDD

공개 CLI(`cli.main`)의 build 산출물과 `app.js`의 공개 함수에 테스트를 걸었다. 네트워크·실제 키는 쓰지 않는다.

| 행동 | 테스트 |
| --- | --- |
| 마커 요약이 묶인 레코드와 일치(두 기관·두 날짜·합계) | `test_markers_summarize_the_visits_bundled_into_each_restaurant` |
| 사람 확인 마커는 확인한 주소, 주소 없는 후보는 근거가 되지 않음 | `test_markers_name_the_provider_that_supplied_the_coordinates`, `test_a_candidate_without_an_address_never_names_the_marker_origin` |
| 필터·범례·색이 같은 구간 | `test_marker_legend_filter_and_colors_share_the_same_visit_bands` |
| 목록·상세·시트 손잡이·지도 위 안내의 자리 | `test_city_page_pairs_the_map_with_a_restaurant_list_and_its_detail`, `test_city_page_publishes_the_period_and_every_organization_status` |
| 순위·동률·50곳 묶음·빈 결과·폐업 표시 | `site_behavior.test.js`의 목록 테스트 |
| 목록·마커 선택 → 상세, 닫기 → 목록과 스크롤 위치 | `a listed restaurant opens its detail…`, `pressing a map marker opens the same detail…` |
| 첫 화면·축소 한계·시트 여백·줌 상한 | `the city view opens on its restaurants…`, `the first view frames where the restaurants are…` |
| 시트: 누르기·흔들린 누르기·끌기·숨은 지도·넓은 화면 | `the list sheet …`, `a shaky tap …`, `a hidden map …`, `a wide screen …` |
| 시트가 가린 만큼 식당을 위로 | `a selection under the mobile sheet …` |

## 코드 리뷰 반영

Standards·Spec 두 축으로 리뷰해 아래를 고쳤다.

- 확정 마커의 주소는 언제나 있으므로 `address`를 필수로 두고 화면의 방어 분기를 뺐다.
- 시트: 창을 돌려 시트가 되어도 손잡이가 동작하도록 리스너를 늘 두고, 장부 탭에서 창 크기가 바뀌어도
  시트가 0 높이로 사라지지 않게 했다. 6화소 미만의 흔들림은 누르기로 보고, 끌기 뒤 click이 없던
  기기에서 다음 누르기가 무시되지 않게 했다. 시트 판정 폭은 CSS 한 곳에만 둔다.
- 수집 보류 안내를 목록 패널에서 지도 위로 되돌렸다. 동률은 같은 순위로 매긴다.
- `storage.py`의 버전 주석, `centerAbove` → `latitudeSouthOf`, `VISIT_BANDS` → `VISIT_BAND_LABELS`(Python).

반영하지 않은 것: 같은 좌표에 다른 업소 후보가 있으면 주소가 그 후보에서 올 수 있다. 좌표 출처와 같은
선택 규칙이며, 주소가 일치한 후보만 채택되므로 실제로는 같은 업소의 주소다.

## 화면 확인

광주 정제 산출물을 저장소 밖 사본으로 build해(커밋된 `data/gwangju/build.json`은 건드리지 않음)
헤드리스 Chrome으로 데스크톱 1280×800, 모바일 390×844(터치 에뮬레이션)에서 확인했다.

| 화면 | 결과 |
| --- | --- |
| 데스크톱 첫 화면 | 상무지구에 맞춘 14단계, 오른쪽 순위 목록 12곳, 왼쪽 위 범례 |
| 데스크톱 상세 | 1위 선택 시 지도가 식당으로 옮기고 상세에 주소·최근 방문·기관·합계 |
| 모바일 접힘 | 검색·필터·결과 수가 보이는 높이, 페이지가 창 밖으로 넘치지 않음 |
| 모바일 검색 | 글자를 치면 시트가 중간으로 오르고 결과가 보임 |
| 모바일 상세 | 선택한 식당이 시트 위 보이는 영역에 옴 |
| 모바일 펼침 | 손잡이를 끌어 펼침, 지도 확대 컨트롤이 시트 위로 올라오지 않음 |

광주 `markers.json`(v7)은 마커 12개, 5,032바이트(gzip 1,480바이트)로 v6의 2,839바이트보다 커졌다.

측정 하네스를 1회씩 돌려 새 화면에서 검색·목록 선택·필터·장부 경로가 끝까지 도는 것만 확인했다.
1회 값은 판정하지 않으며(`미측정`), #22 기준의 재측정은 마커가 늘어난 뒤 한다.

## 남은 제한

- 실기기(Android Chrome·iPhone Safari)의 시트 끌기와 목록 사용감은 아직 확인하지 않았다. #76의 재확인에 포함한다.
- 마커 겹침 묶기·뷰포트 모드는 #22의 조건부 항목으로, #73·#75로 마커가 늘어난 뒤 실측으로 판단한다.
- 색·글꼴·분위기 개편은 2026-09-13 결정으로 보류했다.
