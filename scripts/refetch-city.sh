#!/usr/bin/env bash
# 한 도시의 기관을 병렬로 다시 수집한다. Git Bash의 Bash로 실행한다(WSL Bash가 아니다).
#
#   bash scripts/refetch-city.sh <도시> [동시 실행 수] [원본 루트]
#   bash scripts/refetch-city.sh incheon 4
#
# 기관마다 호스트가 다르므로(seoul 25기관/25호스트, busan 15/15, incheon 12/12 실측)
# 기관을 나란히 돌려도 한 호스트에 대한 요청 간격(`boards.REQUEST_INTERVAL`)은 지켜진다.
# 같은 호스트를 쓰는 기관이 생기면 이 전제가 깨지므로 아래 검사가 먼저 막는다.
#
# 기관 수집이 모두 끝나면 도시 단위 수집을 한 번 더 돌린다. `data/<도시>/fetch.json`은
# `--org` 없는 실행만 만들고, 그 실행은 장부 덕분에 본문과 원본을 건너뛰고 목록만 훑는다.
set -euo pipefail

CITY="${1:-}"
JOBS="${2:-4}"
RAW_ROOT="${3:-../deliciousmap-raw}"

if [ -z "$CITY" ]; then
  echo "usage: bash scripts/refetch-city.sh <city> [jobs] [raw-root]" >&2
  exit 2
fi

LOG_DIR="../refetch-logs/$CITY"
mkdir -p "$LOG_DIR"
STATUS="$LOG_DIR/status.tsv"
: >"$STATUS"

# 레지스트리에서 기관 슬러그를 읽는다. 수집 보류 기관(`hold_reason`)은 게시판이 없어 뺀다.
# 같은 호스트를 두 기관이 쓰면 병렬 전제가 깨지므로 그 자리에서 멈춘다.
#
# Windows의 파이썬은 줄 끝을 CRLF로 쓴다. `\r`를 떼지 않으면 슬러그 끝에 붙어
# `--org incheon-city<CR>`가 되고 CLI가 전량을 `invalid organization selection`으로 물린다.
mapfile -t ORGS < <(
  uv run python - "$CITY" <<'PY' | tr -d '\r'
import sys
import urllib.parse
from collections import Counter

from deliciousmap import registry

slug = sys.argv[1]
city = next((item for item in registry.CITIES if item.slug == slug), None)
if city is None:
    print(f"unknown city: {slug}", file=sys.stderr)
    raise SystemExit(2)

hosts: Counter[str] = Counter()
targets = []
for org in city.organizations:
    if org.hold_reason is not None or not org.boards:
        continue
    targets.append(org.slug)
    for host in {urllib.parse.urlparse(board.url).netloc for board in org.boards}:
        hosts[host] += 1

shared = {host: count for host, count in hosts.items() if count > 1}
if shared:
    print(f"organizations share a host, do not run in parallel: {shared}", file=sys.stderr)
    raise SystemExit(3)

print("\n".join(targets))
PY
)

# 위 파이썬이 멈춘 사유(모르는 도시, 호스트 공유)는 프로세스 치환 안에서 죽어 바깥 종료
# 코드로 오지 않는다. 목록이 비었다는 사실로 그 자리에서 막는다. 그냥 두면 기관을 하나도
# 돌리지 않은 채 도시 단위 수집만 성공으로 끝난다.
if [ "${#ORGS[@]}" -eq 0 ]; then
  echo "no organizations to fetch for $CITY; see the reason above" >&2
  exit 3
fi

echo "city=$CITY orgs=${#ORGS[@]} jobs=$JOBS raw-root=$RAW_ROOT"
echo "logs=$LOG_DIR"

one() {
  local org="$1"
  local log="$LOG_DIR/$org.log"
  local start
  start=$(date +%s)
  local code=0
  uv run python -m deliciousmap fetch --city "$CITY" --org "$org" --raw-root "$RAW_ROOT" \
    >"$log" 2>&1 || code=$?
  printf '%s\t%s\t%s\n' "$org" "$code" "$(( $(date +%s) - start ))" >>"$STATUS"
  if [ "$code" -eq 0 ]; then
    echo "  done $org ($(( $(date +%s) - start ))s)"
  else
    echo "  FAIL $org exit=$code — $log"
  fi
}

started=$(date +%s)
for org in "${ORGS[@]}"; do
  while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do
    wait -n
  done
  one "$org" &
done
wait

failed=$(awk -F'\t' '$2 != 0' "$STATUS" | wc -l)
echo "orgs done: failed=$failed jobs=$JOBS elapsed=$(( $(date +%s) - started ))s"
if [ "$failed" -ne 0 ]; then
  echo "fix the failed orgs first; the city-wide pass was not run" >&2
  awk -F'\t' '$2 != 0 {print "  " $1 " exit=" $2}' "$STATUS" >&2
  exit 1
fi

# 도시 단위 산출물. 기관 실행이 채운 장부를 그대로 쓰므로 본문·원본은 다시 받지 않는다.
echo "city-wide pass (listing only; bodies and originals are skipped)"
city_log="$LOG_DIR/_city.log"
city_start=$(date +%s)
if uv run python -m deliciousmap fetch --city "$CITY" --raw-root "$RAW_ROOT" >"$city_log" 2>&1; then
  echo "  done city ($(( $(date +%s) - city_start ))s)"
else
  echo "  FAIL city — $city_log" >&2
  exit 1
fi

# 첨부 없는 게시글 수. #212가 칸을 더하기 전에는 이 값이 없으므로 `-`로 찍는다.
uv run python - "$CITY" <<'PY'
import json
import pathlib
import sys

city = sys.argv[1]
root = pathlib.Path("data") / city
rows = []
for path in sorted(root.glob("orgs/*/fetch.json")):
    payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
    rows.append(
        (
            path.parent.name,
            len(payload.get("sources", ())),
            payload.get("unattached_postings", "-"),
        )
    )
width = max((len(name) for name, _, _ in rows), default=4)
print(f"\n{'org'.ljust(width)}  {'sources':>7}  {'unattached':>10}")
for name, sources, unattached in rows:
    print(f"{name.ljust(width)}  {sources:7}  {str(unattached):>10}")
print(f"{'total'.ljust(width)}  {sum(row[1] for row in rows):7}")
PY
