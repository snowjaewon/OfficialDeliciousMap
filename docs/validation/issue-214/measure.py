"""기관 하나의 headermap 단계를 돌리며 표 단위 결과를 함께 센다(#214).

`data/seoul/orgs/<org>/headermap.json`은 CLI가 그대로 만든다. 이 스크립트가 더하는 것은
관찰뿐이다. 산출물의 `unresolved`는 원본 단위이고 원본마다 첫 실패만 싣기 때문에
(`headermap.py:122-130`) 표 단위 신규 판정 수를 담지 못한다. 그 수를 세려고 `_map_table()`의
결과를 표마다 기록한다. 판정·저장 경로는 바꾸지 않는다.

    uv run python docs/validation/issue-214/measure.py <기관> <census 경로>
"""

import json
import sys
from pathlib import Path

import deliciousmap.headermap as headermap
from deliciousmap import cli


def main(org: str, out: Path) -> int:
    census: list[dict[str, object]] = []
    # `_map_table()`이 캐시를 몇 개 찾았는지는 그 함수 밖에서 볼 수 없다. 같은 조회를 두 번
    # 하지 않으려고 원래 함수가 낸 값을 받아 두었다가 결과와 함께 적는다.
    slot: dict[str, int] = {}
    original_cached = headermap._cached
    original_map_table = headermap._map_table

    def traced_cached(source, table, cache_path):  # type: ignore[no-untyped-def]
        found = original_cached(source, table, cache_path)
        slot["candidates"] = len(found)
        return found

    def traced_map_table(source, table, stores, mapper):  # type: ignore[no-untyped-def]
        slot["candidates"] = 0
        row = {
            "source_hash": source.source_hash,
            "container": source.container,
            "board": source.board,
            "table": table.name,
            "rows": len(table.rows),
        }
        try:
            mapping = original_map_table(source, table, stores, mapper)
        except headermap.Unresolved as exc:
            row["candidates"] = slot["candidates"]
            # 서명이 맞았는데도 실패했으면 캐시 판정이 코드 검증에 걸린 것이다.
            row["outcome"] = "cache_rejected" if slot["candidates"] else "cache_miss"
            row["reason"] = exc.reason
            census.append(row)
            raise
        row["candidates"] = slot["candidates"]
        row["outcome"] = "cache_hit"
        row["reason"] = None
        census.append(row)
        return mapping

    headermap._cached = traced_cached
    headermap._map_table = traced_map_table
    code = cli.main(["headermap", "--city", "seoul", "--org", org])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in census:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"{org} exit={code} tables={len(census)}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], Path(sys.argv[2])))
