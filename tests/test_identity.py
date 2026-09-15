"""판정 키가 레코드에서 담는 칸의 계약.

`decide_identity`가 읽지 않는 레코드 칸은 판정도 키도 바꾸지 못한다. 레코드 계약에 칸이 늘어도
같아야 한다. 그러지 않으면 판정이 하나도 바뀌지 않은 재실행이 이력을 통째로 다시 쌓는다
([ADR-0005](../docs/adr/0005-key-only-what-the-decision-reads.md)).
"""

import pytest

from deliciousmap.contracts import CandidateLookup, GeocodeResult, Record
from deliciousmap.identity import KEYED_RECORD_FIELDS, decide_identity, digest, lookup_key
from tests.test_geocoding_cli import lookup, synthetic_record

DEPENDENCY_KEY = digest("identity-test")
# 판정이 읽지 않는 레코드 칸마다 다른 값 하나. 아래 첫 테스트가 이 목록이 레코드 계약을
# 빠짐없이 덮는지 본다. 계약에 칸이 늘면 그 칸을 키에 넣을지 여기서 밝혀야 한다.
OTHER_VALUES: dict[str, object] = {
    # 일이 빈 집행일로 둔다. 달까지만 적힌 집행일도 판정 키를 바꾸지 못해야
    # 이미 쌓인 판정 이력이 그대로 재사용된다(#116).
    "spent_on": "2026.03.",
    "department": "다른과",
    "purpose": "다른 목적",
    "amount_krw": "2000",
    "source_location": "sheet1:R9",
    "repeats": [{"source_hash": "b" * 64, "location": "sheet1:R3"}],
    # 사람 검토의 적용 범위를 가르는 두 칸. 그 검사의 결과인 확인·복원명은 이미 키에 값으로
    # 들어 있고, 두 값 자체는 그 조회가 어느 범위에 답한 것인지로서 `lookup.scope`가 담는다.
    "organization": "other-org",
    "source_hash": "c" * 64,
}


def candidates(**scope: str) -> CandidateLookup:
    supplied = lookup()
    supplied["scope"].update(scope)
    return CandidateLookup.model_validate(supplied)


def key(record: Record, found: CandidateLookup | None = None) -> str:
    return lookup_key(record, found or candidates(), None, None, DEPENDENCY_KEY)


def judgement(record: Record) -> GeocodeResult:
    return decide_identity(record, candidates(), dependency_key=DEPENDENCY_KEY)


# 판정이 값이 아니라 사실로 읽는 칸. 키에는 `identity.held_as_merged`가 낸 사실만 담기므로
# 칸을 통째로 담는 쪽에도, 판정이 읽지 않는 쪽에도 두지 않는다(#117).
READ_AS_A_FACT = frozenset({"expense"})


def test_every_record_field_is_declared_either_keyed_or_not() -> None:
    declared = set(KEYED_RECORD_FIELDS) | set(OTHER_VALUES) | READ_AS_A_FACT
    assert declared == set(Record.model_fields)
    assert not set(KEYED_RECORD_FIELDS) & set(OTHER_VALUES)
    assert not READ_AS_A_FACT & (set(KEYED_RECORD_FIELDS) | set(OTHER_VALUES))


def test_only_the_fact_a_merchant_review_leaves_reaches_the_key() -> None:
    """확인이 붙었는지는 판정을 바꾸고, 그 지출의 금액·식별자는 키를 바꾸지 않는다(ADR-0005)."""
    merged = synthetic_record(merchant="시골밥집, 데이지")
    assert judgement(merged).reason == "merged_merchant"
    reviewed = merged.model_copy(update={"expense": {"expense_id": "r1", "amount_krw": "1000"}})
    assert judgement(reviewed).reason != "merged_merchant"
    other = merged.model_copy(update={"expense": {"expense_id": "e9", "amount_krw": "2000"}})
    assert key(reviewed) == key(other) != key(merged)


def test_a_review_on_a_merchant_without_a_separator_leaves_the_key_alone() -> None:
    """구분자가 없는 상호는 확인이 붙어도 판정이 같으므로 이력을 다시 쌓지 않는다."""
    reviewed = synthetic_record().model_copy(
        update={"expense": {"expense_id": "r1", "amount_krw": "1000"}}
    )
    assert key(reviewed) == key(synthetic_record())


@pytest.mark.parametrize("field,value", sorted(OTHER_VALUES.items()))
def test_record_fields_outside_the_key_change_neither_the_judgement_nor_the_key(
    field: str, value: object
) -> None:
    """키뿐 아니라 판정 전체를 견준다. 판정이 이 칸을 읽기 시작하면 여기서 깨져야 한다."""
    assert judgement(synthetic_record(**{field: value})) == judgement(synthetic_record())


def test_the_record_values_the_decision_reads_still_change_the_key() -> None:
    # 판정 결과에 그대로 실리는 두 값이다. 같은 키를 나눠 쓰면 다른 레코드의 판정을 재사용한다.
    assert key(synthetic_record(record_id="r2"), candidates(record_id="r2")) != key(
        synthetic_record()
    )
    assert key(synthetic_record(merchant="다른 식당")) != key(synthetic_record())


def test_what_the_registry_tells_the_decision_changes_the_key() -> None:
    """도시 주소 접두와 기관 청사는 레코드의 칸이 아니지만 판정이 읽는 값이다(ADR-0005·ADR-0010).

    둘을 고치면 어디를 도시 안으로 보고 여러 곳 중 어디를 고를지가 달라지므로, 그 도시의
    판정만 다시 쌓여야 한다. 키에 담지 않으면 옛 답이 그대로 재사용된다.
    """
    plain = key(synthetic_record())
    assert (
        lookup_key(
            synthetic_record(),
            candidates(),
            None,
            None,
            DEPENDENCY_KEY,
            address_prefixes=("부산",),
        )
        != plain
    )
    assert (
        lookup_key(
            synthetic_record(),
            candidates(),
            None,
            None,
            DEPENDENCY_KEY,
            hall=(35.1, 129.1),
        )
        != plain
    )


def test_the_scope_the_lookup_answered_for_still_changes_the_key() -> None:
    """기관·원본은 레코드 조각에서 빠졌을 뿐 조회의 범위로 키에 남는다."""
    assert key(synthetic_record(), candidates(organization="other-org")) != key(synthetic_record())
    assert key(synthetic_record(), candidates(source_hash="c" * 64)) != key(synthetic_record())


def test_a_new_record_field_does_not_change_the_key() -> None:
    """레코드 계약이 늘어도 판정 키는 그대로다. `repeats` 칸이 한 세대를 다시 쌓은 일을 막는다."""

    class ExtendedRecord(Record):
        note: str = "레코드 계약에 새로 생긴 칸"

    extended = ExtendedRecord.model_validate(synthetic_record().model_dump())
    assert extended.note
    assert key(extended) == key(synthetic_record())
