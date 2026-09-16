import subprocess
import sys
from pathlib import Path

import pytest

from deliciousmap.cli import main


@pytest.mark.parametrize(
    "command",
    [None, "fetch", "headermap", "parse", "classify", "geocode", "closure", "build", "run"],
)
def test_help_needs_no_keys_or_network(command: str | None) -> None:
    args = [sys.executable, "-m", "deliciousmap"]
    if command:
        args.append(command)
    result = subprocess.run([*args, "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--city" in result.stdout if command else "headermap" in result.stdout


@pytest.mark.parametrize(
    "selection", [["--city", "unknown"], ["--city", "seoul", "--org", "busan"]]
)
def test_invalid_selection_is_rejected_before_execution(
    selection: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["fetch", *selection]) == 2
    assert "selection" in capsys.readouterr().err


def test_real_adapter_is_explicitly_unimplemented(capsys: pytest.CaptureFixture[str]) -> None:
    # 아직 게시판을 선언하지 않은 도시를 쓴다. 선언한 도시를 쓰면 이 시험이 기관 서버로
    # 실제 요청을 보낸다. 부산이 게시판을 선언해(#140) 대구로 옮겼다. 남은 도시는
    # 대구·인천·대전이며, 그 도시가 게시판을 선언하면 다시 옮긴다.
    assert main(["fetch", "--city", "daegu"]) == 1
    assert "fetch city=daegu org=* cause=not-implemented" in capsys.readouterr().err


def test_originals_cannot_be_stored_inside_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["fetch", "--city", "seoul", "--raw-root", str(Path.cwd() / "원본 파일")]) == 2
    assert "raw-root" in capsys.readouterr().err


def test_cli_injection_executes_the_selected_organization(tmp_path: Path) -> None:
    from deliciousmap.pipeline import execute
    from tests.fakes import SyntheticAdapters
    from tests.test_pipeline import context_at

    context = context_at(tmp_path)
    adapters = SyntheticAdapters()
    # 기관 지오코딩은 도시 판정을 인용하므로 도시 실행이 먼저다(#183).
    execute("run", context, adapters)
    assert (
        main(
            [
                "run",
                "--city",
                "seoul",
                "--org",
                "test-org",
                "--raw-root",
                str(context.paths.raw_root),
                "--data-root",
                str(context.paths.data_root),
                "--output-root",
                str(context.paths.output_root),
            ],
            cities=(context.target.city,),
            adapters=adapters,
        )
        == 0
    )
    assert (context.paths.data_root / "seoul" / "orgs" / "test-org" / "records.csv").exists()


@pytest.mark.parametrize("stage", ["fetch", "run"])
def test_every_real_stage_has_a_nonzero_unimplemented_exit(
    stage: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # 위와 같은 이유로 게시판을 선언하지 않은 도시를 쓴다.
    assert main([stage, "--city", "daegu"]) == 1
    assert "cause=not-implemented" in capsys.readouterr().err


@pytest.mark.parametrize("stage", ["headermap", "parse", "classify", "geocode", "closure", "build"])
def test_stages_with_missing_refined_inputs_report_io_error(
    stage: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([stage, "--city", "seoul", "--data-root", str(tmp_path)]) == 1
    # 사유 코드만으로는 무엇이 없는지 모른다. 종류와 루트 상대 경로를 함께 알린다.
    assert (
        "cause=io-error error=FileNotFoundError errno=ENOENT path=data-root/seoul/"
        in capsys.readouterr().err
    )
