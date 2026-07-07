#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/ai_roguelike}"
THEEBIE_HOST="${THEEBIE_HOST:-root@84.38.65.246}"
THEEBIE_SITE_DIR="${THEEBIE_SITE_DIR:-/var/www/html/sites/roguelike}"

cd "$REPO_DIR"
git fetch -q origin
git merge --ff-only origin/main

cd "$REPO_DIR/game"
npm ci
npm test
npm run build

ssh "$THEEBIE_HOST" "mkdir -p '$THEEBIE_SITE_DIR'"
rsync -az --delete "$REPO_DIR/game/dist/" "$THEEBIE_HOST:$THEEBIE_SITE_DIR/"

echo "Deployed ai_roguelike to https://www.theebie.de/sites/roguelike/"
