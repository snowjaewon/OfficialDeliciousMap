"""원본이 있는 곳은 `--raw-root` 기준 상대 경로 한 가지 모양이다(#202).

수집이 남긴 절대 경로는 `raw_root / source.path`에서 왼쪽을 버리게 해, 원본 폴더를 옮기거나
다른 PC에서 열면 그 PC의 `--raw-root`가 무슨 값이든 수집 당시의 경로를 열었다. Linux에서는
반대로 역슬래시가 구분자가 아니라 파일 이름 한 낱말로 붙었다. 계약이 그 모양을 거부하고,
이관 도구가 이미 커밋된 fetch 산출물과 거기 서명한 headermap 봉투를 함께 옮긴다.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from deliciousmap.contracts import FetchOutput, SourceRef
from deliciousmap.storage import artifact_digest, artifact_text, write_text
from scripts.relativize_source_paths import migrate

RELATIVE = "busan/busan-city/expenses-mayor/21945-1.xlsx"


def source(path: str) -> dict[str, str]:
    return {
        "path": path,
        "source_hash": "a" * 64,
        "organization": "busan-city",
        "board": "expenses-mayor",
        "url": "https://example.invalid/expense/1",
        "container": "ooxml",
    }


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\합성계정\deliciousmap-raw\busan\busan-city\expenses-mayor\21945-1.xlsx",
        "C:/Users/합성계정/deliciousmap-raw/busan/busan-city/expenses-mayor/21945-1.xlsx",
        "/raw/busan/busan-city/expenses-mayor/21945-1.xlsx",
        r"busan\busan-city\expenses-mayor\21945-1.xlsx",
        "",
    ],
)
def test_an_original_outside_the_one_notation_is_refused(path: str) -> None:
    """드라이브·루트·역슬래시를 담은 값은 PC마다 다른 파일을 가리킨다. 계약이 먼저 막는다."""
    with pytest.raises(ValidationError, match="relative to raw-root"):
        SourceRef.model_validate(source(path))


def test_a_fetch_artifact_carrying_an_absolute_original_is_refused() -> None:
    """산출물 검증도 같은 계약을 쓴다. 절대 경로를 담은 fetch는 저장소에 닿지 못한다."""
    absolute = r"C:\Users\합성계정\deliciousmap-raw\busan\busan-city\expenses-mayor\21945-1.xlsx"
    with pytest.raises(ValidationError, match="relative to raw-root"):
        FetchOutput.model_validate({"sources": [source(absolute)]})


def test_a_relative_original_reads_and_writes_one_separator() -> None:
    """플랫폼이 달라도 산출물에 남는 글자는 하나다. 읽을 때는 그 PC의 경로로 이어 붙는다."""
    reference = SourceRef.model_validate(source(RELATIVE))
    assert reference.model_dump(mode="json")["path"] == RELATIVE
    assert reference.path.parts == ("busan", "busan-city", "expenses-mayor", "21945-1.xlsx")
    assert Path("raw") / reference.path == Path("raw", *reference.path.parts)


def artifact(path: Path, envelope: dict[str, object]) -> None:
    write_text(path, artifact_text(envelope))


def committed(data_root: Path, *paths: str) -> tuple[Path, Path]:
    """이관 전 저장소 한 조각. fetch 산출물과 그 해시에 서명한 headermap 봉투다."""
    directory = data_root / "busan" / "orgs" / "busan-city"
    fetch = directory / "fetch.json"
    headermap = directory / "headermap.json"
    artifact(
        fetch,
        {
            "schema_version": 4,
            "city": "busan",
            "org": "busan-city",
            "dependencies": {},
            "payload": {"sources": [source(path) for path in paths], "missing": []},
        },
    )
    artifact(
        headermap,
        {
            "schema_version": 2,
            "city": "busan",
            "org": "busan-city",
            "dependencies": {"fetch.json": artifact_digest(fetch)},
            "payload": {"mappings": [], "unresolved": []},
        },
    )
    return fetch, headermap


def envelope(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_migration_strips_the_collecting_pc_prefix_from_every_original(tmp_path: Path) -> None:
    fetch, _ = committed(
        tmp_path / "data",
        r"C:\Users\합성계정\orca\deliciousmap-raw\busan\busan-city\expenses-mayor\21945-1.xlsx",
        r"C:\Users\상대\deliciousmap-raw\busan\busan-city\expenses-mayor\21945-2.xlsx",
    )
    assert migrate(tmp_path / "data") == (fetch, fetch.parent / "headermap.json")
    assert [item["path"] for item in envelope(fetch)["payload"]["sources"]] == [
        "busan/busan-city/expenses-mayor/21945-1.xlsx",
        "busan/busan-city/expenses-mayor/21945-2.xlsx",
    ]


def test_migration_signs_the_moved_fetch_in_the_headermap_envelope(tmp_path: Path) -> None:
    """두 가지를 같이 하지 않으면 그 사이 저장소 상태에서 parse가 `stale artifact`로 멈춘다."""
    fetch, headermap = committed(
        tmp_path / "data",
        r"C:\Users\합성계정\orca\deliciousmap-raw\busan\busan-city\expenses-mayor\21945-1.xlsx",
    )
    before = envelope(headermap)["dependencies"]["fetch.json"]
    migrate(tmp_path / "data")
    assert envelope(headermap)["dependencies"]["fetch.json"] == artifact_digest(fetch)
    assert envelope(headermap)["dependencies"]["fetch.json"] != before


def test_migration_changes_nothing_on_a_second_run(tmp_path: Path) -> None:
    fetch, headermap = committed(
        tmp_path / "data",
        r"C:\Users\합성계정\orca\deliciousmap-raw\busan\busan-city\expenses-mayor\21945-1.xlsx",
    )
    migrate(tmp_path / "data")
    moved = (fetch.read_bytes(), headermap.read_bytes())
    assert migrate(tmp_path / "data") == ()
    assert (fetch.read_bytes(), headermap.read_bytes()) == moved


def test_migration_refuses_an_original_that_is_not_under_its_own_board(tmp_path: Path) -> None:
    """도시·기관·게시판으로 끝나지 않으면 접두사를 뗄 자리를 알 수 없다. 조용히 넘기지 않는다."""
    committed(tmp_path / "data", r"C:\Users\합성계정\deliciousmap-raw\어딘가\21945-1.xlsx")
    with pytest.raises(ValueError, match="busan/busan-city/expenses-mayor"):
        migrate(tmp_path / "data")


def test_migration_does_not_sign_a_headermap_that_was_already_stale(tmp_path: Path) -> None:
    """이관이 낡게 한 것이 아닌 서명은 덮지 않는다. 덮으면 `stale artifact` 거부를 지나간다."""
    fetch, headermap = committed(
        tmp_path / "data",
        r"C:\Users\합성계정\deliciousmap-raw\busan\busan-city\expenses-mayor\21945-1.xlsx",
    )
    stale = envelope(headermap)
    stale["dependencies"]["fetch.json"] = "f" * 64
    artifact(headermap, stale)
    before = fetch.read_bytes()
    with pytest.raises(ValueError, match="already stale before this migration"):
        migrate(tmp_path / "data")
    assert fetch.read_bytes() == before
    assert envelope(headermap)["dependencies"]["fetch.json"] == "f" * 64
