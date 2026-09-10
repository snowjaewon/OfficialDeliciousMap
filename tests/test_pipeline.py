from pathlib import Path

import pytest

from deliciousmap.paths import Paths
from deliciousmap.pipeline import ExecutionContext, execute
from deliciousmap.registry import Board, City, Organization, select_target
from tests.fakes import SyntheticAdapters


def context_at(tmp_path: Path, city: str = "seoul") -> ExecutionContext:
    registry = (
        City(
            city,
            "합성 도시",
            (
                Organization(
                    "test-org",
                    "합성 기관",
                    (Board("expenses", "https://example.invalid/board", SyntheticAdapters),),
                ),
            ),
        ),
    )
    return ExecutionContext(
        select_target(registry, city, None),
        Paths(
            tmp_path / "저장소",
            tmp_path / "외부 원본",
            tmp_path / "저장소" / "data",
            tmp_path / "출력 폴더",
        ),
    )


def test_run_passes_artifacts_and_preserves_all_records_in_build(tmp_path: Path) -> None:
    context = context_at(tmp_path)
    adapters = SyntheticAdapters()
    result = execute("run", context, adapters)
    assert adapters.calls == [
        "fetch",
        "headermap",
        "parse",
        "classify",
        "geocode",
        "closure",
        "build",
    ]
    assert adapters.build_input is not None
    assert [record.record_id for record in adapters.build_input.records] == ["r0", "r1", "r2", "r3"]
    assert adapters.build_input.candidates[0].record_ids == ("r0",)
    assert adapters.build_input.closures[0].status == "closed"
    assert result.record_count == 4
    assert result.marker_count == 1
    assert result.files[0].read_text(encoding="utf-8") == "TEST ONLY\nr0\nr1\nr2\nr3"


@pytest.mark.parametrize(
    "stage", ["fetch", "headermap", "parse", "classify", "geocode", "closure", "build"]
)
def test_stage_failure_stops_run_without_exposing_exception_contents(
    tmp_path: Path, stage: str
) -> None:
    from deliciousmap.pipeline import STAGES, PipelineFailure

    context = context_at(tmp_path)
    adapters = SyntheticAdapters()

    def fail(*args: object) -> object:
        raise RuntimeError("SECRET and original contents must never reach the CLI")

    setattr(adapters, stage, fail)
    with pytest.raises(PipelineFailure) as failure:
        execute("run", context, adapters)
    assert str(failure.value) == f"{stage} city=seoul org=* cause=adapter-failed"
    assert adapters.calls == list(STAGES[: STAGES.index(stage)])
    assert not (context.paths.city_dir(context.target) / f"{stage}.json").exists()


@pytest.mark.parametrize(
    "stage", ["fetch", "headermap", "parse", "classify", "geocode", "closure", "build"]
)
def test_wrong_output_type_is_rejected_before_persistence(tmp_path: Path, stage: str) -> None:
    from deliciousmap.contracts import FetchOutput
    from deliciousmap.pipeline import STAGES, PipelineFailure

    context = context_at(tmp_path)
    adapters = SyntheticAdapters()
    # Even a construct-bypassed model must be checked again at the public boundary.
    setattr(adapters, stage, lambda *args: FetchOutput.model_construct(sources=("bad source",)))
    with pytest.raises(PipelineFailure, match="cause=invalid-artifact"):
        execute("run", context, adapters)
    assert adapters.calls == list(STAGES[: STAGES.index(stage)])
    assert not (context.paths.city_dir(context.target) / f"{stage}.json").exists()


def test_missing_classification_is_an_error_instead_of_silent_record_loss(tmp_path: Path) -> None:
    from deliciousmap.contracts import ClassifyOutput
    from deliciousmap.pipeline import PipelineFailure

    adapters = SyntheticAdapters()
    adapters.classify = lambda *args: ClassifyOutput(decisions=())
    with pytest.raises(PipelineFailure, match="classify .*cause=invalid-artifact"):
        execute("run", context_at(tmp_path), adapters)
    assert "geocode" not in adapters.calls


def test_single_stages_and_rerun_share_artifacts_and_reuse_fake_caches(tmp_path: Path) -> None:
    from dataclasses import replace

    from deliciousmap.pipeline import STAGES

    context = context_at(tmp_path)
    first = SyntheticAdapters()
    for stage in STAGES:
        execute(stage, context, first)
    assert first.geocode_lookups == 2
    second = SyntheticAdapters()
    execute("run", context, second)
    assert second.build_input == first.build_input
    assert second.cache_misses == 0
    assert second.geocode_lookups == 0
    execute("geocode", replace(context, retry_failed=True), second)
    assert second.geocode_lookups == 1


def test_build_uses_only_refined_artifacts_without_originals_or_fetch_metadata(
    tmp_path: Path,
) -> None:
    context = context_at(tmp_path)
    execute("run", context, SyntheticAdapters())
    directory = context.paths.city_dir(context.target)
    for name in ("fetch.json", "headermap.json"):
        (directory / name).unlink()
    assert not context.paths.raw_root.exists()
    adapters = SyntheticAdapters()
    execute("build", context, adapters)
    assert adapters.calls == ["build"]
    assert len(adapters.build_input.records) == 4


def test_changed_records_cannot_reuse_stale_classification_in_single_build(tmp_path: Path) -> None:
    from deliciousmap.pipeline import PipelineFailure
    from deliciousmap.storage import read_records, write_records

    context = context_at(tmp_path)
    execute("run", context, SyntheticAdapters())
    csv = context.paths.city_dir(context.target) / "records.csv"
    records = read_records(csv)
    write_records(csv, (records[0].model_copy(update={"purpose": "변경된 목적"}), *records[1:]))
    adapters = SyntheticAdapters()
    with pytest.raises(PipelineFailure, match="build .*cause=invalid-artifact"):
        execute("build", context, adapters)
    assert adapters.calls == []


def test_headermap_must_refer_to_fetched_originals(tmp_path: Path) -> None:
    from deliciousmap.contracts import HeaderMapOutput
    from deliciousmap.pipeline import PipelineFailure

    adapters = SyntheticAdapters()
    original = adapters.headermap

    def wrong_mapping(value, context):
        mapped = original(value, context)
        return HeaderMapOutput(
            mappings=(mapped.mappings[0].model_copy(update={"source_hash": "c" * 64}),)
        )

    adapters.headermap = wrong_mapping
    with pytest.raises(PipelineFailure, match="headermap .*cause=invalid-artifact"):
        execute("run", context_at(tmp_path), adapters)
    assert "parse" not in adapters.calls


def test_manual_corrections_from_another_city_are_rejected(tmp_path: Path) -> None:
    from deliciousmap.pipeline import PipelineFailure
    from deliciousmap.storage import write_text

    context = context_at(tmp_path)
    write_text(
        context.paths.manual(context.target),
        '{"city":"busan","merchant":"합성 식당","status":"non_restaurant",'
        '"evidence":"synthetic human decision"}\n',
    )
    adapters = SyntheticAdapters()
    with pytest.raises(PipelineFailure, match="classify .*cause=invalid-artifact"):
        execute("run", context, adapters)
    assert "classify" not in adapters.calls


def test_city_and_org_outputs_are_isolated_but_shared_cache_is_reused(tmp_path: Path) -> None:
    from dataclasses import replace

    from deliciousmap.registry import Target

    seoul = context_at(tmp_path)
    busan = context_at(tmp_path, "busan")
    organization = replace(seoul, target=Target(seoul.target.city, "test-org"))
    for context in (seoul, busan, organization):
        execute("run", context, SyntheticAdapters())
    assert seoul.paths.city_dir(seoul.target) == seoul.paths.data_root / "seoul"
    assert (
        seoul.paths.city_dir(organization.target)
        == seoul.paths.data_root / "seoul" / "orgs" / "test-org"
    )
    assert (
        len({context.paths.city_dir(context.target) for context in (seoul, busan, organization)})
        == 3
    )
    assert seoul.paths.shared("headermap") == busan.paths.shared("headermap")


@pytest.mark.parametrize("stage", ["fetch", "parse"])
def test_unexplained_empty_output_is_not_success(tmp_path: Path, stage: str) -> None:
    from deliciousmap.contracts import FetchOutput, ParseOutput
    from deliciousmap.pipeline import PipelineFailure

    adapters = SyntheticAdapters()
    output = FetchOutput(sources=()) if stage == "fetch" else ParseOutput(records=())
    setattr(adapters, stage, lambda *args: output)
    with pytest.raises(PipelineFailure, match=f"{stage} .*cause=invalid-artifact"):
        execute("run", context_at(tmp_path), adapters)
