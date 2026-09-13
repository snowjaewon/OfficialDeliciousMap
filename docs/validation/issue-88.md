# 이슈 #88 재게시 확정 한 줄 줄이기 검증 기록

2026-09-13, Windows 11 · Git Bash · Python 3.12.10. 도시는 광주, 기관은 광주광역시청 하나다.
기준은 [ADR-0006](../adr/0006-human-confirmed-reposts.md)이고 그 줄을 만든 것은
[#69](https://github.com/snowjaewon/OfficialDeliciousMap/issues/69)([검증 기록](issue-69.md))이다.
작업 브랜치의 기반은 `develop` `1268c3e`다.

## 고친 것

- `RepeatConfirmation`에서 `references`를 뺐다. 기본값이 `()`라 파이프라인이 읽지 않던 칸이며,
  코드 동작은 이 삭제로 달라지지 않는다.
- `evidence`의 뜻을 **대조한 원본의 파일명**으로 바꿨다. 판단을 글로 옮기는 대신 파일명을 적고,
  승인하는 사람이 그 파일을 직접 연다.
- 계약이 바뀌었으므로 확정 한 줄의 `schema_version`을 1에서 **2**로 올렸다. `parse`는 이 입력의
  해시를 산출물에 담지 않아, 옛 뜻으로 쓴 줄을 가려낼 표시는 이 버전뿐이다.
- `data/manual/gwangju/repeats.jsonl` 두 줄을 새 모양으로 다시 적었다.
- 합성 확정을 만드는 테스트 픽스처 둘(`tests/test_extract.py`의 `confirm`,
  `tests/test_parse_cli.py`의 `confirm_repeat`)의 `evidence`도 파일명으로 바꿨다. 새 계약을 쓰는
  테스트가 옛 뜻을 시연하면 그 뜻이 문서가 아니라 코드에서 다시 살아난다.
- 설명을 맞춘 곳은 `RepeatConfirmation` docstring,
  [ADR-0006](../adr/0006-human-confirmed-reposts.md)의 `evidence` 절과 Consequences,
  `README.md`의 `repeats.jsonl` 단락, [#69 검증 기록](issue-69.md)이 `evidence`·`references`를
  가리키던 문장이다.

### 한 줄이 줄어든 만큼

| | 전 | 후 |
| --- | --- | --- |
| 파일 | 3,230바이트 | **879바이트** |
| 화재예방과 줄 | 1,112자 | **410자** |
| 119대응과 줄 | 1,134자 | **405자** |
| 한 줄이 담는 칸 | `decision`·`evidence`·`references`·`schema_version`·`scope` | `references`를 뺀 넷 |

새 `evidence`는 `10887-1.xlsx, 11009-1.xlsx`와 `10841-1.xls, 10870-1.xls`다. 이 이름은
`data/gwangju/fetch.json`이 그 원본 해시에 적은 경로의 파일명이며, 줄이 이미 담고 있던
`scope.sources`(SHA-256)와 같은 원본을 가리킨다. 곧 줄은 원본을 두 번 가리키되 한 번은 사람이
파일 탐색기에서 찾을 수 있는 이름으로 가리킨다.

## 실측 — 광주광역시청 재생성

새 모양의 `repeats.jsonl`을 넣은 뒤
`uv run python -m deliciousmap parse --city gwangju`를 다시 돌렸다(21초, 종료 코드 0).
**실행 직전과 직후의 `data/` 19개 파일이 SHA-256까지 모두 같다.** 해시 목록을 두 번 떠서 비교했고
차이는 없다. 곧 `develop`과 견주어 달라진 `data/` 파일은 사람이 고쳐 쓴 `repeats.jsonl` 하나이고,
`parse`가 다시 만든 `records.csv`·`parse.json`은 바이트까지 커밋된 것과 같다.

| 항목 | 값 | 전과 같은가 |
| --- | --- | --- |
| 레코드(`records.csv`) | 2,797 | 그대로 |
| 기준이 합친 묶음 / 레코드 | 117 / 122 | 그대로 |
| 사람 확정이 더 합친 묶음 / 레코드 | 2 / 2 | 그대로 |
| 가를 근거가 없어 남긴 묶음 / 레코드 | 0 / 0 | 그대로 |
| 별개 지출로 확정해 남긴 묶음 / 레코드 | 0 / 0 | 그대로 |
| 마커(`build.json`의 `marker_count`) | 12 | 그대로 |

확정이 여전히 읽히는 것은 레코드 수가 말해 준다. 새 모양의 줄을 `parse`가 읽지 못했다면 레코드가
#69 이전의 2,799로 돌아가고 `unmerged_expenses`가 2가 된다.

`classify` 이후 단계는 다시 돌리지 않았다. `records.csv`와 `parse.json`이 바이트까지 같아 뒤 단계가
보는 입력 해시가 달라지지 않기 때문이다. 위의 마커 12는 커밋된 `build.json`의 값이며, 그 파일도
해시가 그대로다.

## 구현과 TDD

실패 → 최소 구현 → 통과를 확인한 동작(`tests/test_parse_cli.py`):

- **옛 계약으로 쓴 확정 줄은 `parse`가 거부한다.** 두 원인을 갈라서 본다 — `schema_version`만
  1로 내린 줄과, 뺀 칸(`references`)만 되살린 줄을 차례로 넣고 공개 CLI로 `parse`를 돌린다. 계약을
  바꾸기 전에는 둘 다 통과해 종료 코드가 0이었고(실패 확인), 바꾼 뒤 둘 다 1이 된다. 두 원인을 한
  줄에 섞으면 `Contract`의 `extra="forbid"`가 `references`만으로 거부해 버려, 버전을 2로 올린 것이
  홀로 검증되지 않는다.

`references`를 읽는 코드는 없었으므로 그 칸의 삭제로 깨지는 테스트도 없다. 기존 확정 테스트
11건(`tests/test_extract.py` 7건 · `tests/test_parse_cli.py` 4건)은 그대로 통과한다.

## 짚어 둔 것

- `evidence`는 자동 판정을 사람 판단으로 덮는 입력의 **유일한 필수 근거 칸**이다. 파일명만 남기면 그
  줄을 누가 썼는지와 왜 그렇게 판단했는지가 줄에서 사라진다. 2026-09-13 사용자 결정으로 그대로
  간다 — 승인 비용을 글이 아니라 원본을 여는 쪽에 둔다. 광주 두 줄의 대조 내용은
  [#69 검증 기록](issue-69.md)의 표 두 개에 그대로 있다.
- 다른 사람 검토 입력(`geocode.jsonl`·`restore.jsonl`·`sources.jsonl`)의 `evidence`·`references`는
  건드리지 않았다(#88 제외 범위). `ReviewReference` 계약은 그 입력들이 계속 쓴다.
- 판정 자체는 바뀌지 않았다. `same_expense`/`separate_expenses`와 적용 순서는 ADR-0006 그대로다.
- **계약은 `evidence`가 파일명인지까지는 보지 않는다.** 비어 있지 않은 문자열이면 통과하므로, 옛
  모양의 긴 문장에 `schema_version: 2`만 붙인 줄은 가려내지 못한다. `parse`가 잡는 것은 옛 버전을
  적은 줄과 뺀 칸(`references`)이 남은 줄이다. 파일명을 `scope.sources`와 대조해 검사할지는 이
  이슈에서 정하지 않았다 — 지금은 승인하는 사람이 그 대조를 한다.
- `parse`는 이 입력의 해시를 산출물 의존성에 담지 않는다. 입력을 고치면 `parse`부터 다시 돌려야
  한다. 이번 실행이 그 규칙을 따른 것이다.

## 자동 검사

| 검사 | 결과 |
| --- | --- |
| `uv sync --locked` | 통과 |
| `uv run ruff check .` | 통과 |
| `uv run ruff format --check .` | 104개 파일 통과 |
| `uv run mypy src` | 통과, 44개 소스 파일 |
| `uv run pytest` | **454 passed** |
| `node --test tests/site_behavior.test.js` | 11건 통과 |
| `uv run python -m deliciousmap.ci check-data --data-root data` | `gwangju` |
| `git diff --check` | 통과 |
| gitleaks | 스테이지 전량에 `gitleaks git --pre-commit --staged` 통과 |
