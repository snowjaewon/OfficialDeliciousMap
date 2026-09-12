"""CI workflow가 부르는 판정 명령의 인자·출력·종료 코드 변환. 판정은 publish·deploy가 맡는다.

`python -m deliciousmap.ci <명령>`으로 부른다. 파이프라인 CLI(`python -m deliciousmap`)와 따로 둔다.
종료 코드는 0 통과·건너뜀, 1 검사·배포 실패, 2 요청·설정 거부다.
"""

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from deliciousmap import cloudflare, deploy, github, publish
from deliciousmap.registry import CITIES, City


def main(
    argv: Sequence[str] | None = None,
    *,
    cities: tuple[City, ...] = CITIES,
    fetcher: deploy.Fetcher | None = None,
    uploader: deploy.Uploader | None = None,
    pages: deploy.Pages | None = None,
    checks: deploy.Checks | None = None,
    latest_main: Callable[[], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check-data":
        return _check_data(args.data_root, cities)
    if args.command == "check-dist":
        return _check_dist(args.dist, args.commit, tuple(args.city))
    if args.command == "wait-check":
        return _wait_check(args, checks, sleep)
    verifier = deploy.Verifier(fetcher or cloudflare.HttpFetcher(), cities, sleep)
    site_uploader = uploader or cloudflare.WranglerUploader(args.project)
    if args.command == "preview":
        report = deploy.release_preview(args.dist, args.branch, site_uploader, verifier)
        if args.head:
            report.facts.append(("PR head", f"`{args.head}`"))
        return _finish(report, args.summary)
    try:
        request = deploy.Request(
            event=args.event,
            ref=args.ref,
            reason=args.reason,
            freeze_at=deploy.parse_freeze(args.freeze_at),
            now=clock(),
        )
        # 자격 없는 실행은 Pages 설정을 읽기 전에 거부한다.
        deploy.validate_request(request)
        project_api = pages or cloudflare.CloudflarePages.from_environment(args.project)
    except deploy.Refused as exc:
        print(f"production: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        # 빠진 변수 이름만 알린다. 값은 어디에도 출력하지 않는다.
        print(f"configuration: {exc}", file=sys.stderr)
        return 2

    def keep(report: deploy.Report) -> None:
        if args.record is not None:
            args.record.write_text(report.to_record(), encoding="utf-8")

    report = deploy.release_production(
        args.dist,
        request,
        project_api,
        site_uploader,
        verifier,
        latest_main or _remote_main,
        keep,
    )
    keep(report)
    return _finish(report, args.summary)


def _remote_main() -> str:
    """업로드 직전의 원격 main. 대기하던 오래된 커밋이 더 최신 배포를 덮지 않게 한다."""
    listed = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return listed.split()[0] if listed.strip() else ""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deliciousmap.ci")
    commands = parser.add_subparsers(dest="command", required=True)
    check_data = commands.add_parser("check-data", help="Check refined artifacts before build")
    check_data.add_argument("--data-root", type=Path, default=Path("data"))
    check_dist = commands.add_parser("check-dist", help="Check dist/ and write its manifest")
    check_dist.add_argument("--dist", type=Path, default=Path("dist"))
    check_dist.add_argument("--commit", required=True, help="Commit SHA the site was built from")
    check_dist.add_argument(
        "--city", action="append", default=[], help="City slug that was built (repeatable)"
    )
    wait = commands.add_parser("wait-check", help="Wait for another check on the same commit")
    wait.add_argument("--repo", required=True, help="owner/name")
    wait.add_argument("--sha", required=True)
    wait.add_argument("--name", required=True, help="Check run name, e.g. gitleaks")
    preview = commands.add_parser("preview", help="Upload a PR preview and verify it")
    _deploy_arguments(preview)
    preview.add_argument("--branch", required=True, help="Preview branch, e.g. pr-12")
    preview.add_argument("--head", default="", help="PR head SHA; the build is its merge commit")
    release = commands.add_parser("production", help="Deploy main to production and verify it")
    _deploy_arguments(release)
    release.add_argument("--event", required=True, help="GitHub event: push or workflow_dispatch")
    release.add_argument("--ref", required=True, help="Git ref of the run, e.g. refs/heads/main")
    release.add_argument(
        "--freeze-at",
        default="",
        help="Submission freeze start (ISO 8601 with offset); empty: none",
    )
    release.add_argument("--reason", default="", help="Reason for a manual emergency deploy")
    release.add_argument("--record", type=Path, help="Write the release record JSON here")
    return parser


def _deploy_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--dist", type=Path, default=Path("dist"))
    command.add_argument("--project", required=True, help="Cloudflare Pages project name")
    command.add_argument(
        "--summary",
        type=Path,
        default=os.environ.get("GITHUB_STEP_SUMMARY"),
        help="Markdown summary to append to (default: $GITHUB_STEP_SUMMARY)",
    )


def _finish(report: deploy.Report, summary: Path | None) -> int:
    text = report.markdown()
    print(text)
    if summary is not None:
        with summary.open("a", encoding="utf-8") as stream:
            stream.write(text)
    return 0 if report.passed else 1


def _check_data(data_root: Path, cities: tuple[City, ...]) -> int:
    """문제가 없으면 build할 도시 slug를 한 줄에 하나씩 낸다. workflow가 그대로 받는다."""
    problems = [
        *(f"refined artifact over 20MB: {item}" for item in publish.oversized_refined(data_root)),
        *(
            f"not a registered city directory: {name}"
            for name in publish.unknown_directories(data_root, cities)
        ),
    ]
    buildable = publish.buildable_cities(data_root, cities)
    if not buildable:
        problems.append("no city has committed refined artifacts to build")
    for problem in problems:
        print(f"check-data: {problem}", file=sys.stderr)
    if problems:
        return 1
    for city in buildable:
        print(city.slug)
    return 0


def _check_dist(dist: Path, commit: str, city_slugs: tuple[str, ...]) -> int:
    problems = publish.dist_problems(dist, city_slugs)
    for problem in problems:
        print(f"check-dist: {problem}", file=sys.stderr)
    if problems:
        return 1
    manifest = publish.seal(dist, commit)
    print(f"check-dist: sealed {len(manifest.files)} files for {commit}")
    return 0


def _wait_check(
    args: argparse.Namespace, checks: deploy.Checks | None, sleep: Callable[[float], None]
) -> int:
    try:
        source = checks or github.GitHubChecks.from_environment(args.repo)
    except ValueError as exc:
        print(f"configuration: {exc}", file=sys.stderr)
        return 2
    run = deploy.wait_for_check(source, args.sha, args.name, sleep)
    if run is not None and run.succeeded:
        print(f"wait-check: {args.name} succeeded on {args.sha}")
        return 0
    state = "not found or unavailable" if run is None else f"{run.status}/{run.conclusion}"
    print(f"wait-check: {args.name} on {args.sha} is {state}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
