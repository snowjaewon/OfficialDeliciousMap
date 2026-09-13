# `.hwpx` 원본에서 표 읽기 실측 (#112)

2026-09-13 실행. `grid.read_tables`가 HWPX 본문의 표를 읽게 하고, 남구 대상 4개를 실제로
`headermap`·`parse`에 흘린 기록이다. [#99 실측](issue-99.md) 3절이 `unsupported_format`으로
남긴 4개가 이번 대상이다.

## 1. 무엇을 읽게 했나

HWPX는 표준 ZIP이고 본문은 `Contents/section<번호>.xml`의 OWPML이다. 새 의존성 없이
`zipfile` + `xml.etree`로 읽었다.

| 다룬 것 | 어떻게 |
| --- | --- |
| 표 하나 | `<hp:tbl>` 하나가 `Table` 하나다. 이름은 PDF와 같은 `table1`·`table2`다. |
| 한 칸이 여러 조각으로 쪼개진 표기 | `<hp:tc>` 안의 `<hp:t>`를 사이에 아무것도 끼우지 않고 잇는다. |
| 병합한 칸 | `<hp:cellAddr>`가 가리키는 자리에 놓고 덮인 자리는 비운다. |
| 이름표(`label`) | 표 바로 앞의 비어 있지 않은 문단. 없으면 본문 이름(`section0`). |
| 표 밖 문단 | 표로 만들지 않는다. 표가 하나도 없으면 표 0개이며 집행 없음이 아니다. |

칸의 조각을 이어 붙이는 규칙은 원본이 보여 주는 글자와 같아야 한다는 기준으로 정했다.
`1144-1`의 결제 방법 칸은 `결제`·`방법` 두 문단이고 일시 칸은 `2026. 4. 8.`·`12:00` 두
문단인데, 사이에 공백을 넣으면 원본에 없는 `결제 방법`·`2026. 4. 8. 12:00`이 된다.

병합한 칸을 덮인 자리까지 되풀이하지 않는 것은 통합문서와 같은 규칙이다. openpyxl도 병합
범위의 왼쪽 위에만 값을 두므로, `Table.cell(row, column)`을 읽는 쪽이 형식마다 다른 규칙을
알 필요가 없다.

`.hwp`(HWP 5.0)는 이슈 본문의 제안과 [착수 전 실측](https://github.com/snowjaewon/OfficialDeliciousMap/issues/112#issuecomment-5653752069)
4절대로 범위에서 뺐다. 5절에 실측이 있다.

## 2. 남구 4개를 실제로 돌렸다 (완료 기준 3)

저장소 루트, Git Bash. **산출물을 저장소에 커밋하지 않으려고 `data/`를 복사해 그 사본을
`--data-root`로 주었다.** 아래 수치는 모두 그 사본에서 센 것이고, 커밋된
`data/gwangju/orgs/gwangju-nam/`은 이 작업으로 바뀌지 않았다.

```text
cp -r data "$SCRATCH/data"
uv run python -m deliciousmap headermap --city gwangju --org gwangju-nam \
  --data-root "$SCRATCH/data" --output-root "$SCRATCH/dist"   # 3.6초
uv run python -m deliciousmap parse --city gwangju --org gwangju-nam \
  --data-root "$SCRATCH/data" --output-root "$SCRATCH/dist"   # 2.5초
```

### headermap — `unsupported_format` 4개가 0개가 됐다

| | 커밋된 산출물 | 이번 실행 |
| --- | --- | --- |
| 매핑한 표 | 73 | **77** |
| 미해결 원본 | 7 | **3** |
| 그중 `unsupported_format` | 4 | **0** |

남은 미해결 3개는 형식이 아니라 내용 때문이며 이번 변경 전과 같다 — `1117-1.pdf`
(`table1:R6 spent_on`), `1130-1.xlsx`(`sheet1:R18 spent_on`), `1154-1.pdf`
(`table1:R3 spent_on`). 날짜 표기는 [#113](https://github.com/snowjaewon/OfficialDeliciousMap/issues/113)이 다룬다.

### parse — 레코드 14건

| 원본 | 부서·분기 | 표 행 | 지출 후보 | 레코드 | 총계 대조 |
| --- | --- | --- | --- | --- | --- |
| `1112-1.hwpx` | 회계과 2026 1분기 | 11 | 9 | **9** | `matched` |
| `1127-1.hwpx` | 감사담당관 2026 1분기 | 4 | 3 | **3** | `absent` |
| `1144-1.hwpx` | 회계과 2026 2분기 | 2 | 1 | **1** | `absent` |
| `1168-1.hwpx` | 감사담당관 2026 2분기 | 2 | 1 | **1** | `absent` |
| 합계 | | | 14 | **14** | |

남구 전체로는 통과한 원본이 60개에서 64개로, 지출 후보가 1,087건에서 1,101건으로,
`records.csv`가 1,022줄에서 1,036줄로 늘었다. 범위 밖 지출·분모에서 뺀 행·재검토 대상은
네 원본 모두 0건이다.

`1112-1`의 `matched`가 병합 펼치기의 증거다. 이 원본의 합계 행은 `colSpan=5`로 합쳐져 있어
`합 계`가 0열, `639,100`이 5열에 있다. 금액이 제 열에 놓이지 않으면 `_check_totals`가
`total amount mismatch`로 표를 거부한다. 9건의 합이 639,100원과 정확히 같아 통과했다.

### 기대값 13건은 14건으로 고친다

착수 전 실측은 13건을 기대값으로 적었다. 실제는 14건이고, 어긋난 것은 `1127-1` 하나다.

```text
1127-1.hwpx  <hp:tbl rowCnt="4">  헤더 1행 + 데이터 3행
  R2  감사담당관 | 2026.01.30.18:30 | ... | 216,500
  R3  감사담당관 | 2026.02.04.12:00 | ... | 128,000
  R4  감사담당관 | 2026.02.26.12:00 | ... |  91,000
```

표 행 4에 합계 행이 없으므로 데이터 행은 2가 아니라 3이다. 세 건 모두 2026년 상반기라
기간 밖으로 빠지는 것도 없다. 나머지 셋(9·1·1)은 착수 전 실측과 같다.

## 3. 헤더 판정 하나를 새로 했다 — 커밋하지 않았다

네 원본 중 셋은 공통 캐시의 기존 헤더 서명에 그대로 걸렸다. `1112-1`만 헤더가
`대상 인원수(명)`·`금액(원)`으로 단위를 달고 있어 서명이 달랐고, 모델을 구성하지 않은
실행에서는 `model_not_configured`로 남았다.

그래서 #99와 같은 방식으로 Claude가 표를 읽어 판정하고 답변 이력에 넣었다
(`claude-opus-5/claude-read-1`). **이 판정은 사본에만 있고 저장소에는 커밋하지 않았다** —
이슈의 `남은 제한`대로 이 작업은 형식 지원까지이기 때문이다. 남구를 다시 돌릴 때 같은
판정을 써야 하므로 그대로 옮겨 적는다.

```json
{"amount_unit": "won", "columns": [{"column": 1, "role": "spent_on"},
 {"column": 2, "role": "merchant"}, {"column": 3, "role": "purpose"},
 {"column": 5, "role": "amount_krw"}], "data_start_row": 3, "header_rows": [1],
 "layout": "table", "year_hint": null}
```

`header_rows`가 1이고 `data_start_row`가 3인 것은 2행이 합계 행이기 때문이다.
`year_hint`가 없는 것은 일시에 연도가 있기 때문이다. 이 판정이 코드 검증을 통과해 공통
캐시에 새 서명 하나가 쌓였고(사본의 `headermap.jsonl` 426줄 → 427줄), 다음 분기의 같은
헤더는 모델 없이 매핑된다.

## 4. LLM API 호출 0회

`data/_shared/llm-budget.jsonl`은 실행 전후가 바이트까지 같다. `classify.jsonl`도 그대로다
(이번 실행은 `classify`까지 가지 않는다). 공통 캐시에 늘어난 것은 3절의 서명 하나뿐이다.

## 5. `.hwp` 112개는 그대로 미해결이다 (완료 기준 4)

raw-root의 `.hwp` 112개를 전수로 `grid.read_tables`에 넣었다.

| 결과 | 개수 |
| --- | --- |
| `UnsupportedFormat: OLE2 container without an Excel workbook` | **112** |
| 표를 읽은 것 | 0 |

이번 제출의 대상인 `.hwp`는 **0개**다(`period.targets` 전수 판정). 112개는 모두
`gwangju/gwangju-city/expenses/`에 있고 게시일이 대상 연도 밖이다. `.hwp`는 ZIP이 아니라
OLE2라 `_legacy`가 같은 자리에서 걸리며, 이번 변경은 그 경로를 건드리지 않았다.

## 6. 대상이 아닌 `.hwpx` 3개

raw-root의 `.hwpx`는 7개이고 그중 대상은 4개다. 나머지 3개도 같은 코드 경로를 타므로 확인했다.

| 원본 | 무엇인가 | 이번 구현이 읽은 것 | 대상이 아닌 이유 |
| --- | --- | --- | --- |
| `gwangju-nam/1085-1.hwpx` | 2025 4분기 회계과 | 표 1개·2행 | 제목 기간 밖 |
| `gwangju-nam/1098-1.hwpx` | 2025 4분기 감사담당관 | 표 1개·3행 | 제목 기간 밖 |
| `gwangju-city/10681-2.hwpx` | 보고회 참석자 명단 | 표 2개(1행·88행) | 게시일 2025-10-16 (`posted_out_of_range`) |

`10681-2`는 업무추진비 표가 아니다. 88행 표의 열은 `연번`·`구분`·`기관명`·`성명`·`직위`·`비고`로
집행일도 금액도 없다. 대상이 아니라 `headermap`에 가지 않으며, 설령 간다 해도 날짜·상호·금액
역할을 채울 열이 없어 `missing required roles`로 미해결이 된다. 지출로 오인되지 않는다.

## 7. 합성 fixture를 둔 자리

완료 기준 1은 합성 fixture를 `tests/fixtures/gwangju/`에 두라고 적었다. **대신
`tests/hwpx.py`에 합성 HWPX를 만드는 코드를 두었다.** 근거는 둘이다.

- AGENTS.md의 테스트 규칙이 `tests/fixtures/<city>/`를 **원본에서 만든 fixture** 자리로
  정의한다(익명화 상위 5행·100KB 이내). 합성물은 "합성 fixture를 우선 사용한다" 쪽에 든다.
- 같은 저장소가 이진 형식의 합성 원본을 이미 코드로 만든다 — PDF는 `tests/pdf.py`,
  엑셀 97-2003은 `tests/gwangju.py`의 `workbook`이다. ZIP 덩어리는 diff에서 읽을 수 없고
  코드는 읽을 수 있다.

`tests/hwpx.py`는 실제 원본의 구조만 흉내 낸다 — `mimetype`을 압축하지 않고 맨 앞에 두고,
칸을 `<hp:p>` 여러 개로 쪼개고, 병합으로 덮인 자리의 `<hp:tc>`를 적지 않으며 `colAddr`가
그만큼 건너뛴다. 실제 원본의 글자는 쓰지 않는다.

## 8. 검사

```text
uv run ruff check .          통과
uv run ruff format --check . 통과
uv run mypy src              통과
uv run pytest                512 → 521건 통과
git diff --check             통과
```

`tests/test_grid.py`에 9건을 더했다. 여덟 건은 구현 전에 먼저 실패시킨 것이다 —
이름표·조각 잇기·병합 펼치기·표 번호·표 없는 본문·깨진 본문·`.hwp`·HWPX 본문이 없는
ZIP이다. 나머지 하나(구역이 여럿인 본문)는 구현 뒤에 더했다. 구역 번호를 글자가 아니라
수로 정렬하는 것은 실제 원본 7개가 모두 구역 하나여서 앞의 여덟 건이 짚지 못한다.

## 9. 남은 것

- **네 원본의 14건은 아직 도시 산출물에 없다.** 반영하려면 남구를 다시 돌려야 하고 그때
  `classify`·`geocode`·`build`가 함께 움직인다. 3절의 헤더 판정을 먼저 답변 이력에 넣어야
  한다.
- `1112-1`의 9건 중 3건은 상호 칸에 쉼표로 두 업소가 적혀 있다. `parse`는 통과하지만 좌표를
  받지 못한다. 도시 전체의 기존 문제이며 [#117](https://github.com/snowjaewon/OfficialDeliciousMap/issues/117)이 다룬다.
- 대상 기간 안 단독 `.hwp`가 나타나면 그때 OLE2 읽기를 다시 판단한다. 지금은 0개다.
