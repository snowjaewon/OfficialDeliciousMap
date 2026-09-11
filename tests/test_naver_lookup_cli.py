"""네이버 조회를 실제 어댑터로 수행하고 외부 응답만 주입해 공개 CLI로 관찰한다."""

import json
from pathlib import Path

import pytest

from deliciousmap.cli import main
from deliciousmap.pipeline import ExecutionContext
from deliciousmap.storage import write_text
from tests.fakes import FakeTransport, naver_body, naver_item
from tests.test_geocoding_cli import lookup, payload, prepare, save_input
from tests.test_restoration_cli import FULL_NAME, classify_records, restore_entry, save_restorations

CLIENT_ID = "합성-검색-아이디"
CLIENT_SECRET = "합성-검색-비밀값"
ROAD_ADDRESS = "부산 합성로 10"


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """개발자 PC의 .env 처럼 검색 키가 준비된 상태."""
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_SECRET", CLIENT_SECRET)


def run_cli(
    context: ExecutionContext,
    stage: str,
    *extra: str,
    transport: FakeTransport | None = None,
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
        naver_transport=transport,
    )


def evidence_only(record_id: str = "r1", **facts: object) -> dict:
    """담당자가 독립 근거만 준비하고 후보 조회는 운영 경로에 맡긴 입력."""
    query = lookup()
    query["scope"]["record_id"] = record_id
    query["candidates"] = []
    query["facts"][0].update(facts)
    return query


def matching_place(title: str = "<b>같은 식당</b> 부산점") -> dict[str, str]:
    return naver_item(title, ROAD_ADDRESS)


def geocoded(context: ExecutionContext) -> dict:
    return payload(context, "geocode")["results"][0]


def markers(context: ExecutionContext) -> dict:
    return json.loads(
        (context.paths.output_root / "seoul" / "markers.json").read_text(encoding="utf-8")
    )


def cache_lines(context: ExecutionContext) -> list[dict]:
    path = context.paths.city_dir(context.target) / "geocode-lookup-v1.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_naver_candidates_need_independent_evidence_and_keep_out_of_city_coordinates(
    tmp_path: Path, configured: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    # 검색 순위 첫 후보는 다른 업소다. 근거가 가리키는 후보만 채택해야 한다.
    transport = FakeTransport(
        naver_body(
            naver_item("다른 식당 부산점", "부산 합성로 99", mapx="1299000000", mapy="359000000"),
            matching_place(),
        )
    )
    assert run_cli(context, "geocode", transport=transport) == 0
    result = geocoded(context)
    assert result["status"] == "success"
    assert (result["latitude"], result["longitude"]) == (35.1, 129.1)
    assert result["confirmed_merchant"] == "같은 식당"
    assert [item["source"]["provider"] for item in result["lookup"]["candidates"]] == [
        "naver",
        "naver",
    ]
    query = result["lookup"]["queries"][0]
    assert (query["provider"], query["request"], query["status"]) == ("naver", "같은 식당", "ok")
    assert query["cache"]["revision"] == 1

    # 요청 맥락의 도시는 소재지 근거가 아니다. 질의에 도시를 끼워 넣지 않는다.
    assert len(transport.requests) == 1
    assert transport.requests[0]["query"] == "같은 식당"
    assert "seoul" not in json.dumps(transport.requests[0], ensure_ascii=False)
    assert transport.headers[0]["X-NCP-APIGW-API-KEY-ID"] == CLIENT_ID
    assert transport.headers[0]["X-NCP-APIGW-API-KEY"] == CLIENT_SECRET

    for stage in ("closure", "build"):
        assert run_cli(context, stage, transport=transport) == 0
    built = markers(context)
    assert built["candidates"][0]["record_ids"] == ["r1"]
    assert built["candidates"][0]["latitude"] == 35.1
    assert built["records"][0]["organization"] == "test-org"
    assert payload(context, "build")["record_count"] == 1


def test_local_and_naver_supplied_facts_reach_the_same_business_and_marker(
    tmp_path: Path, configured: None
) -> None:
    local, remote = prepare(tmp_path / "로컬"), prepare(tmp_path / "네이버")
    save_input(local, lookup())
    save_input(remote, evidence_only())
    transport = FakeTransport(naver_body(matching_place()))
    for context in (local, remote):
        for stage in ("geocode", "closure", "build"):
            assert run_cli(context, stage, transport=transport) == 0
    # 로컬 후보가 있으면 조회하지 않는다. 두 경로의 업소 판정과 마커는 같아야 한다.
    assert len(transport.requests) == 1
    assert geocoded(local)["business_id"] == geocoded(remote)["business_id"]
    assert geocoded(local)["reason"] == geocoded(remote)["reason"] == "matched"
    assert markers(local)["candidates"] == markers(remote)["candidates"]
    assert markers(local)["closures"] == markers(remote)["closures"]


def test_unchanged_lookup_is_reused_and_stays_apart_from_the_identity_decision(
    tmp_path: Path, configured: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    transport = FakeTransport(naver_body(matching_place()))
    assert run_cli(context, "geocode", transport=transport) == 0
    assert run_cli(context, "geocode", transport=transport) == 0
    assert len(transport.requests) == 1
    directory = context.paths.city_dir(context.target)
    assert len(cache_lines(context)) == 1
    assert (directory / "geocode-history-v2.jsonl").exists()
    entry = cache_lines(context)[0]
    assert entry["value"]["status"] == "ok"
    assert "business_id" not in json.dumps(entry, ensure_ascii=False)

    # 캐시 적중이 동일 업소 확정은 아니다. 근거가 사라지면 같은 후보로도 확정하지 않는다.
    save_input(context, evidence_only(address=None))
    assert run_cli(context, "geocode", transport=transport) == 0
    assert len(transport.requests) == 1
    result = geocoded(context)
    assert result["reason"] == "missing_address"
    assert result["business_id"] is None
    assert len(result["lookup"]["candidates"]) == 1


def test_failed_lookup_is_reused_until_an_explicit_retry(
    tmp_path: Path, configured: None, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    transport = FakeTransport(TimeoutError("제공자 원문 오류"), naver_body(matching_place()))
    assert run_cli(context, "geocode", transport=transport) == 1
    assert capsys.readouterr().err == "geocode city=seoul org=* cause=lookup-failed\n"
    result = geocoded(context)
    assert result["reason"] == "lookup_error"
    assert result["lookup"]["error"] == "unavailable"
    assert result["lookup"]["queries"][0]["error"] == "unavailable"

    assert run_cli(context, "geocode", transport=transport) == 1
    assert len(transport.requests) == 1
    assert run_cli(context, "geocode", "--retry-failed", transport=transport) == 0
    assert len(transport.requests) == 2
    assert geocoded(context)["status"] == "success"
    assert [entry["revision"] for entry in cache_lines(context)] == [1, 2]
    assert [entry["value"]["status"] for entry in cache_lines(context)] == ["error", "ok"]


@pytest.mark.parametrize(
    "response,reason,error,code",
    [
        (TimeoutError("제공자 원문 오류"), "lookup_error", "unavailable", 1),
        ("<html>제공자 오류 문서</html>".encode(), "lookup_error", "invalid_response", 1),
        (naver_body(), "no_candidates", None, 0),
    ],
)
def test_lookup_failure_and_empty_result_are_distinguished(
    tmp_path: Path,
    configured: None,
    response: bytes | Exception,
    reason: str,
    error: str | None,
    code: int,
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    assert run_cli(context, "geocode", transport=FakeTransport(response)) == code
    result = geocoded(context)
    assert result["reason"] == reason
    assert result["lookup"]["error"] == error
    assert result["lookup"]["candidates"] == []
    assert result["business_id"] is None
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["record_count"] == 1
    assert payload(context, "build")["marker_count"] == 0


def test_candidates_without_confirming_evidence_stay_unresolved(
    tmp_path: Path, configured: None
) -> None:
    context = prepare(tmp_path)
    save_input(context)
    transport = FakeTransport(naver_body(matching_place()))
    assert run_cli(context, "geocode", transport=transport) == 0
    result = geocoded(context)
    assert result["lookup"]["status"] == "ok"
    assert len(result["lookup"]["candidates"]) == 1
    assert result["reason"] == "missing_address"
    assert result["business_id"] is None
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["marker_count"] == 0


def test_keys_and_provider_response_never_reach_artifacts_or_output(
    tmp_path: Path, configured: None, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    transport = FakeTransport(
        RuntimeError(f"제공자 원문 {CLIENT_SECRET}"), naver_body(matching_place())
    )
    assert run_cli(context, "geocode", transport=transport) == 1
    assert run_cli(context, "geocode", "--retry-failed", transport=transport) == 0
    assert capsys.readouterr().err == "geocode city=seoul org=* cause=lookup-failed\n"
    stored = "\n".join(
        path.read_text(encoding="utf-8")
        for path in context.paths.data_root.rglob("*")
        if path.is_file()
    )
    for secret in (CLIENT_ID, CLIENT_SECRET, "제공자 원문", "051-000-0000", "합성 설명"):
        assert secret not in stored


def test_confirmed_restoration_requeries_and_updates_the_affected_decision(
    tmp_path: Path, configured: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only(merchant=FULL_NAME))
    transport = FakeTransport(
        naver_body(matching_place()), naver_body(matching_place(f"{FULL_NAME} 부산점"))
    )
    assert run_cli(context, "geocode", transport=transport) == 0
    assert geocoded(context)["reason"] == "unconfirmed_name"

    save_restorations(context, restore_entry())
    classify_records(context)
    assert run_cli(context, "geocode", transport=transport) == 0
    assert [request["query"] for request in transport.requests] == ["같은 식당", FULL_NAME]
    result = geocoded(context)
    assert result["status"] == "success"
    assert result["merchant"] == "같은 식당"
    assert result["confirmed_merchant"] == FULL_NAME
    assert result["lookup"]["queries"][0]["request"] == FULL_NAME
    # 다른 요청 맥락의 조회는 서로 다른 캐시 항목으로 남는다.
    assert [entry["revision"] for entry in cache_lines(context)] == [1, 1]
    assert len({entry["key"] for entry in cache_lines(context)}) == 2


def test_place_name_and_coordinate_interpretation_never_guesses(
    tmp_path: Path, configured: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only(branch="", address="부산 합성로 10"))
    transport = FakeTransport(
        naver_body(naver_item("<b>같은 식당</b>", ROAD_ADDRESS, mapx="443000", mapy="128000"))
    )
    assert run_cli(context, "geocode", transport=transport) == 0
    result = geocoded(context)
    candidate = result["lookup"]["candidates"][0]
    assert (candidate["merchant"], candidate["branch"]) == ("같은 식당", "")
    assert candidate["address"] == ROAD_ADDRESS
    # 좌표계를 확인할 수 없는 값은 추측하지 않는다.
    assert (candidate["latitude"], candidate["longitude"]) == (None, None)
    assert result["reason"] == "missing_coordinates"


def test_without_search_keys_the_local_only_path_is_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    save_input(context)
    transport = FakeTransport(naver_body(matching_place()))
    assert run_cli(context, "geocode", transport=transport) == 1
    assert capsys.readouterr().err == "geocode city=seoul org=* cause=lookup-failed\n"
    assert transport.requests == []
    assert cache_lines(context) == []
    assert geocoded(context)["lookup"]["error"] == "not_supplied"


def test_incomplete_search_keys_are_rejected_before_any_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_ID", CLIENT_ID)
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    transport = FakeTransport(naver_body(matching_place()))
    assert run_cli(context, "geocode", transport=transport) == 2
    assert "NAVER_SEARCH_CLIENT_SECRET" in capsys.readouterr().err
    assert transport.requests == []
    assert not (context.paths.city_dir(context.target) / "geocode.json").exists()


def test_supplied_lookup_failure_is_not_replaced_by_a_provider_success(
    tmp_path: Path, configured: None
) -> None:
    context = prepare(tmp_path)
    query = evidence_only()
    query.update(status="error", error="unavailable")
    save_input(context, query)
    transport = FakeTransport(naver_body(matching_place()))
    assert run_cli(context, "geocode", transport=transport) == 1
    assert transport.requests == []
    assert geocoded(context)["reason"] == "lookup_error"


def test_changed_lookup_cache_blocks_a_stale_build(tmp_path: Path, configured: None) -> None:
    context = prepare(tmp_path)
    save_input(context, evidence_only())
    transport = FakeTransport(TimeoutError("제공자 원문 오류"), naver_body(matching_place()))
    assert run_cli(context, "geocode", transport=transport) == 1
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["marker_count"] == 0
    assert run_cli(context, "geocode", "--retry-failed", transport=transport) == 0
    assert run_cli(context, "build", transport=transport) == 1
    for stage in ("closure", "build"):
        assert run_cli(context, stage, transport=transport) == 0
    assert payload(context, "build")["marker_count"] == 1
    write_text(context.paths.city_dir(context.target) / "geocode-lookup-v1.jsonl", "")
    assert run_cli(context, "build", transport=transport) == 1
