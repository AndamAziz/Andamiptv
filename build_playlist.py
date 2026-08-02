#!/usr/bin/env python3
"""
M3U Playlist Cleaner & Organizer
پاکژکردنەوە و ڕێکخستنی خۆکاری پلەیلیستی M3U

Features:
- Blocklist filtering (skip channels containing blocked keywords)
- Automatic categorization via configurable keyword rules (categories.json)
- Duplicate stream removal (by URL)
- Channel name cleanup (removes quality tags like 1080p, HD, etc.)
- Correctly handles extra M3U tags between #EXTINF and the stream URL
  (#EXTVLCOPT, #KODIPROP, #EXTGRP, #EXTHTTP, etc.) instead of assuming
  the URL is always the very next line
- Sorts channels by category priority, optionally alphabetically within category
- Writes to a NEW output file by default (never silently overwrites your source)
- Detailed run report (counts + per-category breakdown) saved next to the output
"""

from __future__ import annotations

import os
import re
import json
import logging
import argparse
from datetime import datetime

# ==========================================
# Defaults (all overridable via CLI flags)
# ==========================================
DEFAULT_INPUT = "playlist.m3u"
DEFAULT_OUTPUT = "playlist_clean.m3u"
DEFAULT_BLOCKLIST_FILE = "blocklist.txt"
DEFAULT_CATEGORIES_FILE = "categories.json"

DEFAULT_CATEGORIES = {
    "Kurdish Channels": ["kurd", "rudaw", "nrt", "ava", "kurdistan", "k24", "gkurd", "zagros"],
    "Sky Channels": ["sky cinema", "sky history", "sky arts", "sky nature", "sky kids", "sky one", "sky two", "sky sports"],
    "Sports": ["bein", "ssc", "sport", "channellive", "bt sport", "espn"],
}

QUALITY_TAG_RE = re.compile(
    r'\[.*?\]|\(.*?\)|\b(1080p|720p|480p|HD|FHD|UHD|4K|HEVC|SD|60FPS|50FPS)\b',
    re.IGNORECASE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("m3u_cleaner")


def load_blocklist(filepath: str) -> list[str]:
    """Load blocked keywords, one per line. Lines starting with '#' are comments."""
    if not os.path.exists(filepath):
        log.warning(f"Blocklist file not found, continuing without one: {filepath}")
        return []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]


def load_categories(filepath: str) -> dict:
    """Load category -> keyword rules from JSON if present, else use built-in defaults."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            log.info(f"Loaded {len(data)} categories from {filepath}")
            return data
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Could not read {filepath} ({e}); using built-in defaults")
    return DEFAULT_CATEGORIES


def categorize_channel(extinf_line: str, categories: dict) -> str:
    extinf_lower = extinf_line.lower()
    for category, keywords in categories.items():
        if any(kw in extinf_lower for kw in keywords):
            return category
    return "Other"


def clean_name(extinf_line: str) -> str:
    """Strip quality/resolution tags and bracketed junk from the display name only."""
    if ',' not in extinf_line:
        return extinf_line
    meta, name = extinf_line.split(',', 1)
    cleaned = QUALITY_TAG_RE.sub('', name)
    cleaned = ' '.join(cleaned.split())
    if not cleaned:
        cleaned = name.strip()
    return f"{meta},{cleaned}\n"


def set_group_title(extinf_line: str, category: str) -> str:
    """Set/replace the group-title attribute without corrupting the duration field.

    (The original script's version did `line.replace("#EXTINF:", "#EXTINF:-1 group-title=...")`,
    which -- when a channel had NO existing group-title -- left the original duration value
    stuck right after the new one, e.g. `#EXTINF:-1 group-title="X"-1,Channel Name`. Splitting
    on the first comma and rebuilding avoids that.)
    """
    if ',' not in extinf_line:
        return extinf_line
    prefix, name = extinf_line.split(',', 1)
    if 'group-title="' in prefix:
        prefix = re.sub(r'group-title="[^"]*"', f'group-title="{category}"', prefix)
    else:
        prefix = f'{prefix} group-title="{category}"'
    return f'{prefix},{name}'


def parse_playlist(lines: list[str]):
    """
    Walk raw M3U lines and yield (extinf_line, extra_tag_lines, url_line).
    Correctly skips over #EXTVLCOPT / #KODIPROP / #EXTGRP / etc. lines some
    providers place between #EXTINF and the actual stream URL, and safely
    skips a malformed #EXTINF that has no URL instead of misreading the
    next channel's line as its URL.
    """
    i, n = 0, len(lines)
    while i < n:
        if lines[i].startswith("#EXTINF:"):
            extinf_line = lines[i]
            j = i + 1
            extras = []
            while j < n and lines[j].startswith("#") and not lines[j].startswith("#EXTINF:"):
                extras.append(lines[j])
                j += 1
            if j < n and lines[j].strip() and not lines[j].startswith("#"):
                yield extinf_line, extras, lines[j]
                i = j + 1
            else:
                log.warning(f"Line {i + 1}: #EXTINF with no following URL, skipped")
                i = j
        else:
            i += 1


def process_playlist(input_file: str, output_file: str, blocklist_file: str, categories_file: str, sort_alpha: bool):
    blocklist = load_blocklist(blocklist_file)
    categories = load_categories(categories_file)
    log.info(f"Blocked keywords loaded: {len(blocklist)}")

    if not os.path.exists(input_file):
        log.error(f"Input playlist not found: {input_file}")
        return

    with open(input_file, "r", encoding="utf-8-sig", errors="ignore") as f:
        lines = f.readlines()

    header = lines[0] if lines and lines[0].startswith("#EXTM3U") else "#EXTM3U\n"
    if not header.endswith("\n"):
        header += "\n"

    channels = []
    seen_urls = set()
    skipped_blocked = 0
    skipped_duplicates = 0
    skipped_malformed = 0

    for extinf_line, extras, url_line in parse_playlist(lines):
        extinf_lower = extinf_line.lower()
        clean_url = url_line.strip()

        if not clean_url.lower().startswith(("http://", "https://", "rtmp://", "rtsp://")):
            skipped_malformed += 1
            continue

        if any(kw in extinf_lower for kw in blocklist):
            skipped_blocked += 1
            continue

        if clean_url in seen_urls:
            skipped_duplicates += 1
            continue
        seen_urls.add(clean_url)

        category = categorize_channel(extinf_line, categories)
        if category != "Other":
            extinf_line = set_group_title(extinf_line, category)
        extinf_line = clean_name(extinf_line)

        channels.append({"extinf": extinf_line, "extras": extras, "url": url_line, "category": category})

    priority = {name: idx for idx, name in enumerate(categories.keys())}
    priority["Other"] = len(priority)

    def sort_key(ch):
        name_part = ch["extinf"].split(",", 1)[-1].strip().lower() if sort_alpha else ""
        return (priority.get(ch["category"], 999), name_part)

    channels.sort(key=sort_key)

    out_lines = [header]
    for ch in channels:
        out_lines.append(ch["extinf"])
        out_lines.extend(ch["extras"])
        out_lines.append(ch["url"])

    with open(output_file, "w", encoding="utf-8") as f:
        f.writelines(out_lines)

    by_cat: dict[str, int] = {}
    for ch in channels:
        by_cat[ch["category"]] = by_cat.get(ch["category"], 0) + 1

    report_path = os.path.splitext(output_file)[0] + "_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"M3U Cleaner report - {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"Source: {input_file}\nOutput: {output_file}\n\n")
        f.write(f"Total channels kept:  {len(channels)}\n")
        f.write(f"Blocked (blocklist):  {skipped_blocked}\n")
        f.write(f"Duplicates removed:   {skipped_duplicates}\n")
        f.write(f"Malformed/skipped:    {skipped_malformed}\n\n")
        for cat, count in sorted(by_cat.items(), key=lambda kv: priority.get(kv[0], 999)):
            f.write(f"  {cat}: {count}\n")

    log.info(f"Done. Kept {len(channels)} channels -> {output_file}")
    log.info(f"Blocked: {skipped_blocked} | Duplicates: {skipped_duplicates} | Malformed: {skipped_malformed}")
    log.info(f"Report written to {report_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Clean, categorize, and deduplicate an M3U playlist.")
    p.add_argument("-i", "--input", default=DEFAULT_INPUT, help=f"Input .m3u file (default: {DEFAULT_INPUT})")
    p.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help=f"Output .m3u file (default: {DEFAULT_OUTPUT})")
    p.add_argument("-b", "--blocklist", default=DEFAULT_BLOCKLIST_FILE, help=f"Blocklist file (default: {DEFAULT_BLOCKLIST_FILE})")
    p.add_argument("-c", "--categories", default=DEFAULT_CATEGORIES_FILE, help=f"Categories JSON file (default: {DEFAULT_CATEGORIES_FILE})")
    p.add_argument("--overwrite", action="store_true", help="Overwrite the input file in place (a .bak backup is made first)")
    p.add_argument("--sort-alpha", action="store_true", help="Sort channels alphabetically within each category")
    return p


def main():
    args = build_arg_parser().parse_args()
    output_file = args.input if args.overwrite else args.output

    if args.overwrite:
        backup = args.input + ".bak"
        try:
            with open(args.input, "r", encoding="utf-8-sig", errors="ignore") as src:
                content = src.read()
            with open(backup, "w", encoding="utf-8") as dst:
                dst.write(content)
            log.info(f"Backup of original saved to {backup}")
        except OSError as e:
            log.warning(f"Could not create backup ({e}); continuing anyway")

    process_playlist(args.input, output_file, args.blocklist, args.categories, args.sort_alpha)


if __name__ == "__main__":
    main()
