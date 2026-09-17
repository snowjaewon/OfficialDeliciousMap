"""headermap이 열 서울 원본이 `--raw-root` 아래에 모두 있는지 먼저 확인한다(#214).

`fetch.json`의 전체 원본이 아니라 `reporting_sources()`가 대상 기간으로 고른 것만 센다
(`storage.py:771-781`). 없는 파일이 있으면 기관·컨테이너와 함께 그 사실을 남긴다.

    uv run python docs/validation/issue-214/rawcheck.py [raw-root]
"""

import sys
from collections import Counter
from pathlib import Path

from deliciousmap.paths import Paths
from deliciousmap.registry import CITIES, select_target
from deliciousmap.storage import ArtifactStore


def main(raw_root: Path) -> int:
    paths = Paths(Path.cwd(), raw_root, Path("data"), Path("dist"))
    paths.validate()
    print(f"raw-root: {raw_root.resolve()} exists={raw_root.is_dir()}")
    present = 0
    missing: Counter[str] = Counter()
    for org in sorted(path.name for path in Path("data/seoul/orgs").iterdir() if path.is_dir()):
        store = ArtifactStore(paths, select_target(CITIES, "seoul", org))
        seen: set[str] = set()
        gone: Counter[str] = Counter()
        here = 0
        for source in store.reporting_sources():
            if source.source_hash in seen:
                continue
            seen.add(source.source_hash)
            if (raw_root / source.path).is_file():
                here += 1
            else:
                gone[source.container] += 1
        present += here
        missing.update(gone)
        note = "" if not gone else f"  없음 {dict(gone)} — {raw_root / 'seoul' / org} 아래에 필요"
        print(f"{org:<22}{here:>6}개 있음{sum(gone.values()):>6}개 없음{note}")
    print(f"합계 {present}개 있음 {sum(missing.values())}개 없음")
    return 1 if missing else 0


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd().parent / "deliciousmap-raw"
    sys.exit(main(root))
