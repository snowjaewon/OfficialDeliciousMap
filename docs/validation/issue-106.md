# 이슈 #106 제출 시점 기준과 원본 결함 확정 검증 기록

2026-09-13, Windows 11 · Git Bash · Python 3.12.10. 도시는 광주, 기관은 광주광역시청 하나다.
작업 브랜치의 기반은 `develop` `2d3305a`다. 이 문서가 이번 제출의 **재검증 리포트**이며,
아래 "두 기준을 나란히" 절이 [#9의 제출 기준](
https://github.com/snowjaewon/OfficialDeliciousMap/issues/9#issuecomment-5611347945)과
제출 시점 기준을 항목마다 대조한다.

## 결정의 출처

- 2026-09-13 사용자 결정(선택지 C): [#106](https://github.com/snowjaewon/OfficialDeliciousMap/issues/106).
  원본 결함 확정을 미해결과 나누고, 나머지는 사유별 건수를 공개하면 제출할 수 있으며, 0건 기준은
  버리지 않고 제출 뒤 목표로 옮긴다.
- 0건 기준의 원문: [#9 제출 기준](https://github.com/snowjaewon/OfficialDeliciousMap/issues/9#issuecomment-5611347945)(2026-09-10).
- 미해결 원본의 처리 규칙: [폴백 정책](../specs/header-mapping-fallback.md)의 `끝내 읽지 못한 원본`.
- 16개 원본의 사람 대조 자체는 [#93](https://github.com/snowjaewon/OfficialDeliciousMap/issues/93),
  지오코딩 미확정을 줄이는 일은 [#73](https://github.com/snowjaewon/OfficialDeliciousMap/issues/73)·
  [#74](https://github.com/snowjaewon/OfficialDeliciousMap/issues/74),
  나머지 도시는 [#75](https://github.com/snowjaewon/OfficialDeliciousMap/issues/75)의 범위다.

## 이번에 구현한 것

| 범위 | 결과 |
| --- | --- |
| 집계 | `submission.tally`가 `parse` 원본별 보고와 `data/manual/<city>/sources.jsonl`을 읽어 원본 결함 확정과 그 밖의 미해결을 사유별로 가른다 |
| 계약 | `ConfirmedDefect`·`RemainingSource`·`UnconfirmedPlace`·`SubmissionTally`를 더하고 `BuildInput.tally`로 화면에 넘긴다 |
| 화면 | 자료 범위 대화상자가 원본 결함 확정·미해결 원본·판단 보류·지오코딩 미확정을 사유별로 낸다 |
| 문서 | 폴백 정책에 `원본 결함 확정`·`제출 시점 기준` 절, `CONTEXT.md`에 `원본 결함 확정`, README에 대화상자 설명 |

계약 `BuildOutput`은 바뀌지 않아 `build`의 `schema_version`은 7 그대로다. 정제 산출물은 다시 만들어도
같은 내용이라 이번 PR에 `data/` 변경이 없다.

## 두 기준을 나란히

광주광역시청 하나만 수집한 `develop` `2d3305a`의 산출물 기준이다. 제출 시점 기준은 "사유별 건수를
화면의 자료 범위와 재검증 리포트에 밝혔는가"를 묻고, #9 기준은 "0인가"를 묻는다.

| 항목 | 지금 | #9 기준(0건) | 제출 시점 기준(공개) |
| --- | --- | --- | --- |
| 원본 결함 확정 | 0개(사람 대조 전, [#93](https://github.com/snowjaewon/OfficialDeliciousMap/issues/93)) | 해당 없음 — 미해결로 센다 | 충족(셀 수 있고, 0개라 낼 말이 없어 줄을 내지 않는다) |
| 미해결 원본 | 16개(검증 실패 16개 · 지출 후보 663건) | **미충족** | 충족(사유·원본 수·후보 수를 화면과 이 문서에 적었다) |
| 판단 보류 | 387건 | **미충족** | 충족 |
| 지오코딩 미확정 | 식당 2,232건 가운데 1,933건(주소 근거 없음 1,710 · 후보 없음 223) | **미충족** | 충족 |
| 수집 대상 도시 | 7곳 중 1곳(광주) | **미충족** | 충족(랜딩의 나머지 여섯 도시는 `준비 중`으로 나온다) |
| 수집 대상 기관 | 광주광역시청 1곳, 자치구 5곳 미수집([#99](https://github.com/snowjaewon/OfficialDeliciousMap/issues/99)) | **미충족** | 충족(자료 범위 표의 기관별 수집 상태) |

16개의 사유를 원본 쪽에서 보면 `merchant_blank` 9개, `total_mismatch` 7개다(`sources.jsonl`).
지금은 `confirmed_by`가 모두 비어 있어 **16개 전부 미해결**이며, 화면은 `parse`가 남긴 사유인
`검증 실패 16개`로 적는다. 원본 결함 확정으로 갈리는 것은 #93이 대조를 마친 뒤다.

## 광주 산출물로 빌드한 화면

`build --city gwangju`를 돌려 `dist/gwangju/index.html`의 자료 범위 대화상자를 확인했다.
지도 SDK 키는 화면 문구와 무관하므로 검증용 값을 넣었다.

```text
게시글 원본 11,035개 중 대상 173개 (기간 미표기 제외 0개)
부서가 이미 공개한 기간을 다시 올려 같은 지출이 여러 원본에 반복된 117묶음을 합쳐, 장부에서
122건을 뺐습니다. 원본을 다시 대조해 같은 지출로 확정한 2묶음 2건도 함께 뺐습니다. 다시 올린
것인지 따로 쓴 것인지 가를 근거가 없어 남긴 묶음은 없습니다.
아직 확정하지 못해 미해결로 남은 원본 16개: 검증 실패 16개(지출 후보 663건).
식당 여부를 가르지 못한 판단 보류 387건 · 식당 2,232건 가운데 좌표를 확정하지 못한
1,933건(주소 근거 없음 1,710건 · 후보 없음 223건)은 지도에 오르지 못하고 장부에만 남습니다.
```

레코드 2,810건, 마커 12곳으로 `data/gwangju/build.json`과 같다. 좌표 미확정 1,933건의 사유별 수는
[#73 댓글](https://github.com/snowjaewon/OfficialDeliciousMap/issues/73)이 적은 1,679·254와 다르다.
그 뒤 인허가 조회가 붙어 사유가 옮겨 간 것이며 합계 1,933건은 같다.

## 사람 대조가 차면 어떻게 갈리는가

#93이 아직 끝나지 않아 실제 산출물에는 `confirmed_by`가 없다. 저장소를 건드리지 않고 확인하려고
`data/`를 임시 폴더로 복사해 16줄 가운데 8줄에만 `confirmed_by`를 채우고 같은 `build`를 돌렸다.

```text
사람이 원본과 대조해 원본 자체의 결함으로 확정한 원본 8개는 레코드를 내지 않습니다: 상호 빈칸
5개(지출 후보 189건) · 합계 불일치 3개(지출 후보 43건). 아직 확정하지 못해 미해결로 남은 원본
8개: 검증 실패 8개(지출 후보 431건).
```

원본 결함 확정 8개와 미해결 8개로 갈렸고 두 사유의 후보 수(189 + 43 + 431 = 663)는 대조 전 한 줄로
적던 663건과 같다. 대조가 차면 수가 옮겨 갈 뿐 사라지지 않는다. 임시 폴더는 검증 뒤 지웠고 저장소의
`data/manual/gwangju/sources.jsonl`은 16줄 모두 `confirmed_by`가 빈 상태 그대로다.

## 검증 명령과 결과

양쪽 공통(저장소 루트):

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
node --test tests/*.test.js
git diff --check
```

`ruff check`·`ruff format --check`(118개 파일)·`mypy src`(48개 파일) 통과, `pytest` 507건 통과
(새로 더한 것은 `tests/test_submission.py` 9건과 `tests/test_site_build.py` 7건),
`node --test` 79건 통과, `git diff --check` 지적 없음.

gitleaks는 `gitleaks detect -c .gitleaks.toml`로 돌렸다. 이 브랜치의 변경에서는 탐지가 없다. 전체
히스토리 검사에서 나오는 2건은 `develop`에 없는 다른 브랜치
(`feature/99-gwangju-district-pipeline`, `cac8138`)의 `data/gwangju/orgs/gwangju-gwangsan/`
조회 캐시 두 파일이며, 이 이슈의 범위가 아니라 [#99](https://github.com/snowjaewon/OfficialDeliciousMap/issues/99)
쪽에서 봐야 한다.

## 남은 제한

- 원본 결함 확정은 셀 수 있게 되었을 뿐, 광주 16개는 [#93](https://github.com/snowjaewon/OfficialDeliciousMap/issues/93)이
  대조를 마치기 전까지 미해결이다. 이 구현이 그 수를 줄이지 않는다.
- 지오코딩 미확정 1,933건은 [#73](https://github.com/snowjaewon/OfficialDeliciousMap/issues/73)·
  [#74](https://github.com/snowjaewon/OfficialDeliciousMap/issues/74)의 범위이며 이번 변경으로 줄지 않는다.
- 수집하지 않은 도시·기관은 랜딩의 `준비 중`과 자료 범위 표의 기관별 상태로만 드러난다. 도시마다
  "몇 곳 중 몇 곳"을 세는 화면은 [#75](https://github.com/snowjaewon/OfficialDeliciousMap/issues/75)·
  [#99](https://github.com/snowjaewon/OfficialDeliciousMap/issues/99)가 들어온 뒤에 다시 본다.
- 제출 시점 기준을 코드가 검사하지는 않는다. 화면이 사유별 건수를 내는 것까지가 이번 범위이며,
  "공개했는가"의 판정은 이 재검증 리포트가 한다.
