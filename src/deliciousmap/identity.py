"""Pure business adjudication over provider-independent, scoped evidence."""

import hashlib
import json
import math
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from deliciousmap import merchants
from deliciousmap.contracts import (
    CandidateLookup,
    CandidateSource,
    ConfirmedPlace,
    GeocodeResult,
    PlaceCandidate,
    Record,
    RestoredName,
)

# identity-2: 업소 확인이 상호 범위를 선언할 수 있게 됐다(#64).
# identity-3: 이름 없는 동행 업소의 꼬리말(`외 N`)을 뗀 이름을 근거와 대조하고(#127),
# 합쳐 적은 상호를 사람이 확인하지 않은 레코드를 전용 사유로 보류한다(#117).
# identity-4: 독립 근거가 없어도 네이버·인허가가 도시 안에서 같은 상호·지점·주소를 가리키면
# 제공자 합의(ProviderCross)로 채택하고, 제공자 좌표 차이는 200 m까지 허용한다(ADR-0009).
# identity-5: 제공자 하나만 도시 안에서 상호가 맞아도 채택한다. 같은 상호를 상호 포함 일치
# (`merchants.inclusion_overlap`)로 보고, 도시 안 여러 곳은 기관 청사에 가까운 곳을 고른다
# ([ADR-0010](../../docs/adr/0010-adopt-single-provider-in-city.md)).
POLICY_VERSION = "identity-5"

# 서로 다른 제공자가 같은 업소로 겹쳤을 때 허용하는 좌표 차이. 인허가 좌표는 중부원점TM을
# 변환한 값이라 같은 건물도 수 m~수십 m 어긋난다(광주 실측 최대 166 m, ADR-0009).
# 도시 안 후보를 장소로 묶는 기준이자, 같은 업소로 본 마커를 하나로 합치는 기준이다(ADR-0010).
COORDINATE_TOLERANCE_M = 200
# 겹친 좌표 가운데 마커에 쓰는 순서. 네이버는 WGS84 원값이라 변환 오차가 없다.
COORDINATE_PREFERENCE = ("naver", "local", "license")
EARTH_RADIUS_M = 6_371_000
# 마커를 합칠 후보를 추리는 격자 한 칸의 도(°). 200 m보다 크므로 이웃 아홉 칸 밖은 볼 것이 없다.
MERGE_CELL_DEGREES = 0.005

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
    *,
    address_prefixes: tuple[str, ...] = (),
    hall: tuple[float, float] | None = None,
) -> str:
    return digest(
        {
            "policy": POLICY_VERSION,
            "record": record.model_dump(mode="json", include=set(KEYED_RECORD_FIELDS)),
            "held_as_merged": held_as_merged(record),
            # 도시 안으로 보는 접두. 판정이 읽는 값이므로 키에 담는다(ADR-0005).
            "address_prefixes": list(address_prefixes),
            # 이 레코드의 기관 청사. 여러 곳 가운데 어디를 고를지가 이 값으로 갈린다(ADR-0005).
            "hall": list(hall) if hall is not None else None,
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
    address_prefixes: tuple[str, ...] = (),
    hall: tuple[float, float] | None = None,
) -> GeocodeResult:
    """독립 근거·제공자 합의·단일 제공자 채택으로만 확정한다. 상호가 맞지 않으면 추측하지 않는다."""
    common = {
        "record_id": record.record_id,
        "merchant": record.merchant,
        "lookup_key": lookup_key(
            record,
            lookup,
            confirmation,
            restoration,
            dependency_key,
            address_prefixes=address_prefixes,
            hall=hall,
        ),
        "dependency_key": dependency_key,
        "lookup": lookup,
        "confirmation": confirmation,
        "restoration": restoration,
    }
    # 확정된 복원명만 원본 표기를 대신한다. 확인 전 후보는 복원명이 아니다.
    # 복원명이 없으면 이름 없는 동행 업소의 꼬리말을 뗀 첫 업소의 이름과 대조한다(#127).
    expected_name = merchants.chosen_name(
        record.merchant, restoration.restored_merchant if restoration else None
    )
    # 이 레코드를 어느 경로가 판정하는가. 아래에서 네 번 다시 가르지 않도록 한 번만 정한다.
    # 채택(adopted)은 사람 확인도 독립 근거도 없어 도시 안 후보로 확정하는 경로다(ADR-0010).
    adopted = confirmation is None and not lookup.facts
    # 채택한 장소와 기관 청사의 거리. 독립 근거로 확정한 건에는 고른 일이 없어 남길 거리도 없다.
    hall_distance: float | None = None

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
    if not adopted and confirmation is not None:
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
    elif adopted:
        # 담당자가 독립 근거를 적지 않은 레코드. 후보 하나가 스스로 밝힌 주소는 근거가 아니지만,
        # 그 도시를 다루는 기관이 쓴 돈이라는 사실과 겹치면 도시 안 후보를 채택한다(ADR-0010).
        places = city_places(
            lookup.candidates,
            expected_name,
            address_prefixes,
            whole_name=held_as_merged(record),
        )
        if not places:
            return unresolved("insufficient_evidence")
        # 청사를 모르는 기관은 도시 안 여러 곳 가운데 하나를 고를 근거가 없다.
        if len(places) > 1 and hall is None:
            return unresolved("conflicting_evidence")
        place = min(places, key=lambda item: _place_rank(item, expected_name, hall))
        hall_distance = None if hall is None else _hall_distance(place, hall)
        matches = list(place)
    else:
        if any(fact.address is None for fact in facts):
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
    providers = [candidate.source.provider for candidate in matches]
    located = [
        candidate
        for candidate in matches
        if candidate.latitude is not None and candidate.longitude is not None
    ]
    if not located:
        return unresolved("missing_coordinates")
    # 채택은 이미 한 장소의 후보만 골라 왔다. 근거로 좁힌 후보들만 서로 어긋나는지 본다.
    if not adopted:
        # 한 제공자가 같은 표기의 후보를 여럿 주면 서로 다른 업소일 수 있다. 임의로 줄이지 않는다.
        if len(providers) != len(set(providers)):
            return unresolved("ambiguous")
        if any(
            distance_m(coordinates(first), coordinates(second)) > COORDINATE_TOLERANCE_M
            for index, first in enumerate(located)
            for second in located[index + 1 :]
        ):
            return unresolved("conflicting_evidence")
    # 마커의 좌표·이름은 한 후보에서 함께 나온다. 네이버 표기가 사람이 읽는 이름이다.
    chosen = min(located, key=lambda item: _coordinate_rank(item.source.provider))
    return GeocodeResult.model_validate(
        {
            **common,
            "status": "success",
            "reason": "human_confirmed" if confirmation else "matched",
            "business_id": business_id(chosen),
            "confirmed_merchant": chosen.merchant,
            "latitude": chosen.latitude,
            "longitude": chosen.longitude,
            "evidence": _evidence(
                confirmation,
                restoration,
                providers,
                adopted=adopted,
                hall_distance=hall_distance,
            ),
        }
    )


def business_id(candidate: PlaceCandidate) -> str:
    """후보가 가리키는 업소의 식별자. 상호·지점·주소를 함께 읽어 같은 업소를 한 마커로 모은다."""
    return digest(
        [
            "business-1",
            *(place_identity(candidate.merchant, candidate.branch, candidate.address) or ()),
        ]
    )


def name_overlap(expected_name: str, candidate: PlaceCandidate, *, whole: bool = False) -> int:
    """후보가 레코드의 상호와 겹친 글자 수. 제공자가 지점명을 상호에 붙여 낼 때가 있다.

    후보의 `merchant`와 `merchant+branch` 가운데 더 길게 겹친 쪽을 읽는다. 어느 쪽도 상호 포함
    일치가 아니면 0이며, 그 후보는 이 레코드의 업소가 아니다.

    `whole`이면 뼈대가 글자까지 같은 표기만 센다. 업소 둘 이상으로 읽히는 표기(`시골밥집, 데이지`)
    는 앞뒤가 겹쳤다고 그 업소인 것이 아니라 함께 적힌 둘 중 하나일 뿐이다. 무엇이 업소 몇 곳인지는
    사람 확인만이 가른다(#117).
    """
    written = candidate.merchant + (candidate.branch or "")
    found = max(
        merchants.inclusion_overlap(expected_name, candidate.merchant),
        merchants.inclusion_overlap(expected_name, written),
    )
    if not whole:
        return found
    expected = merchants.bare_name(expected_name)
    same = expected in (merchants.bare_name(candidate.merchant), merchants.bare_name(written))
    return found if expected and same else 0


def city_places(
    candidates: Sequence[PlaceCandidate],
    expected_name: str,
    address_prefixes: tuple[str, ...],
    *,
    whole_name: bool = False,
) -> list[tuple[PlaceCandidate, ...]]:
    """도시 안에서 상호가 맞은 후보들이 가리키는 장소들. 접두가 없는 도시는 채택하지 않는다.

    좌표가 `COORDINATE_TOLERANCE_M` 안인 후보는 제공자가 달라도 한 장소로 묶는다. 주소·좌표가
    없는 후보는 도시 안인지도 어디인지도 밝히지 못하고, 지점 칸이 없는 후보는 업소 식별자를
    만들 수 없어(`business_id`) 채택의 근거가 되지 못한다. 두 제공자 모두 지점을 빈 문자열로
    채우므로 이 조건이 실제 후보를 거르지는 않는다(2026-09-15 광주 실측).
    """
    prefixes = [normalized(prefix) for prefix in address_prefixes]
    inside = [
        candidate
        for candidate in candidates
        if candidate.address is not None
        and candidate.branch is not None
        and candidate.latitude is not None
        and candidate.longitude is not None
        and any(normalized(candidate.address).startswith(prefix) for prefix in prefixes)
        and name_overlap(expected_name, candidate, whole=whole_name)
    ]
    places: list[list[PlaceCandidate]] = []
    for candidate in inside:
        near = [
            place
            for place in places
            if any(
                distance_m(coordinates(candidate), coordinates(other)) <= COORDINATE_TOLERANCE_M
                for other in place
            )
        ]
        joined = [candidate]
        for place in near:
            joined.extend(place)
            places.remove(place)
        places.append(joined)
    return [tuple(place) for place in places]


def coordinates(candidate: PlaceCandidate) -> tuple[float, float]:
    """후보가 밝힌 좌표. 좌표가 없는 후보는 부르지 않는다."""
    assert candidate.latitude is not None and candidate.longitude is not None
    return candidate.latitude, candidate.longitude


def distance_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    """두 좌표의 대원 거리(m)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*first, *second))
    spread = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(spread))


def _hall_distance(place: Sequence[PlaceCandidate], hall: tuple[float, float]) -> float:
    return min(distance_m(hall, coordinates(candidate)) for candidate in place)


def _place_rank(
    place: Sequence[PlaceCandidate], expected_name: str, hall: tuple[float, float] | None
) -> tuple[int, float]:
    """여러 곳 가운데 고르는 순서. 상호가 더 길게 겹친 곳이 먼저고, 같으면 청사에 가까운 곳이다."""
    overlap = max(name_overlap(expected_name, candidate) for candidate in place)
    return -overlap, 0.0 if hall is None else _hall_distance(place, hall)


def _coordinate_rank(provider: str) -> int:
    if provider in COORDINATE_PREFERENCE:
        return COORDINATE_PREFERENCE.index(provider)
    return len(COORDINATE_PREFERENCE)


def _evidence(
    confirmation: ConfirmedPlace | None,
    restoration: RestoredName | None,
    providers: Sequence[str],
    *,
    adopted: bool,
    hall_distance: float | None,
) -> str:
    if confirmation is not None:
        return confirmation.evidence
    if not adopted:
        agreement = (
            "restored-name-branch-address-agreement"
            if restoration
            else "name-branch-address-agreement"
        )
        return agreement if len(providers) == 1 else f"{agreement} {'+'.join(sorted(providers))}"
    # 채택은 몇 제공자가 그 장소를 가리켰는지와, 고른 곳이 청사에서 얼마나 떨어졌는지를 밝힌다.
    found = sorted(set(providers))
    adoption = "provider-cross" if len(found) > 1 else "single-provider"
    if restoration:
        adoption = f"restored-name-{adoption}"
    evidence = f"{adoption} {'+'.join(found)}"
    if hall_distance is None:
        return evidence
    return f"{evidence} nearest-hall {round(hall_distance)}m"


def carried_coordinates(result: GeocodeResult) -> bool:
    """좌표가 자기 후보에서 나오지 않은 판정인가. 합치기가 다른 레코드의 값을 받아 적은 것이다.

    그 값은 상대 레코드의 판정에 딸린 것이라 상대가 달라지면 낡는다. 이력에서 꺼내 그대로 쓰지
    않고 다시 매겨야 하는 판정을 가리는 자리다(`local.LocalAdapters.geocode`, ADR-0010).
    """
    if result.latitude is None or result.longitude is None:
        return False
    return not any(
        (candidate.latitude, candidate.longitude) == (result.latitude, result.longitude)
        for candidate in result.lookup.candidates
    )


def coordinate_owner(results: Sequence[GeocodeResult]) -> GeocodeResult:
    """같은 업소로 묶인 레코드 가운데 그 좌표를 스스로 낸 레코드.

    다른 제공자로 채택한 레코드를 한 마커로 합치면(`reconcile_coordinates`) 합쳐진 쪽의 후보에는
    그 좌표가 없다. 마커의 출처·주소와 업종 조회는 그 좌표를 낸 레코드가 밝힌다.
    """
    for result in results:
        if result.reason == "human_confirmed" and result.confirmation is not None:
            return result
        if any(
            (candidate.latitude, candidate.longitude) == (result.latitude, result.longitude)
            and candidate.address is not None
            for candidate in result.lookup.candidates
        ):
            return result
    raise ValueError("a confirmed coordinate must come from one of its candidates")


def coordinate_origin(result: GeocodeResult) -> tuple[CandidateSource, str]:
    """좌표를 준 후보의 출처와 그 근거의 주소. 사람이 확인한 건은 확인한 후보와 주소가 정본이다.

    업소 확인은 상호·지점·주소가 일치한 후보만 채택하므로(`decide_identity`) 주소 없는
    후보는 좌표의 근거가 될 수 없다.
    """
    if result.reason == "human_confirmed" and result.confirmation is not None:
        return result.confirmation.candidate_source, result.confirmation.address
    # 여러 제공자의 근거가 같은 좌표로 겹치면 제공자 이름 순으로 하나를 밝힌다.
    origins = sorted(
        (
            (candidate.source, candidate.address)
            for candidate in result.lookup.candidates
            if (candidate.latitude, candidate.longitude) == (result.latitude, result.longitude)
            and candidate.address is not None
        ),
        key=lambda origin: (origin[0].provider, origin[1], origin[0].source_id),
    )
    if not origins:
        raise ValueError("a confirmed coordinate must come from one of its candidates")
    return origins[0]


def reconcile_coordinates(results: tuple[GeocodeResult, ...]) -> tuple[GeocodeResult, ...]:
    """업소 사이의 갈림을 정리한다. 좌표가 어긋난 업소는 마커가 되지 못하고, 갈라져 확정된
    같은 업소는 한 마커로 합친다."""
    return _merge_split_places(_drop_conflicting(results))


def _drop_conflicting(results: tuple[GeocodeResult, ...]) -> tuple[GeocodeResult, ...]:
    """Conflicting coordinate evidence cannot produce markers for a shared business."""
    located: dict[str, set[tuple[float | None, float | None]]] = {}
    for result in results:
        if result.business_id is not None:
            located.setdefault(result.business_id, set()).add((result.latitude, result.longitude))
    conflicts = {key for key, values in located.items() if len(values) > 1}
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


def _merge_split_places(results: tuple[GeocodeResult, ...]) -> tuple[GeocodeResult, ...]:
    """상호가 맞고 `COORDINATE_TOLERANCE_M` 안인 업소들을 한 업소로 합친다(ADR-0010).

    같은 식당이라도 레코드마다 채택한 제공자가 달라 상호 표기와 좌표가 갈릴 수 있다. 사람 확인 →
    네이버 → 인허가 순으로 한 곳을 정본으로 삼고 나머지 레코드의 업소·좌표·표기를 그 값으로
    다시 쓴다. 합치는 것은 채택한 판정뿐이다 — 사람 확인과 독립 근거로 확정한 레코드는 채택보다
    단단한 근거이므로 다시 쓰지 않는다(ADR-0010).
    """
    places = _confirmed_places(results)
    winners = _winning_place(places)
    if not winners:
        return results
    merged = []
    for result in results:
        winner = winners.get(result.business_id or "")
        # 정본으로 남은 레코드는 합쳐진 것이 아니다. 자기 자신으로 다시 쓰지 않는다.
        if winner is None or winner.business_id == result.business_id or _rooted(result):
            merged.append(result)
            continue
        merged.append(
            GeocodeResult.model_validate(
                {
                    **result.model_dump(),
                    "business_id": winner.business_id,
                    "confirmed_merchant": winner.merchant,
                    "latitude": winner.latitude,
                    "longitude": winner.longitude,
                    "evidence": f"{result.evidence} merged-into {winner.provider}",
                }
            )
        )
    return tuple(merged)


def _rooted(result: GeocodeResult) -> bool:
    """사람 확인이나 독립 근거로 확정한 판정인가. 채택보다 단단해 합치기가 다시 쓰지 않는다."""
    return result.reason == "human_confirmed" or bool(result.lookup.facts)


@dataclass(frozen=True)
class _ConfirmedPlace:
    """확정된 업소 하나. 같은 업소의 레코드들이 함께 가리키는 값이다."""

    business_id: str
    merchant: str
    latitude: float
    longitude: float
    provider: str
    # 정본을 고르는 순서. 사람이 확인한 업소가 먼저고, 그다음이 좌표를 준 제공자의 순서다.
    rank: tuple[int, int]


def _confirmed_places(results: Sequence[GeocodeResult]) -> list[_ConfirmedPlace]:
    found: dict[str, _ConfirmedPlace] = {}
    for result in results:
        if (
            result.business_id is None
            or result.confirmed_merchant is None
            or result.latitude is None
            or result.longitude is None
        ):
            continue
        provider = min(
            (
                candidate.source.provider
                for candidate in result.lookup.candidates
                if (candidate.latitude, candidate.longitude) == (result.latitude, result.longitude)
            ),
            key=_coordinate_rank,
            default="",
        )
        rank = (0 if _rooted(result) else 1, _coordinate_rank(provider))
        previous = found.get(result.business_id)
        if previous is None or rank < previous.rank:
            found[result.business_id] = _ConfirmedPlace(
                result.business_id,
                result.confirmed_merchant,
                result.latitude,
                result.longitude,
                provider,
                rank,
            )
    return list(found.values())


def _winning_place(places: Sequence[_ConfirmedPlace]) -> dict[str, _ConfirmedPlace]:
    """합쳐질 업소마다 그 정본. 합칠 상대가 없는 업소는 담지 않는다.

    정본이 될 자격이 높은 업소부터 자리를 잡고, 나머지는 상호가 맞으면서 `COORDINATE_TOLERANCE_M`
    안인 정본 가운데 가장 가까운 곳으로 들어간다. **정본과의 거리만** 보므로 200 m씩 이어 붙는
    사슬로 멀리 떨어진 동명 업소까지 한 마커가 되지 않는다. 허용 오차는 좌표 변환 오차를 덮는
    값이지 같은 이름을 모으는 반지름이 아니다(ADR-0010).
    """
    cells: dict[tuple[int, int], list[_ConfirmedPlace]] = {}
    members: dict[str, list[str]] = {}
    by_id = {place.business_id: place for place in places}
    for place in sorted(places, key=lambda item: (item.rank, item.business_id)):
        row, column = _cell(place)
        # 격자 한 칸이 허용 오차보다 넓어 이웃 아홉 칸 밖의 정본은 볼 것이 없다.
        near = [
            (distance_m(coordinate(place), coordinate(leader)), leader)
            for down in (-1, 0, 1)
            for across in (-1, 0, 1)
            for leader in cells.get((row + down, column + across), ())
            if merchants.name_inclusion(leader.merchant, place.merchant)
        ]
        joined = [found for found in near if found[0] <= COORDINATE_TOLERANCE_M]
        if not joined:
            cells.setdefault((row, column), []).append(place)
            members[place.business_id] = [place.business_id]
            continue
        _, leader = min(joined, key=lambda found: (found[0], found[1].business_id))
        members[leader.business_id].append(place.business_id)
    return {
        business: by_id[leader]
        for leader, group in members.items()
        if len(group) > 1
        for business in group
    }


def coordinate(place: _ConfirmedPlace) -> tuple[float, float]:
    return place.latitude, place.longitude


def _cell(place: _ConfirmedPlace) -> tuple[int, int]:
    return (
        math.floor(place.latitude / MERGE_CELL_DEGREES),
        math.floor(place.longitude / MERGE_CELL_DEGREES),
    )
