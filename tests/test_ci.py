"""CI가 부르는 판정 명령. workflow YAML 자체는 실제 실행으로 확인하고 여기서는 판정만 본다."""

import hashlib
import json
from pathlib import Path

import pytest

from deliciousmap import publish
from deliciousmap.ci import main
from tests.test_geocoding_cli import run_cli
from tests.test_site_build import build_ready

LIMIT = 20_000_000


def refined(data_root: Path, name: str, size: int = 10) -> Path:
    path = data_root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_check_data_rejects_a_refined_artifact_over_20mb(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_root = tmp_path / "data"
    refined(data_root, "gwangju/records.csv", LIMIT)
    refined(data_root, "_shared/classify.jsonl", LIMIT + 1)

    assert main(["check-data", "--data-root", str(data_root)]) == 1

    error = capsys.readouterr().err
    assert "_shared/classify.jsonl" in error
    assert "gwangju/records.csv" not in error


def test_check_data_lists_only_cities_with_committed_artifacts_in_registry_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_root = tmp_path / "data"
    refined(data_root, "gwangju/records.csv")
    refined(data_root, "seoul/records.csv")
    refined(data_root, "_shared/classify.jsonl")
    refined(data_root, "manual/busan/classify.jsonl")

    assert main(["check-data", "--data-root", str(data_root)]) == 0

    assert capsys.readouterr().out.split() == ["seoul", "gwangju"]


def test_check_data_fails_when_no_city_can_be_built(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """빈 사이트를 성공으로 배포하지 않는다."""
    data_root = tmp_path / "data"
    refined(data_root, "_shared/classify.jsonl")

    assert main(["check-data", "--data-root", str(data_root)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no city" in captured.err


def test_check_data_rejects_a_directory_that_is_not_a_registered_city(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """오타 난 도시 디렉터리를 조용히 빼고 넘어가지 않는다."""
    data_root = tmp_path / "data"
    refined(data_root, "gwangju/records.csv")
    refined(data_root, "gwanju/records.csv")

    assert main(["check-data", "--data-root", str(data_root)]) == 1

    assert "gwanju" in capsys.readouterr().err


COMMIT = "c0ffee" + "0" * 34
SITE_FILES = {
    "index.html",
    "sw.js",
    "manifest.webmanifest",
    "assets/app.js",
    "assets/styles.css",
    "seoul/index.html",
    "seoul/markers.json",
    "seoul/records.json",
}


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """합성 정제 산출물로 실제 build를 돌린 서울 사이트."""
    context = build_ready(tmp_path)
    assert run_cli(context, "build") == 0
    return context.paths.output_root


def check_dist(dist: Path, *cities: str) -> int:
    city_args = [argument for city in cities for argument in ("--city", city)]
    return main(["check-dist", "--dist", str(dist), "--commit", COMMIT, *city_args])


def test_check_dist_seals_a_built_site_with_path_digests_and_commit(dist: Path) -> None:
    assert check_dist(dist, "seoul") == 0

    manifest = json.loads((dist / "deploy-manifest.json").read_text(encoding="utf-8"))
    assert manifest["commit"] == COMMIT
    files = {item["path"]: item for item in manifest["files"]}
    # manifest 자신은 대조 목록에 넣지 않는다.
    assert set(files) == SITE_FILES
    markers = (dist / "seoul" / "markers.json").read_bytes()
    assert files["seoul/markers.json"]["sha256"] == hashlib.sha256(markers).hexdigest()
    assert files["seoul/markers.json"]["bytes"] == len(markers)


def test_check_dist_rejects_a_file_over_the_pages_25mib_limit_without_sealing(
    dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with (dist / "seoul" / "records.json").open("ab") as stream:
        stream.truncate(25 * 1024 * 1024 + 1)

    assert check_dist(dist, "seoul") == 1

    assert "seoul/records.json" in capsys.readouterr().err
    assert not (dist / "deploy-manifest.json").exists()


def test_check_dist_rejects_more_files_than_the_plan_allows(
    dist: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 실제 한도(Free 20,000개)를 채우는 대신 한도를 사이트 파일 수로 둔다.
    # 함께 올리는 manifest도 한 개로 세므로 한도를 넘는다.
    monkeypatch.setattr(publish, "PAGES_FILE_COUNT", len(SITE_FILES))

    assert check_dist(dist, "seoul") == 1

    assert f"{len(SITE_FILES) + 1} files" in capsys.readouterr().err


def test_check_dist_publishes_only_screen_files(
    dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """정제 산출물이나 캐시가 공개 사이트에 섞이면 막는다."""
    (dist / "seoul" / "records.csv").write_text("record_id\n", encoding="utf-8")
    (dist / "_shared").mkdir()
    (dist / "_shared" / "classify.jsonl").write_text("{}\n", encoding="utf-8")

    assert check_dist(dist, "seoul") == 1

    error = capsys.readouterr().err
    assert "seoul/records.csv" in error
    assert "_shared/classify.jsonl" in error


def test_check_dist_requires_every_built_city_and_nothing_else(
    dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check_dist(dist, "seoul", "gwangju") == 1

    assert "gwangju/index.html" in capsys.readouterr().err


def replace_in(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_check_dist_rejects_references_to_files_that_are_not_published(
    dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    replace_in(
        dist / "seoul" / "index.html",
        'data-markers-url="./markers.json"',
        'data-markers-url="./gone.json"',
    )
    replace_in(dist / "index.html", 'href="./seoul/"', 'href="./busan/"')
    replace_in(dist / "sw.js", '"./assets/styles.css"', '"./assets/old.css"')

    assert check_dist(dist, "seoul") == 1

    error = capsys.readouterr().err
    assert "seoul/index.html -> seoul/gone.json" in error
    assert "index.html -> busan/index.html" in error
    assert "sw.js -> assets/old.css" in error
    assert not (dist / "deploy-manifest.json").exists()
