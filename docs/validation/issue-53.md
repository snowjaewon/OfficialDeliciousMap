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

아직 하지 않았다. 아래 순서로 확인해 채운다.

| 완료 기준 | 상태 |
| --- | --- |
| PR·push에서 `gitleaks`·`ci-build` 실행, 문서만 바뀐 PR에도 보고 | 미확인 |
| 같은 저장소 PR 미리보기(`pr-<n>`), summary의 URL·SHA·검증 결과 | 미확인 |
| `main` push 운영 배포, 고유 URL·운영 alias 대조 | 미확인 |
| 실제 운영 롤백 | 미확인 |
| 동결 설정 시 `main` push 미배포, 사유 있는 수동 실행 배포 | 미확인(판정은 테스트로 확인) |
| ruleset에 `gitleaks`·`ci-build` 필수 체크 추가 | 미적용 |
| 운영 URL·첫 PR alias의 실제 지도 인증 | 미확인 |
| 이전 버전을 연 브라우저의 PWA 갱신 | 미확인 |
