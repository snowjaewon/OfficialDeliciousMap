---
status: accepted
---

# 판정 키는 레코드에서 판정이 읽는 값만 담는다

`lookup_key`가 레코드에서 담는 것은 **`record_id`와 `merchant`뿐**이다. 목록은 `identity.KEYED_RECORD_FIELDS` 한 곳에 두고, `lookup_key`는 그 목록으로만 레코드를 담는다. [ADR-0003](0003-narrow-geocode-history-key.md)이 선행 산출물의 파일 해시에 적용한 논리를 레코드의 칸에 그대로 적용하는 것이다. 이 결정은 [#71](https://github.com/snowjaewon/OfficialDeliciousMap/issues/71)에서 2026-09-13에 했다. 실측은 [검증 기록](../validation/issue-71.md)에 있다.

`decide_identity`가 레코드에서 읽는 값이 그 둘이다. `record_id`는 판정을 그 지출에 묶는다 — 이력에서 꺼낸 판정은 `record_id`를 그대로 싣고 있으므로, 두 레코드가 키를 나눠 쓰면 한쪽이 다른 쪽의 판정을 재사용한다. `merchant`는 확정 복원명이 없을 때 독립 근거와 맞춰 볼 이름이다. 나머지 `spent_on`·`department`·`purpose`·`amount_krw`·`source_location`·`repeats`는 판정을 바꾸지 않으면서 키를 바꾼다.

`record_id`는 지금 `lookup.scope`에도 들어 있어 키에 두 번 들어간다(`GeocodeResult`가 둘의 불일치를 거부한다). 그래도 레코드 조각에 남긴다. 목록이 말하는 것은 "키가 우연히 담고 있는 값"이 아니라 "판정이 레코드에서 읽는 값"이고, 아래 적은 대로 `lookup`을 좁히는 후속 결정이 오면 조각 쪽이 그 값을 지킨다.

[#63](https://github.com/snowjaewon/OfficialDeliciousMap/issues/63)이 이것을 실제로 치렀다. 누적 재게시를 합치며 `Record`에 `repeats` 칸이 생기자, 겹친 출처를 실제로 얻은 117건만이 아니라 **판정 대상 2,225건 전부**의 `model_dump`가 달라진다 — 값이 빈 `repeats`도 키를 바꾸기 때문이다. 그 재생성은 이력을 2,225줄·5,834,944바이트 늘렸다([#64 검증](../validation/issue-64.md)). 같은 실행이 `POLICY_VERSION`도 `identity-2`로 올렸으므로 그 5.8MB 가운데 얼마가 `repeats` 몫인지는 그 실행만으로 가릴 수 없다. 다만 `repeats` 하나로도 전량이 다시 쌓인다는 것은 위 설명대로다. 겹친 출처는 판정 입력이 아니라 출처 표시다.

`organization`과 `source_hash`는 사람 검토의 적용 범위를 가르는 데 쓰이지만(`restoration.applies`), 그 검사의 결과인 확정 복원명·업소 확인은 **이미 키에 값으로 들어 있다.** 범위가 어긋나 적용되지 않으면 키의 그 칸이 `null`이 되어 그대로 드러난다. 두 값은 그 조회가 어느 범위에 답한 것인지로서 `lookup.scope`에 남아 키에 들어간다.

## Considered Options

- **레코드 전체를 담기**(지금까지): 레코드 계약에 칸이 하나 늘 때마다 판정이 하나도 바뀌지 않은 재실행이 이력을 통째로 다시 쌓는다. 광주에서는 한 세대가 약 5.8MB다.
- **판정이 읽는 칸만 담되 목록을 `lookup_key` 안에 적기**: 지금 동작은 같지만 목록이 판정 코드와 떨어져 있어, 판정이 읽는 값이 늘 때 함께 고치기 어렵다.
- **판정이 읽는 칸만 담고 목록을 이름 붙여 한곳에 두기(채택)**: 레코드 계약이 늘어도 키가 조용히 바뀌지 않고, 목록을 고치는 것이 곧 "판정이 읽는 값이 바뀌었다"는 선언이 된다. 테스트가 그 목록을 고정한다.
- **키를 좁히지 않기**: 이번 한 번의 재적재 5.8MB를 아끼지만, 같은 비용을 레코드 계약이 늘 때마다 다시 낸다. 2026-09에만 두 번 냈다 — #59의 집계 세 칸, #63의 `repeats` 칸이다.

## Consequences

- 키 식이 바뀌므로 **이번 한 번은** 광주 2,225건이 새 키로 다시 쌓인다. 조각 2가 10,993,975 → 16,828,919바이트(4,550 → 6,775줄)가 되고 조각 1은 바이트 그대로 남는다. 상한까지 남은 여유는 3,171,081바이트다.
- 판정에 쓰이지 않는 레코드 칸이 바뀌어도 이력에 줄이 늘지 않는다. 광주 레코드 100건에 겹친 출처를 새로 달아 본 실측에서 옛 키는 65줄(186,924바이트)을 더했고 새 키는 0줄이다.
- **원본의 행 번호가 밀리면 키는 여전히 바뀐다.** `source_location`을 뺐지만 `record_id`가 `<원본 해시 앞 16자>-<표>-R<행>`이라 행 번호를 이미 담고 있다. 이 결정은 그것을 고치지 않는다. 레코드의 이름을 무엇으로 할지는 별개 결정이다.
- `lookup`·`confirmation`·`restoration`은 **여전히 통째로** 들어간다. `CandidateLookup`에 칸이 하나 늘면 `repeats`와 같은 일이 그대로 일어난다. 같은 논리를 그 계약들에도 적용할지는 후속 결정이며, `lookup.queries`(어느 제공자에게 물었고 어느 캐시 revision을 썼는지)를 키에서 뺄지가 그 결정의 핵심이다.
- `identity.POLICY_VERSION`은 올리지 않았다. 판정의 의미는 바뀌지 않았고(2,225건이 `lookup_key` 한 칸만 빼고 옛 판과 값까지 같다), 그 버전은 판정 의미가 바뀔 때 올리는 것이다. 대신 커밋된 `geocode.json`은 `_validate`의 키 재계산에서 어긋나 `invalid-artifact`로 거부되므로, 이 결정과 같은 커밋에서 `geocode`·`closure`·`build`를 다시 돌려 산출물을 맞춘다.
- 추가형 이력은 지우지 않는다. 옛 키의 줄은 그대로 둔다([ADR-0001](0001-commit-refined-artifacts.md)·[협업 결정 #8](https://github.com/snowjaewon/OfficialDeliciousMap/issues/8)).
