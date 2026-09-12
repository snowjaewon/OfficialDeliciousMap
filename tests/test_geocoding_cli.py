"""Real local geocoding observed through the public CLI and its artifacts."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from deliciousmap.cli import main
from deliciousmap.contracts import Classification, ClassifyOutput, ParseOutput, Record
from deliciousmap.pipeline import ExecutionContext
from deliciousmap.registry import Target
from deliciousmap.storage import ArtifactStore, write_text
from tests.test_pipeline import context_at


def prepare(tmp_path: Path, org: str | None = None) -> ExecutionContext:
    context = context_at(tmp_path)
    if org is not None:
        context = replace(context, target=Target(context.target.city, org))
    record = Record(
        record_id="r1",
        spent_on="2026-01-02",
        organization="test-org",
        department="총무과",
        merchant="같은 식당",
        purpose="출장 식사",
        amount_krw="1000",
        source_hash="a" * 64,
        source_location="sheet1:R2",
    )
    store = ArtifactStore(context.paths, context.target)
    store.save("parse", ParseOutput(records=(record,)))
    store.save(
        "classify",
        ClassifyOutput(
            decisions=(
                Classification(
                    record_id="r1",
                    status="restaurant",
                    evidence="합성 분류",
                ),
            )
        ),
    )
    return context


def run_cli(context: ExecutionContext, stage: str, *extra: str) -> int:
    return main(
        [
            stage,
            "--city",
            context.target.city.slug,
            *(("--org", context.target.org) if context.target.org else ()),
            "--raw-root",
            str(context.paths.raw_root),
            "--data-root",
            str(context.paths.data_root),
            "--output-root",
            str(context.paths.output_root),
            *extra,
        ],
        cities=(context.target.city,),
    )


def lookup() -> dict:
    return {
        "scope": {
            "city": "seoul",
            "organization": "test-org",
            "record_id": "r1",
            "source_hash": "a" * 64,
        },
        "status": "ok",
        "error": None,
        "facts": [
            {
                "merchant": "같은 식당",
                "branch": "부산점",
                "address": "부산 합성로 10",
                "source": "https://example.invalid/disclosure/1",
            }
        ],
        "candidates": [
            {
                "source": {
                    "provider": "local",
                    "source_id": "place-1",
                    "reference": "https://example.invalid/places/1",
                },
                "merchant": "같은 식당",
                "branch": "부산점",
                "address": "부산 합성로 10",
                "latitude": 35.1,
                "longitude": 129.1,
            }
        ],
    }


def save_input(context: ExecutionContext, *queries: dict) -> None:
    write_text(
        context.paths.city_dir(context.target) / "geocode-input.json",
        json.dumps({"schema_version": 1, "lookups": queries}, ensure_ascii=False),
    )


def payload(context: ExecutionContext, stage: str) -> dict:
    return json.loads(
        (context.paths.city_dir(context.target) / f"{stage}.json").read_text(encoding="utf-8")
    )["payload"]


def test_cli_confirms_evidence_and_builds_actual_out_of_city_marker(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    save_input(context, lookup())
    assert run_cli(context, "geocode") == 0
    result = payload(context, "geocode")["results"][0]
    assert result["record_id"] == "r1"
    assert result["merchant"] == "같은 식당"
    assert result["status"] == "success"
    assert result["latitude"] == 35.1
    assert result["business_id"]
    assert result["lookup"]["scope"]["city"] == "seoul"
    assert result["lookup"]["facts"][0]["source"].endswith("disclosure/1")
    assert run_cli(context, "closure") == 0
    assert run_cli(context, "build") == 0
    built = json.loads(
        (context.paths.output_root / "seoul" / "markers.json").read_text(encoding="utf-8")
    )
    records = json.loads(
        (context.paths.output_root / "seoul" / "records.json").read_text(encoding="utf-8")
    )
    assert records["records"][0]["organization"] == "test-org"
    assert built["markers"][0]["business_id"] == result["business_id"]
    assert built["markers"][0]["latitude"] == 35.1
    assert built["markers"][0]["visit_count"] == 1
    assert built["markers"][0]["closed"] is False


def test_build_separates_map_data_from_complete_record_list(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    add_record(context, "r2", "non_restaurant")
    add_record(context, "r3", "pending")
    add_record(context, "r4")
    unresolved = lookup()
    unresolved["scope"]["record_id"] = "r4"
    unresolved["facts"] = []
    unresolved["candidates"] = []
    save_input(context, lookup(), unresolved)
    assert run_cli(context, "geocode") == 0
    assert run_cli(context, "closure") == 0
    assert run_cli(context, "build") == 0

    directory = context.paths.output_root / "seoul"
    markers = json.loads((directory / "markers.json").read_text(encoding="utf-8"))
    records = json.loads((directory / "records.json").read_text(encoding="utf-8"))

    assert "records" not in markers
    assert markers["markers"] == [
        {
            "business_id": markers["markers"][0]["business_id"],
            "closed": False,
            "coordinate_source": "local",
            "latitude": 35.1,
            "longitude": 129.1,
            "merchant": "같은 식당",
            "visit_count": 1,
        }
    ]
    assert [record["record_id"] for record in records["records"]] == ["r1", "r2", "r3", "r4"]
    assert [record["classification"] for record in records["records"]] == [
        "restaurant",
        "non_restaurant",
        "pending",
        "restaurant",
    ]
    assert [record["map_status"] for record in records["records"]] == [
        "mapped",
        "non_restaurant",
        "pending",
        "geocode_failed",
    ]


def test_build_creates_city_entry_page_and_seven_city_landing(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    save_input(context, lookup())
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0

    output = context.paths.output_root
    landing = (output / "index.html").read_text(encoding="utf-8")
    for city in ("서울", "부산", "대구", "인천", "광주", "대전", "울산"):
        assert city in landing
    # 빌드한 도시만 열 수 있다. 나머지는 카드로 남기되 링크하지 않는다.
    assert 'href="./seoul/"' in landing
    assert 'href="./busan/"' not in landing

    city_page = (output / "seoul" / "index.html").read_text(encoding="utf-8")
    assert '<meta property="og:title" content="합성 도시 공무원 맛집 지도">' in city_page
    assert 'data-city="seoul"' in city_page
    assert 'data-markers-url="./markers.json"' in city_page
    assert 'data-records-url="./records.json"' in city_page
    assert (output / "assets" / "app.js").is_file()
    assert (output / "assets" / "styles.css").is_file()
    assert (output / "manifest.webmanifest").is_file()
    assert (output / "sw.js").is_file()


def test_lookup_error_is_saved_and_reported_without_dropping_the_record(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = prepare(tmp_path)
    query = lookup()
    query.update(status="error", error="unavailable", candidates=[])
    save_input(context, query)
    assert run_cli(context, "geocode") == 1
    assert "cause=lookup-failed" in capsys.readouterr().err
    result = payload(context, "geocode")["results"][0]
    assert result["reason"] == "lookup_error"
    assert result["lookup"]["error"] == "unavailable"
    assert result["business_id"] is None
    assert run_cli(context, "closure") == 0
    assert run_cli(context, "build") == 0
    assert payload(context, "build")["record_count"] == 1
    assert payload(context, "build")["marker_count"] == 0


def test_regenerating_legacy_artifact_preserves_it_and_ignores_name_only_history(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = prepare(tmp_path)
    save_input(context, lookup())
    directory = context.paths.city_dir(context.target)
    legacy = json.dumps(
        {
            "schema_version": 1,
            "city": "seoul",
            "org": None,
            "dependencies": {},
            "payload": {
                "results": [
                    {
                        "merchant": "같은 식당",
                        "status": "success",
                        "latitude": 37.5,
                        "longitude": 127.0,
                        "evidence": "old",
                    }
                ]
            },
        }
    )
    write_text(directory / "geocode.json", legacy)
    write_text(directory / "geocode-history.jsonl", "legacy-name-only-history\n")
    assert run_cli(context, "closure") == 1
    assert "cause=regeneration-required" in capsys.readouterr().err
    assert run_cli(context, "geocode") == 0
    assert payload(context, "geocode")["results"][0]["latitude"] == 35.1
    assert (directory / "geocode-history.jsonl").read_text() == "legacy-name-only-history\n"
    archives = list((directory / "history").glob("geocode-v1-*.json"))
    assert len(archives) == 1
    assert archives[0].read_text(encoding="utf-8") == legacy


def add_record(context: ExecutionContext, record_id: str, status: str = "restaurant") -> None:
    store = ArtifactStore(context.paths, context.target)
    records = store.load("parse", ParseOutput).records
    decisions = store.load("classify", ClassifyOutput).decisions
    store.save(
        "parse",
        ParseOutput(
            records=(
                *records,
                records[0].model_copy(
                    update={
                        "record_id": record_id,
                        "source_location": f"sheet1:{record_id}",
                    }
                ),
            )
        ),
    )
    store.save(
        "classify",
        ClassifyOutput(
            decisions=(
                *decisions,
                Classification.model_validate(
                    {
                        "record_id": record_id,
                        "status": status,
                        "evidence": "합성 분류",
                    }
                ),
            )
        ),
    )


def test_same_named_branches_and_unresolved_records_keep_separate_links(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    for record_id, status in [
        ("r2", "restaurant"),
        ("r3", "restaurant"),
        ("r4", "non_restaurant"),
        ("r5", "pending"),
    ]:
        add_record(context, record_id, status)
    first, second, unresolved = lookup(), lookup(), lookup()
    second["scope"]["record_id"] = "r2"
    second["facts"][0].update(branch="서울점", address="서울 합성로 20")
    second["candidates"][0].update(
        branch="서울점", address="서울 합성로 20", latitude=37.5, longitude=127.0
    )
    # A provider ID may be reused in different supplied scopes; it is not the business ID.
    unresolved["scope"]["record_id"] = "r3"
    unresolved["facts"] = []
    # Search rank must not beat matching evidence.
    first["candidates"].insert(0, deepcopy(second["candidates"][0]))
    first["candidates"][0]["source"]["source_id"] = "wrong-ranked-place"
    save_input(context, first, second, unresolved)
    assert run_cli(context, "geocode") == 0
    results = payload(context, "geocode")["results"]
    assert [item["record_id"] for item in results] == ["r1", "r2", "r3"]
    assert [item["latitude"] for item in results] == [35.1, 37.5, None]
    assert results[0]["business_id"] != results[1]["business_id"]
    assert results[0]["lookup_key"] != results[1]["lookup_key"]
    assert run_cli(context, "closure") == 0
    assert run_cli(context, "build") == 0
    assert payload(context, "build")["record_count"] == 5
    assert payload(context, "build")["marker_count"] == 2
    built = json.loads(
        (context.paths.output_root / "seoul" / "markers.json").read_text(encoding="utf-8")
    )
    assert len({item["business_id"] for item in built["markers"]}) == 2
    assert [item["visit_count"] for item in built["markers"]] == [1, 1]


def test_conflicting_coordinates_for_the_same_business_are_explicitly_unresolved(
    tmp_path: Path,
) -> None:
    context = prepare(tmp_path)
    add_record(context, "r2")
    first, second = lookup(), lookup()
    second["scope"]["record_id"] = "r2"
    second["candidates"][0]["latitude"] = 37.5
    save_input(context, first, second)
    assert run_cli(context, "geocode") == 0
    assert [item["reason"] for item in payload(context, "geocode")["results"]] == [
        "conflicting_evidence",
        "conflicting_evidence",
    ]
    assert run_cli(context, "closure") == 0
    assert run_cli(context, "build") == 0
    assert payload(context, "build")["record_count"] == 2
    assert payload(context, "build")["marker_count"] == 0


def test_failed_results_are_reused_until_explicit_retry_or_changed_evidence(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    query = lookup()
    query["candidates"][0]["latitude"] = None
    save_input(context, query)
    assert run_cli(context, "geocode") == 0
    history = context.paths.city_dir(context.target) / "geocode-history-v2.jsonl"
    original = history.read_bytes()
    assert run_cli(context, "geocode") == 0
    assert history.read_bytes() == original
    assert run_cli(context, "geocode", "--retry-failed") == 0
    entries = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
    assert [entry["revision"] for entry in entries] == [1, 2]
    assert entries[0]["value"]["reason"] == "missing_coordinates"
    save_input(context, lookup())
    assert run_cli(context, "geocode") == 0
    assert payload(context, "geocode")["results"][0]["status"] == "success"
    assert len(history.read_text(encoding="utf-8").splitlines()) == 3


@pytest.mark.parametrize(
    "case,reason",
    [
        ("no_facts", "missing_address"),
        ("no_address", "missing_address"),
        ("no_branch", "unknown_branch"),
        ("conflict", "conflicting_evidence"),
        ("ambiguous", "ambiguous"),
        ("similar_name", "no_match"),
        ("truncated", "unconfirmed_name"),
        ("empty", "no_candidates"),
    ],
)
def test_insufficient_evidence_never_becomes_a_business(
    tmp_path: Path, case: str, reason: str
) -> None:
    context = prepare(tmp_path)
    query = lookup()
    if case == "no_facts":
        query["facts"] = []
    elif case == "no_address":
        query["facts"][0]["address"] = None
    elif case == "no_branch":
        query["facts"][0]["branch"] = None
    elif case == "conflict":
        query["facts"].append({**query["facts"][0], "address": "서울 다른로 1"})
    elif case == "ambiguous":
        other = deepcopy(query["candidates"][0])
        other["source"]["source_id"] = "another-place"
        query["candidates"].append(other)
    elif case == "similar_name":
        query["candidates"][0]["merchant"] = "같은 식당 비슷한 이름"
    elif case == "truncated":
        query["facts"][0]["merchant"] = "같은 식당 전체 이름"
        query["candidates"][0]["merchant"] = "같은 식당 전체 이름"
    else:
        query["candidates"] = []
    save_input(context, query)
    assert run_cli(context, "geocode") == 0
    result = payload(context, "geocode")["results"][0]
    assert result["reason"] == reason
    assert result["business_id"] is None
    assert result["confirmed_merchant"] is None
    assert result["merchant"] == "같은 식당"
    assert run_cli(context, "closure") == 0
    assert run_cli(context, "build") == 0
    assert payload(context, "build")["record_count"] == 1
    assert payload(context, "build")["marker_count"] == 0


def test_scoped_human_confirmation_restores_name_and_invalidates_old_markers(
    tmp_path: Path,
) -> None:
    context = prepare(tmp_path)
    add_record(context, "r2")
    first, second = lookup(), lookup()
    for query in (first, second):
        query["facts"][0]["merchant"] = "같은 식당 전체 이름"
        query["candidates"][0]["merchant"] = "같은 식당 전체 이름"
    second["scope"]["record_id"] = "r2"
    save_input(context, first, second)
    assert run_cli(context, "geocode") == 0
    assert run_cli(context, "closure") == 0
    confirmation_path = context.paths.data_root / "manual" / "seoul" / "geocode.jsonl"
    write_text(
        confirmation_path,
        json.dumps(
            {
                "scope": first["scope"],
                "candidate_source": first["candidates"][0]["source"],
                "merchant": "같은 식당 전체 이름",
                "branch": "부산점",
                "address": "부산 합성로 10",
                "evidence": "https://example.invalid/disclosure/verified-name 담당자 확인",
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    assert run_cli(context, "build") == 1
    assert run_cli(context, "geocode") == 0
    results = payload(context, "geocode")["results"]
    assert [item["reason"] for item in results] == ["human_confirmed", "unconfirmed_name"]
    assert results[0]["merchant"] == "같은 식당"
    assert results[0]["confirmed_merchant"] == "같은 식당 전체 이름"
    assert results[0]["confirmation"]["scope"]["record_id"] == "r1"
    assert run_cli(context, "closure") == 0
    assert run_cli(context, "build") == 0
    write_text(confirmation_path, "")
    assert run_cli(context, "build") == 1
    assert run_cli(context, "geocode") == 0
    assert all(item["business_id"] is None for item in payload(context, "geocode")["results"])


def test_changed_candidates_block_stale_build_and_refined_only_rebuild_is_reproducible(
    tmp_path: Path,
) -> None:
    context = prepare(tmp_path)
    save_input(context, lookup())
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0
    output = context.paths.output_root / "seoul" / "markers.json"
    original = output.read_bytes()
    history = context.paths.city_dir(context.target) / "geocode-history-v2.jsonl"
    previous = history.read_bytes()
    assert not context.paths.raw_root.exists()
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0
    assert output.read_bytes() == original
    assert history.read_bytes() == previous
    query = lookup()
    query["facts"][0]["address"] = None
    save_input(context, query)
    assert run_cli(context, "build") == 1
    assert output.read_bytes() == original
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["marker_count"] == 0
    assert len(history.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("city", "busan"),
        ("organization", "other-org"),
        ("source_hash", "b" * 64),
        ("record_id", "unknown"),
    ],
)
def test_candidate_scope_cannot_cross_record_provenance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    field: str,
    value: str,
) -> None:
    context = prepare(tmp_path)
    query = lookup()
    query["scope"][field] = value
    save_input(context, query)
    assert run_cli(context, "geocode") == 1
    assert "cause=invalid-artifact" in capsys.readouterr().err
    assert not (context.paths.city_dir(context.target) / "geocode.json").exists()


def test_candidate_address_cannot_serve_as_independent_record_evidence(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    query = lookup()
    query["facts"][0]["source"] = query["candidates"][0]["source"]["reference"]
    save_input(context, query)
    assert run_cli(context, "geocode") == 0
    result = payload(context, "geocode")["results"][0]
    assert result["reason"] == "insufficient_evidence"
    assert result["business_id"] is None


def test_run_uses_real_adjudication_storage_and_marker_build(tmp_path: Path) -> None:
    from deliciousmap.local import LocalAdapters
    from tests.fakes import SyntheticAdapters

    class PreparedPredecessors(SyntheticAdapters):
        # Only out-of-scope predecessors supply synthetic records; #37 runs real stages.
        geocode = LocalAdapters.geocode
        closure = LocalAdapters.closure
        build = LocalAdapters.build

    context = context_at(tmp_path)
    assert (
        main(
            [
                "run",
                "--city",
                "seoul",
                "--raw-root",
                str(context.paths.raw_root),
                "--data-root",
                str(context.paths.data_root),
                "--output-root",
                str(context.paths.output_root),
            ],
            cities=(context.target.city,),
            adapters=PreparedPredecessors(),
        )
        == 0
    )
    assert payload(context, "build")["record_count"] == 4
    assert payload(context, "build")["marker_count"] == 1
    assert [item["reason"] for item in payload(context, "geocode")["results"]] == [
        "matched",
        "missing_coordinates",
    ]


def test_invalid_input_reports_only_safe_failure_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    query = lookup()
    query["error"] = "SECRET raw provider response"
    save_input(context, query)
    assert run_cli(context, "geocode") == 1
    assert capsys.readouterr().err == "geocode city=seoul org=* cause=invalid-artifact\n"


def test_oversized_refined_result_is_rejected_before_geocode_history_write(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    query = lookup()
    # Each individual result fits; the combined stage must fail before a partial history write.
    query["facts"][0]["source"] = "x" * 10_000_000
    add_record(context, "r2")
    second = deepcopy(query)
    second["scope"]["record_id"] = "r2"
    path = context.paths.city_dir(context.target) / "geocode-input.json"
    path.write_text(json.dumps({"schema_version": 1, "lookups": [query, second]}), encoding="utf-8")
    assert run_cli(context, "geocode") == 1
    assert not (context.paths.city_dir(context.target) / "geocode.json").exists()
    assert not (context.paths.city_dir(context.target) / "geocode-history-v2.jsonl").exists()


def test_upstream_metadata_change_alone_does_not_repeat_settled_geocode_history(
    tmp_path: Path,
) -> None:
    context = prepare(tmp_path)
    save_input(context, lookup())
    assert run_cli(context, "geocode") == 0
    history = context.paths.city_dir(context.target) / "geocode-history-v2.jsonl"
    settled = history.read_bytes()
    decided = payload(context, "geocode")["results"]
    store = ArtifactStore(context.paths, context.target)
    parsed = store.load("parse", ParseOutput)
    decisions = store.load("classify", ClassifyOutput).decisions
    # 레코드도 식당 여부도 그대로이고 상류 산출물의 메타데이터만 바뀐 재실행이다.
    store.save("parse", parsed.model_copy(update={"reporting_period": "2026-01-01/2026-12-31"}))
    store.save(
        "classify",
        ClassifyOutput(
            decisions=tuple(
                item.model_copy(update={"evidence": "다시 적은 합성 분류"}) for item in decisions
            )
        ),
    )
    assert run_cli(context, "geocode") == 0
    assert history.read_bytes() == settled
    assert payload(context, "geocode")["results"] == decided
