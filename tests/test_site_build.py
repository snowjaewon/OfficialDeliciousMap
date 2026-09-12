import json
import re
from copy import deepcopy
from dataclasses import replace
from importlib.resources import files
from pathlib import Path
from typing import get_args

import pytest

from deliciousmap.contracts import (
    CONFIRMED_REASONS,
    ClassifyOutput,
    ExcludedSources,
    GeocodeReason,
    MapStatus,
    ParseOutput,
    Provider,
    SourceReport,
)
from deliciousmap.pipeline import ExecutionContext
from deliciousmap.registry import CITIES, HoldReason, Organization, Target
from deliciousmap.storage import ArtifactStore, write_text
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
        # 장부 화면이 기관 slug 대신 이름을 쓸 수 있게 함께 내려 준다.
        "organizations": {"test-org": "합성 기관"},
        "site_root": "../",
    }


def build_ready(tmp_path: Path) -> ExecutionContext:
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


def published(context: ExecutionContext, name: str) -> dict:
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


def with_held_organization(
    context: ExecutionContext, reason: HoldReason = "bot_blocked"
) -> ExecutionContext:
    """수집 보류 기관이 하나 있는 도시로 바꾼다. 기존 레코드는 그대로 둔다."""
    city = replace(
        context.target.city,
        organizations=(
            *context.target.city.organizations,
            Organization("held-org", "보류 기관", hold_reason=reason),
        ),
    )
    return replace(context, target=Target(city, context.target.org))


def city_page(context: ExecutionContext) -> str:
    path = context.paths.output_root / context.target.city.slug / "index.html"
    return path.read_text(encoding="utf-8")


def test_city_page_publishes_the_period_and_every_organization_status(tmp_path: Path) -> None:
    context = with_held_organization(build_ready(tmp_path))
    assert run_cli(context, "build") == 0

    page = city_page(context)
    assert "2026년 상반기" in page
    assert "합성 기관" in page and "수집 완료" in page
    assert "보류 기관" in page and "수집 보류" in page and "봇 차단" in page
    # 수집 보류 기관이 있으면 지도 위에서도 누락 가능성을 알린다.
    assert "data-collection-hold" in page


def test_city_page_without_a_hold_keeps_the_map_free_of_the_notice(tmp_path: Path) -> None:
    context = build_ready(tmp_path)
    assert run_cli(context, "build") == 0

    page = city_page(context)
    assert "합성 기관" in page and "수집 완료" in page
    assert "data-collection-hold" not in page


def test_landing_keeps_seven_cards_but_links_only_the_cities_it_built(tmp_path: Path) -> None:
    context = build_ready(tmp_path)
    assert run_cli(context, "build") == 0

    landing = (context.paths.output_root / "index.html").read_text(encoding="utf-8")
    for city in CITIES:
        assert city.name in landing
    assert 'href="./seoul/"' in landing
    assert [city.slug for city in CITIES if f'href="./{city.slug}/"' in landing] == ["seoul"]
    assert landing.count("준비 중") == len(CITIES) - 1


def test_screen_labels_cover_every_published_contract_value() -> None:
    """계약의 값이 늘면 화면 표기도 함께 늘린다. 빈 표기로 조용히 지나가지 않게 한다."""
    source = files("deliciousmap.site_assets").joinpath("app.js").read_text(encoding="utf-8")

    def labelled(name: str) -> set[str]:
        block = re.search(rf"const {name} = \{{(.*?)\n  \}};", source, re.S)
        assert block is not None, name
        return set(re.findall(r"^\s*(\w+):", block.group(1), re.M))

    assert labelled("COORDINATE_SOURCES") == set(get_args(Provider))
    assert labelled("MAP_STATUSES") == set(get_args(MapStatus))
    # 확정된 두 사유는 지도에 오른 레코드의 것이라 장부에서 따로 적지 않는다.
    assert labelled("GEOCODE_REASONS") == set(get_args(GeocodeReason)) - set(CONFIRMED_REASONS)


def fetched(posted: str, title: str | None, digest: str) -> dict:
    """수집 장부 한 줄. 대상 선별은 게시일과 제목만 보므로 나머지는 합성값이다."""
    return {
        "path": "외부 원본/합성.xls",
        "source_hash": digest,
        "organization": "test-org",
        "board": "expenses",
        "url": f"https://example.invalid/{digest[:4]}",
        "container": "ole2",
        "department": "총무과",
        "posted": posted,
        "title": title,
    }


def save_ledger(context: ExecutionContext) -> None:
    """대상 2개와 사유 셋으로 빠진 7개를 담은 fetch 장부를 쓴다."""
    sources = [
        fetched("2026-04-01", "2026년 1분기 업무추진비 집행내역(합성과)", "a" * 64),
        fetched("2026-04-02", "2026년 2분기 업무추진비 집행내역(합성과)", "b" * 64),
        *(
            fetched(
                f"202{year}-03-02",
                f"202{year}년 1분기 업무추진비 집행내역(합성과)",
                str(year) * 64,
            )
            for year in range(1, 5)
        ),
        fetched("2026-01-08", "2025년 4분기 업무추진비 집행내역(합성과)", "c" * 64),
        fetched("2026-05-01", "업무추진비 공개 안내", "d" * 64),
        fetched("2026-05-02", "합성과 업무추진비 집행내역", "e" * 64),
    ]
    write_text(
        context.paths.data_root / context.target.city.slug / "fetch.json",
        json.dumps(
            {
                "schema_version": 3,
                "city": context.target.city.slug,
                "org": context.target.org,
                "dependencies": {},
                "payload": {"sources": sources},
            },
            ensure_ascii=False,
        ),
    )


def scoped_build(tmp_path: Path) -> ExecutionContext:
    """대상 2개를 읽고 7개를 뺀 제출. parse를 고쳐 쓰고 뒤 단계를 그 위에서 다시 만든다."""
    context = prepare(tmp_path)
    save_ledger(context)
    store = ArtifactStore(context.paths, context.target)
    classified = store.load("classify", ClassifyOutput)
    parsed = store.load("parse", ParseOutput)
    store.save(
        "parse",
        parsed.model_copy(
            update={
                "sources": (
                    SourceReport(source_hash="a" * 64, status="parsed", records=1),
                    SourceReport(source_hash="b" * 64, status="parsed", records=0),
                ),
                "excluded_sources": ExcludedSources(
                    posted_out_of_range=4, declared_out_of_range=1, undeclared_in_year=2
                ),
            }
        ),
    )
    store.save("classify", classified)
    save_input(context, lookup())
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0
    return context


def test_city_page_publishes_how_many_originals_the_submission_left_out(tmp_path: Path) -> None:
    """대상만 세고 뺀 것을 감추면 장부가 완전해 보인다. 둘을 한 줄에 같이 낸다."""
    page = city_page(scoped_build(tmp_path))
    assert "원본 9개 중 대상 2개" in page
    assert "기간 미표기 제외 2개" in page


def test_city_page_omits_the_scope_line_when_no_original_was_counted(tmp_path: Path) -> None:
    """원본을 세지 않은 산출물에 0개를 적으면 없는 사실을 지어내는 것이다."""
    context = build_ready(tmp_path)
    assert run_cli(context, "build") == 0
    assert "중 대상" not in city_page(context)
