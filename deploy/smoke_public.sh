#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://www.theebie.de/sites/roguelike}"

check_url() {
  local url="$1"
  local pattern="$2"
  local body
  body="$(curl -fsSL "$url")"
  if ! grep -q "$pattern" <<<"$body"; then
    echo "smoke failed: $url missing pattern: $pattern" >&2
    exit 1
  fi
  echo "smoke ok: $url"
}

check_url "$BASE_URL/" "ai_roguelike"
check_url "$BASE_URL/" 'href="./devlog/"'
check_url "$BASE_URL/devlog/" "Studio devlog"
check_url "$BASE_URL/docs/" "Game docs"

echo "Public smoke passed for game, devlog, and docs."
