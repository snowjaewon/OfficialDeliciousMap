"""인허가 조회와 그 후보의 채택을 공개 CLI로 관찰한다.

조회를 보는 시험은 실제 어댑터로 수행하고 외부 응답만 주입한다. 채택을 보는 시험은
후보를 담당자 입력으로 준다(`both`) — 네이버 우선 순서에서는 두 제공자의 후보가 함께
놓인 자리를 운영 조회가 만들지 않기 때문이다(`docs/adr/0011-ask-providers-in-order.md`).
"""

import json
from pathlib import Path

import pytest

from deliciousmap.cli import main
from deliciousmap.licenses import BASE_URL
from deliciousmap.pipeline import ExecutionContext
from deliciousmap.storage import write_text
from tests.fakes import (
    LICENSE_SERVICES,
    FakeLicenseTransport,
    FakeTransport,
    license_body,
    license_item,
    naver_body,
)
from tests.test_geocoding_cli import payload, prepare, save_input
from tests.test_naver_lookup_cli import (
    CLIENT_ID,
    CLIENT_SECRET,
    ROAD_ADDRESS,
    cache_lines,
    evidence_only,
    geocoded,
    markers,
    matching_place,
)

SERVICE_KEY = "합성-인허가-서비스키"
# 중부원점TM(EPSG:5174) 좌표 한 쌍과 그 WGS84 변환 결과. 네이버 좌표(35.1, 129.1)에서 약 300 m
# 북쪽이라 허용 오차 200 m 밖이다. 오차 안의 좌표는 `NEARBY`다.
LICENSE_X, LICENSE_Y = "391413.5", "180197.3"
LATITUDE, LONGITUDE = 35.10270223741562, 129.10006886326784
# 같은 pyproj·PROJ라도 플랫폼 수학 라이브러리에 따라 변환값의 마지막 자리(1 ULP)가 다르다.
# Windows는 위 값, Linux CI는 위도 끝자리가 3이다. 1e-9도는 약 0.1 mm라 좌표 비교는 이 오차로 본다.
COORDINATE_TOLERANCE = 1e-9
# 네이버 좌표에서 약 9 m 북동쪽. 허용 오차 200 m 안이라 같은 건물로 본다.
NEARBY = 35.10006


@pytest.fixture
def licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """개발자 PC의 .env 처럼 인허가 조회 키가 준비된 상태."""
    monkeypatch.setenv("DATA_GO_KR_KEY", SERVICE_KEY)


@pytest.fixture
def searched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_SECRET", CLIENT_SECRET)


def run_cli(
    context: ExecutionContext,
    stage: str,
    *extra: str,
    licenses: FakeLicenseTransport | None = None,
    naver: FakeTransport | None = None,
) -> int:
    return main(
        [
            stage,
            "--city",
            context.target.city.slug,
            "--raw-root",
            str(context.paths.raw_root),
            "--data-root",
            str(context.paths.data_root),
            "--output-root",
            str(context.paths.output_root),
            *extra,
        ],
        cities=(context.target.city,),
        naver_transport=naver,
        license_transport=licenses,
    )


def licensed_place(name: str = "같은 식당 부산점", **fields: str) -> dict[str, str]:
    return license_item(name, ROAD_ADDRESS, x=LICENSE_X, y=LICENSE_Y, **fields)


def sources(context: ExecutionContext) -> list[str]:
    return [item["source"]["provider"] for item in geocoded(context)["lookup"]["candidates"]]


def naver_candidate(**fields: object) -> dict:
    return {
        "source": {
            "provider": "naver",
            "source_id": "naver-place",
            "reference": "https://example.invalid/naver/1",
        },
        "merchant": "같은 식당",
        "branch": "부산점",
        "address": ROAD_ADDRESS,
        "latitude": 35.1,
        "longitude": 129.1,
        **fields,
    }


def license_candidate(**fields: object) -> dict:
    return {
        "source": {
            "provider": "license",
            "source_id": "3250000-101-2026-00001",
            "reference": "https://example.invalid/license/1",
        },
        "merchant": "같은 식당",
        "branch": "부산점",
        "address": ROAD_ADDRESS,
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        **fields,
    }


def both(*candidates: dict) -> dict:
    """두 제공자의 후보가 함께 놓인 입력. 조회가 아니라 준비된 후보로 만든다.

    네이버 우선 순서에서는 네이버가 후보를 낸 레코드를 인허가에 다시 묻지 않으므로
    (`tests/test_provider_order_cli.py`), 두 제공자의 후보가 함께 놓인 자리는 운영 조회로
    만들어지지 않는다. 담당자 후보 파일·캐시로는 그대로 생기며, 아래 시험이 보는 것은
    조회 순서가 아니라 후보를 맞대는 규칙이다.
    """
    query = evidence_only()
    query["candidates"] = list(candidates)
    return query


def test_license_candidates_convert_coordinates_and_reach_the_marker(
    tmp_path: Path, licensed: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    # 응답 순서는 근거가 아니다. 근거가 가리키는 업소만 채택해야 한다.
    transport = FakeLicenseTransport(
        license_body(
            license_item("다른 식당 부산점", "부산 합성로 99", x="391000.0", y="179000.0"),
            licensed_place(),
        )
    )
    assert run_cli(context, "geocode", licenses=transport) == 0
    result = geocoded(context)
    assert result["status"] == "success"
    assert (result["latitude"], result["longitude"]) == pytest.approx(
        (LATITUDE, LONGITUDE), abs=COORDINATE_TOLERANCE
    )
    assert result["confirmed_merchant"] == "같은 식당"
    assert sources(context) == ["license", "license"]
    query = result["lookup"]["queries"][0]
    assert (query["provider"], query["request"], query["status"]) == ("license", "같은 식당", "ok")
    assert query["cache"]["revision"] == 1

    # 마커가 될 수 있는 세 업종을 모두 조회하고, 요청 맥락의 도시는 질의에 넣지 않는다.
    assert [url.rstrip("/").split("/")[-2] for url in transport.urls] == list(LICENSE_SERVICES)
    assert transport.requests[0]["cond[BPLC_NM::LIKE]"] == "같은 식당"
    assert transport.requests[0]["numOfRows"] == "100"
    assert "seoul" not in json.dumps(transport.requests[0], ensure_ascii=False)

    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert markers(context)["markers"][0]["latitude"] == pytest.approx(
        LATITUDE, abs=COORDINATE_TOLERANCE
    )
    assert markers(context)["markers"][0]["visit_count"] == 1
    assert payload(context, "build")["marker_count"] == 1


def test_local_and_license_supplied_facts_reach_the_same_business_and_marker(
    tmp_path: Path, licensed: None
) -> None:
    local, remote = prepare(tmp_path / "로컬"), prepare(tmp_path / "인허가")
    supplied = evidence_only()
    supplied["candidates"] = [
        {
            "source": {
                "provider": "license",
                "source_id": "general_restaurants/3250000-101-2026-00001",
                "reference": "https://apis.data.go.kr/1741000/general_restaurants/info",
            },
            "merchant": "같은 식당",
            "branch": "부산점",
            "address": ROAD_ADDRESS,
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
        }
    ]
    save_input(local, supplied)
    save_input(remote, evidence_only())
    transport = FakeLicenseTransport(license_body(licensed_place()))
    for context in (local, remote):
        for stage in ("geocode", "closure", "build"):
            assert run_cli(context, stage, licenses=transport) == 0
    # 담당자가 후보를 준 레코드는 조회하지 않는다. 두 경로의 업소 판정과 마커는 같아야 한다.
    assert len(transport.urls) == len(LICENSE_SERVICES)
    assert geocoded(local)["business_id"] == geocoded(remote)["business_id"]
    assert geocoded(local)["reason"] == geocoded(remote)["reason"] == "matched"
    supplied, searched = markers(local)["markers"], markers(remote)["markers"]
    # 업종은 조회로 찾은 후보만 안다. 담당자가 준 후보는 다시 물을 조회가 없다.
    assert [(marker.pop("category"), marker.pop("category_group")) for marker in supplied] == [
        ("미상", "미상")
    ]
    assert [(marker.pop("category"), marker.pop("category_group")) for marker in searched] == [
        ("한식", "한식")
    ]
    # 담당자가 준 좌표는 원값 그대로, 조회한 좌표는 pyproj 변환값이라 마지막 자리가 다를 수 있다.
    for key in ("latitude", "longitude"):
        assert supplied[0].pop(key) == pytest.approx(searched[0].pop(key), abs=COORDINATE_TOLERANCE)
    assert supplied == searched


def test_license_coordinates_complete_a_naver_candidate_without_usable_ones(
    tmp_path: Path,
) -> None:
    context = prepare(tmp_path)
    # 네이버 후보의 좌표계를 확인할 수 없다. 같은 업소의 인허가 좌표로 보강한다.
    save_input(context, both(naver_candidate(latitude=None, longitude=None), license_candidate()))
    assert run_cli(context, "geocode") == 0
    result = geocoded(context)
    assert result["status"] == "success"
    assert (result["latitude"], result["longitude"]) == pytest.approx(
        (LATITUDE, LONGITUDE), abs=COORDINATE_TOLERANCE
    )
    assert sources(context) == ["naver", "license"]
    assert result["lookup"]["candidates"][0]["latitude"] is None
    assert result["evidence"] == "name-branch-address-agreement license+naver"
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["marker_count"] == 1


def test_license_coordinates_within_the_tolerance_agree_and_naver_coordinates_win(
    tmp_path: Path,
) -> None:
    """변환 오차 수준으로 어긋난 두 좌표는 같은 업소다. 마커는 원값인 네이버 좌표를 쓴다."""
    context = prepare(tmp_path)
    save_input(context, both(naver_candidate(), license_candidate(latitude=NEARBY)))
    assert run_cli(context, "geocode") == 0
    result = geocoded(context)
    assert result["reason"] == "matched"
    assert (result["latitude"], result["longitude"]) == (35.1, 129.1)
    assert result["evidence"] == "name-branch-address-agreement license+naver"


def test_conflicting_provider_coordinates_wait_for_a_scoped_confirmation(
    tmp_path: Path,
) -> None:
    context = prepare(tmp_path)
    save_input(context, both(naver_candidate(), license_candidate()))
    assert run_cli(context, "geocode") == 0
    result = geocoded(context)
    assert result["reason"] == "conflicting_evidence"
    assert result["business_id"] is None
    assert sources(context) == ["naver", "license"]
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["marker_count"] == 0

    # 담당자가 산출물의 후보 중 하나를 근거와 함께 확정하면 그 출처의 좌표만 쓴다.
    chosen = result["lookup"]["candidates"][0]
    write_text(
        context.paths.data_root / "manual" / "seoul" / "geocode.jsonl",
        json.dumps(
            {
                "scope": {**result["lookup"]["scope"], "merchant": "같은 식당"},
                "candidate_source": chosen["source"],
                "merchant": "같은 식당",
                "branch": "부산점",
                "address": ROAD_ADDRESS,
                "evidence": "https://example.invalid/disclosure/visited 담당자 현장 확인",
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    assert run_cli(context, "geocode") == 0
    confirmed = geocoded(context)
    assert confirmed["reason"] == "human_confirmed"
    assert (confirmed["latitude"], confirmed["longitude"]) == (35.1, 129.1)


@pytest.mark.parametrize(
    "items,found",
    [
        ({"item": [licensed_place()]}, True),
        # 한 건이면 목록 없이 객체 하나로 올 수 있다. 조용히 버리면 0건으로 숨는다.
        ({"item": licensed_place()}, True),
        ({"item": []}, False),
        ({}, False),
        ("", False),
    ],
)
def test_single_row_responses_are_read_without_hiding_them_as_zero(
    tmp_path: Path, licensed: None, items: object, found: bool
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    body = json.dumps(
        {
            "response": {
                "header": {"resultCode": "0", "resultMsg": "정상"},
                "body": {"numOfRows": 100, "pageNo": 1, "totalCount": 1, "items": items},
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    assert run_cli(context, "geocode", licenses=FakeLicenseTransport(body)) == 0
    result = geocoded(context)
    expected = ("success", "matched") if found else ("failed", "no_candidates")
    assert (result["status"], result["reason"]) == expected


def test_the_services_own_success_envelope_is_read_as_success(
    tmp_path: Path, licensed: None
) -> None:
    """조회서비스는 성공을 `resultCode` "0"·`resultMsg` "정상"으로 알린다(#73 실측)."""
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    body = json.dumps(
        {
            "response": {
                "header": {"resultCode": "0", "resultMsg": "정상"},
                "body": {
                    "dataType": "json",
                    "numOfRows": 100,
                    "pageNo": 1,
                    "totalCount": 1,
                    "items": {"item": [licensed_place()]},
                },
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    assert run_cli(context, "geocode", licenses=FakeLicenseTransport(body)) == 0
    result = geocoded(context)
    assert (result["status"], result["reason"]) == ("success", "matched")
    assert sources(context) == ["license"]


def test_indistinguishable_candidates_from_one_provider_stay_ambiguous(
    tmp_path: Path, licensed: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    transport = FakeLicenseTransport(
        license_body(
            licensed_place(management="3250000-101-2026-00001"),
            licensed_place(management="3250000-101-2026-00002"),
        )
    )
    assert run_cli(context, "geocode", licenses=transport) == 0
    result = geocoded(context)
    assert result["reason"] == "ambiguous"
    assert result["business_id"] is None
    assert len(result["lookup"]["candidates"]) == 2


def test_provider_spellings_and_identifiers_do_not_decide_identity(
    tmp_path: Path,
) -> None:
    context = prepare(tmp_path)
    # 같은 관리번호라도 표기가 근거와 다르면 같은 업소로 보지 않는다.
    save_input(context, both(naver_candidate(), license_candidate(address="부산 합성동 1-2")))
    assert run_cli(context, "geocode") == 0
    result = geocoded(context)
    assert result["status"] == "success"
    assert (result["latitude"], result["longitude"]) == (35.1, 129.1)
    assert sources(context) == ["naver", "license"]
    assert result["lookup"]["candidates"][1]["address"] == "부산 합성동 1-2"
    # 업소 ID는 확인된 상호·지점·주소에서만 나온다. 제공자 ID는 들어가지 않는다.
    assert "3250000-101-2026-00001" not in json.dumps(result["business_id"])


@pytest.mark.parametrize(
    "x,y",
    [("", ""), ("0", "0"), ("2000000", "2000000"), ("좌표없음", "좌표없음"), ("1e9", "1e9")],
)
def test_unreadable_license_coordinates_are_never_guessed(
    tmp_path: Path, licensed: None, x: str, y: str
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    transport = FakeLicenseTransport(
        license_body(license_item("같은 식당 부산점", ROAD_ADDRESS, x=x, y=y))
    )
    assert run_cli(context, "geocode", licenses=transport) == 0
    result = geocoded(context)
    candidate = result["lookup"]["candidates"][0]
    assert (candidate["merchant"], candidate["branch"]) == ("같은 식당", "부산점")
    assert (candidate["latitude"], candidate["longitude"]) == (None, None)
    assert result["reason"] == "missing_coordinates"
    assert result["business_id"] is None


@pytest.mark.parametrize(
    "response,error",
    [
        (TimeoutError("제공자 원문 오류"), "unavailable"),
        (license_body(result_code="-10"), "unavailable"),
        ("<html>제공자 오류 문서</html>".encode(), "invalid_response"),
    ],
)
def test_license_failure_after_an_empty_naver_lookup_is_not_hidden(
    tmp_path: Path,
    licensed: None,
    searched: None,
    capsys: pytest.CaptureFixture[str],
    response: bytes | Exception,
    error: str,
) -> None:
    """네이버가 못 찾아 인허가에 물은 뒤의 실패를 빈 후보로 덮지 않는다."""
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    naver = FakeTransport(naver_body())
    licenses = FakeLicenseTransport(response, license_body(licensed_place()))
    assert run_cli(context, "geocode", licenses=licenses, naver=naver) == 1
    assert capsys.readouterr().err == "geocode city=seoul org=* cause=lookup-failed\n"
    result = geocoded(context)
    assert result["reason"] == "lookup_error"
    assert result["lookup"]["error"] == error
    assert [item["status"] for item in result["lookup"]["queries"]] == ["ok", "error"]
    # 두 제공자 모두 후보를 주지 못했고, 실패는 실패로 남는다.
    assert sources(context) == []
    assert result["business_id"] is None
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["record_count"] == 1
    assert payload(context, "build")["marker_count"] == 0


def test_provider_caches_stay_separate_and_reused_until_an_explicit_retry(
    tmp_path: Path, licensed: None, searched: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    naver = FakeTransport(naver_body())
    licenses = FakeLicenseTransport(
        TimeoutError("제공자 원문 오류"), license_body(licensed_place())
    )
    assert run_cli(context, "geocode", licenses=licenses, naver=naver) == 1
    assert run_cli(context, "geocode", licenses=licenses, naver=naver) == 1
    # 변경 없는 재실행은 제공자마다 한 번씩 남은 결과를 그대로 쓴다.
    # 한 업종이 실패하면 남은 업종을 조회하지 않고 그 조회 전체를 실패로 남긴다.
    assert len(naver.requests) == 1
    assert licenses.urls == [f"{BASE_URL}/general_restaurants/info"]
    entries = cache_lines(context)
    assert len({entry["key"] for entry in entries}) == 2
    assert sorted(entry["evidence"].split("/")[0] for entry in entries) == ["license", "naver"]
    assert "business_id" not in json.dumps(entries, ensure_ascii=False)

    assert run_cli(context, "geocode", "--retry-failed", licenses=licenses, naver=naver) == 0
    assert len(naver.requests) == 1
    assert [url.rstrip("/").split("/")[-2] for url in licenses.urls[1:]] == list(LICENSE_SERVICES)
    # 네이버가 비운 자리를 인허가가 채웠고, 그 후보만 담당자 근거와 맞는다.
    assert geocoded(context)["reason"] == "matched"
    # 실패한 인허가 조회만 새 revision을 얻고 네이버는 처음 결과를 그대로 쓴다.
    # 줄 순서는 키 해시를 따르므로 제공자별로 모아 본다.
    revisions: dict[str, list[int]] = {}
    for entry in cache_lines(context):
        revisions.setdefault(entry["evidence"].split("/")[0], []).append(entry["revision"])
    assert revisions == {"license": [1, 2], "naver": [1]}


def test_without_a_license_key_the_existing_path_is_unchanged(
    tmp_path: Path, searched: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    naver = FakeTransport(naver_body(matching_place()))
    licenses = FakeLicenseTransport(license_body(licensed_place()))
    assert run_cli(context, "geocode", licenses=licenses, naver=naver) == 0
    assert licenses.urls == []
    assert sources(context) == ["naver"]
    assert geocoded(context)["latitude"] == 35.1


def test_license_key_and_response_never_reach_artifacts_or_output(
    tmp_path: Path, licensed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    transport = FakeLicenseTransport(
        RuntimeError(f"제공자 원문 {SERVICE_KEY}"), license_body(licensed_place())
    )
    assert run_cli(context, "geocode", licenses=transport) == 1
    assert run_cli(context, "geocode", "--retry-failed", licenses=transport) == 0
    assert capsys.readouterr().err == "geocode city=seoul org=* cause=lookup-failed\n"
    assert transport.headers[0].get("X-NCP-APIGW-API-KEY") is None
    assert transport.requests[0]["serviceKey"] == SERVICE_KEY
    stored = "\n".join(
        path.read_text(encoding="utf-8")
        for path in context.paths.data_root.rglob("*")
        if path.is_file()
    )
    for secret in (SERVICE_KEY, "제공자 원문", "051-000-0000", "영업/정상", "20200101"):
        assert secret not in stored


def test_changed_license_evidence_blocks_a_stale_build(tmp_path: Path, licensed: None) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    transport = FakeLicenseTransport(license_body(), license_body(licensed_place()))
    assert run_cli(context, "geocode", licenses=transport) == 0
    assert geocoded(context)["reason"] == "no_candidates"
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["marker_count"] == 0

    # 정상 조회의 후보 없음은 실패가 아니므로 다시 요청하지 않는다.
    assert run_cli(context, "geocode", "--retry-failed", licenses=transport) == 0
    assert len(transport.urls) == len(LICENSE_SERVICES)
    assert geocoded(context)["reason"] == "no_candidates"

    write_text(context.paths.city_dir(context.target) / "geocode-lookup-v1.jsonl", "")
    assert run_cli(context, "build") == 1
    assert run_cli(context, "geocode", licenses=transport) == 0
    assert geocoded(context)["status"] == "success"
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["marker_count"] == 1
