"""Pure business adjudication over provider-independent, scoped evidence."""

import hashlib
import json
import unicodedata
from collections.abc import Sequence

from deliciousmap.contracts import (
    CandidateLookup,
    ConfirmedPlace,
    GeocodeResult,
    Record,
    RestoredName,
)

# identity-2: 업소 확인이 상호 범위를 선언할 수 있게 됐다(#64).
POLICY_VERSION = "identity-2"


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def place_identity(
    merchant: str,
    branch: str | None,
    address: str | None,
) -> tuple[str, str, str] | None:
    if branch is None or address is None:
        return None
    return normalized(merchant), normalized(branch), normalized(address)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def lookup_key(
    record: Record,
    lookup: CandidateLookup,
    confirmation: ConfirmedPlace | None,
    restoration: RestoredName | None,
    dependency_key: str,
) -> str:
    return digest(
        {
            "policy": POLICY_VERSION,
            "record": record.model_dump(mode="json"),
            "dependencies": dependency_key,
            "lookup": lookup.model_dump(mode="json"),
            "confirmation": confirmation.model_dump(mode="json") if confirmation else None,
            "restoration": restoration.model_dump(mode="json") if restoration else None,
        }
    )


def decide_identity(
    record: Record,
    lookup: CandidateLookup,
    confirmation: ConfirmedPlace | None = None,
    restoration: RestoredName | None = None,
    *,
    dependency_key: str,
) -> GeocodeResult:
    """Require independent name, branch and address facts; never infer missing context."""
    common = {
        "record_id": record.record_id,
        "merchant": record.merchant,
        "lookup_key": lookup_key(record, lookup, confirmation, restoration, dependency_key),
        "dependency_key": dependency_key,
        "lookup": lookup,
        "confirmation": confirmation,
        "restoration": restoration,
    }
    # 확정된 복원명만 원본 표기를 대신한다. 확인 전 후보는 복원명이 아니다.
    expected_name = restoration.restored_merchant if restoration else record.merchant

    def unresolved(reason: str) -> GeocodeResult:
        return GeocodeResult.model_validate(
            {
                **common,
                "status": "failed",
                "reason": reason,
                "evidence": reason,
            }
        )

    if lookup.status == "error":
        return unresolved("lookup_error")
    if not lookup.candidates:
        return unresolved("no_candidates")
    facts = lookup.facts
    if confirmation is not None:
        if confirmation.record_id != record.record_id:
            raise ValueError("confirmation record mismatch")
        matches = [
            candidate
            for candidate in lookup.candidates
            if (
                candidate.source == confirmation.candidate_source
                and place_identity(candidate.merchant, candidate.branch, candidate.address)
                == place_identity(confirmation.merchant, confirmation.branch, confirmation.address)
            )
        ]
    else:
        if not facts or any(fact.address is None for fact in facts):
            return unresolved("missing_address")
        candidate_references = {candidate.source.reference for candidate in lookup.candidates}
        if all(fact.source in candidate_references for fact in facts):
            return unresolved("insufficient_evidence")
        if any(fact.branch is None for fact in facts):
            return unresolved("unknown_branch")
        identities = {place_identity(fact.merchant, fact.branch, fact.address) for fact in facts}
        if len(identities) != 1:
            return unresolved("conflicting_evidence")
        expected = next(iter(identities))
        if expected is None:
            return unresolved("insufficient_evidence")
        if expected[0] != normalized(expected_name):
            return unresolved("unconfirmed_name")
        matches = [
            candidate
            for candidate in lookup.candidates
            if (place_identity(candidate.merchant, candidate.branch, candidate.address) == expected)
        ]
    if not matches:
        return unresolved("no_match")
    # 한 제공자가 같은 표기의 후보를 여럿 주면 서로 다른 업소일 수 있다. 임의로 줄이지 않는다.
    providers = [candidate.source.provider for candidate in matches]
    if len(providers) != len(set(providers)):
        return unresolved("ambiguous")
    # 서로 다른 제공자가 같은 업소를 가리키면 근거가 겹친 것이다. 좌표가 어긋나면 충돌이다.
    coordinates = {
        (candidate.latitude, candidate.longitude)
        for candidate in matches
        if candidate.latitude is not None and candidate.longitude is not None
    }
    if len(coordinates) > 1:
        return unresolved("conflicting_evidence")
    if not coordinates:
        return unresolved("missing_coordinates")
    latitude, longitude = next(iter(coordinates))
    candidate = matches[0]
    return GeocodeResult.model_validate(
        {
            **common,
            "status": "success",
            "reason": "human_confirmed" if confirmation else "matched",
            "business_id": digest(
                [
                    "business-1",
                    *(
                        place_identity(
                            candidate.merchant,
                            candidate.branch,
                            candidate.address,
                        )
                        or ()
                    ),
                ]
            ),
            "confirmed_merchant": candidate.merchant,
            "latitude": latitude,
            "longitude": longitude,
            "evidence": _evidence(confirmation, restoration, providers),
        }
    )


def _evidence(
    confirmation: ConfirmedPlace | None,
    restoration: RestoredName | None,
    providers: Sequence[str],
) -> str:
    if confirmation is not None:
        return confirmation.evidence
    agreement = (
        "restored-name-branch-address-agreement" if restoration else "name-branch-address-agreement"
    )
    if len(providers) == 1:
        return agreement
    # 여러 제공자의 근거가 겹쳐 하나의 업소를 가리키면 어느 출처가 일치했는지 함께 남긴다.
    return f"{agreement} {'+'.join(sorted(providers))}"


def reconcile_coordinates(results: tuple[GeocodeResult, ...]) -> tuple[GeocodeResult, ...]:
    """Conflicting coordinate evidence cannot produce markers for a shared business."""
    coordinates: dict[str, set[tuple[float | None, float | None]]] = {}
    for result in results:
        if result.business_id is not None:
            coordinates.setdefault(result.business_id, set()).add(
                (result.latitude, result.longitude)
            )
    conflicts = {key for key, values in coordinates.items() if len(values) > 1}
    return tuple(
        GeocodeResult.model_validate(
            {
                **result.model_dump(),
                "status": "failed",
                "reason": "conflicting_evidence",
                "evidence": "conflicting_evidence",
                "business_id": None,
                "confirmed_merchant": None,
                "latitude": None,
                "longitude": None,
            }
        )
        if result.business_id in conflicts
        else result
        for result in results
    )
