# 로컬 근거 기반 지오코딩

[이슈 #37](https://github.com/snowjaewon/OfficialDeliciousMap/issues/37)의 실행 계약이다.
판정 정책은 [부모 스펙 #36](https://github.com/snowjaewon/OfficialDeliciousMap/issues/36)과
[확정 정책 #33](https://github.com/snowjaewon/OfficialDeliciousMap/issues/33#issuecomment-5615154736)을 따른다.
정제 자료를 준비한 담당자가 사용하는 경로이며 외부 HTTP·LLM·과금은 없다.

## 실행

저장소 루트에서 PowerShell·Git Bash 공통:

```text
uv run python -m deliciousmap geocode --city seoul
uv run python -m deliciousmap closure --city seoul
uv run python -m deliciousmap build --city seoul
```

선행 `data/seoul/records.csv`, `parse.json`, `classify.json`은 기존 단계 계약에 맞게 준비한다.
레코드의 기관은 도시 레지스트리에 등록되어 있어야 한다. 현재 실제 수집·분류기는 미구현이다.
`--org <기관>`을 쓰면 입력·산출물은 `data/<city>/orgs/<org>/`에 둔다.
입력이 누락되거나 잘못되면 안전한 원인 코드와 종료 1을 반환한다.

## 후보 파일

같은 디렉터리의 `geocode-input.json`은 `CandidateFile` 계약이다. 아래는 합성 예시이며
실제 원본이나 업소의 품질 검증 결과가 아니다. scope의 해시·ID는 선행 레코드와 일치해야 한다.

```json
{
  "schema_version": 1,
  "lookups": [{
    "scope": {
      "city": "seoul", "organization": "test-org", "record_id": "r1",
      "source_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    },
    "status": "ok",
    "error": null,
    "facts": [{
      "merchant": "같은 식당", "branch": "부산점", "address": "부산 합성로 10",
      "source": "https://example.invalid/disclosure/1"
    }],
    "candidates": [{
      "source": {
        "provider": "local", "source_id": "place-1",
        "reference": "https://example.invalid/places/1"
      },
      "merchant": "같은 식당", "branch": "부산점", "address": "부산 합성로 10",
      "latitude": 35.1, "longitude": 129.1
    }]
  }]
}
```

- `scope`: 도시·기관·레코드 ID·원본 해시 모두 필수. 다른 범위로 전파하지 않는다.
- `facts`: 원본 또는 확인 가능한 공개자료에서 해당 레코드와 연결한 상호·지점·주소와 출처.
  후보 주소를 원본 주소로 복사하지 않는다. 후보 출처만을 사실 출처로 반복하면 자동 채택하지 않는다.
  담당자는 실제 출처의 독립성과 레코드와의 관계를 검토해야 한다. URL 문자열 비교가 그 검토를 대체하지 않는다.
- `candidates`: 정제된 후보만 넣는다. 후보 순위는 의미가 없고, 공급자 응답 원문·HTML·비밀값은 넣지 않는다.
- `branch: null`은 지점 미확인, `branch: ""`는 지점이 없는 업소임을 명시적으로 확인한 경우다.
  주소 부재는 `address: null`이다. 좌표는 WGS84 위도/경도의 유한한 숫자이며 누락은 `null`이다.
- `provider`: 현재 필요한 `local`, `naver`, `license`만 표현한다. 네이버·인허가 HTTP 연결은 없다.
  각 조회 구현이 상호 표기·주소 형식과 좌표계를 정제해 이 계약에 맞춰 공급한다.
- `status: "ok", candidates: []`는 정상 조회의 후보 없음이다. 조회 실패는 `status: "error"`와
  `error: "unavailable" | "invalid_response" | "not_supplied"`로 구분한다.
  오류 때 남아 있는 일부 후보가 있어도 자동 채택하지 않는다. 파일에서 빠진 식당 레코드는 `not_supplied`로 저장한다.

## 판정과 식별자

자동 채택은 독립 근거의 상호·지점·주소가 일치하고 후보 하나를 특정할 때만 한다.
비교 정규화는 Unicode NFC·대소문자·공백 정리에 한정하며, 유사 검색·주소 추정은 하지 않는다.
잘린 원본과 전체 상호가 다르면 사람 확인 전까지 복원명을 확정하지 않는다.
같은 업소의 좌표 근거가 레코드 사이에서 충돌해도 모두 보류한다.

| 식별자 | 용도 |
| --- | --- |
| `record_id` + `scope` | 지출 1건과 기관·도시·원본의 맥락. 원본 `merchant`는 바꾸지 않음 |
| `CandidateSource` | 공급자·출처 내 ID·근거 위치. 확인된 업소 ID와 별개 |
| `business_id` | 확인한 전체 상호·명시된 지점·주소의 정규화 조합을 해시. 마커·폐업 결과 연결 |
| `lookup_key` | 레코드·조회 결과·사람 확인·의존성·정책 해시. 동명이 업소 간 캐시 전파 방지 |

`business_id`는 공급자 ID나 표시명 하나로 만들지 않는다. 미확정 결과에는 업소 ID와
확정 상호·좌표를 넣지 않는다. 주소·정식 이름이 바뀌면 다른 ID가 되며 별칭·이전 주소 병합은 하지 않는다.
같은 이름·지점·주소에 대해 별도 업소의 가능성을 구분할 근거가 없다면 후보를 임의로 하나로 줄이지 않는다.

`GeocodeResult`는 원본 상호, 레코드 ID, 조회·근거·범위 전체, 사람 확인, 의존성 키,
`status`, `reason`, 확인된 업소·상호·좌표를 저장한다.

| reason | 결과 |
| --- | --- |
| `matched`, `human_confirmed` | 근거 일치 또는 범위를 지정한 사람 확인으로 좌표 채택 |
| `missing_address`, `unknown_branch`, `insufficient_evidence` | 주소·지점·독립 근거 부족 |
| `conflicting_evidence`, `ambiguous` | 근거 충돌 또는 특정 불가 |
| `unconfirmed_name`, `no_match`, `no_candidates` | 전체 상호 미확정·일치 후보 없음·정상 조회 0건 |
| `missing_coordinates` | 좌표 미확정 |
| `lookup_error` | 조회 오류. 저장 후 CLI 종료 1, `cause=lookup-failed` |

미확정은 식당 분류의 비식당·판단 보류와 다르다. 모두 장부에 보존하며 마커만 보류한다.
`closure`는 인허가 미연결 상태를 `unknown`으로 명시한다. 폐업 확정 결과를 공급하는 후속 구현도
`ClosureResult.business_id`를 사용해야 하며 폐업 업소를 마커에서 삭제하지 않는다.
`build`는 확인된 업소별 레코드 ID 묶음·좌표·폐업 결과와 전체 레코드를 `markers.json`에 보존한다.
기관 도시 밖 식당도 확인된 실제 좌표를 쓰고 원래 도시·기관을 유지한다.

## 사람 확인

선택적 `data/manual/<city>/geocode.jsonl`은 한 줄당 `IdentityConfirmation`이다.
기존 식당 포함·제외용 `classify.jsonl`과 의미가 다르다. 각 항목에는 후보 파일과 같은
`scope`, 선택한 후보의 `candidate_source`, 확인한 `merchant`, `branch`, `address`,
사람이 검토한 출처·확인 내용을 적는 `evidence`가 필요하다.
같은 scope의 중복 확인은 오류다. 다른 레코드·원본·기관의 확인은 적용하지 않는다.
확인 값이 후보와 일치하지 않거나 조회 오류·좌표 부재가 남으면 성공으로 바꾸지 않는다.
원본이 부족하거나 충돌한 경우 사람 확인은 보충 자료를 검토한 결과로 사용한다.

## 의존성·이력·교체 경계

`identity.decide_identity`는 레코드·후보·근거·확인을 받아 판정만 반환하는 순수 함수다.
파일 직렬화·조회·예산·CLI를 직접 실행하지 않는다. `reconcile_coordinates`도 판정 결과만 다룬다.
조회 구현은 `CandidateLookup`을 공급하고, 내부 판정 구현은 같은 `GeocodeResult` 계약을 반환한다.
따라서 새 공급자 연동이나 판정 구현 교체는 저장·마커·후속 CLI 형식을 바꾸지 않는다.
범용 플러그인 등록 시스템은 없다. 정책 의미가 바뀌면 `identity.POLICY_VERSION`을 올린다.

재사용 키에는 선행 레코드·분류, 후보 파일, 사람 확인 파일, 정책 버전을 포함한다.
같은 실행 범위의 입력 하나가 바뀌면 그 범위의 캐시를 보수적으로 무효화한다.
변경 없는 성공·미확정은 재사용하며 `--retry-failed`는 미확정을 다시 판정한다.
변경된 결과는 새 키에 저장하고 명시적 실패 재시도는 같은 키의 새 revision에 남긴다.
`geocode-history-v2.jsonl`은 키·revision 순으로 정렬한 추가형 이력이다. 단일 작성자만 지원한다.

geocode·closure·build 산출물은 envelope v2다. 이전 v1은 `regeneration-required`로 거부하고
선행 정제 자료와 새 후보 입력을 준비해 세 단계를 재실행한다. 교체 전 기존 파일은
`history/<stage>-v<version>-<content-hash>.json`에 보존한다.
옛 상호 중심 `geocode-history.jsonl`은 읽거나 수정하지 않는다.

정적 빌드에는 앞서 열거한 정제 파일과 사용한 사람 보정·확인 파일을 함께 보관한다.
현재 정책 또는 입력과 일치하지 않는 geocode를 가진 빌드는 실패하며 기존 출력 파일을 유지한다.
원본·수집 메타데이터·API 키는 필요 없다. 산출물 파일은 각각 20MB 이내로 나누며
누적 이력이 상한을 넘으면 담당자가 범위를 분할해야 한다. 자동 이력 삭제는 하지 않는다.
합성 테스트와 중간 빌드 성공은 실제 수집·동일 업소 품질·제출 전 미해결 0건 검증을 대신하지 않는다.
