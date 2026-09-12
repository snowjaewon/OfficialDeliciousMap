"""GitHub 체크 조회 어댑터. 같은 커밋의 다른 workflow 체크 결과를 읽는다."""

import json
from collections.abc import Mapping

from deliciousmap.deploy import CheckRun, ChecksUnavailable, required_environment
from deliciousmap.transport import HttpTransport, ResourceGone, Transport

TOKEN_VARIABLE = "GITHUB_TOKEN"


class GitHubChecks:
    """커밋의 체크 실행 중 이름이 같은 가장 최근 것. 다시 실행한 결과가 앞선 결과를 대신한다."""

    def __init__(self, repository: str, token: str, transport: Transport | None = None) -> None:
        self.url = f"https://api.github.com/repos/{repository}/commits"
        self.token = token
        self.transport: Transport = transport or HttpTransport(timeout=30.0)

    @classmethod
    def from_environment(
        cls, repository: str, environ: Mapping[str, str] | None = None
    ) -> "GitHubChecks":
        (token,) = required_environment((TOKEN_VARIABLE,), environ)
        return cls(repository, token)

    def latest(self, sha: str, name: str) -> CheckRun | None:
        try:
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
        except (OSError, ValueError, KeyError, ResourceGone) as exc:
            raise ChecksUnavailable("check runs request failed") from exc
        if not runs:
            return None
        run = max(runs, key=lambda item: int(item["id"]))
        return CheckRun(status=str(run["status"]), conclusion=run.get("conclusion"))
