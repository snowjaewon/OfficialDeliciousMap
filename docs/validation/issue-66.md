# 이슈 #66 미해결 원본의 후보 수를 장부에 담은 검증 기록

2026-09-13, Windows 11 · Git Bash · Python 3.12.10. 도시는 광주, 기관은 광주광역시청 하나다.
기준은 [폴백 정책](../specs/header-mapping-fallback.md)이고, 이 이슈가 이어받은 실측은
[#62 검증 기록](issue-62.md)이다. 작업 브랜치의 기반은 `develop` `10022b1`이다.

## 이슈 셋 중 하나만 했다

[#66](https://github.com/snowjaewon/OfficialDeliciousMap/issues/66)은 세 가지와 그 셋을 반영한
`data/gwangju/` 재생성을 묶은 이슈다. 이번에 끝낸 것은 **세 번째뿐**이다.

| 이슈가 요구한 것 | 이번 결과 | 막은 것 |
| --- | --- | --- |
| PDF 3개의 헤더 판정 1회 | **하지 않음** | `GEMINI_API_KEY`와 단가 두 값이 `.env`에 비어 있다 |
| 16개 원본의 `confirmed_by` | **하지 않음** | 폴백 정책이 요구하는 사람 확인이며 담당자의 몫이다 |
| 미해결 원본의 후보 수 | **했다** | — |
| `data/gwangju/` 재생성 | **하지 않음**(2026-09-13 사용자 결정) | 위 둘이 갖춰진 뒤에 한다 |

사용자 결정(2026-09-13): **키 없이 재생성하지 않는다.** 지금 재생성하면 PDF 3개는 그대로
미해결이고 +13 레코드가 들어오지 않아, 키가 생긴 뒤 재생성을 한 번 더 해야 한다.
`confirmed_by` 16줄은 담당자가 직접 원본을 열어 채운다.

그래서 이 기록이 담는 실측은 모두 **임시 data-root 사본**에서 돌린 것이고
커밋된 `data/gwangju/`는 건드리지 않았다.

## 고친 것 — 검증에 실패한 매핑을 `parse`까지 넘긴다

폴백 정책: "원본별 후보 수와 미해결 수를 알면 기록하고, 후보 수 자체를 모르면 `알 수 없음`으로
표시한다. 이를 0건 손실로 보고하지 않는다." 그런데 `parse.json`의 미해결 원본은
`SourceReport.candidates`가 전부 `null`이었다. `headermap`이 첫 실패에서 그 원본을 놓아
버려 `parse`에 후보를 셀 근거가 남지 않았기 때문이다.

- `HeaderMapOutput`에 `unresolved_mappings`를 둔다. 미해결 원본의 **표마다 얻은 헤더 매핑**이며
  검증에 실패한 것도, 같은 원본의 다른 표가 통과시킨 것도 함께 싣는다. `mappings`와 달리 레코드를
  내지 않는다.
- `headermap`은 표 하나가 실패해도 **남은 표를 끝까지 판정한다.** 원본의 분모는 표 하나가 아니라
  원본 전체이므로, 첫 실패에서 멈추면 여러 시트짜리 원본의 후보 수를 알 수 없다. 원본의 사유는
  예전처럼 **첫 실패**의 것이다.
- `parse`는 그 매핑으로 후보만 세고 분모에서 뺀 행의 위치·종류도 남긴다. **표 하나라도 매핑이
  없거나 후보가 0건이면 그 원본의 후보 수는 `알 수 없음`이다** — 쓰지 않기로 한 판정의 0건은
  집행 없음의 증거가 아니다(`layout=none`도 같다).
- 계약이 바뀌었으므로 `headermap` 산출물을 **v2**로 올렸다. 버전을 올리지 않으면 커밋된 v1
  `headermap.json`으로 `parse`만 다시 돌렸을 때 후보 수가 조용히 전부 `null`이 된다.
  이제 `parse`가 "rerun the producing stage"로 막는다. `run`은 `headermap`을 먼저 돌리므로
  영향이 없고, CI의 사이트 빌드는 `headermap.json`을 읽지 않는다. 커밋된 산출물 사본으로 확인했다:
  `build`는 종료 코드 0이고 `dist/`를 그대로 만들며, `parse`만 따로 돌리면 종료 코드 1과
  `cause=regeneration-required`로 멈춘다.

## 실측 — 광주 원본 173개

`GEMINI_API_KEY` 없이 임시 data-root 사본에서 돌렸다(양쪽 공통, 저장소 루트 기준).

```text
uv run python -m deliciousmap headermap --city gwangju --raw-root ../deliciousmap-raw \
  --data-root <임시>/data
uv run python -m deliciousmap parse --city gwangju --raw-root ../deliciousmap-raw \
  --data-root <임시>/data
```

| 단계 | 결과 |
| --- | --- |
| headermap | 종료 코드 0, 53초. 매핑 181 · 미해결 19(`validation_failed` 16 · `model_not_configured` 3) · 미해결 원본의 매핑 20 |
| parse | 종료 코드 0, 1분 30초. 원본 173개 보고, 레코드 2,797 · 미해결 19 |

### 후보 663건이 #62의 전수 대조와 그대로 맞는다

코드가 센 16개의 후보 수가 [#62](issue-62.md)에서 사람이 원본별로 남긴
`data/manual/gwangju/sources.jsonl` 16줄과 **원본마다 정확히 일치**한다(합계 663).

| 원본 | 사유 | 후보(`parse.json`) | 분모에서 뺀 행 |
| --- | --- | --- | --- |
| 10905-1.xls | merchant_blank | 47 | 1 |
| 10909-1.xls | total_mismatch | 6 | 1 |
| 10922-1.xls | merchant_blank | 15 | 1 |
| 10929-1.xls | merchant_blank | 10 | 1 |
| 10933-1.xls | merchant_blank | 13 | 1 |
| 10938-1.xls | merchant_blank | 224 | 0 |
| 10939-1.xls | merchant_blank | 57 | 4 |
| 10956-1.xlsx | total_mismatch | 110 | 2 |
| 10960-1.xlsx | merchant_blank | 57 | 531 |
| 10977-1.xls | total_mismatch | 6 | 1 |
| 10990-1.xls | total_mismatch | 17 | 1 |
| 10991-1.xls | total_mismatch | 15 | 1 |
| 10999-1.xls | total_mismatch | 5 | 1 |
| 11000-1.xlsx | merchant_blank | 31 | 1 |
| 11015-1.xls | total_mismatch | 21 | 1 |
| 11017-1.xlsx | merchant_blank | 29 | 1 |
| **합계** | | **663** | **549** |

여러 시트짜리 두 원본도 시트를 모두 세었다. 10939-1은 sheet1 34 · sheet2 8 · sheet3 4 ·
sheet4 11이고, 10956-1은 sheet1 25 · sheet2 85다. #62가 "sheet2~sheet4 후보 23건",
"sheet2 후보 85건"이라고 적은 값과 같다.

뺀 행의 종류는 `blank` 530 · `total` 18 · `note` 1이다. 합계 행이 0개인 10938-1과 10960-1은
#62가 "합계 행 없음"이라고 적은 두 원본이고, 10960-1의 530줄은 그 시트 뒤에 붙은 빈 행이다.

### PDF 3개는 후보 수도 `알 수 없음`이다

10882-1 · 10883-1 · 10943-1은 사유가 `unsupported_format`에서 **`model_not_configured`**로
바뀐다. #62가 PDF 읽기 경로를 넣었으므로 형식은 읽혔고 헤더 판정만 남았다는 뜻이다. 판정이 없으니
매핑도 없고, 후보 수는 `null`로 남는다 — 0건으로 바꾸지 않는다.

### 레코드·예산·캐시는 그대로다

| 확인 | 결과 |
| --- | --- |
| `records.csv` | 커밋된 파일과 **바이트까지 같다**(레코드 2,797) |
| `_shared/llm-budget.jsonl` | 한 줄도 늘지 않았다. 키가 없어 호출이 없었고 누적 사용액은 **USD 0.653** 그대로다 |
| `_shared/headermap.jsonl` | 그대로. 새 판정이 없으니 서명 캐시도 늘지 않았다 |
| `gwangju/headermap-answers-v1.jsonl` | 그대로 |

"표 하나가 실패해도 남은 표를 끝까지 판정한다"는 변경은 원리상 그 표들에 모델 호출을 부를 수
있다. 이번 실측은 키가 없어 애초에 호출이 불가능했으므로 그것만으로 "호출이 늘지 않는다"고 할 수
없다. 다만 **이 변경이 새로 판정한 표 다섯(10939-1의 sheet2~sheet4, 10956-1의 sheet2)이 모두
공통 서명 캐시로 덮였다** — 키가 있었더라도 이 다섯에는 호출이 필요 없었다는 뜻이다. 캐시가 덮지
못하는 표에는 호출이 생기며, 그때는 공통 USD 15 예산이 그대로 집행을 막는다. 키가 준비된 재생성
실행에서는 이 몫까지 포함해 호출 수와 비용을 센다.

산출물 크기는 `headermap.json` 74.4 → 80.7KB, `parse.json` 45.6 → 56.8KB다. ADR-0001의 파일당
20MB 상한과 무관하다.

## 구현과 TDD

실패 → 최소 구현 → 통과를 확인한 동작(`tests/test_parse_cli.py`):

- 검증에 실패한 원본이 후보 수를 싣는다: 최초 `null`이었다.
- 한 시트가 실패해도 통과한 시트의 후보까지 함께 센다(`unresolved_mappings`에 두 시트가 온다).
- 표 하나라도 매핑이 없으면 후보 수는 `알 수 없음`이다: 카드형 답을 받은 시트가 남은 경우.
- 판정을 받지 못한 원본(`model_not_configured`)의 후보 수는 `null`로 남는다.
- 분모에서 뺀 행의 위치·종류를 미해결 원본에도 남긴다.
- 쓰지 않기로 한 판정이 후보를 하나도 찾지 못하면 0건이 아니라 `알 수 없음`이다: 열이 밀려
  지출 행의 금액 칸이 비고 합계 행만 읽히는 매핑으로 확인했다.

## 자동 검사

| 검사 | 결과 |
| --- | --- |
| `uv run ruff check .` | 통과 |
| `uv run ruff format --check .` | 통과, 105개 파일 |
| `uv run mypy src` | 통과, 44개 소스 파일 |
| `uv run pytest` | 457 passed |
| `git diff --check` | 통과 |
| gitleaks 8.30.1 (커밋 훅, 스테이지) | no leaks found |

## 알고도 하지 않은 것

- **`parse` 자신이 미해결로 돌리는 경로에는 후보 수를 달지 않았다.** `parse`가 직접 잡는
  `validation_failed` · `unsupported_format` · `unreadable`은 `headermap`이 통과시킨 원본을
  `parse`가 다시 읽다 실패한 경우라 원본 파일이 그 사이에 바뀌지 않는 한 일어나지 않는다.
  광주 19개는 모두 `headermap`에서 왔다. 실제로 일어나는 경로가 생기면 그때 같은 셈을 붙인다.
- **미해결 16개는 그대로 16개다.** 폴백 정책의 "제출 전 미해결 0개"는 이 16개를 어떻게 할지
  정해야 채워지며, 정책을 바꾸는 일이므로 [#66](https://github.com/snowjaewon/OfficialDeliciousMap/issues/66)의
  제외 범위대로 별도로 제안한다.

## 남은 일 — 이슈 #66의 나머지

1. 담당자가 16개 원본을 열어 대조하고 `data/manual/gwangju/sources.jsonl`의 `confirmed_by`를
   채운다. 결함 행 위치와 근거는 줄마다 이미 있다.
2. `GEMINI_API_KEY`·`GEMINI_INPUT_USD_PER_MTOK`·`GEMINI_OUTPUT_USD_PER_MTOK`가 준비된 PC에서
   `headermap`을 돌려 PDF 헤더 판정 1회를 채운다. 호출 수와 누적 비용을 적는다.
3. 그 뒤 `data/gwangju/` 전 단계를 다시 만든다. 레코드 수는 PDF의 +13과 이미 들어간 재게시
   병합을 함께 받으므로 **미리 확정하지 않고 그 실행에서 재고 차이의 출처를 적는다.**
   이 재생성이 커밋된 v1 `headermap.json`과 새 계약의 어긋남도 함께 푼다.
