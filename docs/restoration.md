# 사람 확인에 따른 상호 복원

[이슈 #38](https://github.com/snowjaewon/OfficialDeliciousMap/issues/38)의 실행 계약이다.
확정 정책은 [부모 스펙 #36](https://github.com/snowjaewon/OfficialDeliciousMap/issues/36)과
[복원 기준 #30](https://github.com/snowjaewon/OfficialDeliciousMap/issues/30#issuecomment-5614946240)을 따른다.
업소·좌표 판정은 [로컬 지오코딩](geocoding.md)에 있다. 이 경로에도 외부 HTTP·LLM·과금은 없다.

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

세 가지 사람 검토 입력은 의미가 다르므로 파일을 나눈다.

| 파일 | 의미 | 결과 |
| --- | --- | --- |
| `classify.jsonl` | 사람 보정 | 식당 포함·제외 판정 |
| `restore.jsonl` | 상호 복원 | 확정 복원명. 원본 표기는 그대로 |
| `geocode.jsonl` | 업소 확인 | 후보 하나를 동일 업소로 확정 |

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

geocode·closure·build 산출물은 v3이며, `markers.json`도 복원 결과를 담은 geocode 판정을
그대로 싣기 때문에 v3다. 이전 v2는 `regeneration-required`로 거부하고
`history/<stage>-v2-<content-hash>.json`에 보존한 뒤 재실행한다.

## 경계

`restoration.py`는 적용 범위 판단만 하는 순수 모듈이다. 파일 탐색·조회·저장·예산 집행을 하지 않으며
직렬화는 `storage`가 소유한다. 이 티켓은 네이버·인허가 HTTP 연결, 담당자 지정 건의 LLM 후보 비교,
별도 검토 화면을 포함하지 않는다. 합성 테스트 통과는 실제 상호 복원 품질의 검증이 아니다.
