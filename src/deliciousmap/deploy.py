"""배포와 배포 뒤 검증. 업로드·Pages API·HTTP는 주입받고 여기서는 판정만 한다.

절차와 근거는 #15 결정의 "배포 검증과 복구"를 따른다.
"""

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from deliciousmap.publish import MANIFEST_NAME, PAGES_FILE_LIMIT, Manifest, read_manifest
from deliciousmap.registry import City
from deliciousmap.transport import HttpTransport, ResourceGone

# 배포 도구의 고정 버전. 올릴 때는 출력 파일 형식(pages-deploy-detailed)을 다시 확인한다.
WRANGLER = "wrangler@4.131.1"
CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
# 배포 job에만 넘기는 비밀값. 빌드 job과 artifact에는 가지 않는다.
TOKEN_VARIABLE = "CLOUDFLARE_API_TOKEN"
ACCOUNT_VARIABLE = "CLOUDFLARE_ACCOUNT_ID"
GITHUB_TOKEN_VARIABLE = "GITHUB_TOKEN"

# 전파 지연을 기다리는 유한한 재시도. 계속 어긋나면 실패로 남긴다.
VERIFY_ATTEMPTS = 6
VERIFY_DELAY = 10.0
# 요약에 싣는 문제의 수. 나머지는 개수만 적는다.
SUMMARY_PROBLEMS = 20
JAVASCRIPT_TYPES = frozenset({"application/javascript", "text/javascript"})


@dataclass(frozen=True)
class Response:
    """압축을 푼 본문. status 0은 서버에 닿지 못한 것이다."""

    status: int
    content_type: str
    body: bytes

    @property
    def media_type(self) -> str:
        return self.content_type.split(";")[0].strip().lower()

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


class Fetcher(Protocol):
    def get(self, url: str) -> Response: ...


@dataclass(frozen=True)
class Deployment:
    """Pages 배포 하나. `url`은 그 배포만의 고유 주소, `alias`는 브랜치 주소다."""

    id: str
    url: str
    environment: str
    alias: str | None = None


class Uploader(Protocol):
    def upload(self, dist: Path, branch: str, commit: str) -> Deployment: ...


@dataclass(frozen=True)
class Project:
    """Pages 프로젝트. `production`은 지금 운영 alias가 가리키는 배포다."""

    production_branch: str
    subdomain: str
    production: Deployment | None


class Pages(Protocol):
    def project(self) -> Project: ...

    def rollback(self, deployment_id: str) -> None: ...


@dataclass(frozen=True)
class Verification:
    url: str
    problems: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.problems


class UploadFailed(Exception):
    """업로드가 배포를 만들지 못했다. 운영 alias는 바뀌지 않은 것으로 본다."""


class HttpFetcher:
    """배포 주소를 브라우저처럼 받는다. 정규 URL 리다이렉트를 따르고 gzip 본문을 푼다."""

    def __init__(self, timeout: float = 30.0, limit: int = PAGES_FILE_LIMIT) -> None:
        self.timeout = timeout
        self.limit = limit

    def get(self, url: str) -> Response:
        request = urllib.request.Request(
            url,
            headers={
                "Accept-Encoding": "gzip",
                "Cache-Control": "no-cache",
                "User-Agent": "deliciousmap-deploy-check",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status, headers = response.status, response.headers
                body = bytes(response.read(self.limit + 1))
        except urllib.error.HTTPError as error:
            return Response(error.code, error.headers.get("Content-Type", ""), b"")
        if len(body) > self.limit:
            raise ValueError("response exceeds the deployment file limit")
        encoding = (headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip":
            body = gzip.decompress(body)
        elif encoding not in {"", "identity"}:
            raise ValueError("unsupported content encoding")
        return Response(status, headers.get("Content-Type", ""), body)


class WranglerUploader:
    """Wrangler Direct Upload. 배포 ID·주소는 Wrangler가 남기는 출력 파일에서 읽는다.

    Cloudflare 토큰·계정은 실행 환경의 CLOUDFLARE_API_TOKEN·CLOUDFLARE_ACCOUNT_ID로만 넘긴다.
    """

    def __init__(
        self,
        project: str,
        run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    ) -> None:
        self.project = project
        self.run = run

    def upload(self, dist: Path, branch: str, commit: str) -> Deployment:
        npx = shutil.which("npx") or "npx"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "wrangler-output.jsonl"
            completed = self.run(
                [
                    npx,
                    "--yes",
                    WRANGLER,
                    "pages",
                    "deploy",
                    str(dist),
                    "--project-name",
                    self.project,
                    "--branch",
                    branch,
                    "--commit-hash",
                    commit,
                ],
                env={**os.environ, "WRANGLER_OUTPUT_FILE_PATH": str(output)},
                check=False,
            )
            if completed.returncode != 0:
                raise UploadFailed(f"wrangler exited with {completed.returncode}")
            if not output.exists():
                raise UploadFailed("wrangler reported no deployment")
            return deployment_from_output(output.read_text(encoding="utf-8"))


class PagesApiFailed(Exception):
    """Pages API가 답하지 않았거나 실패를 알렸다. 응답 원문·계정 값은 담지 않는다."""


class CloudflarePages:
    """Pages API 중 운영 배포 조회와 롤백만 쓴다."""

    def __init__(
        self, project: str, account_id: str, token: str, transport: HttpTransport | None = None
    ) -> None:
        self.url = f"{CLOUDFLARE_API}/accounts/{account_id}/pages/projects/{project}"
        self.token = token
        self.transport = transport or HttpTransport(timeout=30.0)

    @classmethod
    def from_environment(
        cls, project: str, environ: Mapping[str, str] | None = None
    ) -> "CloudflarePages":
        """값은 어디에도 출력하지 않고 빠진 변수 이름만 알린다."""
        values = os.environ if environ is None else environ
        for name in (ACCOUNT_VARIABLE, TOKEN_VARIABLE):
            if not values.get(name, "").strip():
                raise ValueError(name)
        return cls(project, values[ACCOUNT_VARIABLE].strip(), values[TOKEN_VARIABLE].strip())

    def project(self) -> Project:
        result = self._call(lambda: self.transport.fetch(self.url, {}, self._headers()))
        canonical = result.get("canonical_deployment")
        return Project(
            production_branch=str(result["production_branch"]),
            subdomain=str(result["subdomain"]),
            production=(
                Deployment(
                    id=str(canonical["id"]),
                    url=str(canonical["url"]),
                    environment=str(canonical["environment"]),
                )
                if isinstance(canonical, dict)
                else None
            ),
        )

    def rollback(self, deployment_id: str) -> None:
        url = f"{self.url}/deployments/{deployment_id}/rollback"
        self._call(lambda: self.transport.post(url, b"", self._headers()))

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "User-Agent": "deliciousmap-deploy"}

    def _call(self, send: Callable[[], bytes]) -> dict[str, Any]:
        try:
            payload = json.loads(send())
        except (OSError, ValueError, ResourceGone) as exc:
            raise PagesApiFailed("pages api request failed") from exc
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise PagesApiFailed("pages api reported failure")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise PagesApiFailed("pages api returned no result")
        return result


def deployment_from_output(text: str) -> Deployment:
    """Wrangler 출력 파일(ND-JSON)의 마지막 `pages-deploy-detailed` 항목."""
    entries = [json.loads(line) for line in text.splitlines() if line.strip()]
    detailed = [item for item in entries if item.get("type") == "pages-deploy-detailed"]
    if not detailed:
        raise UploadFailed("wrangler reported no deployment")
    last = detailed[-1]
    return Deployment(
        id=str(last["deployment_id"]),
        url=str(last["url"]),
        environment=str(last["environment"]),
        alias=str(last["alias"]) if last.get("alias") else None,
    )


def verify_site(
    fetcher: Fetcher, base_url: str, manifest: Manifest, cities: tuple[City, ...]
) -> Verification:
    """배포된 파일을 내려받아 manifest와 대조하고 주요 경로의 유형·구조를 본다."""
    problems: list[str] = []
    served = _get(fetcher, base_url, MANIFEST_NAME)
    if _served_manifest(served) != manifest:
        problems.append(f"{MANIFEST_NAME}: does not match the build ({_status(served)})")
    for item in manifest.files:
        response = _get(fetcher, base_url, item.path)
        if response.status != 200:
            problems.append(f"{item.path}: {_status(response)}")
        elif hashlib.sha256(response.body).hexdigest() != item.sha256:
            problems.append(f"{item.path}: SHA256 mismatch")
    problems += _key_path_problems(fetcher, base_url, manifest, cities)
    return Verification(base_url, tuple(problems))


def verify_until(
    fetcher: Fetcher,
    base_url: str,
    manifest: Manifest,
    cities: tuple[City, ...],
    sleep: Callable[[float], None],
) -> Verification:
    """전파가 늦을 수 있어 몇 번 다시 본다. 마지막 결과를 그대로 돌려준다."""
    for attempt in range(1, VERIFY_ATTEMPTS + 1):
        result = verify_site(fetcher, base_url, manifest, cities)
        if result.passed or attempt == VERIFY_ATTEMPTS:
            return result
        sleep(VERIFY_DELAY)
    raise AssertionError("unreachable")


def _get(fetcher: Fetcher, base_url: str, path: str) -> Response:
    try:
        return fetcher.get(f"{base_url.rstrip('/')}/{path}")
    except (OSError, ValueError):
        # 연결 실패·해석할 수 없는 응답. 예외 원문은 남기지 않는다.
        return Response(0, "", b"")


def _status(response: Response) -> str:
    return "unreachable" if response.status == 0 else f"HTTP {response.status}"


def _served_manifest(response: Response) -> Manifest | None:
    if response.status != 200:
        return None
    try:
        return Manifest.from_json(response.text)
    except ValueError:
        return None


def _key_path_problems(
    fetcher: Fetcher, base_url: str, manifest: Manifest, cities: tuple[City, ...]
) -> list[str]:
    """첫 화면·7개 도시 진입과 데이터 파일. 없는 JSON 대신 SPA HTML이 오는 것도 잡는다."""
    paths = {item.path for item in manifest.files}
    built = {city.slug for city in cities if f"{city.slug}/index.html" in paths}
    problems: list[str] = []
    landing = _get(fetcher, base_url, "")
    if landing.media_type != "text/html" or 'class="landing-page"' not in landing.text:
        problems.append(f"/: not the city landing ({_status(landing)}, {landing.media_type})")
    for city in cities:
        linked = f'href="./{city.slug}/"' in landing.text
        if linked != (city.slug in built):
            problems.append(f"/: link to {city.slug} does not match the build")
        page = _get(fetcher, base_url, f"{city.slug}/")
        is_city_page = page.media_type == "text/html" and f'data-city="{city.slug}"' in page.text
        if is_city_page != (city.slug in built):
            problems.append(f"/{city.slug}/: city page does not match the build")
        if city.slug in built:
            problems += _data_problems(fetcher, base_url, city.slug)
    for script in ("assets/app.js", "sw.js"):
        response = _get(fetcher, base_url, script)
        if response.media_type not in JAVASCRIPT_TYPES:
            problems.append(
                f"/{script}: not JavaScript ({response.media_type or _status(response)})"
            )
    return problems


def _data_problems(fetcher: Fetcher, base_url: str, slug: str) -> list[str]:
    problems = []
    for name, key in (("markers.json", "markers"), ("records.json", "records")):
        response = _get(fetcher, base_url, f"{slug}/{name}")
        if response.media_type != "application/json":
            problems.append(
                f"/{slug}/{name}: not JSON ({response.media_type or _status(response)})"
            )
            continue
        try:
            payload = json.loads(response.body)
        except ValueError:
            payload = None
        if not (
            isinstance(payload, dict)
            and payload.get("city") == slug
            and isinstance(payload.get(key), list)
        ):
            problems.append(f"/{slug}/{name}: unexpected structure")
    return problems


@dataclass
class Report:
    """Actions summary에 남기는 한 번의 배포 기록."""

    title: str
    commit: str
    passed: bool = False
    outcome: str = ""
    facts: list[tuple[str, str]] = field(default_factory=list)
    checks: list[tuple[str, Verification]] = field(default_factory=list)
    # 운영 배포가 Actions artifact로 남기는 기록(직전 검증 배포·새 배포·검증 결과).
    record: dict[str, object] = field(default_factory=dict)

    def to_record(self) -> str:
        payload = {
            **self.record,
            "commit": self.commit,
            "passed": self.passed,
            "outcome": self.outcome,
            "checks": [
                {"label": label, "url": result.url, "problems": list(result.problems)}
                for label, result in self.checks
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n"

    def markdown(self) -> str:
        verdict = "통과" if self.passed else "실패"
        lines = [
            f"## {self.title}: {verdict}",
            "",
            self.outcome,
            "",
            "| 항목 | 값 |",
            "| --- | --- |",
            f"| commit | `{self.commit}` |",
            *(f"| {name} | {value} |" for name, value in self.facts),
            "",
        ]
        for label, result in self.checks:
            if result.passed:
                lines.append(f"- {label} `{result.url}`: 통과(파일 SHA256·주요 경로)")
                continue
            lines.append(f"- {label} `{result.url}`: 실패 {len(result.problems)}건")
            lines += [f"  - `{problem}`" for problem in result.problems[:SUMMARY_PROBLEMS]]
            if len(result.problems) > SUMMARY_PROBLEMS:
                lines.append(f"  - 외 {len(result.problems) - SUMMARY_PROBLEMS}건")
        return "\n".join(lines) + "\n"


def release_preview(
    dist: Path,
    branch: str,
    uploader: Uploader,
    fetcher: Fetcher,
    cities: tuple[City, ...],
    sleep: Callable[[float], None],
) -> Report:
    """PR 미리보기. 롤백 대상이 아니므로 올리고 검증만 한다."""
    manifest = read_manifest(dist)
    report = Report(title="미리보기 배포", commit=manifest.commit)
    report.facts.append(("branch", f"`{branch}`"))
    try:
        deployment = uploader.upload(dist, branch, manifest.commit)
    except UploadFailed as exc:
        report.outcome = f"업로드가 배포를 만들지 못했다: {exc}"
        return report
    report.facts.append(("배포 ID", f"`{deployment.id}`"))
    report.checks.append(
        ("고유 URL", verify_until(fetcher, deployment.url, manifest, cities, sleep))
    )
    if deployment.alias is None:
        report.checks.append(("alias", Verification(branch, ("no alias for the branch",))))
    else:
        report.checks.append(
            ("alias", verify_until(fetcher, deployment.alias, manifest, cities, sleep))
        )
    report.passed = all(result.passed for _, result in report.checks)
    report.outcome = "미리보기를 올리고 검증했다." if report.passed else "미리보기 검증이 어긋났다."
    return report


MAIN_REF = "refs/heads/main"
# 같은 커밋의 다른 workflow 체크를 기다리는 한도(약 15분).
CHECK_ATTEMPTS = 60
CHECK_DELAY = 15.0


@dataclass(frozen=True)
class CheckRun:
    status: str
    conclusion: str | None


class Checks(Protocol):
    def latest(self, sha: str, name: str) -> CheckRun | None: ...


class GitHubChecks:
    """커밋의 체크 실행 중 이름이 같은 가장 최근 것. 다시 실행한 결과가 앞선 결과를 대신한다."""

    def __init__(self, repository: str, token: str, transport: HttpTransport | None = None) -> None:
        self.url = f"https://api.github.com/repos/{repository}/commits"
        self.token = token
        self.transport = transport or HttpTransport(timeout=30.0)

    @classmethod
    def from_environment(
        cls, repository: str, environ: Mapping[str, str] | None = None
    ) -> "GitHubChecks":
        values = os.environ if environ is None else environ
        if not values.get(GITHUB_TOKEN_VARIABLE, "").strip():
            raise ValueError(GITHUB_TOKEN_VARIABLE)
        return cls(repository, values[GITHUB_TOKEN_VARIABLE].strip())

    def latest(self, sha: str, name: str) -> CheckRun | None:
        body = self.transport.fetch(
            f"{self.url}/{sha}/check-runs",
            {"check_name": name, "filter": "latest", "per_page": "100"},
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "deliciousmap-deploy",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        runs = json.loads(body)["check_runs"]
        if not runs:
            return None
        run = max(runs, key=lambda item: int(item["id"]))
        return CheckRun(status=str(run["status"]), conclusion=run.get("conclusion"))


def wait_for_check(
    checks: Checks, sha: str, name: str, sleep: Callable[[float], None]
) -> CheckRun | None:
    """체크가 끝날 때까지 기다린 마지막 상태. 끝나지 않았으면 끝나지 않은 상태를 돌려준다."""
    run: CheckRun | None = None
    for attempt in range(1, CHECK_ATTEMPTS + 1):
        run = checks.latest(sha, name)
        if (run is not None and run.status == "completed") or attempt == CHECK_ATTEMPTS:
            return run
        sleep(CHECK_DELAY)
    return run


class Refused(ValueError):
    """운영 배포를 요청할 수 없는 실행. 검사하지 않은 브랜치나 사유 없는 수동 실행이다."""


@dataclass(frozen=True)
class Request:
    """운영 배포를 부른 실행. `main_head`는 업로드 직전에 확인한 최신 main이다."""

    event: str
    ref: str
    reason: str
    freeze_at: datetime | None
    now: datetime
    main_head: str


def parse_freeze(value: str) -> datetime | None:
    """제출 동결 시작 시각. 비어 있으면 동결 전이다. 시간대가 없는 값은 받지 않는다."""
    if not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        raise Refused("freeze time must be ISO 8601, e.g. 2026-09-20T18:00:00+09:00") from None
    if moment.tzinfo is None:
        raise Refused("freeze time needs an explicit offset such as +09:00")
    return moment


def hold_reason(request: Request) -> str | None:
    """운영에 올리지 않고 넘어갈 이유. None이면 올린다. 자격 없는 실행은 Refused다.

    동결은 main 잠금이 아니라 자동 배포 제한이다. 사유를 적은 수동 실행만 동결 중에도 올린다.
    """
    if request.ref != MAIN_REF:
        raise Refused(f"production deploys only from {MAIN_REF}")
    if request.event == "workflow_dispatch":
        if not request.reason.strip():
            raise Refused("a manual production deploy needs a reason")
        return None
    if request.event != "push":
        raise Refused(f"event {request.event} does not deploy to production")
    if request.freeze_at is not None and request.now >= request.freeze_at:
        return f"제출 동결 중이다(시작 {request.freeze_at.isoformat()}). main push는 검사만 한다."
    return None


def release_production(
    dist: Path,
    request: Request,
    pages: Pages,
    uploader: Uploader,
    fetcher: Fetcher,
    cities: tuple[City, ...],
    sleep: Callable[[float], None],
) -> Report:
    """직전 검증 배포 보존 → 업로드 → 고유 URL·운영 alias 검증 → 실패하면 롤백·재검증."""
    manifest = read_manifest(dist)
    report = Report(title="운영 배포", commit=manifest.commit)
    report.record |= {"event": request.event, "reason": request.reason}
    report.facts.append(("실행", f"`{request.event}`"))
    if request.reason.strip():
        report.facts.append(("긴급 배포 사유", request.reason.strip()))
    held = hold_reason(request)
    if held is not None:
        report.passed = True
        report.outcome = f"운영 배포를 건너뛰었다: {held}"
        return report
    if request.main_head != manifest.commit:
        report.passed = True
        report.outcome = (
            f"운영 배포를 건너뛰었다: main이 `{request.main_head}`로 앞서 있다."
            " 더 최신 커밋의 실행이 배포한다."
        )
        return report
    try:
        project = pages.project()
    except PagesApiFailed:
        report.outcome = "Pages API에서 운영 배포를 조회하지 못해 올리지 않았다."
        return report
    previous = _verified_previous(project.production, fetcher, cities)
    report.record["previous"] = (
        None
        if previous is None
        else {
            "id": previous[0].id,
            "url": previous[0].url,
            "manifest": json.loads(previous[1].to_json()),
        }
    )
    try:
        deployment = uploader.upload(dist, project.production_branch, manifest.commit)
    except UploadFailed as exc:
        report.outcome = f"업로드가 배포를 만들지 못했다: {exc}"
        return report
    report.record["deployment"] = {"id": deployment.id, "url": deployment.url}
    report.facts.append(("배포 ID", f"`{deployment.id}`"))
    if deployment.environment != "production":
        report.outcome = f"배포가 운영이 아닌 `{deployment.environment}` 환경으로 올라갔다."
        return report
    alias = f"https://{project.subdomain}"
    unique = verify_until(fetcher, deployment.url, manifest, cities, sleep)
    report.checks.append(("고유 URL", unique))
    # 고유 URL이 어긋나면 운영 alias도 같은 배포를 가리키므로 기다리지 않고 복구로 간다.
    if unique.passed:
        report.checks.append(("운영 alias", verify_until(fetcher, alias, manifest, cities, sleep)))
    if all(result.passed for _, result in report.checks):
        report.passed = True
        report.outcome = "운영에 배포하고 검증했다."
        return report
    if previous is None:
        report.outcome = "배포 뒤 검증이 실패했고 롤백할 검증 배포가 없다. 사람이 대응해야 한다."
        return report
    target, target_manifest = previous
    try:
        pages.rollback(target.id)
    except PagesApiFailed:
        report.outcome = (
            f"배포 뒤 검증이 실패했고 Pages API로 `{target.id}` 롤백을 요청하지 못했다."
            " 사람이 대응해야 한다."
        )
        return report
    restored = verify_until(fetcher, alias, target_manifest, cities, sleep)
    report.checks.append(("롤백 뒤 운영 alias", restored))
    report.record["rollback"] = {"id": target.id, "restored": restored.passed}
    report.outcome = (
        f"배포 뒤 검증이 실패해 직전 검증 배포 `{target.id}`로 롤백하고 재검증했다."
        " 이 실행은 실패로 남긴다."
        if restored.passed
        else f"배포 뒤 검증이 실패해 `{target.id}`로 롤백했지만 재검증도 실패했다."
        " 사람이 대응해야 한다."
    )
    return report


def _verified_previous(
    production: Deployment | None, fetcher: Fetcher, cities: tuple[City, ...]
) -> tuple[Deployment, Manifest] | None:
    """롤백해도 되는 운영 배포. 자기 manifest와 다시 대조해 통과한 것만 인정한다."""
    if production is None:
        return None
    served = _served_manifest(_get(fetcher, production.url, MANIFEST_NAME))
    if served is None or not verify_site(fetcher, production.url, served, cities).passed:
        return None
    return production, served
