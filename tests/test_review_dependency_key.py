"""manual 파일 4종의 산출물 의존성 키는 근거 필드를 뺀 판정 필드만 읽는다(#190)."""

import json
from pathlib import Path

import pytest

from deliciousmap.contracts import (
    REVIEW_EVIDENCE_FIELDS,
    ClassifyOutput,
    Contract,
    GeocodeOutput,
    IdentityConfirmation,
    ManualCorrection,
    MerchantReview,
    NameRestoration,
    ParseOutput,
)
from deliciousmap.pipeline import ExecutionContext, execute
from deliciousmap.storage import ArtifactStore, review_digest, write_text
from tests.fakes import SyntheticAdapters
from tests.test_pipeline import context_at

# 합성 레코드의 어느 상호와도 맞지 않는 범위. 판정에 적용되지 않아도 키에는 들어간다.
SCOPE = {
    "city": "seoul",
    "merchant": "무관한 상호",
    "organization": None,
    "source_hash": None,
    "record_id": None,
}
REFERENCE = {"kind": "other", "source": "synthetic", "detail": "synthetic detail"}
SOURCE = {"provider": "naver", "source_id": "1", "reference": "https://example.invalid/1"}

# manual 파일 이름 → (그 파일을 키에 담는 단계, 산출물 모델, 검토 모델, 줄 두 개, 판정 필드 변경)
CASES: dict[str, tuple[str, type[Contract], type[Contract], list[dict], dict]] = {
    "merchants": (
        "parse",
        ParseOutput,
        MerchantReview,
        [
            {"schema_version": 1, "scope": SCOPE, "merchants": ["가", "나"], "evidence": "e1"},
            {
                "schema_version": 1,
                "scope": SCOPE | {"merchant": "다른 상호"},
                "merchants": ["다"],
                "evidence": "e2",
            },
        ],
        {"merchants": ["가", "라"]},
    ),
    "classify": (
        "classify",
        ClassifyOutput,
        ManualCorrection,
        [
            {"city": "seoul", "merchant": "무관한 상호", "status": "restaurant", "evidence": "e1"},
            {
                "city": "seoul",
                "merchant": "다른 상호",
                "status": "non_restaurant",
                "evidence": "e2",
            },
        ],
        {"status": "non_restaurant"},
    ),
    "restore": (
        "classify",
        ClassifyOutput,
        NameRestoration,
        [
            {
                "schema_version": 1,
                "scope": SCOPE,
                "restored_merchant": "복원 상호",
                "evidence": "e1",
            },
            {
                "schema_version": 1,
                "scope": SCOPE | {"merchant": "다른 상호"},
                "restored_merchant": "다른 복원 상호",
                "evidence": "e2",
            },
        ],
        {"restored_merchant": "바뀐 복원 상호"},
    ),
    "geocode": (
        "geocode",
        GeocodeOutput,
        IdentityConfirmation,
        [
            {
                "schema_version": 1,
                "scope": SCOPE,
                "candidate_source": SOURCE,
                "merchant": "확인 상호",
                "branch": "",
                "address": "합성 주소 1",
                "evidence": "e1",
            },
            {
                "schema_version": 1,
                "scope": SCOPE | {"merchant": "다른 상호"},
                "candidate_source": SOURCE,
                "merchant": "다른 확인 상호",
                "branch": "본점",
                "address": "합성 주소 2",
                "evidence": "e2",
            },
        ],
        {"address": "바뀐 주소"},
    ),
}

# 판정이 읽는 필드. 모델에 판정 필드가 늘면 여기와 키가 함께 늘고, 근거 필드가 늘면
# `REVIEW_EVIDENCE_FIELDS`를 고쳐야 한다(#190).
DECISION_FIELDS: dict[type[Contract], set[str]] = {
    MerchantReview: {"schema_version", "scope", "merchants"},
    ManualCorrection: {
        "schema_version",
        "city",
        "merchant",
        "organization",
        "source_hash",
        "status",
    },
    NameRestoration: {"schema_version", "scope", "restored_merchant"},
    IdentityConfirmation: {
        "schema_version",
        "scope",
        "candidate_source",
        "merchant",
        "branch",
        "address",
    },
}


def save_lines(context: ExecutionContext, name: str, entries: list[dict]) -> None:
    write_text(
        context.paths.manual(context.target, name),
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
    )


def run_with(tmp_path: Path, name: str) -> tuple[ExecutionContext, ArtifactStore]:
    context = context_at(tmp_path)
    save_lines(context, name, CASES[name][3])
    execute("run", context, SyntheticAdapters())
    return context, ArtifactStore(context.paths, context.target)


def with_evidence_changed(entry: dict, model: type[Contract]) -> dict:
    changed = entry | {"evidence": entry["evidence"] + " (문구 보강)"}
    if "references" in model.model_fields:
        changed["references"] = [REFERENCE]
    return changed


@pytest.mark.parametrize("name", CASES)
def test_evidence_and_references_edits_do_not_stale_the_artifact(tmp_path: Path, name: str) -> None:
    stage, output, model, entries, _ = CASES[name]
    context, store = run_with(tmp_path, name)
    save_lines(context, name, [with_evidence_changed(entry, model) for entry in entries])
    store.load(stage, output)


@pytest.mark.parametrize("name", CASES)
def test_reordered_lines_do_not_stale_the_artifact(tmp_path: Path, name: str) -> None:
    stage, output, _, entries, _ = CASES[name]
    context, store = run_with(tmp_path, name)
    save_lines(context, name, list(reversed(entries)))
    store.load(stage, output)


@pytest.mark.parametrize("name", CASES)
def test_a_changed_decision_field_stales_the_artifact(tmp_path: Path, name: str) -> None:
    stage, output, _, entries, change = CASES[name]
    context, store = run_with(tmp_path, name)
    save_lines(context, name, [entries[0] | change, entries[1]])
    with pytest.raises(ValueError, match="stale artifact"):
        store.load(stage, output)


def test_restorations_stale_geocode_as_well_as_classify(tmp_path: Path) -> None:
    """복원명은 classify와 geocode가 함께 읽으므로 두 산출물이 같은 키를 검사한다."""
    _, _, _, entries, change = CASES["restore"]
    context, store = run_with(tmp_path, "restore")
    save_lines(context, "restore", [entries[0] | change, entries[1]])
    with pytest.raises(ValueError, match="stale artifact"):
        store.load("geocode", GeocodeOutput)


def test_review_models_are_exactly_decision_fields_plus_the_evidence_list() -> None:
    """근거 필드 목록은 `contracts.py` 상수 한곳이고, 네 모델은 그 목록과 판정 필드로만 이뤄진다."""
    assert REVIEW_EVIDENCE_FIELDS == {"evidence", "references"}
    for model, decision in DECISION_FIELDS.items():
        fields = set(model.model_fields)
        evidence = fields & REVIEW_EVIDENCE_FIELDS
        assert "evidence" in evidence, model.__name__
        assert fields == decision | evidence, model.__name__
        assert not (decision & REVIEW_EVIDENCE_FIELDS), model.__name__


def test_review_digest_treats_a_missing_file_and_an_empty_file_alike(tmp_path: Path) -> None:
    path = tmp_path / "manual" / "seoul" / "restore.jsonl"
    absent = review_digest(path, NameRestoration)
    write_text(path, "")
    assert review_digest(path, NameRestoration) == absent
    # 판정 줄이 생기면 키가 바뀐다. 근거 필드만 다른 두 파일은 같은 키다.
    save = lambda evidence: write_text(  # noqa: E731
        path,
        json.dumps(
            {"scope": SCOPE, "restored_merchant": "복원 상호", "evidence": evidence},
            ensure_ascii=False,
        )
        + "\n",
    )
    save("e1")
    first = review_digest(path, NameRestoration)
    assert first != absent
    save("e2")
    assert review_digest(path, NameRestoration) == first
