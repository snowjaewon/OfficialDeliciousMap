"""확정 업소의 업종을 실제 어댑터로 조회하고 외부 응답만 주입해 공개 CLI로 관찰한다."""

from pathlib import Path

import pytest

from deliciousmap.pipeline import ExecutionContext
from tests.fakes import (
    FakeLicenseTransport,
    FakeTransport,
    license_body,
    license_item,
    naver_body,
    naver_item,
)
from tests.test_geocoding_cli import lookup, payload, prepare, save_input
from tests.test_license_lookup_cli import SERVICE_KEY, licensed_place
from tests.test_license_lookup_cli import run_cli as license_cli
from tests.test_naver_lookup_cli import (
    CLIENT_ID,
    CLIENT_SECRET,
    ROAD_ADDRESS,
    evidence_only,
    geocoded,
    markers,
    run_cli,
)


@pytest.fixture
def searched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_SECRET", CLIENT_SECRET)


@pytest.fixture
def licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_GO_KR_KEY", SERVICE_KEY)


def history(context: ExecutionContext) -> str:
    path = context.paths.city_dir(context.target) / "geocode-history-v2.jsonl"
    return path.read_text(encoding="utf-8")


def build(context: ExecutionContext, transport: FakeTransport) -> list[dict]:
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage, transport=transport) == 0
    return markers(context)["markers"]


def test_a_naver_marker_carries_the_category_of_the_candidate_that_confirmed_it(
    tmp_path: Path, searched: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    # 첫 후보는 다른 업소다. 업종은 업소를 확정한 후보의 것만 쓴다.
    transport = FakeTransport(
        naver_body(
            naver_item("다른 식당 부산점", "부산 합성로 99", category="카페,디저트>카페"),
            naver_item("같은 식당 부산점", ROAD_ADDRESS, category="한식>육류,고기요리"),
        )
    )
    assert [marker["category"] for marker in build(context, transport)] == ["한식>육류,고기요리"]
    # 방금 받은 응답에 업종이 있다. 업종 때문에 같은 요청을 다시 보내지 않는다.
    assert len(transport.requests) == 1


def looked_up_before_confirmation(context: ExecutionContext) -> None:
    """조회는 캐시에 있고 업소는 그 뒤에 확정된 상태. 쌓인 광주 확정 업소가 이 경로다."""
    save_input(context, evidence_only(address=None))
    place = naver_body(naver_item("같은 식당 부산점", ROAD_ADDRESS, category="한식"))
    assert run_cli(context, "geocode", transport=FakeTransport(place)) == 0
    assert geocoded(context)["reason"] == "missing_address"
    save_input(context, evidence_only())


def test_a_business_confirmed_from_a_cached_lookup_asks_its_query_again(
    tmp_path: Path, searched: None
) -> None:
    context = prepare(tmp_path)
    looked_up_before_confirmation(context)
    transport = FakeTransport(
        naver_body(naver_item("같은 식당 부산점", ROAD_ADDRESS, category="한식>국밥"))
    )
    assert [marker["category"] for marker in build(context, transport)] == ["한식>국밥"]
    assert [request["query"] for request in transport.requests] == ["같은 식당"]
    # 얻은 업종은 쌓아 두고 다시 묻지 않는다.
    assert run_cli(context, "geocode", transport=transport) == 0
    assert len(transport.requests) == 1


def test_a_marker_whose_candidate_is_no_longer_found_stays_unknown(
    tmp_path: Path, searched: None
) -> None:
    context = prepare(tmp_path)
    looked_up_before_confirmation(context)
    # 업종을 다시 물었을 때는 확정한 후보가 빠지고 다른 업소만 온다.
    transport = FakeTransport(
        naver_body(naver_item("다른 식당 부산점", "부산 합성로 99", category="카페"))
    )
    assert [marker["category"] for marker in build(context, transport)] == ["미상"]


def test_a_candidate_supplied_without_a_lookup_is_not_asked_and_stays_unknown(
    tmp_path: Path, searched: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, lookup())
    transport = FakeTransport(naver_body(naver_item("같은 식당 부산점", ROAD_ADDRESS)))
    assert [marker["category"] for marker in build(context, transport)] == ["미상"]
    assert transport.requests == []


def test_a_failed_category_lookup_is_reported_and_reused_until_an_explicit_retry(
    tmp_path: Path, searched: None, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    looked_up_before_confirmation(context)
    place = naver_body(naver_item("같은 식당 부산점", ROAD_ADDRESS, category="한식"))
    transport = FakeTransport(OSError("timeout"), place)
    # 판정은 저장하되 업종을 얻지 못한 것을 성공으로 숨기지 않는다.
    assert run_cli(context, "geocode", transport=transport) == 1
    assert capsys.readouterr().err == "geocode city=seoul org=* cause=lookup-failed\n"
    assert geocoded(context)["status"] == "success"
    assert run_cli(context, "geocode", transport=transport) == 1
    assert len(transport.requests) == 1
    for stage in ("closure", "build"):
        assert run_cli(context, stage, transport=transport) == 0
    assert [marker["category"] for marker in markers(context)["markers"]] == ["미상"]

    assert run_cli(context, "geocode", "--retry-failed", transport=transport) == 0
    assert len(transport.requests) == 2
    assert [marker["category"] for marker in build(context, transport)] == ["한식"]


def test_categories_never_reach_the_identity_decision_or_its_key(
    tmp_path: Path, searched: None
) -> None:
    described, failed = prepare(tmp_path / "업종"), prepare(tmp_path / "실패")
    for context in (described, failed):
        looked_up_before_confirmation(context)
    place = naver_body(naver_item("같은 식당 부산점", ROAD_ADDRESS, category="한식"))
    assert run_cli(described, "geocode", transport=FakeTransport(place)) == 0
    assert run_cli(failed, "geocode", transport=FakeTransport(OSError("timeout"))) == 1
    # 업종을 얻든 못 얻든 판정 결과와 판정 키·이력은 같다.
    assert payload(described, "geocode") == payload(failed, "geocode")
    assert history(described) == history(failed)


def test_a_license_marker_carries_the_business_type_of_its_licence(
    tmp_path: Path, licensed: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    transport = FakeLicenseTransport(
        license_body(
            license_item(
                "다른 식당 부산점",
                "부산 합성로 99",
                management="3250000-101-2026-00002",
                category="호프/통닭",
            ),
            licensed_place(category="경양식"),
        )
    )
    for stage in ("geocode", "closure", "build"):
        assert license_cli(context, stage, licenses=transport) == 0
    assert [marker["category"] for marker in markers(context)["markers"]] == ["경양식"]
