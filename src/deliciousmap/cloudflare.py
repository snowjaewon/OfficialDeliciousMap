"""Cloudflare Pages 어댑터: Wrangler Direct Upload, Pages API, 배포 주소 내려받기.

판정은 `deploy`가 한다. 토큰·계정 값은 환경으로만 받고 출력·예외에 싣지 않는다.
"""

import gzip
import http.client
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from deliciousmap.deploy import (
    Deployment,
    PagesApiFailed,
    Project,
    Response,
    UploadFailed,
    required_environment,
)
from deliciousmap.publish import PAGES_FILE_LIMIT
from deliciousmap.transport import HttpTransport, JsonTransport, ResourceGone, Transport

# 배포 도구의 고정 버전. 올릴 때는 출력 파일 형식(pages-deploy-detailed)을 다시 확인한다.
WRANGLER = "wrangler@4.131.1"
API = "https://api.cloudflare.com/client/v4"
# 배포 job에만 넘기는 비밀값. 빌드 job과 artifact에는 가지 않는다.
TOKEN_VARIABLE = "CLOUDFLARE_API_TOKEN"
ACCOUNT_VARIABLE = "CLOUDFLARE_ACCOUNT_ID"


class ApiTransport(Transport, JsonTransport, Protocol):
    """조회와 요청을 함께 보내는 경계."""


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
            if len(body) > self.limit:
                raise ValueError("response exceeds the deployment file limit")
            encoding = (headers.get("Content-Encoding") or "").lower()
            if encoding == "gzip":
                body = gzip.decompress(body)
            elif encoding not in {"", "identity"}:
                raise ValueError("unsupported content encoding")
        except urllib.error.HTTPError as error:
            return Response(error.code, error.headers.get("Content-Type", ""), b"")
        except (http.client.HTTPException, EOFError, zlib.error) as exc:
            # 끊긴 본문·깨진 압축. 연결 실패(OSError)와 구별해 해석 실패로 알린다.
            raise ValueError("unreadable response") from exc
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


def deployment_from_output(text: str) -> Deployment:
    """Wrangler 출력 파일(ND-JSON)의 마지막 `pages-deploy-detailed` 항목."""
    try:
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
    except (ValueError, KeyError, AttributeError) as exc:
        raise UploadFailed("wrangler output is unreadable") from exc


class CloudflarePages:
    """Pages API 중 운영 배포 조회와 롤백만 쓴다."""

    def __init__(
        self, project: str, account_id: str, token: str, transport: ApiTransport | None = None
    ) -> None:
        self.url = f"{API}/accounts/{account_id}/pages/projects/{project}"
        self.token = token
        self.transport: ApiTransport = transport or HttpTransport(timeout=30.0)

    @classmethod
    def from_environment(
        cls, project: str, environ: Mapping[str, str] | None = None
    ) -> "CloudflarePages":
        account, token = required_environment((ACCOUNT_VARIABLE, TOKEN_VARIABLE), environ)
        return cls(project, account, token)

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
