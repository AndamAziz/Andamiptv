#!/usr/bin/env bash
# Runs discover_movies.py from environment variables (used by the add-archive-movies workflow).
# APPLY=true writes to playlist.m3u (after validation); anything else is a report only (dry run).
set -euo pipefail
args=(--sources "${SOURCES:-internet_archive,wikimedia}" --max-items "${MAX_ITEMS:-20}"
      --primary-years "${PRIMARY_YEARS:-2}" --secondary-years "${SECONDARY_YEARS:-5}"
      --min-height "${MIN_HEIGHT:-1080}" --min-minutes "${MIN_MINUTES:-40}"
      --min-rating "${MIN_RATING:-0}" --min-votes "${MIN_VOTES:-0}" --group "${GROUP:-Recent Movies}")
[ -n "${QUERY:-}" ] && args+=(--query "$QUERY")
[ "${ALLOW_CC_BY:-false}" = "true" ] && args+=(--allow-cc-by)
[ "${ALLOW_WEBM:-false}" = "true" ] && args+=(--allow-webm)
[ "${APPLY:-false}" = "true" ] && args+=(--apply)
python discover_movies.py "${args[@]}"
