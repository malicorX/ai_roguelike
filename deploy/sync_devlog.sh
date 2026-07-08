#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/ai_roguelike}"
THEEBIE_HOST="${THEEBIE_HOST:-root@84.38.65.246}"
THEEBIE_SITE_DIR="${THEEBIE_SITE_DIR:-/var/www/html/sites/roguelike}"

cd "$REPO_DIR"

ssh "$THEEBIE_HOST" "mkdir -p '$THEEBIE_SITE_DIR/devlog' '$THEEBIE_SITE_DIR/docs'"
rsync -az --delete "$REPO_DIR/site/devlog/" "$THEEBIE_HOST:$THEEBIE_SITE_DIR/devlog/"
rsync -az --delete "$REPO_DIR/site/docs/" "$THEEBIE_HOST:$THEEBIE_SITE_DIR/docs/"

echo "Synced devlog/docs to https://www.theebie.de/sites/roguelike/devlog/"
