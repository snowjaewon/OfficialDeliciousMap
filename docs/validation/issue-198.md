# 기장군 HTML 표 게시판 실측 (#198)

[#198](https://github.com/snowjaewon/OfficialDeliciousMap/issues/198)이 구현 전에 재라고 한 세 가지를
2026-09-17에 쟀다. 대상은 부산 기장군 `busan-gijang/expenses`
(`https://www.gijang.go.kr/board/list.gijang?boardId=BBS_0000147&menuCd=DOM_000000101002014000&paging=ok`)이며
요청은 프로젝트 UA로 보냈다. 원본 응답은 커밋하지 않는다(ADR-0001).

## 1. 행 수 조건 — `listRow`만으로는 열리지 않는다

`listRow`를 혼자 보내면 게시판이 무시하고 열 줄을 준다. **`listCel=1`을 함께 보내야** 조건이 열린다.

| 조회 조건 | 응답 크기 | 집행 줄 | 목록이 밝힌 쪽 |
| --- | --- | --- | --- |
| (없음) | 123,138 B | 10 | 330 |
| `listRow=1000` | 123,125 B | 10 | 330 |
| `rowSize=1000` · `pageSize=1000` · `listSize=1000` | 약 123,130 B | 10 | 330 |
| `listCel=1&listRow=50` | 158,214 B | 50 | 66 |
| `listCel=1&listRow=1000` | 983,665 B | 1,000 | 4 |
| `listCel=1&listRow=3500` | 2,959,758 B | 3,297 | **1** |
| `listCel=1&listRow=4000` (이 구현이 보내는 값) | 2,959,657 B | 3,297 | **1** |

전량은 3,297줄이고 목록이 스스로 `총게시물 <b>3297</b>건 ｜ 페이지 : 1/1`로 밝힌다. `listRow=3500`
한 응답에 전량이 담기므로 원본 단위는 **게시판 전량 한 쪽**이다.

마지막 줄은 아래 4절의 `fetch` 실행이 실제로 보낸 값이며, 받아 둔 원본의 크기다. 전량보다
넉넉한 값을 보내도 게시판은 있는 만큼만 준다.

그 한 응답을 받는 데 **116.4초**가 걸렸다(`listRow=1000`은 40.0초). 게시판 공통 기다림
(`boards.REQUEST_TIMEOUT` 30초) 안에 오지 않아 이 호스트만 `boards.HOST_TIMEOUTS`로 300초를 둔다.
쪽을 나눠 짧게 만드는 쪽은 고르지 않는다 — 새 줄이 위에 쌓여 둘째 쪽부터 내용이 밀린다(ADR-0008).

## 2. 헤더 10열 — 이슈가 적은 글자와 같다

받은 쪽에는 `<table>`이 하나뿐이고(`table1`) 첫 행이 다음과 같다.

```text
부서 · 사용자 · 사용일자(일시) · 사용장소(가맹점) · 사용목적(내역) · 사용금액(원) · 대상인원(명) · 사용방법 · 연도 · 월
```

이슈가 적은 열 이름과 글자까지 같아 선언을 그대로 등록했다(`registry/busan.py`의 `GIJANG_TABLE`).
헤더가 `(원)`이라 금액 배수는 1이다.

## 3. 사용일자를 읽지 못하는 줄 — 3,297줄 중 67줄

`extract.parse_spent_on`에 사용일자 칸(2열)을 그대로 넣어 셌다.

| 값 | 줄 수 |
| --- | --- |
| (빈 칸) | 49 |
| `4월 9일` | 2 |
| `10.22.` · `7.3.` · `5.11.` · `4.25.` · `4.11.` | 각 1 |
| `6.27.(금)` · `5.20.(화)` · `2.26.(수)` · `3. 25. (화)` | 각 1 |
| `202503222` · `2024.1021.` · `201-12-28` | 각 1 |
| `5월 9일` · `4월 22일` · `4월 7일` · `3월 23일` | 각 1 |
| **합계** | **67** |

읽힌 3,230줄 가운데 대상 기간(2026년 상반기)은 422줄이다. 연도 분포는 2018년 5 · 2019년 10 ·
2020년 16 · 2021년 116 · 2022년 301 · 2023년 617 · 2024년 872 · 2025년 753 · 2026년 540이다.

67줄 가운데 빈 칸 49줄은 사용일자만 빈 것이 아니라 **줄 전체가 빈 행**이라, 지출 1건이 아닌
행으로 갈려(`blank`) 후보에서도 빠진다. 지출 후보는 3,297 − 49 = **3,248줄**이고, 집행일을 읽지
못해 이번 구현이 행 단위로 빼는 것은 나머지 **18줄**이다.

이번 이슈는 파서를 넓히지 않는다(#198 Out of scope). 그 18줄은 레코드가 되지 않고 자리와 사유가
parse 산출물의 `excluded`에 `table1:R<행> spent_on`으로 남으며, 지출 후보 수(분모)에는 그대로 남는다.

## 4. 이 구현으로 돌린 결과 — 원본은 받았고 레코드는 아직 0건이다

2026-09-17에 세 단계를 실제로 돌렸다(`data/busan/orgs/busan-gijang/`).

- `fetch`: `.html` 원본 1건(2,959,657 B, `container=html`), `empty_reason` 없음,
  `uncollected_postings=0`.
- `headermap`: 모델도 캐시도 부르지 않고 선언 매핑만 썼다(`declared=true`, `mappings`는 비고
  `unresolved_mappings`에 그 매핑이 남는다).
- `parse`: `candidates=3248` · `records=0` · `status=unresolved` ·
  `reason=validation_failed` · `detail=table1:R365 merchant`.

미해결로 끝난 원본의 `excluded`에는 빈 행 49줄만 있고 `spent_on` 줄은 없다. 미해결 원본의 분모는
값을 읽지 않고 행의 종류로만 세므로(`_denominator`) 행 하나가 왜 레코드가 되지 못했는지는 그
경로가 내지 않는다 — 이 게시판의 `spent_on` 제외 18줄은 원본이 통과해야 장부에 자리로 남는다.
지금 장부가 밝히는 것은 후보 3,248줄과 원본 전체가 걸린 사유 하나다.

레코드가 0건인 것은 집행일 때문이 아니다. 후보 3,248줄을 한 줄씩 읽으면 이렇게 갈린다.

| 갈래 | 줄 수 |
| --- | --- |
| 값이 다 읽힌 줄 | 3,219 (그중 대상 기간 421) |
| 집행일을 읽지 못한 줄 → 이번 구현이 행 단위로 뺀다 | 18 |
| 사용장소가 빈 줄 → 원본 전체 `validation_failed` | 5 |
| 금액 칸에 숫자 대신 `원`을 적은 줄 → 원본 전체 `validation_failed` | 6 |

뒤의 11줄은 원본 자체의 결함이다(`R365` 몽골 방문단 환송연·`R2372`·`R2844`·`R2849` 격려금 지급은
사용장소가 비어 있고, `R3071`~ 정관읍 여섯 줄은 금액 칸이 `원`, 인원 칸이 `명`이다). 금액·상호
실패를 행 단위로 빼는 것은 #198의 범위 밖이고([Key interfaces](
https://github.com/snowjaewon/OfficialDeliciousMap/issues/198)), 폴백 정책은 이런 원본을
`data/manual/<city>/sources.jsonl`의 사람 대조(`merchant_blank`)로 보낸다. 그 대조를 마치기 전까지
이 원본은 미해결이며, 그 사유와 지출 후보 3,248줄이 장부에 남는다.

## 재현

```text
uv run python -m deliciousmap fetch --city busan --org busan-gijang
uv run python -m deliciousmap headermap --city busan --org busan-gijang
uv run python -m deliciousmap parse --city busan --org busan-gijang
```

행 수 조건과 사용일자 계수는 받은 `.html` 원본 하나를 `deliciousmap.grid.read_tables`로 읽어
`parse_spent_on`에 넣어 센 것이다.
