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
    "spent_on": "2026-03-04",
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


def test_every_record_field_is_declared_either_keyed_or_not() -> None:
    assert set(KEYED_RECORD_FIELDS) | set(OTHER_VALUES) == set(Record.model_fields)
    assert not set(KEYED_RECORD_FIELDS) & set(OTHER_VALUES)


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
