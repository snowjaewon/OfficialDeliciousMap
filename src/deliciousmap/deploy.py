"""배포와 배포 뒤 검증의 판정. 업로드·Pages API·HTTP·GitHub 체크는 주입받는다.

실제 어댑터는 `cloudflare`(Pages)·`github`(체크 조회)에 있다. 절차와 근거는 #15 결정의
"배포 검증과 복구"를 따른다.
"""

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from deliciousmap.publish import MANIFEST_NAME, Manifest, read_manifest
from deliciousmap.registry import City

# 전파 지연을 기다리는 유한한 재시도. 계속 어긋나면 실패로 남긴다.
VERIFY_ATTEMPTS = 6
VERIFY_DELAY = 10.0
# 같은 커밋의 다른 workflow 체크를 기다리는 한도(약 15분).
CHECK_ATTEMPTS = 60
CHECK_DELAY = 15.0
# 요약에 싣는 문제의 수. 나머지는 개수만 적는다.
SUMMARY_PROBLEMS = 20
JAVASCRIPT_TYPES = frozenset({"application/javascript", "text/javascript"})
MAIN_REF = "refs/heads/main"


@dataclass(frozen=True)
class Response:
    """압축을 푼 본문. status 0은 응답을 받지 못한 것이고 `failure`가 그 사유다."""

    status: int
    content_type: str
    body: bytes
    failure: str = ""

    @property
    def media_type(self) -> str:
        return self.content_type.split(";")[0].strip().lower()

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def describe(self) -> str:
        return self.failure or f"HTTP {self.status}"


class Fetcher(Protocol):
    def get(self, url: str) -> Response: ...


@dataclass(frozen=True)
class Deployment:
    """Pages 배포 하나. `url`은 그 배포만의 고유 주소, `alias`는 브랜치 주소다."""

    id: str
    url: str
    environment: str
    alias: str | None = None


class UploadFailed(Exception):
    """업로드가 배포를 확인해 주지 못했다. 배포가 만들어졌는지는 알 수 없다."""


class Uploader(Protocol):
    def upload(self, dist: Path, branch: str, commit: str) -> Deployment: ...


@dataclass(frozen=True)
class Project:
    """Pages 프로젝트. `production`은 지금 운영 alias가 가리키는 배포다."""

    production_branch: str
    subdomain: str
    production: Deployment | None


class PagesApiFailed(Exception):
    """Pages API가 답하지 않았거나 실패를 알렸다. 응답 원문·계정 값은 담지 않는다."""


class Pages(Protocol):
    def project(self) -> Project: ...

    def rollback(self, deployment_id: str) -> None: ...


@dataclass(frozen=True)
class CheckRun:
    status: str
    conclusion: str | None

    @property
    def succeeded(self) -> bool:
        """성공만 통과다. 실패·취소·건너뜀·진행 중을 성공으로 보지 않는다."""
        return self.status == "completed" and self.conclusion == "success"


class ChecksUnavailable(Exception):
    """체크 조회가 답하지 않았다. 기다리는 동안에는 아직 결과가 없는 것으로 본다."""


class Checks(Protocol):
    def latest(self, sha: str, name: str) -> CheckRun | None: ...


def required_environment(
    names: tuple[str, ...], environ: Mapping[str, str] | None = None
) -> tuple[str, ...]:
    """비어 있으면 그 변수 이름만 담은 ValueError다. 값은 어디에도 출력하지 않는다."""
    values = os.environ if environ is None else environ
    for name in names:
        if not values.get(name, "").strip():
            raise ValueError(name)
    return tuple(values[name].strip() for name in names)


def _retry[T](
    attempt: Callable[[], T],
    done: Callable[[T], bool],
    attempts: int,
    delay: float,
    sleep: Callable[[float], None],
) -> T:
    """끝났다고 볼 때까지 유한하게 다시 한다. 마지막 결과를 그대로 돌려준다."""
    result = attempt()
    for _ in range(attempts - 1):
        if done(result):
            break
        sleep(delay)
        result = attempt()
    return result


@dataclass(frozen=True)
class Verification:
    url: str
    problems: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class Verifier:
    """배포 주소를 manifest와 대조한다. 한 실행 안에서 여러 주소를 같은 기준으로 본다."""

    fetcher: Fetcher
    cities: tuple[City, ...]
    sleep: Callable[[float], None]

    def verify(self, base_url: str, manifest: Manifest) -> Verification:
        """배포된 파일을 내려받아 manifest와 대조하고 주요 경로의 유형·구조를 본다."""
        problems: list[str] = []
        served = self._get(base_url, MANIFEST_NAME)
        if _manifest_in(served) != manifest:
            problems.append(f"{MANIFEST_NAME}: does not match the build ({served.describe()})")
        for item in manifest.files:
            response = self._get(base_url, item.path)
            if response.status != 200:
                problems.append(f"{item.path}: {response.describe()}")
            elif hashlib.sha256(response.body).hexdigest() != item.sha256:
                problems.append(f"{item.path}: SHA256 mismatch")
        problems += self._key_path_problems(base_url, manifest)
        return Verification(base_url, tuple(problems))

    def verify_until(self, base_url: str, manifest: Manifest) -> Verification:
        """전파가 늦을 수 있어 몇 번 다시 본다."""
        return _retry(
            lambda: self.verify(base_url, manifest),
            lambda result: result.passed,
            VERIFY_ATTEMPTS,
            VERIFY_DELAY,
            self.sleep,
        )

    def served_manifest(self, base_url: str) -> Manifest | None:
        return _manifest_in(self._get(base_url, MANIFEST_NAME))

    def _get(self, base_url: str, path: str) -> Response:
        # 예외 원문은 남기지 않는다.
        try:
            return self.fetcher.get(f"{base_url.rstrip('/')}/{path}")
        except OSError:
            return Response(0, "", b"", "unreachable")
        except ValueError:
            return Response(0, "", b"", "unreadable response")

    def _key_path_problems(self, base_url: str, manifest: Manifest) -> list[str]:
        """첫 화면·7개 도시 진입과 데이터 파일. 없는 JSON 대신 SPA HTML이 오는 것도 잡는다."""
        paths = {item.path for item in manifest.files}
        built = {city.slug for city in self.cities if f"{city.slug}/index.html" in paths}
        problems: list[str] = []
        landing = self._get(base_url, "")
        if landing.media_type != "text/html" or 'class="landing-page"' not in landing.text:
            problems.append(f"/: not the city landing ({_kind(landing)})")
        for city in self.cities:
            linked = f'href="./{city.slug}/"' in landing.text
            if linked != (city.slug in built):
                problems.append(f"/: link to {city.slug} does not match the build")
            page = self._get(base_url, f"{city.slug}/")
            is_city_page = (
                page.media_type == "text/html" and f'data-city="{city.slug}"' in page.text
            )
            if is_city_page != (city.slug in built):
                problems.append(f"/{city.slug}/: city page does not match the build")
            if city.slug in built:
                problems += self._data_problems(base_url, city.slug)
        for script in ("assets/app.js", "sw.js"):
            response = self._get(base_url, script)
            if response.media_type not in JAVASCRIPT_TYPES:
                problems.append(f"/{script}: not JavaScript ({_kind(response)})")
        return problems

    def _data_problems(self, base_url: str, slug: str) -> list[str]:
        problems = []
        for name, key in (("markers.json", "markers"), ("records.json", "records")):
            response = self._get(base_url, f"{slug}/{name}")
            if response.media_type != "application/json":
                problems.append(f"/{slug}/{name}: not JSON ({_kind(response)})")
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


def _manifest_in(response: Response) -> Manifest | None:
    if response.status != 200:
        return None
    try:
        return Manifest.from_json(response.text)
    except ValueError:
        return None


def _kind(response: Response) -> str:
    """받은 것의 유형. 응답이 없으면 그 사유다."""
    return response.media_type or response.describe()


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


def release_preview(dist: Path, branch: str, uploader: Uploader, verifier: Verifier) -> Report:
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
    report.checks.append(("고유 URL", verifier.verify_until(deployment.url, manifest)))
    if deployment.alias is None:
        report.checks.append(("alias", Verification(branch, ("no alias for the branch",))))
    else:
        report.checks.append(("alias", verifier.verify_until(deployment.alias, manifest)))
    report.passed = all(result.passed for _, result in report.checks)
    report.outcome = "미리보기를 올리고 검증했다." if report.passed else "미리보기 검증이 어긋났다."
    return report


def wait_for_check(
    checks: Checks, sha: str, name: str, sleep: Callable[[float], None]
) -> CheckRun | None:
    """체크가 끝날 때까지 기다린 마지막 상태. 끝나지 않았으면 끝나지 않은 상태를 돌려준다."""

    def look() -> CheckRun | None:
        try:
            return checks.latest(sha, name)
        except ChecksUnavailable:
            return None

    return _retry(
        look,
        lambda run: run is not None and run.status == "completed",
        CHECK_ATTEMPTS,
        CHECK_DELAY,
        sleep,
    )


class Refused(ValueError):
    """운영 배포를 요청할 수 없는 실행. 검사하지 않은 브랜치나 사유 없는 수동 실행이다."""


@dataclass(frozen=True)
class Request:
    """운영 배포를 부른 실행."""

    event: str
    ref: str
    reason: str
    freeze_at: datetime | None
    now: datetime

    @property
    def frozen(self) -> bool:
        return self.freeze_at is not None and self.now >= self.freeze_at


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


def validate_request(request: Request) -> None:
    """운영에 올릴 수 있는 실행인지. main의 push와 사유를 적은 수동 실행만 받는다."""
    if request.ref != MAIN_REF:
        raise Refused(f"production deploys only from {MAIN_REF}")
    if request.event == "workflow_dispatch" and not request.reason.strip():
        raise Refused("a manual production deploy needs a reason")
    if request.event not in {"push", "workflow_dispatch"}:
        raise Refused(f"event {request.event} does not deploy to production")


def release_production(
    dist: Path,
    request: Request,
    pages: Pages,
    uploader: Uploader,
    verifier: Verifier,
    latest_main: Callable[[], str],
    checkpoint: Callable[[Report], None] = lambda report: None,
) -> Report:
    """직전 검증 배포 보존 → 업로드 → 고유 URL·운영 alias 검증 → 실패하면 롤백·재검증.

    `checkpoint`는 단계마다 불러 기록을 남기게 한다. 도중에 예외로 끝나도 보존한 직전 배포는 남는다.
    """
    validate_request(request)
    manifest = read_manifest(dist)
    report = Report(title="운영 배포", commit=manifest.commit)
    report.record |= {"event": request.event, "reason": request.reason}
    report.facts.append(("실행", f"`{request.event}`"))
    if request.reason.strip():
        report.facts.append(("긴급 배포 사유", request.reason.strip()))
    if request.event == "push" and request.frozen and request.freeze_at is not None:
        report.passed = True
        report.outcome = (
            f"운영 배포를 건너뛰었다: 제출 동결 중이다(시작 {request.freeze_at.isoformat()})."
            " main push는 검사만 한다."
        )
        return report
    try:
        project = pages.project()
    except PagesApiFailed:
        report.outcome = "Pages API에서 운영 배포를 조회하지 못해 올리지 않았다."
        return report
    previous = _verified_previous(project.production, verifier)
    report.record["previous"] = (
        None
        if previous is None
        else {
            "id": previous[0].id,
            "url": previous[0].url,
            "manifest": json.loads(previous[1].to_json()),
        }
    )
    checkpoint(report)
    head = latest_main()
    if head != manifest.commit:
        # 동결 전에는 더 최신 커밋의 push가 배포하므로 건너뛴 것이 정상이다. 동결 중에는
        # 아무도 배포하지 않으므로 성공으로 남기지 않고 최신 main에서 다시 실행하게 한다.
        report.passed = not request.frozen
        report.outcome = f"운영 배포를 건너뛰었다: main이 `{head}`로 앞서 있다." + (
            " 더 최신 커밋의 실행이 배포한다."
            if report.passed
            else " 동결 중이므로 최신 main에서 사유를 적어 다시 수동 실행해야 한다."
        )
        return report
    alias = f"https://{project.subdomain}"
    try:
        deployment = uploader.upload(dist, project.production_branch, manifest.commit)
    except UploadFailed as exc:
        # 배포가 만들어졌는지 모른다. 운영 alias가 직전 배포 그대로인지 직접 확인한다.
        report.outcome = f"업로드 결과를 확인하지 못했다: {exc}."
        _recover(report, pages, verifier, previous, alias)
        return report
    report.record["deployment"] = {"id": deployment.id, "url": deployment.url}
    report.facts.append(("배포 ID", f"`{deployment.id}`"))
    checkpoint(report)
    if deployment.environment != "production":
        report.outcome = f"배포가 운영이 아닌 `{deployment.environment}` 환경으로 올라갔다."
        return report
    unique = verifier.verify_until(deployment.url, manifest)
    report.checks.append(("고유 URL", unique))
    # 고유 URL이 어긋나면 운영 alias도 같은 배포를 가리키므로 기다리지 않고 복구로 간다.
    if unique.passed:
        report.checks.append(("운영 alias", verifier.verify_until(alias, manifest)))
    if all(result.passed for _, result in report.checks):
        report.passed = True
        report.outcome = "운영에 배포하고 검증했다."
        return report
    report.outcome = "배포 뒤 검증이 실패했다."
    _recover(report, pages, verifier, previous, alias)
    return report


def _recover(
    report: Report,
    pages: Pages,
    verifier: Verifier,
    previous: tuple[Deployment, Manifest] | None,
    alias: str,
) -> None:
    """운영을 직전 검증 배포로 돌려놓는다. 복구가 되어도 실행은 실패로 남긴다.

    운영이 바뀌었는지는 전파가 늦을 수 있는 alias가 아니라 Pages API의 현재 운영 배포로 판단한다.
    """
    if previous is None:
        report.outcome += " 롤백할 검증 배포가 없다. 사람이 대응해야 한다."
        return
    target, target_manifest = previous
    try:
        current = pages.project().production
        changed = current is None or current.id != target.id
        if changed:
            pages.rollback(target.id)
    except PagesApiFailed:
        report.outcome += (
            f" Pages API로 `{target.id}` 복구를 확인·요청하지 못했다. 사람이 대응해야 한다."
        )
        return
    restored = verifier.verify_until(alias, target_manifest)
    if not changed:
        report.checks.append(("운영 alias(직전 배포 유지)", restored))
        report.outcome += (
            f" 운영은 직전 검증 배포 `{target.id}` 그대로다."
            if restored.passed
            else f" 운영은 `{target.id}`를 가리키지만 재검증이 실패했다. 사람이 대응해야 한다."
        )
        return
    report.checks.append(("롤백 뒤 운영 alias", restored))
    report.record["rollback"] = {"id": target.id, "restored": restored.passed}
    report.outcome += (
        f" 직전 검증 배포 `{target.id}`로 롤백하고 재검증했다. 이 실행은 실패로 남긴다."
        if restored.passed
        else f" `{target.id}`로 롤백했지만 재검증도 실패했다. 사람이 대응해야 한다."
    )


def _verified_previous(
    production: Deployment | None, verifier: Verifier
) -> tuple[Deployment, Manifest] | None:
    """롤백해도 되는 운영 배포. 자기 manifest와 다시 대조해 통과한 것만 인정한다."""
    if production is None:
        return None
    served = verifier.served_manifest(production.url)
    if served is None or not verifier.verify(production.url, served).passed:
        return None
    return production, served
