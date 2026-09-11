# 사람 확인에 따른 상호 복원

[이슈 #38](https://github.com/snowjaewon/OfficialDeliciousMap/issues/38)의 실행 계약이다.
확정 정책은 [부모 스펙 #36](https://github.com/snowjaewon/OfficialDeliciousMap/issues/36)과
[복원 기준 #30](https://github.com/snowjaewon/OfficialDeliciousMap/issues/30#issuecomment-5614946240)을 따른다.
[후보 비교 기준 #41](https://github.com/snowjaewon/OfficialDeliciousMap/issues/41)의 실행 계약도 이 문서에 있다.
업소·좌표 판정은 [지오코딩](geocoding.md)에 있다. 사람 확인만으로 복원하는 기본 경로에는
외부 HTTP·LLM·과금이 없다. 담당자가 지정한 건에만 아래의 후보 비교가 붙는다.

상호 복원은 원본에서 잘린 상호를 근거 자료와 대조해 동일 업소의 전체 상호로 확인하는 일이다.
후보 수집이나 검색 순위가 아니라 사람의 확인만 복원명을 확정한다.

## 검토 입력

`data/manual/<city>/restore.jsonl`은 한 줄당 `NameRestoration`이다. 도시 파일이며
`--org` 실행은 그 기관에 해당하는 줄만 적용한다. 파일이 없으면 복원 확인이 없는 것과 같다.

```json
{
  "schema_version": 1,
  "scope": {
    "city": "seoul", "merchant": "같은 식당",
    "organization": null, "source_hash": null, "record_id": "r1"
  },
  "restored_merchant": "같은 식당 전체 이름",
  "evidence": "기관의 다른 공개자료에서 같은 날짜·금액 항목의 전체 상호를 확인",
  "references": [{
    "kind": "disclosure",
    "source": "https://example.invalid/disclosure/2026-01",
    "detail": "2026-01-02 총무과 업무추진비 명세의 같은 금액 항목 상호"
  }]
}
```

- `scope`: 근거가 뒷받침하는 적용 범위다. `city`와 원본 표기 `merchant`는 필수이고
  `organization`·`source_hash`·`record_id`는 범위를 좁히는 선택 항목이다.
  선언한 항목이 모두 맞는 레코드에만 적용하며 같은 표기의 다른 업소로 번지지 않는다.
  같은 `scope`를 두 줄에 적으면 오류다. 다른 도시의 줄은 그 도시 파일에 둔다.
- `restored_merchant`: 사람이 확정한 전체 상호. 원본 표기가 이미 완전하면 같은 값을 적어 확인한다.
  확인 전의 복원 후보는 이 파일에 넣지 않는다. 후보는 조회 결과 그대로 `GeocodeResult.lookup`에
  남으며 복원명으로 쓰지 않는다.
- `evidence`: 무엇을 보고 동일 업소로 판단했는지 적는다.
- `references`: 검토에 쓴 자료의 종류·출처·근거다. `kind`는 `disclosure`(기관의 다른 공개자료),
  `license`(인허가 자료), `place`(지역검색 후보), `other`다. `detail`은 500자 이내로,
  동일성 판단에 필요한 부분만 적고 원본 전체나 개인정보·비밀값을 옮기지 않는다.

네 가지 사람 검토 입력은 의미가 다르므로 파일을 나눈다.

| 파일 | 의미 | 결과 |
| --- | --- | --- |
| `classify.jsonl` | 사람 보정 | 식당 포함·제외 판정 |
| `restore.jsonl` | 상호 복원 | 확정 복원명. 원본 표기는 그대로 |
| `geocode.jsonl` | 업소 확인 | 후보 하나를 동일 업소로 확정 |
| `compare.jsonl` | 후보 비교 지정 | 모델에 보낼 미해결 건의 지정. 확정은 아니다 |

## 적용과 실행

기존 공개 CLI 실행에 그대로 반영되며 새 명령이나 수정 화면은 없다.
저장소 루트에서 PowerShell·Git Bash 공통:

```text
uv run python -m deliciousmap classify --city seoul
uv run python -m deliciousmap geocode --city seoul
uv run python -m deliciousmap closure --city seoul
uv run python -m deliciousmap build --city seoul
```

- classify: 확정 복원명이 있으면 그 이름을 판별 대상으로 전달한다. 레코드의 원본 표기는 바뀌지 않고
  같은 원본을 다시 파싱하지 않는다. 복원명은 공통 LLM 캐시의 다른 키이므로 기존 항목을 덮어쓰지 않는다.
- geocode: 근거의 상호를 원본 표기 대신 확정 복원명과 대조한다. 지점·주소 근거와 후보 특정 기준은
  그대로이며 복원만으로 업소가 확정되지는 않는다. 복원명이 확정돼도 좌표 근거가 없으면
  `missing_coordinates`로 남고 마커는 보류한다. 복원 결과는 `GeocodeResult.restoration`에 보존한다.
- closure·build: 확정된 업소만 마커가 되며 미확정 레코드는 장부에 남는다.

적용한 복원이 있으면 성공 결과의 `evidence`는 `restored-name-branch-address-agreement`다.
업소 확인까지 있으면 그 확인의 `evidence`를 쓴다.

## 충돌과 재실행

한 레코드에 적용되는 줄이 여럿이고 확정 복원명이 서로 다르면 임의로 고르지 않는다.
확정 복원명이 같아도 어느 줄이 더 좁은지 정할 수 없으면 마찬가지다. 한 줄이 다른 모든 줄의
선언 항목을 포함할 때만 그 줄의 근거·범위를 결과에 남긴다. 예를 들어 도시 범위 줄과
같은 레코드 범위 줄은 뒤쪽이 좁으므로 충돌이 아니지만, 기관으로만 좁힌 줄과 원본으로만 좁힌 줄은
어느 쪽도 더 좁지 않으므로 충돌이다.

같은 레코드의 복원명과 업소 확인의 상호가 다를 때도 충돌이다. 판단 보류·비식당 레코드의
어긋난 확인도 마커 대상이 아니라는 이유로 넘기지 않는다. 모든 경우에 산출물을 쓰지 않고
`cause=conflicting-review`와 종료 1로 알린다. 담당자가 범위를 좁히거나 내용을 고쳐야 한다.

`restore.jsonl`의 파일 해시와 `restoration.POLICY_VERSION`은 classify·geocode의 의존성에 들어간다.
확인을 추가·수정·철회하거나 범위를 바꾸면 이전 판정을 그대로 재사용하지 않고 classify부터 다시 실행한다.
같은 실행 범위의 다른 업소 결과는 그대로 유지되며 `geocode-history-v2.jsonl`의 이전 이력은 남는다.

geocode·closure·build 산출물은 조회 요청 기록까지 담은 v4이며, `markers.json`도 그 판정을
그대로 싣기 때문에 v4다. 이전 버전은 `regeneration-required`로 거부하고
`history/<stage>-v<version>-<content-hash>.json`에 보존한 뒤 재실행한다. 후보 비교 제안은
이 산출물에 실리지 않으므로 제안이 늘어도 산출물 버전은 바뀌지 않는다.

## 지정 건의 후보 비교

자료 대조와 사람 검토로도 상호를 확정하지 못한 건 중 담당자가 지정한 건만 모델에 보낸다.
결과는 사람 검토용 **제안**이며 복원명도 좌표도 확정하지 않는다. 확정은 위의 `restore.jsonl` 경로뿐이다.
좌표 선택에는 모델을 쓰지 않는다.

### 지정 입력

`data/manual/<city>/compare.jsonl`은 한 줄당 `ComparisonRequest`다. `scope`는 업소 확인과 같은
도시·기관·레코드 ID·원본 해시이며 같은 scope의 중복 지정은 오류다.

```json
{
  "schema_version": 1,
  "scope": {
    "city": "seoul", "organization": "test-org", "record_id": "r1",
    "source_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "evidence": "네이버·인허가 대조와 사람 검토로 해결하지 못해 후보 비교를 지정"
}
```

지정하지 않은 건에는 호출이 0회다. 비교 대상은 상호를 확정하지 못한 판정(`unconfirmed_name`,
`no_match`)뿐이다. 이미 확정 복원명·업소 확인이 있거나 판정이 성공한 건, 주소·지점·좌표·조회
문제로 미확정인 건, 후보가 없는 건은 호출하지 않고 `not_unresolved`·`no_candidates`로 남긴다.
모델 키를 구성하지 않으면 비교 자체를 수행하지 않으므로 제안 파일에 줄이 생기지 않는다.
그때도 지정 건은 geocode 판정에 미확정으로 그대로 남는다.

### 보내는 것과 보내지 않는 것

| 경계 | 내용 |
| --- | --- |
| 키·모델 | `.env`의 `GEMINI_API_KEY`·`GEMINI_MODEL`. 키가 없으면 비교를 구성하지 않는다 |
| 단가 | `.env`의 `GEMINI_INPUT_USD_PER_MTOK`·`GEMINI_OUTPUT_USD_PER_MTOK`(1M 토큰당 USD). 확인할 수 없으면 종료 코드 2 |
| 입력 | 원본 표기와 코드로 추린 후보 상호·지점·주소·출처, 그리고 동일성 판단에 필요한 근거뿐 |
| 요청 | `generateContent` 한 번. 구조화 출력과 `thinkingLevel=minimal`, 출력 토큰 상한을 건다 |
| 금지 | 원본 전체·HTML 전체의 반복 입력, 도구·검색 연동, 자동 웹 탐색, 좌표 선택 |
| 오류 | 통신 실패는 `unavailable`, 해석 불가는 `invalid_response`, 잘린 응답은 `incomplete_response` |

모델은 제시한 후보 하나를 가리키고 사유를 적어야 한다. 후보에 없는 상호나 출처를 답하거나
사유가 비면 `ungrounded_response`로 남기고 제안을 만들지 않는다. 응답 원문·인증키·사용량 원문은
산출물에 남기지 않는다.

### 제안 보존과 재사용

제안은 `data/<city>/restore-proposal-v1.jsonl`에 요청 키·revision의 추가형 이력으로 쌓는다.
요청 키는 정책·모델·프롬프트 버전·지정 내용·후보·근거의 해시다. 모델·프롬프트·후보·근거가 바뀌면
키가 달라져 이전 제안을 새 입력에 그대로 쓰지 않는다. 바뀌지 않은 실행은 제안을 재사용하며
중복 유료 호출을 하지 않는다. 보류된 제안은 `--retry-failed`로만 다시 시도한다.

이 파일은 geocode의 의존성에 들어가지 않는다. 제안이 갱신돼도 사람 확인의 유효성과 기존 판정은
그대로이며, 반대로 제안만으로 판정이 바뀌지도 않는다. 제안의 `confirmed`는 언제나 `false`다.

| reason | 결과 |
| --- | --- |
| `candidate_supported` | 후보 하나를 가리킨 제안. 사람 확인 대상 |
| `not_unresolved`, `no_candidates` | 비교 대상이 아니어서 호출하지 않음 |
| `no_supported_candidate`, `ungrounded_response` | 근거 부족·근거 없는 답변 |
| `incomplete_response`, `invalid_response`, `unavailable` | 잘린 응답·해석 불가·통신 실패 |
| `oversized_request`, `budget_exhausted`, `unknown_prior_usage`, `concurrent_execution` | 호출 보류 |

## 공통 LLM 예산

한도·공유 범위·기간·초기화 금지는 [폴백 정책](specs/header-mapping-fallback.md)이 단일 출처다.
여기에는 그 정책을 집행하는 방법만 적는다. 집행은 `budget` 모듈 한 곳이 소유하며 호출자는
잔액을 따로 계산하거나 장부를 직접 고치지 않는다.

`data/_shared/llm-budget.jsonl`은 한 줄당 `LedgerEntry`인 추가형 장부다. 집행 순서를 그대로 남기며
같은 요청의 같은 항목을 다시 쓰지 않는다.

| kind | 의미 |
| --- | --- |
| `prior_usage` | 제공자의 사용량·청구 기록으로 확인한 기존 사용액. 두 개발자의 프로토타입·재시도·과금된 실패를 포함한다 |
| `reservation` | 호출 전에 잡는 요청 하나의 비용 상한 |
| `settlement` | 응답의 실제 사용량으로 정산한 금액 |

누적액은 `prior_usage` + 정산액 + 아직 정산되지 않은 예약액이다. 여기에 새 요청의 상한을 더해
한도를 넘으면 호출하지 않는다. `prior_usage` 줄이 없으면 남은 잔액을 가정하지 않고
`unknown_prior_usage`로 보류한다. 사용량을 확인하지 못한 호출은 예약을 그대로 남긴다.

요청 하나의 상한은 실제로 보내는 요청 본문 전체의 문자 수를 입력 토큰 상한으로, 요청에 건 출력
토큰 상한을 출력으로 잡아 적용 단가로 계산한다. 과금 항목은 제공자 정의를 따르며 합계
필드(`totalTokenCount`)를 다시 더하지 않는다. 사고 토큰은 출력 단가로 센다.

예약부터 호출·정산까지는 `data/_shared/llm-budget.lock`을 잡고 직렬화한다. 다른 실행이 잡고 있으면
호출하지 않고 `concurrent_execution`으로 남긴다. 두 개발자의 공유는 장부 파일의 커밋·동기화로
이뤄지며, 같은 파일 시스템 밖의 동시 실행까지 잠금이 막지는 못한다. 실행이 비정상 종료해 잠금이
남으면 담당자가 지운다. 예산이 부족하거나 모델이 응답하지 않아도 사람 검토 경로는 그대로 동작한다.

모델 제공자를 바꿀 때 고치는 범위는 `gemini` 어댑터와 구성·적용 단가·과금 항목 해석뿐이다.
업소 판정·사람 확정·공통 한도 규칙은 그대로 둔다. 쓰지 않는 모델용 어댑터는 만들지 않는다.

## 경계

`restoration.py`는 적용 범위 판단만 하는 순수 모듈이다. 파일 탐색·조회·저장·예산 집행을 하지 않으며
직렬화는 `storage`가 소유한다. `comparison.py`는 지정·미해결 판단과 제안 보존만 하고 업소 판정·사람
확정·잔액 계산을 하지 않는다. `budget.py`는 예약·정산·한도만 소유하고 모델을 호출하지 않으며,
`gemini.py`는 요청·응답·사용량 해석만 한다.

별도 검토 화면, 사용자 대면 AI, 실제 수집기·전체 웹사이트·배포는 이 범위가 아니다.
합성 응답으로만 검증했고 실제 키로 유료 호출을 한 건도 하지 않았다. 남은 확인은
[이슈 #41 검증](validation/issue-41.md)의 제한을 읽는다. 합성 테스트 통과는 실제 상호 복원 품질의
검증이 아니다.
