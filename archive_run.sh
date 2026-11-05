#!/usr/bin/env bash
# Runs archive_add.py from environment variables (used by the add-archive-movies workflow).
# APPLY=true writes to playlist.m3u; anything else is a report only.
set -euo pipefail
args=(--collection "${COLLECTION:-feature_films}" --max-items "${MAX_ITEMS:-10}" --min-downloads "${MIN_DOWNLOADS:-2000}"
      --group "${GROUP:-Free Classics}" --min-height "${MIN_HEIGHT:-1080}" --min-minutes "${MIN_MINUTES:-40}")
[ -n "${QUERY:-}" ] && args+=(--query "$QUERY")
[ "${INCLUDE_PRE1930:-false}" = "true" ] && args+=(--include-pre1930)
[ "${ALLOW_CC_BY:-false}" = "true" ] && args+=(--allow-cc-by)
[ "${APPLY:-false}" = "true" ] && args+=(--apply)
python archive_add.py "${args[@]}"
