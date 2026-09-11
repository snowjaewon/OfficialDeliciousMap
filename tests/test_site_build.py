import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from deliciousmap.registry import CITIES
from deliciousmap.storage import write_text
from tests.test_geocoding_cli import (
    add_record,
    lookup,
    payload,
    prepare,
    run_cli,
    save_input,
)


def test_every_city_declares_a_valid_map_bounds() -> None:
    for city in CITIES:
        bounds = city.map_bounds
        assert -90 <= bounds.south < bounds.north <= 90
        assert -180 <= bounds.west < bounds.east <= 180


def test_city_page_contains_its_map_bounds_and_public_map_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NAVER_MAP_CLIENT_ID", "public-test-key")
    monkeypatch.setenv("NAVER_MAP_KEY_PARAM", "ncpKeyId")
    context = prepare(tmp_path)
    save_input(context, lookup())
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0

    page = (context.paths.output_root / "seoul" / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<script id="site-config" type="application/json">(.*?)</script>', page)
    assert match is not None
    config = json.loads(match.group(1))
    assert config == {
        "city": "seoul",
        "map_bounds": {"east": 129.4, "north": 38.0, "south": 34.8, "west": 126.7},
        "naver_map_client_id": "public-test-key",
        "naver_map_key_param": "ncpKeyId",
        "site_root": "../",
    }


def build_ready(tmp_path: Path) -> "object":
    """build 직전까지의 정제 산출물을 만든다."""
    context = prepare(tmp_path)
    save_input(context, lookup())
    for stage in ("geocode", "closure"):
        assert run_cli(context, stage) == 0
    return context


@pytest.mark.parametrize("command", ["build", "run"])
def test_shell_commands_refuse_to_run_without_the_public_map_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    context = build_ready(tmp_path)
    monkeypatch.delenv("NAVER_MAP_CLIENT_ID", raising=False)
    assert run_cli(context, command) == 2
    assert "configuration: NAVER_MAP_CLIENT_ID" in capsys.readouterr().err
    assert not context.paths.output_root.exists()


def test_other_commands_do_not_require_the_public_map_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = prepare(tmp_path)
    save_input(context, lookup())
    monkeypatch.delenv("NAVER_MAP_CLIENT_ID", raising=False)
    for stage in ("geocode", "closure"):
        assert run_cli(context, stage) == 0


def test_unknown_map_key_parameter_is_rejected_without_echoing_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    context = build_ready(tmp_path)
    monkeypatch.setenv("NAVER_MAP_KEY_PARAM", "onerror=alert")
    assert run_cli(context, "build") == 2
    error = capsys.readouterr().err
    assert "configuration: NAVER_MAP_KEY_PARAM" in error
    assert "synthetic-map-key" not in error


def test_organization_build_writes_data_without_touching_the_city_shell(tmp_path: Path) -> None:
    context = prepare(tmp_path, org="test-org")
    save_input(context, lookup())
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0

    output_root = context.paths.output_root
    directory = output_root / "seoul" / "orgs" / "test-org"
    assert sorted(path.name for path in directory.iterdir()) == ["markers.json", "records.json"]
    assert [Path(name).name for name in payload(context, "build")["files"]] == [
        "markers.json",
        "records.json",
    ]
    for missing in ("index.html", "assets", "manifest.webmanifest", "sw.js"):
        assert not (output_root / missing).exists()
    assert not (output_root / "seoul" / "index.html").exists()


def published(context: "object", name: str) -> dict:
    directory = context.paths.output_root / context.target.city.slug
    if context.target.org:
        directory = directory / "orgs" / context.target.org
    return json.loads((directory / name).read_text(encoding="utf-8"))


def shared_place(provider: str, reference: str) -> dict:
    """같은 업소를 가리키는 다른 제공자의 후보. 좌표는 일치한다."""
    candidate = deepcopy(lookup()["candidates"][0])
    candidate["source"] = {"provider": provider, "source_id": "place-2", "reference": reference}
    return candidate


def test_markers_name_the_provider_that_supplied_the_coordinates(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    query = lookup()
    query["candidates"].append(shared_place("naver", "https://example.invalid/naver/1"))
    save_input(context, query)
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0
    assert published(context, "markers.json")["markers"][0]["coordinate_source"] == "local"

    write_text(
        context.paths.manual(context.target, "geocode"),
        json.dumps(
            {
                "scope": query["scope"],
                "candidate_source": query["candidates"][1]["source"],
                "merchant": "같은 식당",
                "branch": "부산점",
                "address": "부산 합성로 10",
                "evidence": "https://example.invalid/disclosure/verified 담당자 확인",
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "geocode")["results"][0]["reason"] == "human_confirmed"
    assert published(context, "markers.json")["markers"][0]["coordinate_source"] == "naver"


def test_ledger_keeps_unmapped_records_with_the_reason_they_missed_the_map(
    tmp_path: Path,
) -> None:
    context = prepare(tmp_path)
    add_record(context, "r2", "non_restaurant")
    add_record(context, "r3", "pending")
    add_record(context, "r4")
    unresolved = lookup()
    unresolved["scope"]["record_id"] = "r4"
    unresolved["facts"] = []
    unresolved["candidates"] = []
    save_input(context, lookup(), unresolved)
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0

    marker = published(context, "markers.json")["markers"][0]
    records = published(context, "records.json")["records"]
    assert [record["record_id"] for record in records] == ["r1", "r2", "r3", "r4"]
    assert [record["geocode_reason"] for record in records] == [
        "matched",
        None,
        None,
        "no_candidates",
    ]
    assert [record["business_id"] for record in records] == [
        marker["business_id"],
        None,
        None,
        None,
    ]
    assert payload(context, "build")["record_count"] == 4
    assert payload(context, "build")["marker_count"] == 1


def test_public_files_carry_no_original_or_lookup_provenance(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    save_input(context, lookup())
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0

    written = [path for path in context.paths.output_root.rglob("*") if path.is_file()]
    assert written
    for path in written:
        content = path.read_text(encoding="utf-8")
        for secret in ("source_hash", "source_location", "lookup_key", "dependency_key"):
            assert secret not in content, path
        for value in ("a" * 64, "example.invalid", "합성 분류"):
            assert value not in content, path
