"""Pure business adjudication over provider-independent, scoped evidence."""

import hashlib
import json
import unicodedata

from deliciousmap.contracts import (
    CandidateLookup,
    GeocodeResult,
    IdentityConfirmation,
    Record,
)

POLICY_VERSION = "identity-1"


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def _place_identity(
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
    confirmation: IdentityConfirmation | None,
    dependency_key: str,
) -> str:
    return digest(
        {
            "policy": POLICY_VERSION,
            "record": record.model_dump(mode="json"),
            "dependencies": dependency_key,
            "lookup": lookup.model_dump(mode="json"),
            "confirmation": confirmation.model_dump(mode="json") if confirmation else None,
        }
    )


def decide_identity(
    record: Record,
    lookup: CandidateLookup,
    confirmation: IdentityConfirmation | None = None,
    *,
    dependency_key: str,
) -> GeocodeResult:
    """Require independent name, branch and address facts; never infer missing context."""
    common = {
        "record_id": record.record_id,
        "merchant": record.merchant,
        "lookup_key": lookup_key(record, lookup, confirmation, dependency_key),
        "dependency_key": dependency_key,
        "lookup": lookup,
        "confirmation": confirmation,
    }

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
        if confirmation.scope != lookup.scope:
            raise ValueError("confirmation scope mismatch")
        matches = [
            candidate
            for candidate in lookup.candidates
            if (
                candidate.source == confirmation.candidate_source
                and _place_identity(candidate.merchant, candidate.branch, candidate.address)
                == _place_identity(confirmation.merchant, confirmation.branch, confirmation.address)
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
        identities = {_place_identity(fact.merchant, fact.branch, fact.address) for fact in facts}
        if len(identities) != 1:
            return unresolved("conflicting_evidence")
        expected = next(iter(identities))
        if expected is None:
            return unresolved("insufficient_evidence")
        if expected[0] != normalized(record.merchant):
            return unresolved("unconfirmed_name")
        matches = [
            candidate
            for candidate in lookup.candidates
            if (
                _place_identity(candidate.merchant, candidate.branch, candidate.address) == expected
            )
        ]
    if not matches:
        return unresolved("no_match")
    if len(matches) != 1:
        return unresolved("ambiguous")
    candidate = matches[0]
    if candidate.latitude is None or candidate.longitude is None:
        return unresolved("missing_coordinates")
    return GeocodeResult.model_validate(
        {
            **common,
            "status": "success",
            "reason": "human_confirmed" if confirmation else "matched",
            "business_id": digest(
                [
                    "business-1",
                    *(
                        _place_identity(
                            candidate.merchant,
                            candidate.branch,
                            candidate.address,
                        )
                        or ()
                    ),
                ]
            ),
            "confirmed_merchant": candidate.merchant,
            "latitude": candidate.latitude,
            "longitude": candidate.longitude,
            "evidence": confirmation.evidence if confirmation else "name-branch-address-agreement",
        }
    )


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
