# 이슈 #53 CI 빌드와 Pages 배포 검증 기록

2026-09-12, Windows 11 · Git Bash · Python 3.12.10 · Node.js 24.
범위는 [정제 산출물 빌드와 Pages 운영·미리보기 배포 구현 #53](https://github.com/snowjaewon/OfficialDeliciousMap/issues/53),
기준 결정은 [#15](https://github.com/snowjaewon/OfficialDeliciousMap/issues/15#issuecomment-5611503849)다.
사용법은 [README "CI·배포"](../../README.md#ci배포)에 있다.

## 로컬 확인

### 판정 테스트

`tests/test_ci.py`·`tests/test_deploy.py`가 `python -m deliciousmap.ci`를 네트워크 없이 부른다.
사이트는 합성 정제 산출물로 실제 `build`를 돌려 만들고, Cloudflare 대신 가짜 Pages 프로젝트를 쓴다.
가짜는 배포마다 고유 주소를 주고 브랜치 alias를 옮기며, 실제 Pages처럼 없는 경로에 첫 화면
HTML을 200으로 준다. alias가 늦게 옮겨 가는 전파 지연도 흉내 낸다.

| 완료 기준의 판정 | 테스트 |
| --- | --- |
| 정제 산출물 20MB 초과 실패(20,000,000바이트는 통과) | `test_check_data_rejects_a_refined_artifact_over_20mb` |
| build 도시 0곳 실패 | `test_check_data_fails_when_no_city_can_be_built` |
| `dist/` 파일당 25MiB 초과, 파일 수 초과 실패 | `test_check_dist_rejects_a_file_over_…`, `…_more_files_than_the_plan_allows` |
| 참조 누락 실패(HTML 속성·`sw.js` 사전 캐시·랜딩 링크) | `test_check_dist_rejects_references_to_files_that_are_not_published` |
| 화면용 파일만 공개 | `test_check_dist_publishes_only_screen_files` |
| manifest의 상대 경로·SHA256·commit | `test_check_dist_seals_a_built_site_with_path_digests_and_commit` |
| 배포본 SHA256 불일치, 없는 JSON 대신 SPA HTML 실패 | `test_preview_fails_when_…`, `test_preview_rejects_the_spa_page_…` |
| alias 전파 지연의 유한한 재시도 | `test_alias_is_rechecked_…`, `test_alias_that_never_catches_up_…` |
| 검증 실패 → 직전 검증 배포로 롤백·재검증, 실행은 실패 | `test_failed_verification_rolls_back_…` |
| 검증한 적 없는 배포(빈 배포)는 롤백 대상 아님 | `test_a_production_deployment_that_was_never_verified_…` |
| 롤백 뒤 재검증 실패·Pages API 실패 보고 | `test_rollback_that_does_not_restore_…`, `test_pages_api_failures_…` |
| Wrangler가 배포를 확인해 주지 못함: 운영이 그대로면 두고, 바뀌었으면 롤백 | `test_an_upload_with_no_deployment_…`, `test_an_unconfirmed_upload_that_did_change_…` |
| 직전 검증 배포를 업로드 전에 기록 | `test_the_last_verified_deployment_is_recorded_before_the_upload` |
| 동결 뒤 main push는 올리지 않음, 사유 있는 수동 실행만 배포 | `test_main_push_after_the_freeze_…`, `test_manual_run_with_a_reason_…` |
| 사유 없는 수동 실행·main 아닌 ref·시간대 없는 동결 시각 거부 | `test_runs_that_may_not_deploy_to_production_are_refused` |
| 대기하던 오래된 SHA는 업로드하지 않음. 동결 중이면 실패로 남김 | `test_a_run_for_an_older_main_commit_…`, `test_manual_run_during_the_freeze_for_an_older_commit_…` |
| 같은 커밋 gitleaks의 성공만 통과 | `test_wait_check_…` 세 개 |
| Wrangler 출력 파일·Pages API·체크 조회 응답 해석 | `test_wrangler_upload_…`, `test_pages_api_…`, `test_github_checks_…` |

### 실제 광주 산출물로 CI와 같은 순서

커밋된 `data/`로 workflow의 build 단계를 그대로 실행했다(`build`는 약 2분 걸렸다).

```text
Git Bash: cities="$(uv run python -m deliciousmap.ci check-data --data-root data)"
          NAVER_MAP_CLIENT_ID=<합성 값> uv run python -m deliciousmap build --city gwangju --output-root <임시 dist>
          uv run python -m deliciousmap.ci check-dist --dist <임시 dist> --commit <HEAD> --city gwangju
```

`check-data`는 `gwangju` 하나를 냈고, `check-dist`는 8개 파일을 봉인했다. build가 고쳐 쓴
`data/gwangju/build.json`(출력 경로를 담는다)은 되돌렸다. CI에서도 이 파일은 작업 트리에서만 바뀐다.
그 `dist/`를 `python -m http.server`로 띄우고 실제 `HttpFetcher`로 `verify_site`를 돌려 통과했다.
Pages의 SPA 동작·콘텐츠 유형은 이 서버와 다르므로 실제 배포에서 다시 본다.

### 기본 검증

```text
uv sync --locked; uv run ruff check .; uv run ruff format --check .; uv run mypy src
uv run pytest                              # 422 passed
node --test tests/site_behavior.test.js    # 11 pass
uv run python -m deliciousmap --help; git diff --check
```

## 코드 리뷰

Standards·Spec 두 축으로 리뷰했고 다음을 반영했다.

- 외부 통신 어댑터(Wrangler·Pages API·배포 주소 내려받기)를 `cloudflare.py`, 체크 조회를 `github.py`로
  나눴다. `deploy.py`는 판정만 한다. 어댑터는 기존 `Transport` Protocol을 받는다.
- Wrangler가 종료 코드 0으로 끝났어도 배포를 알리지 않으면 운영이 이미 바뀌었을 수 있다. 이 경우를
  "바뀌지 않음"으로 두지 않고, Pages API의 지금 운영 배포로 판단해 필요하면 롤백한다. 검증 실패
  때도 전파가 늦는 alias가 아니라 API의 운영 배포로 롤백 여부를 정한다.
- 끊긴 본문·깨진 압축은 연결 실패와 구별해 `unreadable response`로 검증 실패에 넣는다.
- 직전 검증 배포를 업로드 전에 `release.json`에 쓴다. 도중에 예외로 끝나도 남는다.
- 최신 `main` 확인을 step 시작이 아니라 업로드 직전에 한다. 동결 중 수동 실행이 더 최신 `main`
  때문에 건너뛰면 성공이 아니라 실패로 남긴다.
- PR 미리보기 summary에 PR head SHA를 함께 적는다(build는 임시 merge commit).
  재실행 때 site artifact는 덮어쓴다.
- 수집 보류 사유(`HoldReason`)와 겹치던 `hold_reason`을 `validate_request`로 바꾸고, 재시도 모양을 하나로 합쳤다.

그대로 둔 것: `check-data`는 레지스트리에 없는 `data/<dir>`를 실패로 본다. 7개 도시가 모두 등록되어
있어 실제 도시 디렉터리를 막지 않고, 오타 난 도시를 build에서 조용히 빠뜨리지 않기 위해서다.

## 원격 확인

### PR #80 (2026-09-12)

[PR #80](https://github.com/snowjaewon/OfficialDeliciousMap/pull/80)(`develop` 대상, 같은 저장소)의
첫 실행([run 34688092946](https://github.com/snowjaewon/OfficialDeliciousMap/actions/runs/34688092946))이다.

- `gitleaks`: push와 PR 두 실행 모두 통과.
- `ci-build`: 통과. GitHub 러너(ubuntu)에서 기본 검증을 모두 돌렸다(pytest 422 passed, node 11 pass).
  이어서 `check-data`가 `gwangju`를 냈고, build(약 11초) 뒤 `check-dist`가 8개 파일을 봉인했다.
  artifact `site-<SHA>`(126,411바이트)를 올렸다.
- `production`: PR이라 건너뜀.
- `preview` 첫 시도: **실패**. Wrangler가 `CLOUDFLARE_ACCOUNT_ID` 형식을 거부했고,
  `CLOUDFLARE_API_TOKEN`은 빈 값으로 전달됐다. GitHub Secrets가 2026-09-09 등록 뒤로 로컬 `.env`와
  달랐다. 코드는 이 실패를 `업로드가 배포를 만들지 못했다: wrangler exited with 1`로 summary에 남기고
  job을 실패로 끝냈다. 사용자 승인으로 두 Secret만 `.env` 값으로 다시 등록했다
  (`scripts/sync-github.sh`와 같은 방식이며 값은 출력하지 않았다).
- `preview` 재실행: 통과. 9개 파일(manifest 포함)을 올렸다.

| 항목 | 값 |
| --- | --- |
| build commit(PR의 임시 merge commit) | `31f932c32f6291229c2590532006d8c379b0aa09` |
| PR head | `770412e637740abb1be562e11cedda2ffc7bb718` |
| 배포 ID | `7756c1f4-93d3-4408-bd7c-e2a7989ea4f4` |
| 고유 URL | `https://7756c1f4.officialdeliciousmap.pages.dev` — 통과(파일 SHA256·주요 경로) |
| alias | `https://pr-80.officialdeliciousmap.pages.dev` — 통과(파일 SHA256·주요 경로) |

실제 Pages에서도 `.json`은 `application/json`, `.js`는 JavaScript 유형이었다. 빌드하지 않은 도시 주소는
도시 화면이 아니었다(검증 통과로 확인).

### 필수 체크

`ci-build`가 실제로 성공한 것을 본 뒤 ruleset `main: PR 필수`(id 22636798, `main`·`develop` 대상)에
`required_status_checks`로 `gitleaks`·`ci-build`(GitHub Actions 앱)를 더했다. 기존 PR 필수·승인 0·
삭제·force-push 금지 규칙은 그대로다. `strict`(최신 기준 브랜치 요구)는 켜지 않았다.
PR #80에서 `gh pr checks 80 --required`가 두 체크를 필수로 보였고 병합 상태는 `CLEAN`이었다.

### 지도 인증

#50의 방법대로 Chrome으로 `/gwangju/`를 열었다. 키 값은 어디에도 기록하지 않았다.

**처음에는 실패했고, 원인은 도메인이 아니라 키였다.** 처음 연 두 주소
(`pr-80.…`, 배포 고유 URL `7756c1f4.…`)에서 SDK가 `navermap_authFailure`를 불렀다.
콘솔에는 `Error: Naver Maps authentication failed`가 찍혔고, 지도 자리에 "인증이 실패했습니다" 타일이 떴다.
화면은 설계대로 "네이버 지도 설정을 확인해 주세요" 안내를 띄우고, 검색 집계(12곳)와 장부는 계속
제공했다. 처음에는 하위 도메인이 등록되지 않은 탓으로 보았다. 사용자가 콘솔에
`http://*.officialdeliciousmap.pages.dev`와 `http://pr-80.officialdeliciousmap.pages.dev`를 추가했다
(사용자 보고). 그래도 실패했다. 원인은 이렇게 가렸다.

- 브라우저의 인증 요청 `oapi.map.naver.com/v3/auth`는 `503`·`401`이었다. 같은 PC에서 curl로 `.env` 키를
  넣은 같은 요청은 `200`이었다. 헤더를 브라우저와 똑같이 맞춰도, 공인 IP가 같아도 결과는 같았다.
- 확장이 없는 새 프로필 headless Chrome에서도, 어제 성공한 `http://127.0.0.1:8765`에서도 실패했다.
  이 로컬 사이트는 CI artifact를 띄운 것이다.
- 사이트에 들어간 키는 GitHub Variable `NAVER_MAP_CLIENT_ID`와 같았고 `.env` 키와는 달랐다. 그 키로는
  인증 서버가 `401 Authentication Failed`, `.env` 키로는 `200`이었다. Variable은 #50에서 사용자가 `.env`
  키를 바꾸기 전(2026-09-09)에 등록된 채였다.

사용자 승인으로 Variable을 `.env` 키로 바꾸고 PR #80 workflow를 다시 돌렸다. 그 뒤의 관찰은 이렇다.

| 주소 | 등록(사용자 보고) | 실제 인증(관찰) |
| --- | --- | --- |
| `https://pr-80.officialdeliciousmap.pages.dev` | 와일드카드 하위 도메인, 이 주소 | **성공** |
| `https://officialdeliciousmap.pages.dev` | 운영 도메인 | 미확인(운영 배포 전). 인증 서버 판정은 `200` |

`pr-80`에서는 인증 요청이 `200`이었다. 지도 타일과 마커 묶음(12)이 그려졌고 설정 안내는 뜨지 않았다.
움직이기 전에 `12곳 전체 · 12곳 현재 지도 영역`과 `first-ready`가 기록됐다. 인증 서버에 직접 물으면
등록한 적 없는 `pr-999.officialdeliciousmap.pages.dev`도 `200`이었다. 다른 `*.pages.dev` 프로젝트와
`example.com`은 `401`이었다. 우리 프로젝트의 하위 도메인만 허용되고 `pages.dev` 전체는 열리지 않았다.
운영 도메인 한 줄만으로 하위 도메인이 허용되는지는, 키가 틀린 동안 시험했으므로 가르지 못했다.
#15의 "대표 도메인 등록으로 preview alias도 허용될 것"은 그래서 여전히 확인하지 않은 추론이다.

키를 바꾸는 곳이 `.env`와 GitHub Variable 두 곳이라 어긋날 수 있다. `scripts/sync-github.sh`가
`.env` 값을 Variable에 올리므로 키를 바꾸면 이 스크립트를 다시 실행한다.

### 운영 첫 배포 (2026-09-12)

PR #80을 `develop`에 머지했다(`d688411`). 그 `develop` push에서 `gitleaks`·`ci`가 통과했고 `production`은
건너뛰었다. 이어 AGENTS.md의 릴리스 흐름대로 `release/0.1.0`을 만들고
[PR #82](https://github.com/snowjaewon/OfficialDeliciousMap/pull/82)를 `main`에 머지했다(`78cc110`).
그 `main` push의 [run 34695584834](https://github.com/snowjaewon/OfficialDeliciousMap/actions/runs/34695584834)는
다음 순서로 진행됐다.

- `ci-build` 통과
- `production`: `wait-check`가 같은 커밋의 `gitleaks` 성공을 확인했다. 이어 Wrangler가 올렸고
  (9개 파일 중 8개는 미리보기에서 이미 올린 것과 같아 1개만 새로 올림), 검증을 통과했다.

| 항목 | 값 |
| --- | --- |
| commit | `78cc110a00645b2c568afb835e3200ab24c1c941` |
| 배포 ID | `a6778b37-c351-4937-8325-c3bd2369d3f3` |
| 고유 URL | `https://a6778b37.officialdeliciousmap.pages.dev` — 통과(파일 SHA256·주요 경로) |
| 운영 alias | `https://officialdeliciousmap.pages.dev` — 통과(파일 SHA256·주요 경로) |
| 직전 검증 배포 | 없음(`release.json`의 `previous: null`) |

직전 운영 배포는 프로젝트를 만들 때 올린 빈 배포(404)라 자기 manifest가 없다. 그래서 롤백 대상으로
보존하지 않았다. 이 실행이 실패했다면 사람이 대응해야 했다. artifact `release-78cc110…-1`에
`release.json`이 남아 있다.

**운영 지도 인증.** Chrome으로 `https://officialdeliciousmap.pages.dev/gwangju/`를 열었다. 결과는 이렇다.

- 인증 요청 `200`, 설정 안내 없음, 인증 오류 콘솔 없음
- 타일과 마커 묶음(12)이 그려짐
- 움직이기 전 `12곳 전체 · 12곳 현재 지도 영역`
- 서비스 워커 `sw.js`가 `/` 범위에서 `activated`, 다시 불렀을 때 페이지를 제어함
- 받은 `deploy-manifest.json`의 commit은 `78cc110`

창이 가려져 `first-ready`는 기록되지 않았다(#50의 확인 환경 주의).

### 완료 기준 상태

| 완료 기준 | 상태 |
| --- | --- |
| `develop`·`main` 대상 PR과 두 브랜치 push에서 `gitleaks`·`ci-build` 실행 | 확인(PR #80·#82, `develop` push `d688411`, `main` push `78cc110`) |
| 문서만 바뀐 PR에도 두 체크 보고 | 경로 필터가 없다. 문서만 바꾼 커밋의 push(PR #80의 `6c710e8`·`a526f8d`)에서 두 체크가 돌았다 |
| `ci-build` 실패 판정(20MB·`dist/` 한도·참조 누락·build 도시 0곳) | 테스트로 확인 |
| 같은 저장소 PR 미리보기, summary의 URL·SHA·검증 결과 | 확인(`pr-80`·`pr-82`) |
| fork PR은 배포하지 않음 | job 조건으로만 확인. fork PR은 관찰하지 않음 |
| `main` push 운영 배포, 고유 URL·운영 alias 대조 | 확인(`78cc110`) |
| 검증 실패 시 롤백, 실행은 실패 | 판정은 테스트로 확인. 실제 운영 롤백은 **미확인**(정상 운영을 일부러 깨지 않았다) |
| 동결 설정 시 `main` push 미배포, 사유 있는 수동 실행 배포 | 판정은 테스트로 확인. 실제 동결 실행은 **미확인**(동결 시각 설정은 #53 제외 범위) |
| ruleset 필수 체크 추가 | 적용 |
| 운영 URL·첫 PR alias의 실제 지도 인증 | 둘 다 성공(PR alias는 Variable 키 교체 뒤) |
| 이전 버전을 연 브라우저의 PWA 갱신 | 미리보기에서 관찰(아래) |
| AGENTS.md 기본 검증 명령과 gitleaks | 확인(로컬과 CI) |

**PWA 갱신.** 미리보기 `pr-80`에서 관찰한 것이다. 같은 Chrome 프로필이 예전 키로 build한 배포를 먼저
열어 서비스 워커를 등록했다. 새 키로 다시 배포한 뒤 같은 주소를 다시 열자, 새 배포의 페이지와 키를
받아 지도 인증에 성공했다. `sw.js`는 모든 GET을 네트워크에서 먼저 받고 실패할 때만 캐시를 쓴다.
그래서 캐시가 예전 화면을 붙잡지 않는다. 운영 주소에서 두 번째 배포로 같은 확인을 되풀이하지는 않았다.
