#!/usr/bin/env bash
# publish-wiki.sh — push wiki/*.md to the GitHub wiki in one command.
#
# GitHub has no wiki REST/GraphQL API, but each repo's wiki IS a git repo:
#   https://github.com/<owner>/<repo>.wiki.git
# The remote only exists AFTER one page has been created once via the web UI
# ("Create first page" on the Wiki tab). This script fails with instructions
# until that one-time click has happened.
#
# Usage: ./scripts/publish-wiki.sh [owner/repo]
set -euo pipefail
SLUG="${1:-Shuvam-Banerji-Seal/opngx}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$HERE/wiki"
WT="$(mktemp -d /tmp/opngx-wiki.XXXXXX)"
trap 'rm -rf "$WT"' EXIT

git clone "https://github.com/${SLUG}.wiki.git" "$WT/w" 2>/dev/null \
  || { echo "wiki remote not found."
       echo "One-time step: open https://github.com/${SLUG}/wiki and create"
       echo "any page via the web UI; then re-run this script."; exit 1; }

cp "$SRC"/*.md "$WT/w/"
git -C "$WT/w" add -A
if git -C "$WT/w" diff --cached --quiet; then
  echo "wiki already up to date"; exit 0
fi
git -C "$WT/w" -c user.name=opngx -c user.email=opngx@users.noreply.github.com \
  commit -m "sync pages from repo ($(date -u +%F))"
git -C "$WT/w" push origin master 2>/dev/null || git -C "$WT/w" push origin main
echo "published: $(ls "$SRC" | tr '\n' ' ')"
