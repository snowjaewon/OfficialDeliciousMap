"""사람이 확정한 상호 복원의 적용 범위 판단. 조회·저장·파일 탐색은 하지 않는다."""

from deliciousmap.contracts import (
    IdentityConfirmation,
    NameRestoration,
    Record,
    RestoredName,
)
from deliciousmap.identity import normalized

POLICY_VERSION = "restoration-1"


class ConflictingReview(Exception):
    """사람 확인이 서로 어긋난다. 임의로 고르지 않고 범위나 내용을 고쳐야 한다."""


def applies(entry: NameRestoration, record: Record) -> bool:
    """선언한 범위가 모두 맞을 때만 적용한다. 같은 표기의 다른 업소로 번지지 않는다."""
    scope = entry.scope
    return (
        normalized(scope.merchant) == normalized(record.merchant)
        and scope.organization in (None, record.organization)
        and scope.source_hash in (None, record.source_hash)
        and scope.record_id in (None, record.record_id)
    )


def resolve(
    records: tuple[Record, ...], entries: tuple[NameRestoration, ...]
) -> tuple[RestoredName, ...]:
    """확정된 복원만 돌려준다. 확인이 없는 레코드는 미확정으로 남는다.

    entries는 대상 도시의 확인만 담아야 한다. 도시 검사와 읽기는 저장 모듈이 한다.
    """
    restored = []
    for record in records:
        applicable = [entry for entry in entries if applies(entry, record)]
        if not applicable:
            continue
        if len({normalized(entry.restored_merchant) for entry in applicable}) != 1:
            raise ConflictingReview("restoration name")
        chosen = _narrowest(applicable)
        restored.append(
            RestoredName(
                record_id=record.record_id,
                merchant=record.merchant,
                restored_merchant=chosen.restored_merchant,
                scope=chosen.scope,
                evidence=chosen.evidence,
                references=chosen.references,
            )
        )
    return tuple(restored)


def require_agreement(
    restorations: tuple[RestoredName, ...], confirmations: tuple[IdentityConfirmation, ...]
) -> None:
    """같은 레코드의 복원명과 업소 확인이 다른 상호를 가리키면 알린다."""
    restored = {item.record_id: item.restored_merchant for item in restorations}
    for confirmation in confirmations:
        expected = restored.get(confirmation.scope.record_id)
        if expected is not None and normalized(expected) != normalized(confirmation.merchant):
            raise ConflictingReview("restoration and identity confirmation")


def _declared(entry: NameRestoration) -> frozenset[str]:
    """범위를 좁히려고 선언한 항목. 많이 선언할수록 좁은 범위다."""
    scope = entry.scope
    return frozenset(
        name
        for name, value in (
            ("organization", scope.organization),
            ("source_hash", scope.source_hash),
            ("record_id", scope.record_id),
        )
        if value is not None
    )


def _narrowest(applicable: list[NameRestoration]) -> NameRestoration:
    """근거를 남길 확인 하나를 고른다. 어느 쪽도 더 좁지 않으면 임의로 고르지 않는다."""
    chosen = max(applicable, key=lambda entry: len(_declared(entry)))
    fields = _declared(chosen)
    others = [entry for entry in applicable if entry is not chosen]
    if any(_declared(entry) == fields or not _declared(entry) <= fields for entry in others):
        raise ConflictingReview("restoration scope")
    return chosen
