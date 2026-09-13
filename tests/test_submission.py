"""제출 시점 기준이 공개하는 남은 미해결의 집계. 사람 대조가 있는 것만 결함 확정으로 센다."""

import pytest
from pydantic import ValidationError

from deliciousmap.contracts import (
    Classification,
    ClassificationStatus,
    GeocodeReason,
    GeocodeResult,
    Record,
    SourceFinding,
    SourceReport,
    SourceReview,
    SubmissionTally,
    UnnamedCompanions,
    UnresolvedCount,
    UnresolvedReason,
)
from deliciousmap.submission import tally

CITY = "gwangju"
ORGANIZATION = "gwangju-city"


def unresolved(
    source_hash: str, reason: UnresolvedReason = "validation_failed", candidates: int | None = 3
) -> SourceReport:
    return SourceReport(
        source_hash=source_hash, status="unresolved", reason=reason, candidates=candidates
    )


def review(
    source_hash: str,
    finding: SourceFinding = "merchant_blank",
    confirmed_by: str = "",
    candidates: int = 3,
) -> SourceReview:
    return SourceReview(
        city=CITY,
        organization=ORGANIZATION,
        source_hash=source_hash,
        finding=finding,
        candidates=candidates,
        rows=("sheet1:R4",),
        evidence="사용장소 칸이 빈 현금 축의금 1건.",
        confirmed_by=confirmed_by,
    )


def decision(record_id: str, status: ClassificationStatus) -> Classification:
    return Classification(record_id=record_id, status=status, evidence="합성 판정")


def geocode(record_id: str, reason: GeocodeReason) -> GeocodeResult:
    confirmed = {
        "business_id": "b" * 64,
        "confirmed_merchant": "합성식당",
        "latitude": 35.1,
        "longitude": 126.9,
    }
    return GeocodeResult.model_validate(
        {
            "record_id": record_id,
            "merchant": "합성식당",
            "status": "success" if reason in {"matched", "human_confirmed"} else "failed",
            "reason": reason,
            "lookup_key": "1" * 64,
            "dependency_key": "2" * 64,
            "lookup": {
                "scope": {
                    "city": CITY,
                    "organization": ORGANIZATION,
                    "record_id": record_id,
                    "source_hash": "a" * 64,
                },
                "status": "ok",
            },
            "evidence": reason,
            **(confirmed if reason in {"matched", "human_confirmed"} else {}),
        }
    )


def test_a_defect_a_person_confirmed_is_counted_apart_from_the_unresolved() -> None:
    """사람이 원본과 대조해 확정한 원본 결함은 미해결과 나누어 센다(#106 선택지 C)."""
    counted = tally(
        (unresolved("a" * 64, candidates=47),),
        (review("a" * 64, confirmed_by="합성 검토자", candidates=47),),
        (),
        (),
        (),
    )

    defects = [(item.finding, item.sources, item.candidates) for item in counted.confirmed_defects]
    assert defects == [("merchant_blank", 1, 47)]
    assert counted.unresolved_sources == ()


def test_a_defect_without_a_person_check_stays_unresolved() -> None:
    """같은 사유라도 사람 대조를 거치지 않은 원본은 원본 결함 확정이 아니다(#93 전의 16개)."""
    counted = tally((unresolved("a" * 64),), (review("a" * 64),), (), (), ())

    assert counted.confirmed_defects == ()
    assert [(item.reason, item.sources) for item in counted.unresolved_sources] == [
        ("validation_failed", 1)
    ]


def test_an_unresolved_original_nobody_reviewed_stays_unresolved() -> None:
    counted = tally((unresolved("a" * 64, reason="unsupported_format"),), (), (), (), ())

    assert counted.confirmed_defects == ()
    assert [(item.reason, item.sources) for item in counted.unresolved_sources] == [
        ("unsupported_format", 1)
    ]


def test_originals_that_were_read_are_not_counted_as_remaining() -> None:
    counted = tally(
        (SourceReport(source_hash="a" * 64, status="parsed", records=2), unresolved("b" * 64)),
        (),
        (),
        (),
        (),
    )

    assert [item.sources for item in counted.unresolved_sources] == [1]
    assert counted.counted_sources is True


def test_reasons_are_counted_together_and_ordered_by_how_many_originals_they_hold() -> None:
    counted = tally(
        (
            unresolved("a" * 64, candidates=5),
            unresolved("b" * 64, reason="unreadable", candidates=7),
            unresolved("c" * 64, candidates=11),
        ),
        (),
        (),
        (),
        (),
    )

    unresolved_counts = [
        (item.reason, item.sources, item.candidates) for item in counted.unresolved_sources
    ]
    assert unresolved_counts == [("validation_failed", 2, 16), ("unreadable", 1, 7)]


def test_candidates_stay_unknown_when_one_original_never_counted_them() -> None:
    """후보 수를 모르는 원본이 섞이면 나머지만 더한 수를 전체인 것처럼 내지 않는다(폴백 정책)."""
    counted = tally(
        (unresolved("a" * 64, candidates=5), unresolved("b" * 64, candidates=None)),
        (),
        (),
        (),
        (),
    )

    assert [(item.sources, item.candidates) for item in counted.unresolved_sources] == [(2, None)]


def test_nothing_is_counted_when_the_parse_left_no_report() -> None:
    """원본을 세지 않은 산출물의 0은 사실이 아니다. 셌는지를 함께 낸다."""
    counted = tally(
        (), (), (record("r1"),), (decision("r1", "restaurant"),), (geocode("r1", "matched"),)
    )

    assert counted.counted_sources is False
    assert counted.confirmed_defects == ()
    assert counted.unresolved_sources == ()


def test_records_left_off_the_map_are_counted_by_their_reason() -> None:
    counted = tally(
        (),
        (),
        tuple(record(f"r{index}") for index in range(1, 5)),
        (
            decision("r1", "restaurant"),
            decision("r2", "restaurant"),
            decision("r3", "pending"),
            decision("r4", "non_restaurant"),
        ),
        (geocode("r1", "matched"), geocode("r2", "missing_address")),
    )

    assert counted.classified_records == 4
    assert counted.pending_records == 1
    assert counted.restaurant_records == 2
    assert [(item.reason, item.records) for item in counted.unconfirmed_places] == [
        ("missing_address", 1)
    ]


def test_a_submission_that_confirmed_every_place_leaves_nothing_unconfirmed() -> None:
    counted = tally(
        (),
        (),
        (record("r1"),),
        (decision("r1", "restaurant"),),
        (geocode("r1", "human_confirmed"),),
    )

    assert counted.unconfirmed_places == ()
    assert counted.restaurant_records == 1


def test_a_tally_cannot_report_originals_it_did_not_count() -> None:
    """세지 않았다면 사유별 수도 없다. 두 칸이 어긋난 집계는 계약이 받지 않는다."""
    with pytest.raises(ValidationError):
        SubmissionTally(unresolved_sources=(UnresolvedCount(reason="unreadable", sources=1),))


def record(record_id: str, merchant: str = "합성식당") -> Record:
    return Record.model_validate(
        {
            "record_id": record_id,
            "spent_on": "2026-01-02",
            "organization": ORGANIZATION,
            "department": "총무과",
            "merchant": merchant,
            "purpose": "간담회",
            "amount_krw": "1000",
            "source_hash": "a" * 64,
            "source_location": f"sheet1:{record_id}",
        }
    )


def test_places_the_original_never_named_are_counted_as_places_and_records() -> None:
    """이름 없는 동행 업소는 조회할 이름이 없어 영영 마커가 되지 못한다. 그 수를 남긴다(#127)."""
    counted = tally(
        (),
        (),
        (
            record("r1", "합성식당 외 1"),
            record("r2", "합성분식 외 2"),
            record("r3", "합성카페"),
        ),
        (decision("r1", "restaurant"), decision("r2", "restaurant"), decision("r3", "restaurant")),
        (),
    )

    assert counted.unnamed_companions == UnnamedCompanions(records=2, places=3)


def test_a_tail_without_a_count_is_never_reported_as_a_known_number() -> None:
    """원본이 수를 적지 않았으면 몇 곳인지 모른다. 0곳으로도 1곳으로도 세지 않는다."""
    counted = tally((), (), (record("r1", "합성낙지 외"), record("r2", "합성식당 외 1")), (), ())

    assert counted.unnamed_companions == UnnamedCompanions(records=2, places=1, uncounted_records=1)


def test_a_ledger_without_a_tail_reports_none_instead_of_guessing() -> None:
    counted = tally((), (), (record("r1"),), (), ())

    assert counted.unnamed_companions == UnnamedCompanions()


def test_a_tally_cannot_report_more_uncounted_tails_than_records() -> None:
    with pytest.raises(ValidationError):
        UnnamedCompanions(records=1, uncounted_records=2)


def test_a_tally_cannot_report_places_no_record_named() -> None:
    """꼬리말을 쓴 레코드가 없으면 밝혀진 업소도 없다. 어긋난 집계는 계약이 받지 않는다."""
    with pytest.raises(ValidationError):
        UnnamedCompanions(places=5)
