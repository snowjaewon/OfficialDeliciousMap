"""배포 전 오프라인 검사. 커밋된 정제 산출물과 build한 `dist/`를 네트워크 없이 판정한다."""

import hashlib
import json
import posixpath
import re
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path

from deliciousmap import site
from deliciousmap.registry import City
from deliciousmap.storage import SIZE_LIMIT, write_text

# 도시가 아닌 정제 산출물 디렉터리: 도시 무관 캐시와 사람 보정(README "저장 형식").
SHARED_DIRECTORIES = frozenset({"_shared", "manual"})
# 배포 대조의 기준. 공개 파일과 함께 올리지만 자기 자신은 대조 목록에 넣지 않는다.
MANIFEST_NAME = "deploy-manifest.json"
MANIFEST_VERSION = 1
# Cloudflare Pages Free 플랜의 배포 asset 한도. 정제 산출물 상한(20MB)과 다른 검사다.
PAGES_FILE_LIMIT = 25 * 1024 * 1024
PAGES_FILE_COUNT = 20_000
# 공개 파일이 서로를 가리키는 자리. site.py가 쓰는 속성과 sw.js의 사전 캐시 목록이다.
HTML_REFERENCE = re.compile(r'\b(?:href|src|data-markers-url|data-records-url)="([^"]*)"')
SITE_CONFIG = re.compile(r'<script id="site-config" type="application/json">(.*?)</script>', re.S)
SERVICE_WORKER_SHELL = re.compile(r"const SHELL = (\[[^\]]*\]);")
# HTML 밖에서 다른 공개 파일을 가리키는 파일. 나머지 자산·데이터는 참조를 담지 않는다.
REFERRING_FILES = frozenset({"sw.js", "manifest.webmanifest"})


@dataclass(frozen=True)
class PublishedFile:
    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class Manifest:
    """한 번 검사한 `dist/`의 공개 파일 목록과 그 파일을 만든 commit."""

    commit: str
    files: tuple[PublishedFile, ...]

    def to_json(self) -> str:
        payload = {
            "schema_version": MANIFEST_VERSION,
            "commit": self.commit,
            "files": [asdict(item) for item in self.files],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        """manifest를 되읽는다. 모양이 다르면 ValueError다."""
        try:
            payload = json.loads(text)
            if payload["schema_version"] != MANIFEST_VERSION:
                raise ValueError("unsupported manifest version")
            return cls(
                commit=str(payload["commit"]),
                files=tuple(
                    PublishedFile(str(item["path"]), str(item["sha256"]), int(item["bytes"]))
                    for item in payload["files"]
                ),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("malformed manifest") from exc


def read_manifest(dist: Path) -> Manifest:
    return Manifest.from_json((dist / MANIFEST_NAME).read_text(encoding="utf-8"))


def site_files(dist: Path) -> tuple[str, ...]:
    """`dist/`의 파일을 상대 POSIX 경로로. manifest 자신은 뺀다."""
    return tuple(
        relative
        for path in sorted(dist.rglob("*"))
        if path.is_file() and (relative := path.relative_to(dist).as_posix()) != MANIFEST_NAME
    )


def dist_problems(dist: Path, city_slugs: tuple[str, ...]) -> tuple[str, ...]:
    """배포하기 전에 막아야 할 `dist/`의 문제. 비어 있으면 봉인할 수 있다."""
    files = site_files(dist)
    expected = site.public_paths(city_slugs)
    problems = [
        *(f"not a screen file: {relative}" for relative in files if relative not in expected),
        *(f"missing site file: {relative}" for relative in sorted(expected - set(files))),
    ]
    if not city_slugs:
        problems.append("no city was built")
    problems += [
        f"file over 25MiB: {relative} ({(dist / relative).stat().st_size:,} bytes)"
        for relative in files
        if (dist / relative).stat().st_size > PAGES_FILE_LIMIT
    ]
    # 함께 올라가는 manifest도 배포 파일 한 개다.
    uploaded = len(files) + 1
    if uploaded > PAGES_FILE_COUNT:
        problems.append(f"{uploaded} files exceed the {PAGES_FILE_COUNT:,}-file deployment limit")
    present = set(files)
    problems += [
        f"broken reference: {relative} -> {target}"
        for relative in files
        if relative.endswith(".html") or relative in REFERRING_FILES
        for target in _local_targets(relative, (dist / relative).read_text(encoding="utf-8"))
        if target not in present
    ]
    return tuple(problems)


def _local_targets(relative: str, text: str) -> tuple[str, ...]:
    """공개 파일이 브라우저에서 가리키는 사이트 안 파일. 외부 주소는 보지 않는다."""
    references: list[str] = []
    if relative.endswith(".html"):
        references += HTML_REFERENCE.findall(text)
        config = SITE_CONFIG.search(text)
        if config is not None:
            # 화면은 이 값으로 랜딩과 service worker를 찾는다(app.js registerServiceWorker).
            root = json.loads(config.group(1))["site_root"]
            references += [root, f"{root}sw.js"]
    elif relative == "sw.js":
        shell = SERVICE_WORKER_SHELL.search(text)
        references += json.loads(shell.group(1)) if shell is not None else []
    elif relative == "manifest.webmanifest":
        references.append(json.loads(text)["start_url"])
    return tuple(
        target for reference in references if (target := _resolve(relative, reference)) is not None
    )


def _resolve(relative: str, reference: str) -> str | None:
    """참조를 `dist/` 기준 파일 경로로. 디렉터리 주소는 그 안의 index.html이다."""
    parts = urllib.parse.urlsplit(reference)
    if parts.scheme or parts.netloc or not parts.path:
        return None
    target = posixpath.normpath(posixpath.join(posixpath.dirname(relative), parts.path))
    if parts.path.endswith("/") or target == ".":
        target = posixpath.join(target, "index.html") if target != "." else "index.html"
    return target


def seal(dist: Path, commit: str) -> Manifest:
    """검사를 통과한 `dist/`에 manifest를 쓴다. 배포 단계는 이것으로만 대조한다."""
    manifest = Manifest(
        commit=commit,
        files=tuple(
            PublishedFile(
                path=relative,
                sha256=hashlib.sha256((dist / relative).read_bytes()).hexdigest(),
                bytes=(dist / relative).stat().st_size,
            )
            for relative in site_files(dist)
        ),
    )
    write_text(dist / MANIFEST_NAME, manifest.to_json())
    return manifest


def buildable_cities(data_root: Path, cities: tuple[City, ...]) -> tuple[City, ...]:
    """커밋된 `data/<city>/`가 있는 도시. 레지스트리 순서를 따른다."""
    return tuple(city for city in cities if (data_root / city.slug).is_dir())


def unknown_directories(data_root: Path, cities: tuple[City, ...]) -> tuple[str, ...]:
    """도시도 공통 디렉터리도 아닌 것. 오타 난 도시를 build에서 조용히 빠뜨리지 않는다."""
    known = SHARED_DIRECTORIES | {city.slug for city in cities}
    return tuple(
        path.name
        for path in sorted(data_root.iterdir())
        if path.is_dir() and path.name not in known
    )


def oversized_refined(data_root: Path) -> tuple[str, ...]:
    """상한(ADR-0001)을 넘는 정제 산출물. 넘은 파일은 build 전에 분할해야 한다."""
    return tuple(
        f"{path.relative_to(data_root).as_posix()} ({path.stat().st_size:,} bytes)"
        for path in sorted(data_root.rglob("*"))
        if path.is_file() and path.stat().st_size > SIZE_LIMIT
    )
