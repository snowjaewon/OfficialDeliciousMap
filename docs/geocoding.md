# 근거 기반 지오코딩과 후보 조회

[이슈 #37](https://github.com/snowjaewon/OfficialDeliciousMap/issues/37),
[이슈 #39](https://github.com/snowjaewon/OfficialDeliciousMap/issues/39),
[이슈 #40](https://github.com/snowjaewon/OfficialDeliciousMap/issues/40)의 실행 계약이다.
판정 정책은 [부모 스펙 #36](https://github.com/snowjaewon/OfficialDeliciousMap/issues/36)과
[확정 정책 #33](https://github.com/snowjaewon/OfficialDeliciousMap/issues/33#issuecomment-5615154736)을 따른다.
정제 자료를 준비한 담당자가 개발자 PC에서 실행하는 경로다. 외부 호출은 네이버 지역검색과
인허가 조회서비스뿐이고 LLM·과금 호출은 없다. 두 키가 모두 없으면 준비된 후보 파일만으로 동작한다.

## 실행

저장소 루트에서 PowerShell·Git Bash 공통:

```text
uv run python -m deliciousmap geocode --city seoul
uv run python -m deliciousmap closure --city seoul
uv run python -m deliciousmap build --city seoul
```

선행 `data/seoul/records.csv`, `parse.json`, `classify.json`은 기존 단계 계약에 맞게 준비한다.
레코드의 기관은 도시 레지스트리에 등록되어 있어야 한다. 실제 수집·분류는 광주광역시청만 구현했다(#51).
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
- `provider`: 현재 필요한 `local`, `naver`, `license`만 표현한다.
  각 조회 구현이 상호 표기·주소 형식과 좌표계를 정제해 이 계약에 맞춰 공급한다.
  담당자가 인허가 자료를 직접 추려 넣을 때도 `provider: "license"`의 같은 계약을 쓴다.
- `status: "ok", candidates: []`는 정상 조회의 후보 없음이다. 조회 실패는 `status: "error"`와
  `error: "unavailable" | "invalid_response" | "not_supplied"`로 구분한다.
  오류 때 남아 있는 일부 후보가 있어도 자동 채택하지 않는다. 파일에서 빠진 식당 레코드는 `not_supplied`로 저장한다.
- `queries`: 실행이 수행한 조회의 기록이다. 담당자가 적을 필요는 없고 결과에만 남는다.

## 제공자 조회

후보가 비어 있고 담당자가 조회 실패를 적어 두지도 않은 레코드만 조회한다.
근거만 적고 후보를 비워 둔 항목(`status: "ok"`, `candidates: []`)과 파일에 없는 레코드가 조회 대상이다.
담당자가 넣은 근거·후보는 그대로 두고 후보만 채운다. 담당자가 적은 조회 실패는 덮지 않는다.
구성된 제공자는 네이버·인허가 순으로 모두 조회하고, 후보는 출처(`CandidateSource`)를 달아 한 목록에 모은다.
한 제공자라도 실패하면 그 조회를 `status: "error"`로 남긴다. 성공한 제공자의 후보는 보존하되 채택하지 않는다.
`data/manual/<city>/restore.jsonl`의 확정 복원명이 있으면 그 이름으로, 없으면 원본 표기로 요청한다.
요청 맥락의 도시·기관은 질의에 넣지 않는다. 도시는 자료를 공개한 기관의 단위일 뿐이므로
기관 도시 밖 후보를 거르거나 기관 도시 안 동명이 업소로 바꾸지 않는다.

### 네이버 조회

| 경계 | 내용 |
| --- | --- |
| 키 | `.env`의 `NAVER_SEARCH_CLIENT_ID`·`NAVER_SEARCH_CLIENT_SECRET`. 둘 다 없으면 조회하지 않고, 한쪽만 있으면 종료 코드 2 |
| 요청 | NAVER API HUB 지역검색 엔드포인트에 질의어와 결과 수(현재 5)만 보낸다. 지역검색은 다음 페이지를 제공하지 않는다 |
| 해석 | 강조 태그·문자 참조를 지운 장소 이름, 도로명(없으면 지번) 주소, WGS84 정수 좌표 |
| 오류 | 통신·인증·응답 실패는 `unavailable`, 해석 불가는 `invalid_response`. 원문·상태 코드·키는 남기지 않는다 |

장소 이름의 마지막 낱말이 지점명이면 상호와 나눈다(`같은 식당 부산점` → `같은 식당` + `부산점`).
지점명이 없는 이름은 지점 없는 업소(`branch: ""`)로 본다. 그 밖의 이름은 임의로 쪼개지 않는다.
이 분리가 실제와 다르면 근거와 어긋나 미확정으로 남을 뿐 다른 업소를 채택하지는 않는다.
좌표는 위경도를 10^7배한 정수로 해석하고, 그 범위를 벗어난 값은 좌표계를 확인할 수 없으므로
`null`로 남긴다. 이때 후보는 남고 판정은 `missing_coordinates`가 된다.
어댑터는 후보 사실만 공급한다. 업소 채택 규칙은 `identity` 모듈 하나에 두며 제공자마다 복제하지 않는다.
한 항목이라도 계약으로 옮길 수 없으면 그 조회를 `invalid_response`로 남기고 일부만 조용히 버리지 않는다.

### 인허가 조회

인허가 자료는 공공데이터포털의 행정안전부 식품 조회서비스로 받는다.
localdata.go.kr은 2026-04-16 종료했으므로 옛 API는 쓰지 않는다. 원본은 저장소 밖에 두고
정제한 후보·근거·좌표만 남긴다. 근거와 절차는
[인허가 자료 조사 #5](https://github.com/snowjaewon/OfficialDeliciousMap/issues/5#issuecomment-5613253000)를 따른다.

| 경계 | 내용 |
| --- | --- |
| 키 | `.env`의 `DATA_GO_KR_KEY` 하나. 없으면 조회하지 않는다. 서비스마다 활용신청이 필요하고 디코딩 키를 쓴다 |
| 업종 | `general_restaurants`(일반음식점)·`rest_cafes`(휴게음식점)·`bakeries`(제과점영업). 카페는 휴게음식점, 빵집·떡집은 제과점에만 있다 |
| 요청 | `apis.data.go.kr/1741000/<업종>/info`에 `cond[BPLC_NM::LIKE]=<질의어>`와 `numOfRows=100`, `pageNo=1`. 한 조회가 업종마다 한 쪽씩 본다 |
| 해석 | 사업장명(`BPLC_NM`), 도로명(없으면 지번) 주소, `CRD_INFO_X/Y`를 EPSG:5174에서 WGS84로 변환한 좌표 |
| 오류 | 통신 실패와 `resultCode`가 성공이 아닌 응답은 `unavailable`, 해석 불가는 `invalid_response`. 원문·상태 코드·키는 남기지 않는다 |

한 업종이라도 실패하면 남은 업종을 조회하지 않고 그 조회 전체를 실패로 남긴다.
좌표정보는 보정계수 없는 Bessel 중부원점TM(EPSG:5174)이며 위경도는 제공하지 않는다.
`pyproj`의 EPSG 정의로 WGS84로 변환하고, 비어 있거나 숫자가 아닌 값, 원점(`0`), 변환할 수 없는 값,
변환 결과가 한반도 범위 밖인 값은 좌표계를 확인할 수 없으므로 `null`로 남긴다.
이때 후보는 남고 판정은 `missing_coordinates`가 된다. 좌표를 임의로 보정하거나 추측하지 않는다.
지점명 분리와 좌표 범위 확인은 네이버와 같은 공통 규칙(`places`)을 쓴다.
관리번호(`MNG_NO`)는 `source_id`에만 남는 인허가 자료 안의 번호이며 업소 동일성의 근거가 아니다.
영업상태·전화번호·인허가일자 같은 제공자 전용 필드는 계약으로 옮기지 않는다.
결과가 없으면 `items`가 빈 문자열·빈 목록으로, 한 건이면 `item`이 목록 없이 객체 하나로 올 수 있다.
셋 다 그대로 읽고 0건으로 숨기지 않는다.
`resultCode`의 성공 값과 공백이 든 질의어의 동작은 실제 키로 확인하지 않았다.

### 조회 캐시와 재사용

조회 결과는 `geocode-lookup-v1.jsonl`에 제공자·요청 맥락(질의어·결과 수)·해석 버전의 해시 키로
쌓는다. 제공자가 다르면 키가 달라 항목이 섞이지 않는다. 확정 업소 판정 이력인
`geocode-history-v2.jsonl`과 파일을 나누며, 캐시 적중은 조회를 아꼈다는 뜻일 뿐
동일 업소 확정이나 사람 확인이 아니다. 같은 키의 결과가 달라지면 새 revision으로
남기고, 값이 같으면 다시 쌓지 않는다. 한 레코드가 받은 조회 결과가 달라지면 그 레코드의
`lookup_key`가 달라져 그 전 판정을 재사용하지 않는다. 다른 레코드의 조회가 바뀐 것은
이 레코드의 판정을 바꾸지 않으므로 키도 바꾸지 않는다. `--retry-failed`는 실패한 조회만 다시 요청한다.
정상 조회의 후보 없음(`no_candidates`)은 실패가 아니므로 다시 요청하지 않는다.

로컬 후보 파일과 제공자 응답이 같은 후보 사실을 주면 같은 업소·좌표·마커가 나와야 한다.
공급자 응답의 전화번호·설명·순위 같은 필드는 계약에 옮기지 않는다.
합성 응답으로만 검증했고 실제 키로는 한 건도 조회하지 않았다. 남은 확인은
[이슈 #39 검증](validation/issue-39.md)과 [이슈 #40 검증](validation/issue-40.md)의 제한을 읽는다.

## 판정과 식별자

자동 채택은 독립 근거의 상호·지점·주소가 일치하고 업소 하나를 특정할 때만 한다.
한 제공자가 같은 상호·지점·주소의 후보를 여럿 주면 서로 다른 업소일 수 있으므로 `ambiguous`로 남긴다.
서로 다른 제공자가 같은 상호·지점·주소를 가리키면 근거가 겹친 것으로 보고 한 업소로 다룬다.
이때 좌표를 준 곳이 하나면 그 좌표로 보강하고, 좌표가 서로 다르면 `conflicting_evidence`로 남겨
사람이 후보 하나를 확정할 때까지 마커를 보류한다. 제공자별 좌표 오차를 허용 범위로 눙치지 않는다.
성공한 판정의 `evidence`에는 근거가 겹친 출처를 함께 적는다(`... license+naver`).
비교 정규화는 Unicode NFC·대소문자·공백 정리에 한정하며, 유사 검색·주소 추정은 하지 않는다.
잘린 원본과 전체 상호가 다르면 사람 확인 전까지 복원명을 확정하지 않는다.
확정 복원명이 있으면 원본 표기 대신 그 이름을 근거와 대조한다.
같은 업소의 좌표 근거가 레코드 사이에서 충돌해도 모두 보류한다.

| 식별자 | 용도 |
| --- | --- |
| `record_id` + `scope` | 지출 1건과 기관·도시·원본의 맥락. 원본 `merchant`는 바꾸지 않음 |
| `CandidateSource` | 공급자·출처 내 ID·근거 위치. 확인된 업소 ID와 별개이며 제공자 간 ID 비교는 하지 않음 |
| `business_id` | 확인한 전체 상호·명시된 지점·주소의 정규화 조합을 해시. 마커·폐업 결과 연결 |
| `lookup_key` | 그 레코드의 값·조회 결과·사람 확인·확정 복원명·정책 해시. 동명이 업소 간 캐시 전파 방지 |

`business_id`는 공급자 ID나 표시명 하나로 만들지 않는다. 미확정 결과에는 업소 ID와
확정 상호·좌표를 넣지 않는다. 주소·정식 이름이 바뀌면 다른 ID가 되며 별칭·이전 주소 병합은 하지 않는다.
같은 이름·지점·주소에 대해 별도 업소의 가능성을 구분할 근거가 없다면 후보를 임의로 하나로 줄이지 않는다.

`GeocodeResult`는 원본 상호, 레코드 ID, 조회·근거·범위 전체, 사람 확인, 적용한 상호 복원,
판정 정책 키(`dependency_key`), `status`, `reason`, 확인된 업소·상호·좌표를 저장한다.

| reason | 결과 |
| --- | --- |
| `matched`, `human_confirmed` | 근거 일치 또는 범위를 지정한 사람 확인으로 좌표 채택 |
| `missing_address`, `unknown_branch`, `insufficient_evidence` | 주소·지점·독립 근거 부족 |
| `conflicting_evidence`, `ambiguous` | 근거 충돌 또는 특정 불가 |
| `unconfirmed_name`, `no_match`, `no_candidates` | 전체 상호 미확정·일치 후보 없음·정상 조회 0건 |
| `missing_coordinates` | 좌표 미확정 |
| `lookup_error` | 조회 오류. 저장 후 CLI 종료 1, `cause=lookup-failed` |

사람 확인이 서로 어긋나면 저장하지 않고 종료 1, `cause=conflicting-review`로 알린다.

미확정은 식당 분류의 비식당·판단 보류와 다르다. 모두 장부에 보존하며 마커만 보류한다.
`closure`는 인허가 미연결 상태를 `unknown`으로 명시한다. 폐업 확정 결과를 공급하는 후속 구현도
`ClosureResult.business_id`를 사용해야 하며 폐업 업소를 마커에서 삭제하지 않는다.
`build`는 확인된 업소별 레코드 ID 묶음·좌표·폐업 결과와 전체 레코드를 `markers.json`에 보존한다.
기관 도시 밖 식당도 확인된 실제 좌표를 쓰고 원래 도시·기관을 유지한다.

## 사람 확인

선택적 `data/manual/<city>/geocode.jsonl`은 한 줄당 `IdentityConfirmation`이다.
식당 포함·제외용 `classify.jsonl`, 상호 복원용 `restore.jsonl`과 의미가 다르다.
확정 복원명의 형식과 적용 규칙은 [상호 복원](restoration.md)에 있다.
각 항목에는 후보 파일과 같은 `scope`, 선택한 후보의 `candidate_source`, 확인한 `merchant`,
`branch`, `address`, 사람이 검토한 출처·확인 내용을 적는 `evidence`가 필요하다.
같은 scope의 중복 확인은 오류다. 다른 레코드·원본·기관의 확인은 적용하지 않는다.
확인 값이 후보와 일치하지 않거나 조회 오류·좌표 부재가 남으면 성공으로 바꾸지 않는다.
같은 레코드의 확정 복원명과 확인한 상호가 다르면 `conflicting-review`로 알린다.
원본이 부족하거나 충돌한 경우 사람 확인은 보충 자료를 검토한 결과로 사용한다.

## 의존성·이력·교체 경계

`identity.decide_identity`는 레코드·후보·근거·확인을 받아 판정만 반환하는 순수 함수다.
파일 직렬화·조회·예산·CLI를 직접 실행하지 않는다. `reconcile_coordinates`도 판정 결과만 다룬다.
조회 구현은 `CandidateLookup`을 공급하고, 내부 판정 구현은 같은 `GeocodeResult` 계약을 반환한다.
따라서 새 공급자 연동이나 판정 구현 교체는 저장·마커·후속 CLI 형식을 바꾸지 않는다.
범용 플러그인 등록 시스템은 없다. 정책 의미가 바뀌면 `identity.POLICY_VERSION`을 올린다.

재사용 키(`lookup_key`)에는 판정이 실제로 읽는 것만 넣는다. 그 레코드의 값, 적용한 후보 조회 결과,
그 레코드의 사람 확인과 확정 복원명, 그리고 판정 정책 키다. 선행 산출물·후보 파일·조회 캐시·검토
파일의 **파일 해시는 넣지 않는다**. 판정이 그 파일들에서 실제로 읽은 값은 이미 키 안에 값으로 들어
있고, 파일 해시를 묶으면 판정이 하나도 바뀌지 않은 재실행이 모든 키를 갈아 이력을 통째로 다시
쌓기 때문이다([ADR-0003](adr/0003-narrow-geocode-history-key.md)). 산출물 단위의 낡음은 envelope의
`dependencies`가 그대로 검사하므로, 상류가 바뀌면 geocode를 다시 돌려야 하는 것은 전과 같다.
변경 없는 성공·미확정은 재사용하며 `--retry-failed`는 미확정을 다시 판정한다.
변경된 결과는 새 키에 저장하고 명시적 실패 재시도는 같은 키의 새 revision에 남긴다.

`geocode-history-v2.jsonl`은 조각마다 키·revision 순으로 정렬한 추가형 이력이다. 단일 작성자만
지원한다. 이번 배치가 마지막 조각에 들어가지 않으면 그 조각을 그대로 닫고
`geocode-history-v2.002.jsonl`부터 세 자리 번호를 붙인 다음 조각을 연다. 읽는 쪽은 번호 순으로
이어 읽으며, 조각 번호가 비었거나 같은 `(key, revision)`이 두 조각에 있으면 실패한다.

**앞 조각은 다시 쓰지 않는다. 마지막 조각은 정렬을 지키려고 통째로 다시 쓴다.** 그래서 조각이
20MB에 딱 차지 않고 닫힐 수 있는데, 커밋된 앞 조각을 다시 쓰지 않기 위한 대가다. 유효한 최신
판정은 줄 순서가 아니라 `valid=true`인 가장 큰 revision으로 고르므로, 조각이 늘어도 선택은
달라지지 않는다.

geocode·closure 산출물은 envelope v4이고 build는 좌표 출처·장부 사유를 담은 v6다.
이전 버전은 `regeneration-required`로 거부하고
선행 정제 자료와 새 후보 입력을 준비해 세 단계를 재실행한다. 교체 전 기존 파일은
`history/<stage>-v<version>-<content-hash>.json`에 보존한다. 이 사본은 커밋하지 않는다.
옛 상호 중심 `geocode-history.jsonl`은 읽거나 수정하지 않는다.

정적 빌드에는 앞서 열거한 정제 파일과 사용한 사람 보정·확인 파일을 함께 보관한다.
현재 정책 또는 입력과 일치하지 않는 geocode를 가진 빌드는 실패하며 기존 출력 파일을 유지한다.
원본·수집 메타데이터·API 키는 필요 없다. 산출물 파일은 각각 20MB 이내로 나누며
누적 이력은 상한에 닿을 때 다음 조각으로 이어 쓴다. 자동 이력 삭제는 하지 않는다.
합성 테스트와 중간 빌드 성공은 실제 수집·동일 업소 품질·제출 전 미해결 0건 검증을 대신하지 않는다.
