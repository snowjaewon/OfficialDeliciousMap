# 이슈 #95 PWA 설치 안내와 앱 아이콘 검증

2026-09-13, Windows 11 · Git Bash · Python 3.12.10 · Node.js v24.17.0 · Chrome(헤드리스).
범위: [feat(map): PWA 설치 안내와 앱 아이콘 #95](https://github.com/snowjaewon/OfficialDeliciousMap/issues/95).
화면과 공개 파일의 설명은 [README의 홈 화면 설치](../../README.md#홈-화면-설치)에 있다.

## 결정의 출처

- PWA 설치 안내는 [#12 결정](https://github.com/snowjaewon/OfficialDeliciousMap/issues/12#issuecomment-5611428144)에서
  "있으면 좋음"이었고, 2026-09-13 사용자가 이번에 넣기로 했다(#94에서 나눔).
- 담당자는 iPhone 13 Safari에서 공유 → 홈 화면에 추가로 사이트를 추가했고, 아이콘이 없어 화면 캡처가
  홈 화면 아이콘이 되었다([#76](https://github.com/snowjaewon/OfficialDeliciousMap/issues/76)).

## 이번에 구현한 것

| 범위 | 결과 |
| --- | --- |
| 앱 아이콘 | 지도 마커 모양의 핀. `icon-192.png`·`icon-512.png`(둥근 사각형), `icon-maskable-512.png`(안전 영역 안), `apple-touch-icon.png`(180, 불투명) |
| 아이콘 원본 | `scripts/make_icons.py`가 표준 라이브러리만으로 PNG를 만든다. 같은 코드는 같은 바이트를 낸다 |
| manifest | `icons`(192·512·maskable 512), `id`, `description` 추가 |
| 페이지 머리 | 랜딩·도시 화면에 `rel="icon"`(192)과 `rel="apple-touch-icon"` |
| Android Chrome | `beforeinstallprompt`를 받으면 화면 아래 안내에 `설치` 버튼. 누르면 설치 창 |
| iOS Safari | 홈 화면 앱이 아니면 "공유 메뉴에서 ‘홈 화면에 추가’" 안내를 한 번. 본 화면에서는 닫을 때까지 남는다. iOS Chrome·앱 안 브라우저 제외 |
| 다시 띄우지 않기 | standalone으로 열렸거나, 닫았거나, 설치 창에서 거절했거나, Safari 안내를 이미 보였으면 띄우지 않는다. `localStorage`에만 기억 |
| 랜딩 | 안내와 service worker 등록을 위해 `app.js`와 `site_root`만 담은 설정을 싣는다 |
| 배포 허용 목록 | `site.public_paths`에 아이콘 4개. `check-dist`가 manifest의 아이콘 참조도 끊긴 참조로 본다 |
| service worker | 셸 목록에 아이콘 4개. 설치 때 사전 캐시하고 셸 캐시에서 먼저 내준다 |

안내는 브라우저의 설치 막대처럼 화면 아래에 떠서 지도 영역의 크기를 바꾸지 않는다. 좁은 화면에서는
접힌 목록 시트 위에 겹치며 닫으면 사라진다. Android에서 이 화면의 버튼으로 설치하도록 브라우저의 기본
설치 막대는 막는다. 안내를 닫은 사람에게도 기본 막대는 띄우지 않는다.

셸 캐시 이름(`deliciousmap-shell-v2`)은 올리지 않았다. 새 워커가 설치될 때 셸 전체를 다시 받으므로
기존 항목도 새 응답으로 바뀌고, 셸 전략은 그대로다.

### 이슈에 없던 판단

| 판단 | 이유 |
| --- | --- |
| "한 번 보여 준다"를 문자 그대로 읽음 | Safari 안내를 처음 보인 때 기억한다. 닫지 않고 다른 화면으로 가도 다시 띄우지 않는다 |
| 설치 창에서 거절하면 닫은 것으로 봄 | 설치를 분명히 거절한 사람에게 같은 버튼을 다시 내밀지 않는다 |
| `beforeinstallprompt`를 늘 `preventDefault` | 안내를 닫은 사람에게 Chrome의 기본 설치 막대가 대신 뜨면 닫은 안내가 돌아온 것과 같다. 설치는 Chrome 메뉴로 언제든 할 수 있다 |
| 설치 완료(`appinstalled`)는 기억하지 않음 | 설치된 동안 Chrome은 설치 제안을 보내지 않는다. 기억하면 앱을 지운 뒤에도 안내가 돌아오지 않는다 |
| 랜딩에 `app.js`·service worker 등록 | 설치한 앱의 시작 주소가 랜딩이다. 랜딩에서 곧바로 설치한 앱도 첫 실행부터 오프라인 셸을 갖는다 |
| iOS Chrome·앱 안 브라우저 제외 | 메뉴 위치와 이름이 달라 Safari 안내가 틀린 설명이 된다 |
| `rel="icon"`, manifest `id`·`description` | 같은 아이콘을 탭 아이콘으로 쓰고, DevTools가 권하는 식별자와 설명을 채운다 |

## 구현과 TDD

사전에 합의한 네 경계에서만 테스트했다. 네트워크·실제 키는 쓰지 않는다.

| 행동 | 테스트 |
| --- | --- |
| manifest가 선언한 크기와 같은 PNG가 `dist/`에 있고 192·512·maskable을 싣는다 | `test_manifest_icons_are_published_at_the_sizes_it_declares` |
| 두 화면이 180×180 `apple-touch-icon`을 연결한다 | `test_every_page_links_the_home_screen_icon` |
| 두 화면이 숨긴 설치 안내 자리·`app.js`·`site_root` 설정을 싣는다 | `test_landing_and_city_pages_both_carry_the_install_guide` |
| 새 아이콘은 허용하고 봉인한다 | `test_check_dist_seals_a_built_site_with_path_digests_and_commit` |
| manifest가 없는 아이콘을 가리키면 거부 | `test_check_dist_rejects_an_app_icon_that_is_not_published` |
| 허용 목록 밖의 이미지는 여전히 거부 | `test_check_dist_still_rejects_an_image_outside_the_published_icons` |
| 바이너리 공개 파일에도 원본·조회 출처가 없다 | `test_public_files_carry_no_original_or_lookup_provenance`(바이트로 검사하도록 고침) |
| 설치 때 아이콘 사전 캐시, 아이콘을 셸 캐시에서 응답 | `install precaches the current shell`, `an installed app's icon is served from the shell cache` |
| Android 설치 제안 → 버튼 → 설치 창 | `Android Chrome's install offer becomes an install button…` |
| 닫으면 다음 방문에도 닫힘, 설치 창 거절도 닫기로 봄 | `a closed install guide stays closed…`, `declining the install dialog…` |
| iPhone Safari 안내를 한 번만, 본 화면에서는 닫을 때까지, 데스크톱 사이트를 요청한 iPad | `iPhone Safari shows how to add the site to the home screen once`, `an iPad asking for the desktop site…` |
| iOS Chrome·카카오톡·네이버 앱에는 Safari 안내 없음 | `iOS browsers other than Safari do not get the Safari instructions` |
| 홈 화면 앱(standalone)은 안내 없음 | `an app already opened from the home screen never shows the install guide` |
| 저장소를 거부하는 브라우저도 안내를 보이고 닫는다 | `a browser that refuses storage still shows and closes the guide on this page` |
| 메뉴로 설치하면 버튼을 숨긴다 | `installing from the browser menu hides the install button` |
| 랜딩에서도 안내와 service worker 등록 | `the landing page shows the install guide and registers the service worker` |

## 코드 리뷰 반영

Standards·Spec 두 축으로 리뷰해 아래를 고쳤다.

- Safari 안내를 닫기 전까지 매번 띄우던 것을 이슈 문구대로 한 번만 보이게 했다.
- 크기 초과 메시지를 `storage.TOO_LARGE` 하나로 모았다. 텍스트 자산과 아이콘을 따로 복사하는 이유
  (텍스트는 LF로 맞춤, 아이콘은 바이트 그대로)를 주석으로 남겼다.
- 설치 안내에서 버튼 숨김을 한 곳으로 모으고 불리언 인자를 없앴다.
- `make_icons.py`의 바탕 종류를 `Literal`로 좁히고 거리 함수 이름에 `_distance`를 붙였다. 다시 만든 PNG의
  SHA-256이 이전과 같음을 확인했다.

반영하지 않은 것: 아이콘 이름이 `make_icons.py`·`site.ICON_NAMES`·`sw.js`·manifest에 반복된다.
`sw.js`·manifest와 공개 목록의 어긋남은 `check-dist`가, 스크립트와 `ICON_NAMES`의 어긋남은 build가
파일을 읽지 못해 드러낸다.

## 검사

Git Bash, 저장소 루트.

| 명령 | 결과 |
| --- | --- |
| `uv run ruff check .` | 통과 |
| `uv run ruff format --check .` | 통과(115개 파일) |
| `uv run mypy src` | 통과(47개 파일) |
| `uv run pytest` | 485개 통과 |
| `node --test tests/*.test.js` | 79개 통과 |
| `git diff --cached --check` | 통과 |
| `gitleaks git --pre-commit --staged` | 누출 없음 |

## 설치 가능성과 화면 확인

광주 정제 산출물을 저장소 밖 사본으로 build해(커밋된 `data/gwangju/build.json`은 되돌림)
`check-dist`를 통과시키고(12개 파일 봉인) `http://127.0.0.1:8765`로 띄웠다. 설치된 Chrome을
헤드리스로 띄워 CDP로 확인했다. `Page.getInstallabilityErrors`는 DevTools Application → Manifest의
설치 가능성 검사와 같은 판정이다.

| 확인 | 결과 |
| --- | --- |
| 데스크톱 Chrome `/`·`/gwangju/`의 manifest 오류 | 0건 |
| 데스크톱 Chrome `/`·`/gwangju/`의 설치 가능성 오류 | 0건 |
| service worker 제어(재방문) | 두 화면 모두 제어됨 |
| 데스크톱 Chrome의 실제 `beforeinstallprompt` | 두 화면 모두 받아 `설치` 버튼이 보임 |
| iPhone Safari 사용자 에이전트, 390×844 | 랜딩·도시 화면에 공유 메뉴 안내, `설치` 버튼 없음. 닫은 뒤 새로고침하면 뜨지 않음 |
| Android 폭 412×915 | 접힌 목록 시트 위에 안내와 `설치` 버튼, 지도·범례는 가리지 않음 |

iPhone 확인은 Chrome에서 사용자 에이전트만 바꾼 것이므로 Chrome이 보내는 설치 제안 이벤트를 막고 봤다.

## 실기기

| 기기 | 결과 |
| --- | --- |
| Android Chrome | 미확인 |
| iPhone Safari(iPhone 13) | 미확인 |

실기기에서는 운영 배포 뒤 아래를 본다.

- Android Chrome: 화면 아래 `설치` → 설치 창 → 홈 화면 아이콘이 핀 모양(maskable로 잘려도 핀이 온전함),
  설치한 앱으로 열면 안내가 뜨지 않음.
- iPhone Safari: 공유 메뉴 안내 → 홈 화면에 추가 → 아이콘이 화면 캡처가 아니라 핀 모양, 홈 화면에서 열면
  안내가 뜨지 않음. 이미 캡처 아이콘으로 추가한 항목은 지우고 다시 추가해야 새 아이콘이 된다.

## 남은 제한

- 실기기 확인이 남았다(위 표).
- 앱 안 브라우저 판별은 알려진 사용자 에이전트 목록(카카오톡·네이버·다음·인스타그램·페이스북·라인)에 기댄다.
  목록에 없는 앱 안 브라우저가 Safari와 같은 사용자 에이전트를 쓰면 Safari 안내가 뜰 수 있다.
- Safari 안내는 한 번만 보이므로, 그 화면을 곧바로 떠난 사람은 안내를 거의 보지 못할 수 있다.
  공유 메뉴의 `홈 화면에 추가`는 안내 없이도 언제든 쓸 수 있다.
- 푸시 알림·오프라인 데이터 동기화, 색·분위기 개편은 이번 범위가 아니다.
