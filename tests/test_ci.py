"""CI가 부르는 판정 명령. workflow YAML 자체는 실제 실행으로 확인하고 여기서는 판정만 본다."""

import hashlib
import json
from pathlib import Path

import pytest

from deliciousmap import publish
from deliciousmap.ci import main
from deliciousmap.registry import gwangju
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
    refined(data_root, "gwangju/closure.json")
    refined(data_root, "seoul/closure.json")
    refined(data_root, "_shared/classify.jsonl")
    refined(data_root, "manual/busan/classify.jsonl")
    # 수집만 끝난 도시는 빌드 대상이 아니다. 디렉터리는 있지만 `build` 입력이 없다.
    refined(data_root, "ulsan/orgs/ulsan-city/fetch.json")

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


def write_classify_artifact(
    path: Path, city: str, org: str | None, decisions: list[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 5,
                "city": city,
                "org": org,
                "dependencies": {},
                "payload": {"decisions": decisions},
            }
        ),
        encoding="utf-8",
    )


def test_check_data_accepts_matching_city_and_organization_classification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    decision = {"record_id": "record-1", "status": "restaurant", "evidence": "model"}
    write_classify_artifact(tmp_path / "gwangju" / "classify.json", "gwangju", None, [decision])
    write_classify_artifact(
        tmp_path / "gwangju" / "orgs" / "gwangju-buk" / "classify.json",
        "gwangju",
        "gwangju-buk",
        [decision],
    )
    refined(tmp_path, "gwangju/closure.json")

    assert main(["check-data", "--data-root", str(tmp_path)], cities=(gwangju.CITY,)) == 0
    assert capsys.readouterr().out.split() == ["gwangju"]


def test_check_data_rejects_city_and_organization_classification_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    city_decision = {"record_id": "record-1", "status": "restaurant", "evidence": "model"}
    org_decision = {"record_id": "record-1", "status": "pending", "evidence": "not-configured"}
    write_classify_artifact(
        tmp_path / "gwangju" / "classify.json", "gwangju", None, [city_decision]
    )
    write_classify_artifact(
        tmp_path / "gwangju" / "orgs" / "gwangju-buk" / "classify.json",
        "gwangju",
        "gwangju-buk",
        [org_decision],
    )
    refined(tmp_path, "gwangju/closure.json")

    assert main(["check-data", "--data-root", str(tmp_path)], cities=(gwangju.CITY,)) == 1
    error = capsys.readouterr().err
    assert "city/organization classify mismatch" in error
    assert "gwangju/gwangju-buk/record-1" in error


def test_check_data_rejects_an_organization_record_missing_from_city_classification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_classify_artifact(
        tmp_path / "gwangju" / "classify.json",
        "gwangju",
        None,
        [{"record_id": "city-record", "status": "restaurant", "evidence": "model"}],
    )
    write_classify_artifact(
        tmp_path / "gwangju" / "orgs" / "gwangju-buk" / "classify.json",
        "gwangju",
        "gwangju-buk",
        [{"record_id": "org-record", "status": "restaurant", "evidence": "model"}],
    )
    refined(tmp_path, "gwangju/closure.json")

    assert main(["check-data", "--data-root", str(tmp_path)], cities=(gwangju.CITY,)) == 1
    assert "organization classify record not in city" in capsys.readouterr().err


def write_geocode_artifact(
    path: Path, city: str, org: str | None, results: list[dict[str, object]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 5,
                "city": city,
                "org": org,
                "dependencies": {},
                "payload": {"results": results},
            }
        ),
        encoding="utf-8",
    )


def placed(record_id: str, latitude: float, evidence: str) -> dict[str, object]:
    return {"record_id": record_id, "latitude": latitude, "evidence": evidence}


def test_check_data_names_every_record_the_organization_geocodes_differently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """사이트는 도시 판정으로 빌드한다. 기관이 다르게 판정한 레코드를 조용히 두지 않는다(#183)."""
    write_geocode_artifact(
        tmp_path / "gwangju" / "geocode.json",
        "gwangju",
        None,
        [
            placed("record-1", 35.1, "provider-cross license+naver"),
            placed("record-2", 35.3, "single-provider license"),
        ],
    )
    write_geocode_artifact(
        tmp_path / "gwangju" / "orgs" / "gwangju-buk" / "geocode.json",
        "gwangju",
        "gwangju-buk",
        [
            placed("record-1", 35.1, "provider-cross license+naver"),
            placed("record-2", 35.2, "provider-cross license+naver"),
            placed("record-3", 35.4, "single-provider license"),
        ],
    )
    refined(tmp_path, "gwangju/closure.json")

    assert main(["check-data", "--data-root", str(tmp_path)], cities=(gwangju.CITY,)) == 1
    assert capsys.readouterr().err.splitlines() == [
        "check-data: city/organization geocode mismatch: gwangju/gwangju-buk/record-2",
        "check-data: organization geocode record not in city: gwangju/gwangju-buk/record-3",
        "check-data: city/organization geocode mismatches: gwangju/gwangju-buk 2",
    ]


def test_check_data_accepts_an_organization_geocode_citing_the_city(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = placed("record-1", 35.1, "provider-cross license+naver")
    write_geocode_artifact(
        tmp_path / "gwangju" / "geocode.json",
        "gwangju",
        None,
        [result, placed("record-2", 35.3, "single-provider license")],
    )
    write_geocode_artifact(
        tmp_path / "gwangju" / "orgs" / "gwangju-buk" / "geocode.json",
        "gwangju",
        "gwangju-buk",
        [result],
    )
    refined(tmp_path, "gwangju/closure.json")

    assert main(["check-data", "--data-root", str(tmp_path)], cities=(gwangju.CITY,)) == 0
    assert capsys.readouterr().out.split() == ["gwangju"]


COMMIT = "c0ffee" + "0" * 34
SITE_FILES = {
    "index.html",
    "sw.js",
    "manifest.webmanifest",
    "assets/app.js",
    "assets/styles.css",
    "assets/icon-192.png",
    "assets/icon-512.png",
    "assets/icon-maskable-512.png",
    "assets/apple-touch-icon.png",
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


def test_check_dist_rejects_an_app_icon_that_is_not_published(
    dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """manifest가 없는 아이콘을 가리키면 설치 조건이 조용히 깨진다."""
    replace_in(dist / "manifest.webmanifest", '"assets/icon-512.png"', '"assets/icon-1024.png"')

    assert check_dist(dist, "seoul") == 1

    assert "manifest.webmanifest -> assets/icon-1024.png" in capsys.readouterr().err
    assert not (dist / "deploy-manifest.json").exists()


def test_check_dist_still_rejects_an_image_outside_the_published_icons(
    dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (dist / "assets" / "icon-1024.png").write_bytes((dist / "assets" / "icon-512.png").read_bytes())

    assert check_dist(dist, "seoul") == 1

    assert "not a screen file: assets/icon-1024.png" in capsys.readouterr().err


def test_a_city_with_only_collection_artifacts_is_not_buildable(tmp_path: Path) -> None:
    """수집만 끝난 도시는 사이트 빌드 대상이 아니다(이슈 #141).

    `data/<city>/`가 생겼다고 빌드하면 `build`가 읽을 입력이 없어 io-error로 멈춘다.
    서울은 기관별 `fetch.json`만 커밋된 상태로 이 자리에 들어온다.
    """
    from deliciousmap import publish
    from deliciousmap.registry import CITIES as REGISTRY

    (tmp_path / "seoul" / "orgs" / "seoul-city").mkdir(parents=True)
    (tmp_path / "seoul" / "orgs" / "seoul-city" / "fetch.json").write_text("{}", encoding="utf-8")
    (tmp_path / "gwangju").mkdir()
    (tmp_path / "gwangju" / "closure.json").write_text("{}", encoding="utf-8")

    buildable = publish.buildable_cities(tmp_path, REGISTRY)
    assert [city.slug for city in buildable] == ["gwangju"]


def test_check_data_rejects_an_organization_geocode_with_nothing_to_cite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_geocode_artifact(
        tmp_path / "gwangju" / "orgs" / "gwangju-buk" / "geocode.json",
        "gwangju",
        "gwangju-buk",
        [placed("record-1", 35.1, "provider-cross license+naver")],
    )
    refined(tmp_path, "gwangju/closure.json")

    assert main(["check-data", "--data-root", str(tmp_path)], cities=(gwangju.CITY,)) == 1
    assert capsys.readouterr().err.splitlines() == [
        "check-data: organization geocode without city geocode: gwangju/gwangju-buk",
    ]
