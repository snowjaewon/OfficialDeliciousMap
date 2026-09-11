"""Argument and exit-code translation for the pipeline."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from deliciousmap import gemini, licenses, naver
from deliciousmap.lookup import CandidateProvider
from deliciousmap.paths import Paths
from deliciousmap.pipeline import STAGES, Adapters, ExecutionContext, PipelineFailure, execute
from deliciousmap.registry import CITIES, City, select_target
from deliciousmap.transport import JsonTransport, Transport


def main(
    argv: Sequence[str] | None = None,
    *,
    cities: tuple[City, ...] = CITIES,
    adapters: Adapters | None = None,
    naver_transport: Transport | None = None,
    license_transport: Transport | None = None,
    model_transport: JsonTransport | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="deliciousmap")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (*STAGES, "run"):
        command = commands.add_parser(name, help=f"Execute {name}")
        command.add_argument("--city", required=True, help="City slug (e.g. seoul)")
        command.add_argument(
            "--org", help="Organization slug; default: all registered organizations"
        )
        command.add_argument(
            "--raw-root",
            type=Path,
            default=Path.cwd().parent / "deliciousmap-raw",
            help="Originals outside repository (default: ../deliciousmap-raw)",
        )
        command.add_argument(
            "--data-root", type=Path, default=Path("data"), help="Refined artifacts (default: data)"
        )
        command.add_argument(
            "--output-root", type=Path, default=Path("dist"), help="Build output (default: dist)"
        )
        command.add_argument(
            "--retry-failed",
            action="store_true",
            help="Allow failed geocoding retries (default: reuse failures)",
        )
    args = parser.parse_args(argv)
    try:
        target = select_target(cities, args.city, args.org)
        paths = Paths(Path.cwd(), args.raw_root, args.data_root, args.output_root)
        paths.validate()
    except ValueError as exc:
        print(f"selection: {exc}", file=sys.stderr)
        return 2
    try:
        configured: tuple[CandidateProvider | None, ...] = (
            naver.from_environment(naver_transport),
            licenses.from_environment(license_transport),
        )
        comparator = gemini.from_environment(model_transport)
    except ValueError as exc:
        # 변수 이름만 알린다. 값은 어디에도 출력하지 않는다.
        print(f"configuration: {exc}", file=sys.stderr)
        return 2
    providers = tuple(item for item in configured if item is not None)
    try:
        execute(
            args.command,
            ExecutionContext(target, paths, args.retry_failed, providers, comparator),
            adapters,
        )
    except PipelineFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
