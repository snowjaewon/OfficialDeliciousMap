"""한 실행이 같은 산출물과 같은 이력을 되풀이해 읽던 것을 막는다(#191).

읽기 횟수를 세는 이유: 줄인 것이 계산이 아니라 읽기·검증 자체다. 결과만 보면 다섯 번 읽어도
같은 값이 나오므로 시험이 아무것도 지키지 못한다. 재사용이 다시 읽은 것과 다른 답을 내면
안 되므로, 산출물·장부·상류가 바뀐 뒤의 재사용도 함께 막는다. 원본 경로 검증 두 건은 같은
이슈가 뺀 루프 불변 `resolve()`가 검증 의미를 바꾸지 않았음을 고정한다.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from deliciousmap import storage
from deliciousmap.contracts import (
    CacheEntry,
    ClassifyOutput,
    FetchOutput,
    GeocodeOutput,
    ParseOutput,
    SourceRef,
    SourceReport,
)
from deliciousmap.paths import Paths
from deliciousmap.pipeline import ExecutionContext, execute
from deliciousmap.storage import ArtifactStore
from tests.fakes import SyntheticAdapters
from tests.test_pipeline import context_at


def counted(monkeypatch: pytest.MonkeyPatch, name: str) -> Counter[str]:
    """`storage`의 읽기 함수를 파일 이름별로 센다."""
    counts: Counter[str] = Counter()
    original = getattr(storage, name)

    def wrapper(path: Path, *rest: Any, **named: Any) -> Any:
        counts[path.name] += 1
        return original(path, *rest, **named)

    monkeypatch.setattr(storage, name, wrapper)
    return counts


def prepared(tmp_path: Path) -> ExecutionContext:
    context = context_at(tmp_path)
    execute("run", context, SyntheticAdapters())
    return context


def test_a_geocode_run_reads_each_upstream_artifact_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """도시 geocode는 parse를 직접·classify 검증·후보 조회·저장 검증에서 거듭 필요로 한다."""
    context = prepared(tmp_path)
    reads = counted(monkeypatch, "read_artifact")
    execute("geocode", context, SyntheticAdapters())
    assert reads["parse.json"] == 1
    assert reads["classify.json"] == 1


def test_a_second_parse_read_does_not_revalidate_the_collection_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """parse 검증은 원본별 보고를 대조하려고 수집 장부를 연다. 그 읽기가 parse마다 따라온다."""
    context = context_at(tmp_path)
    adapters = SyntheticAdapters()
    for stage in ("fetch", "headermap", "parse"):
        execute(stage, context, adapters)
    store = ArtifactStore(context.paths, context.target)
    parsed = store.load("parse", ParseOutput)
    reported = SourceReport(source_hash="a" * 64, status="parsed", records=len(parsed.records))
    reads = counted(monkeypatch, "read_artifact")
    store.save("parse", parsed.model_copy(update={"sources": (reported,)}))
    assert store.load("parse", ParseOutput).sources == (reported,)
    assert store.load("parse", ParseOutput).sources == (reported,)
    # 저장 검증이 한 번, 바뀐 파일을 다시 읽은 것이 한 번이다. 수집 장부는 그동안 그대로다.
    assert reads["parse.json"] == 1
    assert reads["fetch.json"] == 1


def test_a_rewritten_artifact_is_read_again_within_one_store(tmp_path: Path) -> None:
    context = prepared(tmp_path)
    store = ArtifactStore(context.paths, context.target)
    assert store.load("parse", ParseOutput).reporting_period == ""
    path = context.paths.city_dir(context.target) / "parse.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["reporting_period"] = "2026-01-01/2026-12-31"
    storage.write_text(path, storage.artifact_text(envelope))
    assert store.load("parse", ParseOutput).reporting_period == "2026-01-01/2026-12-31"


def test_a_rewritten_record_ledger_is_read_again_within_one_store(tmp_path: Path) -> None:
    """레코드는 `parse.json`이 아니라 장부 CSV에 있다. 든 값은 그 파일의 변경도 놓치면 안 된다."""
    context = prepared(tmp_path)
    store = ArtifactStore(context.paths, context.target)
    assert {record.department for record in store.load("parse", ParseOutput).records} == {"총무과"}
    path = context.paths.city_dir(context.target) / "records.csv"
    storage.write_text(path, path.read_text(encoding="utf-8").replace("총무과", "기획과"))
    assert {record.department for record in store.load("parse", ParseOutput).records} == {"기획과"}


def test_a_changed_upstream_still_stales_a_held_artifact(tmp_path: Path) -> None:
    """든 값이 상류의 낡음을 건너뛰면 안 된다. 적중은 다시 읽은 것과 같은 답이어야 한다."""
    context = prepared(tmp_path)
    store = ArtifactStore(context.paths, context.target)
    store.load("classify", ClassifyOutput)
    path = context.paths.city_dir(context.target) / "parse.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["reporting_period"] = "2026-01-01/2026-12-31"
    storage.write_text(path, storage.artifact_text(envelope))
    with pytest.raises(ValueError, match="stale artifact"):
        store.load("classify", ClassifyOutput)


def test_saving_drops_the_history_the_store_held(tmp_path: Path) -> None:
    """저장이 이력에 덧쓴다. 든 값을 그대로 두면 다음에 묻는 쪽이 방금 쓴 줄을 못 본다."""
    context = prepared(tmp_path)
    store = ArtifactStore(context.paths, context.target)
    assert store.previous_geocodes()
    geocoded = store.load("geocode", GeocodeOutput)
    changed = geocoded.model_copy(
        update={
            "results": tuple(
                item.model_copy(update={"evidence": item.evidence + " (다시 확인)"})
                for item in geocoded.results
            )
        }
    )
    store.save("geocode", changed)
    assert {item.evidence for item in store.previous_geocodes()} == {
        item.evidence for item in changed.results
    }


def test_a_geocode_run_reads_its_history_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """앞선 판정 읽기·저장의 revision 계산·이력 덧쓰기가 같은 파일을 각각 열었다."""
    context = context_at(tmp_path)
    reads = counted(monkeypatch, "read_cache")
    execute("run", context, SyntheticAdapters())
    assert (context.paths.city_dir(context.target) / "geocode-history-v2.jsonl").exists()
    assert reads["geocode-history-v2.jsonl"] == 1


def test_supplied_history_still_refuses_to_overwrite(tmp_path: Path) -> None:
    """이미 읽어 둔 이력을 넘겨도 같은 키/revision을 다른 값으로 덮는 것은 막는다."""
    path = tmp_path / "이력.jsonl"
    entry = CacheEntry(key="가", revision=1, valid=True, evidence="synthetic", value={"a": 1})
    storage.append_cache(path, entry)
    known = storage.read_cache(path)
    with pytest.raises(ValueError, match="cannot overwrite cache history"):
        storage.append_cache_entries(
            path, (entry.model_copy(update={"value": {"a": 2}}),), known=known
        )


def source_at(path: Path) -> FetchOutput:
    return FetchOutput(
        sources=(
            SourceRef(
                path=path,
                source_hash="a" * 64,
                organization="test-org",
                board="expenses",
                url="https://example.invalid/expense/1",
                container="ooxml",
            ),
        )
    )


def test_a_source_outside_raw_root_is_refused(tmp_path: Path) -> None:
    """상대 경로라도 거슬러 올라가면 raw-root 밖이다. 이어 붙인 자리를 보고 판정한다."""
    context = context_at(tmp_path)
    store = ArtifactStore(context.paths, context.target)
    with pytest.raises(ValueError, match="outside repository and within raw-root"):
        store.save("fetch", source_at(Path("..") / "바깥" / "원본.xlsx"))


def test_a_source_inside_a_repository_under_raw_root_is_refused(tmp_path: Path) -> None:
    """저장소를 raw-root 아래에 둔 배치. raw-root 안이어도 저장소 안이면 거부한다."""
    raw_root = tmp_path / "외부 원본"
    repository = raw_root / "저장소"
    paths = Paths(repository, raw_root, repository / "data", tmp_path / "출력 폴더")
    store = ArtifactStore(paths, context_at(tmp_path).target)
    with pytest.raises(ValueError, match="outside repository and within raw-root"):
        store.save("fetch", source_at(Path("저장소") / "원본.xlsx"))
    store.save("fetch", source_at(Path("원본.xlsx")))
