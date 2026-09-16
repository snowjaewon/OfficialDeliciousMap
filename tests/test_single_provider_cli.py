"""단일 제공자 채택(identity-5)을 공개 CLI로 관찰한다.

독립 근거도 제공자 합의도 없는 레코드를, 도시 안에서 상호가 맞은 제공자 하나의 후보로 확정하는
경로다. 무엇을 같은 상호로 보고 여러 곳 가운데 어느 곳을 고르는지가 이 파일의 관찰 대상이다
([ADR-0010](../docs/adr/0010-adopt-single-provider-in-city.md), [#169](
https://github.com/snowjaewon/OfficialDeliciousMap/issues/169)).
"""

import json
from dataclasses import replace
from pathlib import Path

from deliciousmap.contracts import Classification, ClassifyOutput, ParseOutput, Record
from deliciousmap.identity import distance_m
from deliciousmap.pipeline import ExecutionContext
from deliciousmap.registry import Hall, Target
from deliciousmap.storage import ArtifactStore, write_text
from tests.test_geocoding_cli import (
    confirmation_file,
    lookup,
    payload,
    prepare,
    run_cli,
    save_input,
    synthetic_record,
)
from tests.test_site_build import published

CITY_PREFIX = "부산"
NAVER = (35.1, 129.1)
# 네이버 좌표에서 약 7 m 북쪽. 인허가 좌표계 변환 오차 수준이라 같은 장소다.
NEARBY = (35.10006, 129.1)
# 약 1.1 km 남쪽. 200 m 밖이라 다른 장소이며 청사가 여기에 더 가깝다.
FAR = (35.09, 129.1)
HALL = Hall(35.089, 129.1)


def in_city(
    tmp_path: Path,
    *prefixes: str,
    hall: Hall | None = None,
    records: tuple[Record, ...] = (synthetic_record(),),
) -> ExecutionContext:
    context = prepare(tmp_path, records=records)
    organizations = tuple(replace(org, hall=hall) for org in context.target.city.organizations)
    city = replace(context.target.city, address_prefixes=prefixes, organizations=organizations)
    return replace(context, target=Target(city, context.target.org))


def candidate(
    provider: str,
    coordinates: tuple[float, float],
    source_id: str | None = None,
    **fields: object,
) -> dict:
    latitude, longitude = coordinates
    return {
        "source": {
            "provider": provider,
            "source_id": source_id or f"{provider}-place",
            "reference": f"https://example.invalid/{provider}/1",
        },
        "merchant": "같은 식당",
        "branch": "",
        "address": "부산 합성로 10",
        "latitude": latitude,
        "longitude": longitude,
        **fields,
    }


def unsupported(record_id: str, *candidates: dict) -> dict:
    """담당자가 독립 근거를 적지 않은 조회. 후보가 스스로 밝힌 주소밖에 없다."""
    query = lookup()
    query["scope"]["record_id"] = record_id
    query["facts"] = []
    query["candidates"] = list(candidates)
    return query


def result(context: ExecutionContext) -> dict:
    return payload(context, "geocode")["results"][0]


def decided(records: tuple[Record, ...]) -> ClassifyOutput:
    return ClassifyOutput(
        decisions=tuple(
            Classification(record_id=item.record_id, status="restaurant", evidence="합성 분류")
            for item in records
        )
    )


def hall_distance(coordinates: tuple[float, float]) -> int:
    return round(distance_m((HALL.latitude, HALL.longitude), coordinates))


def test_one_naver_candidate_inside_the_city_confirms_the_place(tmp_path: Path) -> None:
    """제공자 하나뿐이어도 도시 안에서 상호가 맞으면 채택하고 청사 거리를 근거에 남긴다."""
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL)
    save_input(context, unsupported("r1", candidate("naver", NAVER)))
    assert run_cli(context, "geocode") == 0
    found = result(context)
    assert found["status"] == "success"
    assert found["reason"] == "matched"
    assert (found["latitude"], found["longitude"]) == NAVER
    assert found["evidence"] == f"single-provider naver nearest-hall {hall_distance(NAVER)}m"
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["marker_count"] == 1


def test_a_license_only_candidate_is_adopted_under_its_own_name(tmp_path: Path) -> None:
    """네이버 지역검색은 한 요청에 5건까지만 준다. 인허가에만 있는 업소도 도시 안이면 채택한다."""
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL)
    licensed = {"merchant": "같은 식당 상무점"}
    save_input(context, unsupported("r1", candidate("license", NEARBY, **licensed)))
    assert run_cli(context, "geocode") == 0
    found = result(context)
    assert found["status"] == "success"
    assert found["confirmed_merchant"] == "같은 식당 상무점"
    assert found["evidence"].startswith("single-provider license nearest-hall")


def test_a_candidate_that_extends_the_recorded_name_is_the_same_place(tmp_path: Path) -> None:
    """원본의 `달리는커피`와 제공자의 `달리는커피광주상무역`은 같은 업소다(상호 포함 일치)."""
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL)
    extended = {"merchant": "같은 식당광주상무역"}
    save_input(context, unsupported("r1", candidate("naver", NAVER, **extended)))
    assert run_cli(context, "geocode") == 0
    assert result(context)["confirmed_merchant"] == "같은 식당광주상무역"


def test_a_candidate_that_only_shares_the_middle_is_not_this_place(tmp_path: Path) -> None:
    """`강가`가 `건강가정지원센터` 안에 들어 있다고 같은 업소가 되지는 않는다."""
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL)
    inner = {"merchant": "주식같은 식당가"}
    save_input(context, unsupported("r1", candidate("naver", NAVER, **inner)))
    assert run_cli(context, "geocode") == 0
    assert result(context)["reason"] == "insufficient_evidence"


def test_a_merged_merchant_is_not_adopted_by_one_of_the_names_it_lists(tmp_path: Path) -> None:
    """`시골밥집, 데이지`의 후보로 `시골밥집`이 나와도 그 지출이 그 업소의 것은 아니다(#117).

    무엇이 업소 몇 곳인지는 사람 확인만이 가른다. 채택은 그 확인을 대신하지 않는다.
    """
    records = (synthetic_record(merchant="같은 식당, 다른 카페"),)
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL, records=records)
    save_input(context, unsupported("r1", candidate("naver", NAVER)))
    assert run_cli(context, "geocode") == 0
    assert result(context)["reason"] == "merged_merchant"


def test_a_merged_looking_name_that_a_provider_carries_whole_is_adopted(tmp_path: Path) -> None:
    """`본죽&비빔밥`처럼 이름 안에 구분자가 든 한 업소는 표기가 글자까지 같으면 채택한다."""
    records = (synthetic_record(merchant="같은 식당&카페"),)
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL, records=records)
    whole = {"merchant": "같은 식당 & 카페"}
    save_input(context, unsupported("r1", candidate("naver", NAVER, **whole)))
    assert run_cli(context, "geocode") == 0
    assert result(context)["reason"] == "matched"


def test_a_human_confirmation_outranks_the_nearest_place(tmp_path: Path) -> None:
    """사람이 확인한 후보가 청사에서 멀어도 그것이 정본이다. 채택은 확인을 대신하지 않는다."""
    far_away = {"address": "부산 다른로 5", "source_id": "naver-2"}
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL)
    save_input(
        context,
        unsupported(
            "r1",
            candidate("naver", FAR),
            candidate("naver", NAVER, **far_away),
        ),
    )
    write_text(
        confirmation_file(context),
        json.dumps(
            {
                "scope": {"city": "seoul", "merchant": "같은 식당"},
                "candidate_source": {
                    "provider": "naver",
                    "source_id": "naver-2",
                    "reference": "https://example.invalid/naver/1",
                },
                "merchant": "같은 식당",
                "branch": "",
                "address": "부산 다른로 5",
                "evidence": "합성 확인",
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    assert run_cli(context, "geocode") == 0
    found = result(context)
    assert found["reason"] == "human_confirmed"
    assert (found["latitude"], found["longitude"]) == NAVER
    assert found["evidence"] == "합성 확인"


def test_the_place_nearest_the_hall_is_chosen_when_the_name_matches_both(tmp_path: Path) -> None:
    """같은 상호가 도시 안 두 곳에 있으면 그 기관 청사에 가까운 곳을 고른다."""
    elsewhere = {"address": "부산 다른로 5"}
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL)
    save_input(
        context,
        unsupported(
            "r1",
            candidate("naver", NAVER),
            candidate("naver", FAR, source_id="naver-2", **elsewhere),
        ),
    )
    assert run_cli(context, "geocode") == 0
    found = result(context)
    assert (found["latitude"], found["longitude"]) == FAR
    assert found["evidence"].endswith(f"nearest-hall {hall_distance(FAR)}m")


def test_a_longer_name_overlap_outranks_a_nearer_place(tmp_path: Path) -> None:
    """겹침이 더 긴 후보가 먼저다. 가까운 곳이 이름의 3자만 겹친 다른 업소일 수 있다."""
    shorter = {"merchant": "같은 식", "address": "부산 다른로 5"}
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL)
    save_input(
        context,
        unsupported(
            "r1",
            candidate("naver", NAVER),
            candidate("naver", FAR, source_id="naver-2", **shorter),
        ),
    )
    assert run_cli(context, "geocode") == 0
    found = result(context)
    assert (found["latitude"], found["longitude"]) == NAVER


def test_two_places_without_a_declared_hall_stay_unresolved(tmp_path: Path) -> None:
    """청사를 모르는 기관은 도시 안 여러 곳 가운데 하나를 고르지 않는다."""
    elsewhere = {"address": "부산 다른로 5"}
    context = in_city(tmp_path, CITY_PREFIX)
    save_input(
        context,
        unsupported(
            "r1",
            candidate("naver", NAVER),
            candidate("naver", FAR, source_id="naver-2", **elsewhere),
        ),
    )
    assert run_cli(context, "geocode") == 0
    assert result(context)["reason"] == "conflicting_evidence"


def test_the_naver_name_is_published_when_both_providers_share_the_place(tmp_path: Path) -> None:
    """네이버 표기가 사람이 읽는 이름이다. 인허가 표기는 법인명·옛 상호일 때가 있다."""
    licensed = {"merchant": "같은 식당 영업신고"}
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL)
    save_input(
        context,
        unsupported(
            "r1",
            candidate("license", NEARBY, **licensed),
            candidate("naver", NAVER),
        ),
    )
    assert run_cli(context, "geocode") == 0
    found = result(context)
    assert found["confirmed_merchant"] == "같은 식당"
    assert found["evidence"].startswith("provider-cross license+naver nearest-hall")


def test_two_records_adopted_from_different_providers_share_one_marker(tmp_path: Path) -> None:
    """같은 업소를 한 레코드는 네이버로, 다른 레코드는 인허가로 채택해도 마커는 하나다."""
    records = (
        synthetic_record(),
        synthetic_record(record_id="r2", merchant="같은 식당 상무점", source_location="sheet1:R3"),
    )
    licensed = {"merchant": "같은 식당 상무점"}
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL, records=records)
    save_input(
        context,
        unsupported("r1", candidate("naver", NAVER)),
        unsupported("r2", candidate("license", NEARBY, **licensed)),
    )
    assert run_cli(context, "geocode") == 0
    first, second = payload(context, "geocode")["results"]
    assert first["business_id"] == second["business_id"]
    assert (second["latitude"], second["longitude"]) == NAVER
    assert second["confirmed_merchant"] == "같은 식당"
    assert second["evidence"].endswith("merged-into naver")
    # 정본으로 남은 레코드는 합쳐진 것이 아니라 합쳐진 쪽을 받은 것이다.
    assert "merged-into" not in first["evidence"]
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["marker_count"] == 1


def test_an_organization_marker_merged_into_another_organizations_record_still_builds(
    tmp_path: Path,
) -> None:
    """도시 판정을 인용한 기관에는 합쳐진 좌표를 스스로 낸 레코드가 없을 수 있다(#183).

    좌표의 출처·주소와 업종 조회는 그 좌표를 낸 레코드가 밝히므로 도시 판정에서 같은 업소의
    다른 기관 레코드를 찾아 쓴다.
    """
    records = (
        synthetic_record(organization="other-org"),
        synthetic_record(record_id="r2", merchant="같은 식당 상무점", source_location="sheet1:R3"),
    )
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL, records=(records[1],))
    organizations = (
        *context.target.city.organizations,
        replace(context.target.city.organizations[0], slug="other-org"),
    )
    city = replace(context.target.city, organizations=organizations)
    context = replace(context, target=Target(city))
    store = ArtifactStore(context.paths, context.target)
    store.save("parse", ParseOutput(records=records))
    store.save("classify", decided(records))
    elsewhere = unsupported("r1", candidate("naver", NAVER))
    elsewhere["scope"]["organization"] = "other-org"
    save_input(
        context,
        elsewhere,
        unsupported("r2", candidate("license", NEARBY, merchant="같은 식당 상무점")),
    )
    assert run_cli(context, "geocode") == 0
    assert payload(context, "geocode")["results"][1]["evidence"].endswith("merged-into naver")

    organization = replace(context, target=Target(city, "test-org"))
    store = ArtifactStore(organization.paths, organization.target)
    store.save("parse", ParseOutput(records=(records[1],)))
    store.save("classify", decided((records[1],)))
    for stage in ("geocode", "closure", "build"):
        assert run_cli(organization, stage) == 0
    marker = published(organization, "markers.json")["markers"][0]
    assert (marker["latitude"], marker["longitude"]) == NAVER
    assert marker["coordinate_source"] == "naver"


def test_a_chain_of_nearby_places_does_not_become_one_marker(tmp_path: Path) -> None:
    """허용 오차는 좌표 변환 오차를 덮는 값이지 같은 이름을 모으는 반지름이 아니다.

    150 m씩 이어 붙는 사슬을 허용하면 같은 상호가 늘어선 거리 전체가 마커 하나가 된다. 정본
    (네이버 좌표)에서 150 m인 곳은 합쳐지고, 300 m인 곳은 사슬로 이어져도 따로 남아야 한다.
    """
    step = 0.00135  # 위도 약 150 m
    records = tuple(
        synthetic_record(record_id=f"r{index}", source_location=f"sheet1:R{index}")
        for index in (1, 2, 3)
    )
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL, records=records)
    save_input(
        context,
        unsupported("r1", candidate("naver", NAVER)),
        unsupported(
            "r2",
            candidate("license", (NAVER[0] + step, NAVER[1]), address="부산 합성로 2"),
        ),
        unsupported(
            "r3",
            candidate("license", (NAVER[0] + step * 2, NAVER[1]), address="부산 합성로 3"),
        ),
    )
    assert run_cli(context, "geocode") == 0
    first, second, third = payload(context, "geocode")["results"]
    assert first["business_id"] == second["business_id"] != third["business_id"]
    assert second["evidence"].endswith("merged-into naver")
    assert "merged-into" not in third["evidence"]
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["marker_count"] == 2


def test_an_independent_root_is_not_rewritten_by_a_nearby_adoption(tmp_path: Path) -> None:
    """독립 근거로 확정한 레코드는 채택보다 단단하다. 가까운 채택이 그 업소를 덮어쓰지 않는다."""
    records = (
        synthetic_record(),
        synthetic_record(record_id="r2", source_location="sheet1:R3"),
    )
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL, records=records)
    rooted = lookup()
    rooted["scope"]["record_id"] = "r1"
    rooted["candidates"] = [candidate("license", NEARBY, branch="부산점")]
    save_input(context, rooted, unsupported("r2", candidate("naver", NAVER)))
    assert run_cli(context, "geocode") == 0
    first, second = payload(context, "geocode")["results"]
    assert first["evidence"] == "name-branch-address-agreement"
    assert "merged-into" not in first["evidence"]
    assert (first["latitude"], first["longitude"]) == NEARBY
    # 채택한 쪽이 독립 근거 쪽으로 들어간다.
    assert second["business_id"] == first["business_id"]
    assert second["evidence"].endswith("merged-into license")


def test_a_merged_marker_names_the_source_that_gave_its_coordinate(tmp_path: Path) -> None:
    """합쳐진 레코드의 후보에는 그 좌표가 없다. 마커의 출처·주소는 좌표를 낸 레코드가 밝힌다."""
    records = (
        synthetic_record(merchant="같은 식당 상무점"),
        synthetic_record(record_id="r2", source_location="sheet1:R3"),
    )
    licensed = {"merchant": "같은 식당 상무점", "address": "부산 합성로 10-1"}
    context = in_city(tmp_path, CITY_PREFIX, hall=HALL, records=records)
    save_input(
        context,
        unsupported("r1", candidate("license", NEARBY, **licensed)),
        unsupported("r2", candidate("naver", NAVER)),
    )
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0
    merged, owner = payload(context, "geocode")["results"]
    assert merged["business_id"] == owner["business_id"]
    assert (merged["latitude"], merged["longitude"]) == NAVER
    marker = published(context, "markers.json")["markers"][0]
    assert marker["coordinate_source"] == "naver"
    assert marker["address"] == "부산 합성로 10"
    assert marker["visit_count"] == 2
