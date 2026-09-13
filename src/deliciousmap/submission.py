"""제출 시점 기준이 공개하는 남은 미해결의 집계. 파일을 읽거나 외부에 닿지 않는다.

[#106](https://github.com/snowjaewon/OfficialDeliciousMap/issues/106)의 2026-09-13 결정이다.
사람이 원본과 대조해 원본 자체의 결함으로 확정한 원본은 나머지 미해결과 나누어 센다. 대조가
없으면 사유가 같아도 미해결이며, 이 집계는 어느 쪽도 0건으로 감추지 않는다. 0건 기준
([#9](https://github.com/snowjaewon/OfficialDeliciousMap/issues/9))은 이 집계가 대신하지 않는다.
"""

from collections import Counter
from collections.abc import Sequence

from deliciousmap import merchants
from deliciousmap.contracts import (
    CONFIRMED_REASONS,
    Classification,
    ConfirmedDefect,
    GeocodeResult,
    Record,
    SourceReport,
    SourceReview,
    SubmissionTally,
    UnconfirmedPlace,
    UnresolvedCount,
)


def tally(
    sources: Sequence[SourceReport],
    reviews: Sequence[SourceReview],
    decisions: Sequence[Classification],
    geocodes: Sequence[GeocodeResult],
    records: Sequence[Record],
) -> SubmissionTally:
    """이번 제출이 남긴 미해결을 사유별로 센다. `reviews`는 대상 도시·기관의 것만 받는다.

    `records`에 기본값을 두지 않는다. 빠뜨린 호출이 가르지 못한 지출을 0건으로 통과시키면
    세지 않은 것과 0건인 것을 구별할 수 없다.
    """
    confirmed = {item.source_hash: item for item in reviews if item.confirmed_by.strip()}
    unresolved = [item for item in sources if item.status == "unresolved"]
    return SubmissionTally(
        confirmed_defects=_confirmed_defects(
            [confirmed[item.source_hash] for item in unresolved if item.source_hash in confirmed]
        ),
        unresolved_sources=_unresolved_sources(
            [item for item in unresolved if item.source_hash not in confirmed]
        ),
        counted_sources=bool(sources),
        classified_records=len(decisions),
        pending_records=sum(item.status == "pending" for item in decisions),
        restaurant_records=sum(item.status == "restaurant" for item in decisions),
        unconfirmed_places=_unconfirmed_places(geocodes),
        unsplit_expenses=merchants.unsplit_expenses(records),
    )


def _confirmed_defects(reviews: Sequence[SourceReview]) -> tuple[ConfirmedDefect, ...]:
    sources = Counter(item.finding for item in reviews)
    candidates: Counter[str] = Counter()
    for item in reviews:
        candidates[item.finding] += item.candidates
    return tuple(
        ConfirmedDefect(finding=finding, sources=count, candidates=candidates[finding])
        for finding, count in _ordered(sources)
    )


def _unresolved_sources(reports: Sequence[SourceReport]) -> tuple[UnresolvedCount, ...]:
    sources = Counter(item.reason for item in reports if item.reason is not None)
    counted: dict[str, int | None] = {}
    for item in reports:
        if item.reason is None:
            continue
        total = counted.get(item.reason, 0)
        counted[item.reason] = (
            None if total is None or item.candidates is None else total + item.candidates
        )
    return tuple(
        UnresolvedCount(reason=reason, sources=count, candidates=counted[reason])
        for reason, count in _ordered(sources)
    )


def _unconfirmed_places(geocodes: Sequence[GeocodeResult]) -> tuple[UnconfirmedPlace, ...]:
    reasons = Counter(item.reason for item in geocodes if item.reason not in CONFIRMED_REASONS)
    return tuple(
        UnconfirmedPlace(reason=reason, records=count) for reason, count in _ordered(reasons)
    )


def _ordered[T: str](counts: Counter[T]) -> list[tuple[T, int]]:
    """많은 사유부터, 수가 같으면 사유 이름 순으로. 같은 입력이 늘 같은 순서를 낸다."""
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))
