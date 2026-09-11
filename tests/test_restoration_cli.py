"""사람 확인에 따른 상호 복원을 공개 CLI와 저장된 산출물로 관찰한다."""

import json
from pathlib import Path

import pytest

from deliciousmap.contracts import Classification, ClassifyOutput, ParseOutput
from deliciousmap.pipeline import ExecutionContext
from deliciousmap.storage import ArtifactStore, write_text
from tests.test_geocoding_cli import lookup, payload, prepare, run_cli, save_input

FULL_NAME = "같은 식당 전체 이름"


def classify_records(context: ExecutionContext, statuses: dict[str, str] | None = None) -> None:
    """담당자가 classify 단계를 다시 실행한 것과 같은 결과를 남긴다."""
    store = ArtifactStore(context.paths, context.target)
    store.save(
        "classify",
        ClassifyOutput(
            decisions=tuple(
                Classification(
                    record_id=record.record_id,
                    status=(statuses or {}).get(record.record_id, "restaurant"),
                    evidence="합성 분류",
                )
                for record in store.load("parse", ParseOutput).records
            )
        ),
    )


def add_record(context: ExecutionContext, record_id: str, **update: str) -> None:
    store = ArtifactStore(context.paths, context.target)
    records = store.load("parse", ParseOutput).records
    store.save(
        "parse",
        ParseOutput(
            records=(
                *records,
                records[0].model_copy(
                    update={
                        "record_id": record_id,
                        "source_location": f"sheet1:{record_id}",
                        **update,
                    }
                ),
            )
        ),
    )
    classify_records(context)


def restore_entry(**overrides: object) -> dict:
    entry: dict = {
        "schema_version": 1,
        "scope": {
            "city": "seoul",
            "merchant": "같은 식당",
            "organization": None,
            "source_hash": None,
            "record_id": "r1",
        },
        "restored_merchant": FULL_NAME,
        "evidence": "기관의 다른 공개자료에서 같은 날짜·금액 항목의 전체 상호를 확인",
        "references": [
            {
                "kind": "disclosure",
                "source": "https://example.invalid/disclosure/2026-01",
                "detail": "2026-01-02 총무과 업무추진비 명세의 같은 금액 항목 상호",
            }
        ],
    }
    entry.update(overrides)
    return entry


def save_restorations(context: ExecutionContext, *entries: dict) -> None:
    write_text(
        context.paths.manual(context.target, "restore"),
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
    )


def truncated_lookup(record_id: str = "r1", **candidate: object) -> dict:
    query = lookup()
    query["scope"]["record_id"] = record_id
    query["facts"][0]["merchant"] = FULL_NAME
    query["candidates"][0]["merchant"] = FULL_NAME
    query["candidates"][0].update(candidate)
    return query


def results(context: ExecutionContext) -> dict[str, dict]:
    return {item["record_id"]: item for item in payload(context, "geocode")["results"]}


def test_confirmed_restoration_matches_without_overwriting_the_original_name(
    tmp_path: Path,
) -> None:
    context = prepare(tmp_path)
    save_input(context, truncated_lookup())
    assert run_cli(context, "geocode") == 0
    unconfirmed = results(context)["r1"]
    assert unconfirmed["reason"] == "unconfirmed_name"
    assert unconfirmed["restoration"] is None

    save_restorations(context, restore_entry())
    assert run_cli(context, "geocode") == 1
    classify_records(context)
    assert run_cli(context, "geocode") == 0
    result = results(context)["r1"]
    assert result["status"] == "success"
    assert result["merchant"] == "같은 식당"
    assert result["confirmed_merchant"] == FULL_NAME
    assert result["restoration"]["merchant"] == "같은 식당"
    assert result["restoration"]["restored_merchant"] == FULL_NAME
    assert result["restoration"]["scope"]["record_id"] == "r1"
    assert result["restoration"]["references"][0]["kind"] == "disclosure"
    assert result["lookup"]["candidates"][0]["merchant"] == FULL_NAME

    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    built = json.loads(
        (context.paths.output_root / "seoul" / "markers.json").read_text(encoding="utf-8")
    )
    assert built["markers"][0]["merchant"] == FULL_NAME
    assert built["markers"][0]["visit_count"] == 1
    ledger = json.loads(
        (context.paths.output_root / "seoul" / "ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["records"][0]["merchant"] == "같은 식당"


def other_source_lookup(record_id: str, source_hash: str) -> dict:
    """같은 원본 표기이지만 다른 원본·다른 소재지의 업소."""
    query = truncated_lookup(record_id, branch="서울점", address="서울 합성로 20")
    query["scope"]["source_hash"] = source_hash
    query["candidates"][0].update(latitude=37.5, longitude=127.0)
    query["facts"][0].update(branch="서울점", address="서울 합성로 20")
    return query


def test_restoration_scope_does_not_reach_another_business_with_the_same_name(
    tmp_path: Path,
) -> None:
    context = prepare(tmp_path)
    add_record(context, "r2", source_hash="b" * 64)
    save_input(context, truncated_lookup(), other_source_lookup("r2", "b" * 64))
    save_restorations(
        context,
        restore_entry(
            scope={**restore_entry()["scope"], "record_id": None, "source_hash": "a" * 64}
        ),
    )
    classify_records(context)
    assert run_cli(context, "geocode") == 0
    confirmed, untouched = results(context)["r1"], results(context)["r2"]
    assert confirmed["status"] == "success"
    assert untouched["reason"] == "unconfirmed_name"
    assert untouched["restoration"] is None
    assert untouched["merchant"] == "같은 식당"
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["record_count"] == 2
    assert payload(context, "build")["marker_count"] == 1


def test_conflicting_restorations_are_reported_instead_of_silently_chosen(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    save_input(context, truncated_lookup())
    save_restorations(
        context,
        restore_entry(),
        restore_entry(
            scope={**restore_entry()["scope"], "record_id": None},
            restored_merchant="다른 식당 전체 이름",
        ),
    )
    classify_records(context)
    assert run_cli(context, "geocode") == 1
    assert "cause=conflicting-review" in capsys.readouterr().err
    assert not (context.paths.city_dir(context.target) / "geocode.json").exists()


def test_the_narrower_review_supplies_the_evidence_when_both_agree(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    save_input(context, truncated_lookup())
    save_restorations(
        context,
        restore_entry(
            scope={**restore_entry()["scope"], "record_id": None}, evidence="도시 범위 확인"
        ),
        restore_entry(evidence="레코드 범위에서 다시 확인"),
    )
    classify_records(context)
    assert run_cli(context, "geocode") == 0
    applied = results(context)["r1"]["restoration"]
    assert applied["evidence"] == "레코드 범위에서 다시 확인"
    assert applied["scope"]["record_id"] == "r1"


def test_reviews_whose_scopes_do_not_contain_each_other_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    save_input(context, truncated_lookup())
    save_restorations(
        context,
        restore_entry(
            scope={**restore_entry()["scope"], "record_id": None, "organization": "test-org"}
        ),
        restore_entry(
            scope={**restore_entry()["scope"], "record_id": None, "source_hash": "a" * 64}
        ),
    )
    classify_records(context)
    assert run_cli(context, "geocode") == 1
    assert "cause=conflicting-review" in capsys.readouterr().err
    assert not (context.paths.city_dir(context.target) / "geocode.json").exists()


def test_conflicting_reviews_on_a_record_outside_the_markers_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    add_record(context, "r2")
    save_input(context, truncated_lookup())
    save_restorations(context, restore_entry(scope={**restore_entry()["scope"], "record_id": "r2"}))
    write_text(
        context.paths.manual(context.target, "geocode"),
        json.dumps(
            {
                "scope": {**truncated_lookup()["scope"], "record_id": "r2"},
                "candidate_source": truncated_lookup()["candidates"][0]["source"],
                "merchant": "확인자가 고른 다른 상호",
                "branch": "부산점",
                "address": "부산 합성로 10",
                "evidence": "https://example.invalid/disclosure/verified 담당자 확인",
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    # r2는 판단 보류라 마커 대상이 아니지만 어긋난 확인은 그대로 알린다.
    classify_records(context, {"r2": "pending"})
    assert run_cli(context, "geocode") == 1
    assert "cause=conflicting-review" in capsys.readouterr().err
    assert not (context.paths.city_dir(context.target) / "geocode.json").exists()


def test_restoration_conflicting_with_an_identity_confirmation_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    query = truncated_lookup()
    save_input(context, query)
    save_restorations(context, restore_entry())
    write_text(
        context.paths.manual(context.target, "geocode"),
        json.dumps(
            {
                "scope": query["scope"],
                "candidate_source": query["candidates"][0]["source"],
                "merchant": "확인자가 고른 다른 상호",
                "branch": "부산점",
                "address": "부산 합성로 10",
                "evidence": "https://example.invalid/disclosure/verified 담당자 확인",
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    classify_records(context)
    assert run_cli(context, "geocode") == 1
    assert "cause=conflicting-review" in capsys.readouterr().err


def test_restored_name_is_kept_while_the_marker_waits_for_coordinates(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    save_input(context, truncated_lookup(latitude=None, longitude=None))
    save_restorations(context, restore_entry())
    classify_records(context)
    assert run_cli(context, "geocode") == 0
    result = results(context)["r1"]
    assert result["reason"] == "missing_coordinates"
    assert result["restoration"]["restored_merchant"] == FULL_NAME
    assert result["business_id"] is None
    assert result["confirmed_merchant"] is None
    for stage in ("closure", "build"):
        assert run_cli(context, stage) == 0
    assert payload(context, "build")["record_count"] == 1
    assert payload(context, "build")["marker_count"] == 0


def test_added_changed_and_withdrawn_review_updates_only_its_own_records(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    add_record(context, "r2", merchant="다른 식당", source_hash="b" * 64)
    other = other_source_lookup("r2", "b" * 64)
    other["facts"][0]["merchant"] = "다른 식당"
    other["candidates"][0]["merchant"] = "다른 식당"
    save_input(context, truncated_lookup(), other)
    assert run_cli(context, "geocode") == 0
    history = context.paths.city_dir(context.target) / "geocode-history-v2.jsonl"

    def decision(record_id: str) -> dict:
        item = results(context)[record_id]
        return {
            key: item[key]
            for key in (
                "status",
                "reason",
                "business_id",
                "confirmed_merchant",
                "latitude",
                "longitude",
                "evidence",
            )
        }

    def entries() -> set[str]:
        return set(history.read_text(encoding="utf-8").splitlines())

    unrelated, earlier = decision("r2"), entries()
    assert decision("r1")["reason"] == "unconfirmed_name"
    assert unrelated["status"] == "success"

    save_restorations(context, restore_entry())
    assert run_cli(context, "geocode") == 1
    classify_records(context)
    assert run_cli(context, "geocode") == 0
    assert decision("r1")["status"] == "success"
    assert decision("r2") == unrelated
    assert earlier <= entries()

    save_restorations(context, restore_entry(restored_merchant="또 다른 전체 이름"))
    classify_records(context)
    assert run_cli(context, "geocode") == 0
    assert decision("r1")["reason"] == "unconfirmed_name"
    assert decision("r2") == unrelated

    write_text(context.paths.manual(context.target, "restore"), "")
    classify_records(context)
    assert run_cli(context, "geocode") == 0
    assert results(context)["r1"]["restoration"] is None
    assert decision("r2") == unrelated
    assert earlier <= entries()


@pytest.mark.parametrize("case", ["single_candidate", "similar_name", "no_candidates"])
def test_candidates_alone_never_become_a_restored_name(tmp_path: Path, case: str) -> None:
    context = prepare(tmp_path)
    query = truncated_lookup()
    if case == "similar_name":
        query["facts"][0]["merchant"] = "같은 식당 비슷한 이름"
        query["candidates"][0]["merchant"] = "같은 식당 비슷한 이름"
    elif case == "no_candidates":
        query["candidates"] = []
    save_input(context, query)
    assert run_cli(context, "geocode") == 0
    result = results(context)["r1"]
    assert result["restoration"] is None
    assert result["business_id"] is None
    assert result["merchant"] == "같은 식당"


def test_a_short_but_complete_name_needs_no_restoration(tmp_path: Path) -> None:
    context = prepare(tmp_path)
    store = ArtifactStore(context.paths, context.target)
    records = store.load("parse", ParseOutput).records
    store.save("parse", ParseOutput(records=(records[0].model_copy(update={"merchant": "명가"}),)))
    classify_records(context)
    query = lookup()
    query["facts"][0]["merchant"] = "명가"
    query["candidates"][0]["merchant"] = "명가"
    save_input(context, query)
    assert run_cli(context, "geocode") == 0
    result = results(context)["r1"]
    assert result["status"] == "success"
    assert result["restoration"] is None
    assert result["evidence"] == "name-branch-address-agreement"


def test_restoration_from_another_city_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    save_input(context, truncated_lookup())
    save_restorations(context, restore_entry(scope={**restore_entry()["scope"], "city": "busan"}))
    classify_records(context)
    assert run_cli(context, "geocode") == 1
    assert "cause=invalid-artifact" in capsys.readouterr().err
    assert not (context.paths.city_dir(context.target) / "geocode.json").exists()


def test_a_review_reference_cannot_carry_a_whole_original(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    save_input(context, truncated_lookup())
    entry = restore_entry()
    entry["references"][0]["detail"] = "가" * 501
    save_restorations(context, entry)
    classify_records(context)
    assert run_cli(context, "geocode") == 1
    assert "cause=invalid-artifact" in capsys.readouterr().err
    assert not (context.paths.city_dir(context.target) / "geocode.json").exists()


def test_previous_contract_version_is_preserved_and_regenerated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = prepare(tmp_path)
    save_input(context, truncated_lookup())
    save_restorations(context, restore_entry())
    classify_records(context)
    directory = context.paths.city_dir(context.target)
    legacy = json.dumps(
        {
            "schema_version": 2,
            "city": "seoul",
            "org": None,
            "dependencies": {},
            "payload": {"results": []},
        }
    )
    write_text(directory / "geocode.json", legacy)
    assert run_cli(context, "closure") == 1
    assert "cause=regeneration-required" in capsys.readouterr().err
    assert run_cli(context, "geocode") == 0
    assert results(context)["r1"]["restoration"]["restored_merchant"] == FULL_NAME
    archives = list((directory / "history").glob("geocode-v2-*.json"))
    assert len(archives) == 1
    assert archives[0].read_text(encoding="utf-8") == legacy


def test_run_applies_review_to_classification_and_marker_without_reparsing(
    tmp_path: Path,
) -> None:
    from deliciousmap.local import LocalAdapters
    from deliciousmap.pipeline import execute
    from tests.fakes import SyntheticAdapters
    from tests.test_pipeline import context_at

    class PreparedPredecessors(SyntheticAdapters):
        # 수집·파싱·분류만 합성이며 복원·판정·연결·빌드는 실제 구현을 실행한다.
        geocode = LocalAdapters.geocode
        closure = LocalAdapters.closure
        build = LocalAdapters.build

    context = context_at(tmp_path)
    execute("run", context, PreparedPredecessors())
    shared = context.paths.shared("headermap").read_bytes()
    assert payload(context, "build")["marker_count"] == 1

    write_text(
        context.paths.manual(context.target, "restore"),
        json.dumps(
            {
                "schema_version": 1,
                "scope": {"city": "seoul", "merchant": "합성 식당", "record_id": "r0"},
                "restored_merchant": "합성 식당 본점",
                "evidence": "기관의 다른 공개자료에서 전체 상호를 확인",
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    adapters = PreparedPredecessors()
    for stage in ("classify", "geocode", "closure", "build"):
        execute(stage, context, adapters)
    # 합성 어댑터는 분류만 담당한다. 원본을 새로 수집·파싱하지 않고 검토 결과만 반영한다.
    assert adapters.calls == ["classify"]
    assert adapters.classify_input is not None
    assert adapters.classify_input.merchants[0] == "합성 식당 본점"
    assert adapters.classify_input.records[0].merchant == "합성 식당"
    assert adapters.classify_input.restorations[0].record_id == "r0"
    assert context.paths.shared("headermap").read_bytes() == shared
    built = json.loads(
        (context.paths.output_root / "seoul" / "markers.json").read_text(encoding="utf-8")
    )
    assert built["schema_version"] == 5
    assert built["markers"][0]["merchant"] == "합성 식당 본점"
    ledger = json.loads(
        (context.paths.output_root / "seoul" / "ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["records"][0]["merchant"] == "합성 식당"
    assert payload(context, "build")["marker_count"] == 1
