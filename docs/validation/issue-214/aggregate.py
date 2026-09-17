"""25개 기관의 headermap 산출물과 표 단위 census를 합쳐 적중률을 낸다(#214).

uv run python docs/validation/issue-214/aggregate.py <census 디렉터리>
"""

import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

DATA = Path("data")
# 호출당이 아니라 표당 단가를 쓴다. 장부는 같은 표에 재호출한 줄도 따로 싣는다.
BUDGET = DATA / "_shared" / "llm-budget.jsonl"
LIMIT_USD = Decimal(15)


def unit_price() -> tuple[Decimal, int, int]:
    """지난 header_mapping 지출을 고유 (원본, 표) 키로 나눈 표당 단가."""
    settled = [
        entry
        for line in BUDGET.read_text("utf-8").splitlines()
        if (entry := json.loads(line))["kind"] == "settlement"
        and entry["purpose"] == "header_mapping"
    ]
    spent = sum((Decimal(entry["amount_usd"]) for entry in settled), Decimal(0))
    # `entry_id`는 `header_mapping:<원본 앞 16자>:<표>:<호출 uuid>`다(`headermap.py:424`).
    tables = {":".join(entry["entry_id"].split(":")[:-1]) for entry in settled}
    return spent / len(tables), len(settled), len(tables)


def main(census_dir: Path) -> int:
    orgs = sorted(path.name for path in (DATA / "seoul" / "orgs").iterdir() if path.is_dir())
    by_container: dict[str, Counter[str]] = defaultdict(Counter)
    stuck: dict[str, Counter[str]] = defaultdict(Counter)
    outcomes: Counter[str] = Counter()
    artifact: Counter[str] = Counter()
    rows = []
    for org in orgs:
        payload = json.loads((DATA / f"seoul/orgs/{org}/headermap.json").read_text("utf-8"))
        found = payload["payload"]
        fetched = json.loads((DATA / f"seoul/orgs/{org}/fetch.json").read_text("utf-8"))
        container = {
            item["source_hash"]: item["container"] for item in fetched["payload"]["sources"]
        }
        census = [
            json.loads(line)
            for line in (census_dir / f"{org}.jsonl").read_text("utf-8").splitlines()
            if line
        ]
        counted = Counter(row["outcome"] for row in census)
        outcomes.update(counted)
        artifact["mappings"] += len(found["mappings"])
        artifact["unresolved"] += len(found["unresolved"])
        artifact["unresolved_mappings"] += len(found["unresolved_mappings"])
        opened = {row["source_hash"] for row in census}
        for row in census:
            by_container[row["container"]][row["outcome"]] += 1
        for item in found["unresolved"]:
            if item["source_hash"] not in opened:
                stuck[container[item["source_hash"]]][item["reason"]] += 1
        rows.append((org, len(census), counted["cache_hit"], counted["cache_rejected"]))

    print(f"{'기관':<22}{'연 표':>8}{'적중':>7}{'검증 실패':>10}{'신규 판정':>10}")
    for org, tables, hit, rejected in sorted(rows, key=lambda row: -row[1]):
        print(f"{org:<22}{tables:>8}{hit:>7}{rejected:>10}{tables - hit:>10}")
    tables = sum(row[1] for row in rows)
    hit = sum(row[2] for row in rows)
    print(f"{'합계':<22}{tables:>8}{hit:>7}{sum(row[3] for row in rows):>10}{tables - hit:>10}")
    print(f"\n표 단위 결과: {dict(outcomes)}")
    print(f"산출물 합계(mappings·unresolved_mappings는 표, unresolved는 원본): {dict(artifact)}")

    print(f"\n{'컨테이너':<10}{'표':>8}{'적중':>7}{'검증 실패':>10}{'미적중':>8}{'적중률':>9}")
    for name in sorted(by_container, key=lambda key: -sum(by_container[key].values())):
        counts = by_container[name]
        total = sum(counts.values())
        share = 100 * counts["cache_hit"] / total
        print(
            f"{name:<10}{total:>8}{counts['cache_hit']:>7}{counts['cache_rejected']:>10}"
            f"{counts['cache_miss']:>8}{share:>8.1f}%"
        )
    print("\n표를 하나도 열지 못한 원본")
    for name in sorted(stuck, key=lambda key: -sum(stuck[key].values())):
        print(f"  {name:<8}{dict(stuck[name])}")

    price, calls, judged = unit_price()
    spent = sum(
        (
            Decimal(entry["amount_usd"])
            for line in BUDGET.read_text("utf-8").splitlines()
            if (entry := json.loads(line))["kind"] == "settlement"
        ),
        Decimal(0),
    )
    left = LIMIT_USD - spent
    need = tables - hit
    print(f"\n표당 단가 USD {price:.6f} (호출 {calls}회로 표 {judged}개 판정)")
    print(f"신규 판정 {need}표를 API로 전량: USD {price * need:.2f}")
    print(f"잔여 예산 USD {left}: {int(left / price)}표 ({100 * int(left / price) / need:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
