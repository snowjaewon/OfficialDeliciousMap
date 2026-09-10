#!/usr/bin/env bash
# .env 에 적어 둔 값 중 CI 가 쓰는 것만 GitHub Actions 에 올린다. 값은 화면에 찍지 않는다.
# 실행: bash scripts/sync-github.sh   (Git Bash)
set -euo pipefail
ENV_FILE="${ENV_FILE:-.env}"
[[ -f "$ENV_FILE" ]] || { echo ".env 가 없다. .env.example 을 복사해 채운 뒤 다시 실행."; exit 1; }
get() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '\r"' ; }
need() { local v; v=$(get "$1"); [[ -n "$v" ]] || { echo "  - $1 이 .env 에 비어 있음, 건너뜀"; return 1; }; printf '%s' "$v"; }

if v=$(need CLOUDFLARE_API_TOKEN);     then printf '%s' "$v" | gh secret set CLOUDFLARE_API_TOKEN     && echo "  ✓ secret CLOUDFLARE_API_TOKEN"; fi
if v=$(need CLOUDFLARE_ACCOUNT_ID);    then printf '%s' "$v" | gh secret set CLOUDFLARE_ACCOUNT_ID    && echo "  ✓ secret CLOUDFLARE_ACCOUNT_ID"; fi
if v=$(need CLOUDFLARE_PAGES_PROJECT); then gh variable set CLOUDFLARE_PAGES_PROJECT --body "$v"       && echo "  ✓ variable CLOUDFLARE_PAGES_PROJECT"; fi
if v=$(need NAVER_MAP_CLIENT_ID);      then gh variable set NAVER_MAP_CLIENT_ID --body "$v"            && echo "  ✓ variable NAVER_MAP_CLIENT_ID"; fi
if v=$(need NAVER_MAP_KEY_PARAM);      then gh variable set NAVER_MAP_KEY_PARAM --body "$v"            && echo "  ✓ variable NAVER_MAP_KEY_PARAM"; fi

echo; echo "GitHub 에 등록된 것:"; gh secret list; gh variable list
