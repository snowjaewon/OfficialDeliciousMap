"""커밋된 fetch 산출물의 원본 경로를 raw-root 기준 상대 경로로 옮긴다(#202). 일회성 도구다.

원본을 읽지 않고 단계 재실행에도 기대지 않는다 — 여섯 도시 가운데 셋의 원본은 상대 담당자
PC에만 있다. 바꾸는 것은 경로 표기법뿐이라 `fetch.json`이 밝히는 사실(어느 원본을 어떤
`source_hash`로 어느 기관·게시판에서 받았는지)은 그대로다.

`fetch.json`을 다시 쓰면 파일 해시가 바뀐다. 같은 디렉터리 `headermap.json`이 봉투의
`dependencies["fetch.json"]`에 그 해시를 적어 두었으므로 둘을 같이 옮긴다. 따로 하면 그 사이
저장소 상태에서 `parse`가 `stale artifact`로 멈춘다.

접두사를 짐작하지 않는다. 경로의 마지막 네 칸이 도시·기관·게시판·이름과 맞는지 확인한 뒤
그 네 칸만 남긴다. 맞지 않으면 조용히 넘기지 않고 멈춘다.

양쪽 공통: uv run python scripts/relativize_source_paths.py --data-root data
"""

import argparse
import json
from pathlib import Path
from typing import Any

from deliciousmap.storage import artifact_digest, artifact_text, write_text


def relative_original(value: str, city: str, organization: str, board: str) -> str:
    """원본 하나의 자리. 이미 옮긴 값에 다시 돌리면 같은 값을 돌려준다."""
    board_path = f"{city}/{organization}/{board}"
    parts = value.replace("\\", "/").split("/")
    tail = parts[-4:]
    if len(tail) != 4 or "/".join(tail[:3]) != board_path:
        raise ValueError(f"original is not under {board_path}: {len(parts)} path segments")
    return "/".join(tail)


def _envelope(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _move_fetch(path: Path) -> bool:
    """옮길 것이 있으면 다시 쓰고 알린다. 이미 상대 경로뿐이면 파일에 손대지 않는다."""
    envelope = _envelope(path)
    city = envelope["city"]
    sources = envelope["payload"].get("sources") or []
    moved = [
        {
            **source,
            "path": relative_original(
                source["path"], city, source["organization"], source["board"]
            ),
        }
        for source in sources
    ]
    if moved == sources:
        return False
    envelope["payload"]["sources"] = moved
    write_text(path, artifact_text(envelope))
    return True


def _resign_headermap(path: Path, fetch: Path) -> bool:
    """headermap 봉투가 서명한 fetch 해시를 옮긴 뒤의 값으로 갱신한다."""
    envelope = _envelope(path)
    digest = artifact_digest(fetch)
    if envelope["dependencies"].get("fetch.json") == digest:
        return False
    envelope["dependencies"]["fetch.json"] = digest
    write_text(path, artifact_text(envelope))
    return True


def migrate(data_root: Path) -> tuple[Path, ...]:
    """바꾼 파일을 돌려준다. 이미 옮긴 저장소에 다시 돌리면 빈 값이고 파일도 그대로다."""
    changed: list[Path] = []
    orphans = {
        path
        for path in data_root.rglob("headermap.json")
        if not (path.parent / "fetch.json").exists()
    }
    if orphans:
        raise ValueError(f"headermap without its fetch artifact: {len(orphans)} files")
    for fetch in sorted(data_root.rglob("fetch.json")):
        if _move_fetch(fetch):
            changed.append(fetch)
        headermap = fetch.parent / "headermap.json"
        if headermap.exists() and _resign_headermap(headermap, fetch):
            changed.append(headermap)
    return tuple(changed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    arguments = parser.parse_args(argv)
    changed = migrate(arguments.data_root)
    for path in changed:
        print(path.as_posix())
    print(f"moved {len(changed)} artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
