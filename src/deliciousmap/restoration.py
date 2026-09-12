"""사람이 확정한 검토 입력의 적용 범위 판단. 조회·저장·파일 탐색은 하지 않는다.

상호 복원(`restore.jsonl`)과 업소 확인(`geocode.jsonl`)이 같은 범위 규칙을 쓴다.
`POLICY_VERSION`은 복원명 적용 규칙의 버전이다. 업소 확인의 적용은 좌표 판정의 일부이므로
`identity.POLICY_VERSION`이 버전을 가진다.
"""

from deliciousmap.contracts import (
    ConfirmedPlace,
    IdentityConfirmation,
    NameRestoration,
    Record,
    RestoredName,
)
from deliciousmap.identity import normalized, place_identity

POLICY_VERSION = "restoration-1"

# 범위를 선언하는 사람 검토 입력. 적용·충돌 규칙을 공유한다.
type ScopedEntry = NameRestoration | IdentityConfirmation


class ConflictingReview(Exception):
    """사람 확인이 서로 어긋난다. 임의로 고르지 않고 범위나 내용을 고쳐야 한다."""


def applies(entry: ScopedEntry, record: Record) -> bool:
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


def confirm(
    records: tuple[Record, ...], entries: tuple[IdentityConfirmation, ...]
) -> tuple[ConfirmedPlace, ...]:
    """확정된 업소 확인만 레코드마다 적용한다. 확인이 없는 레코드는 미확정으로 남는다.

    entries는 대상 도시의 확인만 담아야 한다. 도시 검사와 읽기는 저장 모듈이 한다.
    """
    confirmed = []
    for record in records:
        applicable = [entry for entry in entries if applies(entry, record)]
        if not applicable:
            continue
        if len({_place(entry) for entry in applicable}) != 1:
            raise ConflictingReview("identity confirmation place")
        chosen = _narrowest(applicable)
        confirmed.append(
            ConfirmedPlace(
                record_id=record.record_id,
                candidate_source=chosen.candidate_source,
                merchant=chosen.merchant,
                branch=chosen.branch,
                address=chosen.address,
                scope=chosen.scope,
                evidence=chosen.evidence,
                references=chosen.references,
            )
        )
    return tuple(confirmed)


def _place(entry: IdentityConfirmation) -> tuple[str, ...]:
    """확인이 가리키는 후보와 업소. 두 줄이 다른 곳을 가리키면 임의로 고르지 않는다.

    업소 동일성의 정규화는 `identity`가 소유한다. 여기서 따로 비교하면 판정과 어긋날 수 있다.
    """
    return (
        entry.candidate_source.provider,
        entry.candidate_source.source_id,
        entry.candidate_source.reference,
        *(place_identity(entry.merchant, entry.branch, entry.address) or ()),
    )


def require_agreement(
    restorations: tuple[RestoredName, ...], confirmations: tuple[ConfirmedPlace, ...]
) -> None:
    """같은 레코드의 복원명과 업소 확인이 다른 상호를 가리키면 알린다."""
    restored = {item.record_id: item.restored_merchant for item in restorations}
    for confirmation in confirmations:
        expected = restored.get(confirmation.record_id)
        if expected is not None and normalized(expected) != normalized(confirmation.merchant):
            raise ConflictingReview("restoration and identity confirmation")


def _declared(entry: ScopedEntry) -> frozenset[str]:
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


def _narrowest[T: ScopedEntry](applicable: list[T]) -> T:
    """근거를 남길 확인 하나를 고른다. 어느 쪽도 더 좁지 않으면 임의로 고르지 않는다."""
    chosen = max(applicable, key=lambda entry: len(_declared(entry)))
    fields = _declared(chosen)
    others = [entry for entry in applicable if entry is not chosen]
    if any(_declared(entry) == fields or not _declared(entry) <= fields for entry in others):
        raise ConflictingReview("review scope")
    return chosen
