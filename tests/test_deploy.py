"""배포 명령의 판정. Cloudflare·GitHub 대신 가짜 Pages 프로젝트와 응답을 주입한다."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from deliciousmap.ci import main
from deliciousmap.deploy import (
    WRANGLER,
    CheckRun,
    CloudflarePages,
    Deployment,
    GitHubChecks,
    PagesApiFailed,
    Project,
    Response,
    UploadFailed,
    WranglerUploader,
)
from tests.test_ci import COMMIT
from tests.test_geocoding_cli import run_cli
from tests.test_site_build import build_ready

PROJECT = "officialdeliciousmap"
PRODUCTION_ALIAS = f"https://{PROJECT}.pages.dev"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
}


class FakePages:
    """Direct Upload 프로젝트 하나. 배포마다 고유 주소를 주고, 브랜치 alias를 옮긴다.

    없는 경로에는 실제 Pages처럼 루트 index.html을 200으로 돌려준다(SPA 동작).
    alias는 `lag`번 기다린 뒤에야 새 배포를 가리킨다(전파 지연).
    """

    def __init__(self) -> None:
        self.sites: dict[str, dict[str, Response]] = {}
        self.aliases: dict[str, str] = {}
        self.pending: dict[str, tuple[str, int]] = {}
        self.production: Deployment | None = None
        self.uploads: list[tuple[str, str]] = []
        self.rollbacks: list[str] = []
        self.lag = 0
        self.waited = 0
        self.tamper: Callable[[str, bytes], bytes | None] = lambda path, body: body
        self.rollback_works = True

    # Pages API
    def project(self) -> Project:
        return Project(
            production_branch="main", subdomain=f"{PROJECT}.pages.dev", production=self.production
        )

    def rollback(self, deployment_id: str) -> None:
        self.rollbacks.append(deployment_id)
        if self.rollback_works:
            self.aliases[PRODUCTION_ALIAS] = f"https://{deployment_id}.{PROJECT}.pages.dev"

    # Wrangler
    def upload(self, dist: Path, branch: str, commit: str) -> Deployment:
        self.uploads.append((branch, commit))
        number = f"d{len(self.sites) + 1}"
        url = f"https://{number}.{PROJECT}.pages.dev"
        self.sites[url] = {}
        for path in sorted(dist.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(dist).as_posix()
            body = self.tamper(relative, path.read_bytes())
            if body is not None:
                self.sites[url][relative] = Response(200, CONTENT_TYPES[path.suffix], body)
        alias = PRODUCTION_ALIAS if branch == "main" else f"https://{branch}.{PROJECT}.pages.dev"
        self.pending[alias] = (url, self.waited + self.lag)
        deployment = Deployment(
            id=number,
            url=url,
            environment="production" if branch == "main" else "preview",
            alias=alias,
        )
        if branch == "main":
            self.production = deployment
        return deployment

    def sleep(self, seconds: float) -> None:
        self.waited += 1

    # 브라우저가 보는 응답
    def get(self, url: str) -> Response:
        for alias, (target, ready_at) in list(self.pending.items()):
            if self.waited >= ready_at:
                self.aliases[alias] = target
                del self.pending[alias]
        base, _, path = url.removeprefix("https://").partition("/")
        base = f"https://{base}"
        site = self.sites.get(self.aliases.get(base, base))
        if site is None:
            return Response(404, "", b"")
        if path == "" or path.endswith("/"):
            path += "index.html"
        found = site.get(path) or site.get("index.html")
        return found if found is not None else Response(404, "", b"")

    def seed(self, dist: Path) -> Deployment:
        """직전에 검증을 마친 운영 배포를 둔다."""
        deployment = self.upload(dist, "main", "previous")
        self.aliases[PRODUCTION_ALIAS] = deployment.url
        self.pending.clear()
        self.uploads.clear()
        return deployment


@pytest.fixture
def cloud() -> FakePages:
    return FakePages()


def built_site(root: Path, commit: str) -> Path:
    context = build_ready(root)
    assert run_cli(context, "build") == 0
    dist = context.paths.output_root
    city_args = ["--city", "seoul"]
    assert main(["check-dist", "--dist", str(dist), "--commit", commit, *city_args]) == 0
    return dist


@pytest.fixture
def sealed(tmp_path: Path) -> Path:
    return built_site(tmp_path / "new", COMMIT)


def preview(cloud: FakePages, dist: Path, summary: Path) -> int:
    return main(
        [
            "preview",
            "--dist",
            str(dist),
            "--project",
            PROJECT,
            "--branch",
            "pr-7",
            "--summary",
            str(summary),
        ],
        fetcher=cloud,
        uploader=cloud,
        sleep=cloud.sleep,
    )


def test_preview_uploads_to_the_pr_branch_and_records_verified_urls(
    cloud: FakePages, sealed: Path, tmp_path: Path
) -> None:
    summary = tmp_path / "summary.md"

    assert preview(cloud, sealed, summary) == 0

    assert cloud.uploads == [("pr-7", COMMIT)]
    text = summary.read_text(encoding="utf-8")
    assert f"https://d1.{PROJECT}.pages.dev" in text
    assert f"https://pr-7.{PROJECT}.pages.dev" in text
    assert COMMIT in text
    assert "통과" in text
    assert "실패" not in text


def test_preview_fails_when_a_deployed_file_differs_from_the_build(
    cloud: FakePages, sealed: Path, tmp_path: Path
) -> None:
    cloud.tamper = lambda path, body: b"{}" if path == "seoul/markers.json" else body
    summary = tmp_path / "summary.md"

    assert preview(cloud, sealed, summary) == 1

    text = summary.read_text(encoding="utf-8")
    assert "seoul/markers.json: SHA256 mismatch" in text
    assert "실패" in text


def test_preview_rejects_the_spa_page_served_in_place_of_missing_json(
    cloud: FakePages, sealed: Path, tmp_path: Path
) -> None:
    """Pages는 없는 경로에 첫 화면을 200으로 준다. 상태 코드만 보면 통과해 버린다."""
    cloud.tamper = lambda path, body: None if path == "seoul/records.json" else body
    summary = tmp_path / "summary.md"

    assert preview(cloud, sealed, summary) == 1

    text = summary.read_text(encoding="utf-8")
    assert "/seoul/records.json: not JSON (text/html)" in text


def test_alias_is_rechecked_while_it_propagates(
    cloud: FakePages, sealed: Path, tmp_path: Path
) -> None:
    cloud.lag = 2

    assert preview(cloud, sealed, tmp_path / "summary.md") == 0

    assert cloud.waited == 2


def test_alias_that_never_catches_up_fails_after_bounded_retries(
    cloud: FakePages, sealed: Path, tmp_path: Path
) -> None:
    cloud.lag = 1_000
    summary = tmp_path / "summary.md"

    assert preview(cloud, sealed, summary) == 1

    assert cloud.waited == 5
    assert f"alias `https://pr-7.{PROJECT}.pages.dev`: 실패" in summary.read_text(encoding="utf-8")


PREVIOUS = "0" * 40
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def production(
    cloud: FakePages,
    dist: Path,
    tmp_path: Path,
    *,
    event: str = "push",
    ref: str = "refs/heads/main",
    main_head: str = COMMIT,
    freeze_at: str = "",
    reason: str = "",
) -> int:
    return main(
        [
            "production",
            "--dist",
            str(dist),
            "--project",
            PROJECT,
            "--event",
            event,
            "--ref",
            ref,
            "--main-head",
            main_head,
            "--freeze-at",
            freeze_at,
            "--reason",
            reason,
            "--summary",
            str(tmp_path / "summary.md"),
            "--record",
            str(tmp_path / "release.json"),
        ],
        fetcher=cloud,
        uploader=cloud,
        pages=cloud,
        sleep=cloud.sleep,
        clock=lambda: NOW,
    )


def summary_of(tmp_path: Path) -> str:
    return (tmp_path / "summary.md").read_text(encoding="utf-8")


@pytest.fixture
def previous(cloud: FakePages, tmp_path: Path) -> Deployment:
    """직전 main 커밋으로 올려 검증까지 마친 운영 배포."""
    return cloud.seed(built_site(tmp_path / "old", PREVIOUS))


def test_main_push_deploys_to_production_and_verifies_unique_url_and_alias(
    cloud: FakePages, sealed: Path, previous: Deployment, tmp_path: Path
) -> None:
    assert production(cloud, sealed, tmp_path) == 0

    assert cloud.uploads == [("main", COMMIT)]
    assert cloud.rollbacks == []
    text = summary_of(tmp_path)
    assert f"고유 URL `https://d2.{PROJECT}.pages.dev`: 통과" in text
    assert f"운영 alias `{PRODUCTION_ALIAS}`: 통과" in text
    record = json.loads((tmp_path / "release.json").read_text(encoding="utf-8"))
    # 업로드 전에 직전 검증 성공 배포의 ID와 manifest를 보존한다.
    assert record["previous"]["id"] == previous.id
    assert record["previous"]["manifest"]["commit"] == PREVIOUS
    assert record["deployment"]["id"] == "d2"
    assert record["passed"] is True


def corrupt_markers(path: str, body: bytes) -> bytes:
    return b"{}" if path == "seoul/markers.json" else body


def test_failed_verification_rolls_back_to_the_last_verified_deployment_and_still_fails(
    cloud: FakePages, sealed: Path, previous: Deployment, tmp_path: Path
) -> None:
    cloud.tamper = corrupt_markers

    assert production(cloud, sealed, tmp_path) == 1

    assert cloud.rollbacks == [previous.id]
    text = summary_of(tmp_path)
    assert f"롤백 뒤 운영 alias `{PRODUCTION_ALIAS}`: 통과" in text
    assert "seoul/markers.json: SHA256 mismatch" in text
    # 복구가 끝나도 이 실행은 실패다.
    assert text.startswith("## 운영 배포: 실패")
    assert json.loads((tmp_path / "release.json").read_text(encoding="utf-8"))["passed"] is False


def test_a_production_deployment_that_was_never_verified_is_not_a_rollback_target(
    cloud: FakePages, sealed: Path, tmp_path: Path
) -> None:
    """프로젝트를 만들 때 올린 빈 배포처럼 manifest가 없는 배포로는 되돌리지 않는다."""
    placeholder = f"https://d0.{PROJECT}.pages.dev"
    cloud.production = Deployment(id="d0", url=placeholder, environment="production")
    cloud.tamper = corrupt_markers

    assert production(cloud, sealed, tmp_path) == 1

    assert cloud.rollbacks == []
    assert "롤백할 검증 배포가 없다" in summary_of(tmp_path)
    assert json.loads((tmp_path / "release.json").read_text(encoding="utf-8"))["previous"] is None


def test_rollback_that_does_not_restore_the_verified_site_is_reported(
    cloud: FakePages, sealed: Path, previous: Deployment, tmp_path: Path
) -> None:
    cloud.tamper = corrupt_markers
    cloud.rollback_works = False

    assert production(cloud, sealed, tmp_path) == 1

    assert cloud.rollbacks == [previous.id]
    text = summary_of(tmp_path)
    assert f"롤백 뒤 운영 alias `{PRODUCTION_ALIAS}`: 실패" in text
    assert "재검증도 실패" in text


FREEZE = "2026-09-20T18:00:00+09:00"


def test_main_push_after_the_freeze_is_checked_but_not_deployed(
    cloud: FakePages, sealed: Path, previous: Deployment, tmp_path: Path
) -> None:
    assert production(cloud, sealed, tmp_path, freeze_at=FREEZE) == 0

    assert cloud.uploads == []
    assert "동결" in summary_of(tmp_path)


def test_main_push_before_the_freeze_deploys(
    cloud: FakePages, sealed: Path, previous: Deployment, tmp_path: Path
) -> None:
    assert production(cloud, sealed, tmp_path, freeze_at="2026-09-22T00:00:00+09:00") == 0

    assert cloud.uploads == [("main", COMMIT)]


def test_manual_run_with_a_reason_deploys_the_same_way_during_the_freeze(
    cloud: FakePages, sealed: Path, previous: Deployment, tmp_path: Path
) -> None:
    code = production(
        cloud,
        sealed,
        tmp_path,
        event="workflow_dispatch",
        freeze_at=FREEZE,
        reason="지도 링크 장애 긴급 수정",
    )

    assert code == 0
    assert cloud.uploads == [("main", COMMIT)]
    text = summary_of(tmp_path)
    assert "지도 링크 장애 긴급 수정" in text
    assert f"운영 alias `{PRODUCTION_ALIAS}`: 통과" in text


@pytest.mark.parametrize(
    "overrides",
    [
        {"event": "workflow_dispatch", "reason": "  "},
        {"ref": "refs/heads/develop"},
        {"event": "pull_request"},
        {"freeze_at": "2026-09-20T18:00:00"},
        {"freeze_at": "제출 후"},
    ],
    ids=["manual-without-reason", "not-main", "other-event", "freeze-without-offset", "bad-freeze"],
)
def test_runs_that_may_not_deploy_to_production_are_refused(
    cloud: FakePages,
    sealed: Path,
    previous: Deployment,
    tmp_path: Path,
    overrides: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert production(cloud, sealed, tmp_path, **overrides) == 2

    assert cloud.uploads == []
    assert capsys.readouterr().err.startswith("production: ")


def test_a_run_for_an_older_main_commit_skips_the_upload(
    cloud: FakePages, sealed: Path, previous: Deployment, tmp_path: Path
) -> None:
    """대기하던 오래된 SHA가 더 최신의 정상 배포를 덮어쓰지 않는다."""
    assert production(cloud, sealed, tmp_path, main_head="f" * 40) == 0

    assert cloud.uploads == []
    assert "f" * 40 in summary_of(tmp_path)


def test_an_upload_that_creates_no_deployment_fails_without_touching_production(
    cloud: FakePages, sealed: Path, previous: Deployment, tmp_path: Path
) -> None:
    def refuse(dist: Path, branch: str, commit: str) -> Deployment:
        raise UploadFailed("wrangler exited with 1")

    cloud.upload = refuse  # type: ignore[method-assign]

    assert production(cloud, sealed, tmp_path) == 1

    assert cloud.rollbacks == []
    assert "wrangler exited with 1" in summary_of(tmp_path)


@pytest.mark.parametrize("failing", ["project", "rollback"])
def test_pages_api_failures_are_reported_as_failures(
    cloud: FakePages, sealed: Path, previous: Deployment, tmp_path: Path, failing: str
) -> None:
    def unavailable(*args: object) -> None:
        raise PagesApiFailed("pages api request failed")

    setattr(cloud, failing, unavailable)
    cloud.tamper = corrupt_markers

    assert production(cloud, sealed, tmp_path) == 1

    assert "Pages API" in summary_of(tmp_path)


class RecordingTransport:
    """Pages API 응답만 대신한다. 보낸 주소와 헤더를 기록한다."""

    def __init__(self, *bodies: bytes) -> None:
        self.bodies = list(bodies)
        self.requests: list[tuple[str, str, dict[str, str]]] = []

    def fetch(self, url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
        self.requests.append(("GET", url, dict(headers)))
        return self.bodies.pop(0)

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.requests.append(("POST", url, dict(headers)))
        return self.bodies.pop(0)


def api(result: object, success: bool = True) -> bytes:
    return json.dumps({"success": success, "errors": [], "result": result}).encode()


def test_pages_api_reads_the_current_production_deployment_and_rolls_back() -> None:
    transport = RecordingTransport(
        api(
            {
                "name": PROJECT,
                "subdomain": f"{PROJECT}.pages.dev",
                "production_branch": "main",
                "canonical_deployment": {
                    "id": "2bef-uuid",
                    "url": f"https://2bef.{PROJECT}.pages.dev",
                    "environment": "production",
                },
            }
        ),
        api({"id": "2bef-uuid"}),
    )
    pages = CloudflarePages(PROJECT, "합성-계정", "합성-토큰", transport)  # type: ignore[arg-type]

    project = pages.project()
    pages.rollback("2bef-uuid")

    assert project == Project(
        production_branch="main",
        subdomain=f"{PROJECT}.pages.dev",
        production=Deployment(
            id="2bef-uuid", url=f"https://2bef.{PROJECT}.pages.dev", environment="production"
        ),
    )
    base = f"https://api.cloudflare.com/client/v4/accounts/합성-계정/pages/projects/{PROJECT}"
    assert [(method, url) for method, url, _ in transport.requests] == [
        ("GET", base),
        ("POST", f"{base}/deployments/2bef-uuid/rollback"),
    ]
    assert transport.requests[0][2]["Authorization"] == "Bearer 합성-토큰"


def test_pages_api_failure_response_is_an_api_failure() -> None:
    pages = CloudflarePages(PROJECT, "a", "t", RecordingTransport(api(None, success=False)))  # type: ignore[arg-type]

    with pytest.raises(PagesApiFailed):
        pages.project()


def test_production_without_cloudflare_configuration_names_only_the_variable(
    sealed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "production",
            "--dist",
            str(sealed),
            "--project",
            PROJECT,
            "--event",
            "push",
            "--ref",
            "refs/heads/main",
            "--main-head",
            COMMIT,
        ],
        clock=lambda: NOW,
    )

    assert code == 2
    assert capsys.readouterr().err == "configuration: CLOUDFLARE_ACCOUNT_ID\n"


class FakeChecks:
    """같은 커밋의 체크 상태를 차례로 돌려준다. 마지막 상태는 계속 유지된다."""

    def __init__(self, *states: CheckRun | None) -> None:
        self.states = list(states)
        self.asked: list[tuple[str, str]] = []

    def latest(self, sha: str, name: str) -> CheckRun | None:
        self.asked.append((sha, name))
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


def wait_check(checks: FakeChecks, sleeps: list[float]) -> int:
    return main(
        ["wait-check", "--repo", "owner/repo", "--sha", COMMIT, "--name", "gitleaks"],
        checks=checks,
        sleep=sleeps.append,
    )


def test_wait_check_waits_until_the_same_commit_check_succeeds() -> None:
    checks = FakeChecks(None, CheckRun("in_progress", None), CheckRun("completed", "success"))
    sleeps: list[float] = []

    assert wait_check(checks, sleeps) == 0

    assert len(sleeps) == 2
    assert set(checks.asked) == {(COMMIT, "gitleaks")}


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", None])
def test_wait_check_does_not_treat_an_unsuccessful_check_as_passing(
    conclusion: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert wait_check(FakeChecks(CheckRun("completed", conclusion)), []) == 1

    assert "gitleaks" in capsys.readouterr().err


def test_github_checks_takes_the_most_recent_run_of_that_name() -> None:
    """다시 실행한 체크가 앞선 실패를 대신한다."""
    body = {
        "total_count": 2,
        "check_runs": [
            {"id": 7, "name": "gitleaks", "status": "completed", "conclusion": "failure"},
            {"id": 9, "name": "gitleaks", "status": "completed", "conclusion": "success"},
        ],
    }
    transport = RecordingTransport(json.dumps(body).encode())
    checks = GitHubChecks("owner/repo", "합성-토큰", transport)  # type: ignore[arg-type]

    assert checks.latest(COMMIT, "gitleaks") == CheckRun("completed", "success")
    method, url, headers = transport.requests[0]
    assert url == f"https://api.github.com/repos/owner/repo/commits/{COMMIT}/check-runs"
    assert headers["Authorization"] == "Bearer 합성-토큰"


def test_wait_check_gives_up_on_a_check_that_never_finishes() -> None:
    sleeps: list[float] = []

    assert wait_check(FakeChecks(CheckRun("queued", None)), sleeps) == 1

    assert 0 < len(sleeps) < 100


def wrangler(
    returncode: int, *entries: dict[str, object]
) -> Callable[..., CompletedProcess[bytes]]:
    """Wrangler 대신 출력 파일만 쓰는 프로세스. 받은 인자와 환경을 기록한다."""
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(args: list[str], *, env: dict[str, str], check: bool) -> CompletedProcess[bytes]:
        calls.append((args, env))
        lines = "".join(json.dumps(entry) + "\n" for entry in entries)
        Path(env["WRANGLER_OUTPUT_FILE_PATH"]).write_text(lines, encoding="utf-8")
        return CompletedProcess(args, returncode)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_wrangler_upload_reads_the_deployment_from_its_output_file(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "합성-토큰")
    run = wrangler(
        0,
        {"type": "wrangler-session", "version": 1},
        {
            "type": "pages-deploy-detailed",
            "version": 1,
            "pages_project": PROJECT,
            "deployment_id": "abc-123",
            "url": f"https://abc.{PROJECT}.pages.dev",
            "alias": f"https://pr-7.{PROJECT}.pages.dev",
            "environment": "preview",
        },
    )

    deployment = WranglerUploader(PROJECT, run=run).upload(sealed, "pr-7", COMMIT)

    assert deployment == Deployment(
        id="abc-123",
        url=f"https://abc.{PROJECT}.pages.dev",
        environment="preview",
        alias=f"https://pr-7.{PROJECT}.pages.dev",
    )
    args, env = run.calls[0]  # type: ignore[attr-defined]
    assert args[1:] == [
        "--yes",
        WRANGLER,
        "pages",
        "deploy",
        str(sealed),
        "--project-name",
        PROJECT,
        "--branch",
        "pr-7",
        "--commit-hash",
        COMMIT,
    ]
    # 토큰은 인자가 아니라 환경으로만 넘긴다.
    assert env["CLOUDFLARE_API_TOKEN"] == "합성-토큰"
    assert "합성-토큰" not in " ".join(args)


@pytest.mark.parametrize(
    "run",
    [wrangler(1), wrangler(0, {"type": "pages-deploy", "deployment_id": "x", "url": "u"})],
)
def test_wrangler_upload_without_a_detailed_deployment_is_an_upload_failure(
    sealed: Path, run: Callable[..., CompletedProcess[bytes]]
) -> None:
    with pytest.raises(UploadFailed):
        WranglerUploader(PROJECT, run=run).upload(sealed, "pr-7", COMMIT)
