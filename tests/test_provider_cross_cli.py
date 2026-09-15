"""제공자 합의(ProviderCross)로 독립 근거 없이 업소를 확정하는 경로를 공개 CLI로 관찰한다."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from deliciousmap.pipeline import ExecutionContext
from deliciousmap.registry import Target
from tests.test_geocoding_cli import lookup, payload, prepare, run_cli, save_input

CITY_PREFIX = "부산"
NAVER = (35.1, 129.1)
# 네이버 좌표에서 약 7 m 북쪽. 인허가 좌표계 변환 오차 수준이다.
NEARBY = (35.10006, 129.1)
# 약 220 m 북쪽. 허용 오차 200 m 밖이다.
FAR = (35.102, 129.1)


def in_city(tmp_path: Path, *prefixes: str) -> ExecutionContext:
    context = prepare(tmp_path)
    city = replace(context.target.city, address_prefixes=prefixes)
    return replace(context, target=Target(city, context.target.org))


def candidate(
    provider: str,
    coordinates: tuple[float, float] | None,
    source_id: str | None = None,
    **fields: object,
) -> dict:
    latitude, longitude = coordinates if coordinates else (None, None)
    return {
        "source": {
            "provider": provider,
            "source_id": source_id or f"{provider}-place",
            "reference": f"https://example.invalid/{provider}/1",
        },
        "merchant": "같은 식당",
        "branch": "부산점",
        "address": "부산 합성로 10",
        "latitude": latitude,
        "longitude": longitude,
        **fields,
    }


def cross_lookup(*candidates: dict) -> dict:
    """담당자가 독립 근거를 적지 않았고 두 제공자의 후보만 있는 조회."""
    query = lookup()
    query["facts"] = []
    query["candidates"] = list(candidates)
    return query


def result(context: ExecutionContext) -> dict:
    return payload(context, "geocode")["results"][0]


def test_two_providers_agreeing_inside_the_city_confirm_the_place_with_naver_coordinates(
    tmp_path: Path,
) -> None:
    context = in_city(tmp_path, CITY_PREFIX)
    save_input(context, cross_lookup(candidate("naver", NAVER), candidate("license", NEARBY)))
    assert run_cli(context, "geocode") == 0
    found = result(context)
    assert found["status"] == "success"
    assert found["reason"] == "matched"
    assert (found["latitude"], found["longitude"]) == NAVER
    assert found["confirmed_merchant"] == "같은 식당"
    assert found["evidence"] == "provider-cross license+naver"
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["marker_count"] == 1


def test_agreement_outside_the_city_is_not_evidence_for_this_record(tmp_path: Path) -> None:
    """경기도 광주시 '다미정'처럼 다른 지역의 동명 업소에 두 제공자가 합의해도 채택하지 않는다."""
    context = in_city(tmp_path, CITY_PREFIX)
    elsewhere = {"address": "경기도 광주시 설월길 29"}
    save_input(
        context,
        cross_lookup(
            candidate("naver", NAVER, **elsewhere), candidate("license", NEARBY, **elsewhere)
        ),
    )
    assert run_cli(context, "geocode") == 0
    found = result(context)
    assert found["reason"] == "insufficient_evidence"
    assert found["business_id"] is None


def test_agreement_on_a_different_name_is_not_evidence_for_this_record(tmp_path: Path) -> None:
    """'나룻배'의 후보로 두 제공자가 '나룻배식당'에 합의해도 레코드의 상호가 아니다."""
    context = in_city(tmp_path, CITY_PREFIX)
    other = {"merchant": "같은 식당 횟집"}
    save_input(
        context,
        cross_lookup(candidate("naver", NAVER, **other), candidate("license", NEARBY, **other)),
    )
    assert run_cli(context, "geocode") == 0
    assert result(context)["reason"] == "insufficient_evidence"


def test_coordinates_beyond_the_tolerance_are_a_conflict(tmp_path: Path) -> None:
    context = in_city(tmp_path, CITY_PREFIX)
    save_input(context, cross_lookup(candidate("naver", NAVER), candidate("license", FAR)))
    assert run_cli(context, "geocode") == 0
    found = result(context)
    assert found["reason"] == "conflicting_evidence"
    assert found["business_id"] is None


def test_two_agreed_places_for_one_name_are_a_conflict(tmp_path: Path) -> None:
    """'유진정'처럼 담양·화순 두 곳에 각각 합의가 서면 어느 곳인지 고르지 않는다."""
    context = in_city(tmp_path, CITY_PREFIX)
    second = {"address": "부산 다른로 5", "branch": ""}
    save_input(
        context,
        cross_lookup(
            candidate("naver", NAVER),
            candidate("license", NEARBY),
            candidate("naver", (35.2, 129.2), source_id="naver-2", **second),
            candidate("license", (35.2, 129.2), source_id="license-2", **second),
        ),
    )
    assert run_cli(context, "geocode") == 0
    assert result(context)["reason"] == "conflicting_evidence"


def test_one_provider_alone_is_insufficient_evidence(tmp_path: Path) -> None:
    """후보 하나가 스스로 밝힌 주소는 근거가 아니다. 사유는 주소 부재가 아니라 근거 부족이다."""
    context = in_city(tmp_path, CITY_PREFIX)
    save_input(context, cross_lookup(candidate("naver", NAVER)))
    assert run_cli(context, "geocode") == 0
    assert result(context)["reason"] == "insufficient_evidence"


def test_a_city_without_address_prefixes_never_adopts_by_agreement(tmp_path: Path) -> None:
    context = in_city(tmp_path)
    save_input(context, cross_lookup(candidate("naver", NAVER), candidate("license", NEARBY)))
    assert run_cli(context, "geocode") == 0
    assert result(context)["reason"] == "insufficient_evidence"


def test_independent_facts_take_precedence_over_provider_agreement(tmp_path: Path) -> None:
    """독립 근거가 있으면 그 경로가 판정한다. 근거가 다른 주소면 합의가 있어도 쓰지 않는다."""
    context = in_city(tmp_path, CITY_PREFIX)
    query = cross_lookup(candidate("naver", NAVER), candidate("license", NEARBY))
    query["facts"] = deepcopy(lookup()["facts"])
    query["facts"][0]["address"] = "부산 다른로 5"
    save_input(context, query)
    assert run_cli(context, "geocode") == 0
    assert result(context)["reason"] == "no_match"
