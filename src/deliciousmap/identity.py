"""Pure business adjudication over provider-independent, scoped evidence."""

import hashlib
import json
import unicodedata
from collections.abc import Sequence

from deliciousmap import merchants
from deliciousmap.contracts import (
    CandidateLookup,
    ConfirmedPlace,
    GeocodeResult,
    Record,
    RestoredName,
)

# identity-2: 업소 확인이 상호 범위를 선언할 수 있게 됐다(#64).
# identity-3: 이름 없는 동행 업소의 꼬리말(`외 N`)을 뗀 이름을 근거와 대조하고(#127),
# 합쳐 적은 상호를 사람이 확인하지 않은 레코드를 전용 사유로 보류한다(#117).
POLICY_VERSION = "identity-3"

# 판정 키가 레코드에서 값으로 담는 칸. `decide_identity`가 레코드의 값으로 읽는 것이 이 둘뿐이다 —
# `record_id`는 판정을 그 지출에 묶고, `merchant`는 확정 복원명이 없을 때 근거와 맞춰 볼 이름의
# 출처이자 합쳐 적은 상호인지 읽는 표기다. 꼬리말을 뗀 이름도 이 칸 하나에서 나오므로 키에 담는
# 칸은 늘지 않는다. `expense`는 값이 아니라 사실로만 읽으므로 아래 `held_as_merged`가 그 사실을
# 키에 담는다.
# 판정이 읽지 않는 칸을 담으면 판정이 하나도 바뀌지 않은 재실행이 이력을 통째로 다시 쌓는다.
# 목록을 여기 두는 것은 레코드 계약이 늘 때 키가 조용히 바뀌지 않게 하기 위해서다([ADR-0005](
# ../../docs/adr/0005-key-only-what-the-decision-reads.md)).
KEYED_RECORD_FIELDS = ("record_id", "merchant")


def held_as_merged(record: Record) -> bool:
    """사람이 업소별로 보지 않은 합쳐 적은 상호인가. 판정이 `expense`에서 읽는 것은 이 사실뿐이다.

    `Expense`를 통째로 키에 담으면 판정이 읽지 않는 금액까지 키를 바꾼다 — ADR-0005가 이름을
    대어 뺀 `amount_krw`가 그 안에 있다. 그래서 값이 아니라 이 사실만 키에 담는다. 사실이
    `merchant`까지 함께 읽는 덕에, 구분자가 없는 상호는 확인이 붙어도 키가 그대로다.
    """
    return record.expense is None and merchants.is_merged(record.merchant)


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
            "record": record.model_dump(mode="json", include=set(KEYED_RECORD_FIELDS)),
            "held_as_merged": held_as_merged(record),
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
    # 복원명이 없으면 이름 없는 동행 업소의 꼬리말을 뗀 첫 업소의 이름과 대조한다(#127).
    expected_name = (
        restoration.restored_merchant if restoration else merchants.read(record.merchant).named
    )

    def unresolved(reason: str) -> GeocodeResult:
        # 사람이 업소별로 보지 않은 합쳐 적은 상호는 나뉘지 않은 질의어로 조회한 결과다.
        # 그 사유를 내용인 것처럼 남기지 않고 확인이 없다는 사실을 사유로 남긴다(#117).
        # 조회 실패만은 덮지 않는다 — 제공자 장애를 보류로 바꾸면 실행이 종료 0으로 지나간다.
        if reason != "lookup_error" and held_as_merged(record):
            reason = "merged_merchant"
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
