#!/usr/bin/env python3
"""
fix_m3u_logos.py
-----------------
Auto-fills missing/broken tvg-logo attributes in an M3U playlist using the
public iptv-org channel + logo database (https://github.com/iptv-org/database).

Usage:
    pip install requests
    python3 fix_m3u_logos.py playlist.m3u

Optional flags:
    -o, --output PATH        write to a different file (default: overwrite input, backup made automatically)
    -t, --threshold FLOAT    fuzzy name-match confidence 0-1 (default 0.82)
    --verify-existing        HEAD-check existing tvg-logo URLs and replace broken ones too (slower, needs internet)
    --report PATH            where to write the list of channels that could NOT be matched (default: missing_logos.txt)

What it does:
    1. Downloads channels.json + logos.json from iptv-org's API.
    2. Parses every #EXTINF line in your playlist.
    3. For channels with empty tvg-logo (or, with --verify-existing, a dead logo URL),
       tries to match by tvg-id first, then by fuzzy name match against iptv-org's
       channel names/alt_names.
    4. Writes the fixed playlist + a report of anything it couldn't match (fix those manually).
"""

import argparse
import difflib
import json
import re
import shutil
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run: pip install requests")

CHANNELS_URL = "https://iptv-org.github.io/api/channels.json"
LOGOS_URL = "https://iptv-org.github.io/api/logos.json"

EXTINF_RE = re.compile(r'^#EXTINF:(?P<duration>-?\d+)(?P<attrs>.*?),(?P<name>.*)$')
ATTR_RE = re.compile(r'([a-zA-Z0-9\-]+)="([^"]*)"')

JUNK_WORDS = {
    "hd", "fhd", "uhd", "4k", "sd", "tv", "channel", "live", "backup",
    "official", "asia", "europe", "east", "west", "feed",
}


def normalize(name: str) -> str:
    """Lowercase, strip diacritics/punctuation/junk words for fuzzy matching."""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[^a-zA-Z0-9\s]", " ", name)
    words = [w for w in name.lower().split() if w not in JUNK_WORDS]
    return " ".join(words).strip()


def fetch_json(url: str, cache_path: Path):
    """Download JSON, with a local cache fallback if the request fails."""
    try:
        print(f"Downloading {url} ...")
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        cache_path.write_text(json.dumps(data))
        return data
    except Exception as e:
        if cache_path.exists():
            print(f"  Warning: download failed ({e}), using local cache {cache_path}")
            return json.loads(cache_path.read_text())
        raise


def build_indexes(channels, logos):
    """Return (name_index: normalized_name -> channel_id, id_to_logo: channel_id -> logo_url)."""
    name_index = {}
    for ch in channels:
        candidates = [ch.get("name", "")] + ch.get("alt_names", [])
        for cand in candidates:
            norm = normalize(cand)
            if norm:
                name_index.setdefault(norm, ch["id"])

    id_to_logo = {}
    for entry in logos:
        if not entry.get("in_use", True):
            continue
        cid = entry.get("channel")
        if not cid or cid in id_to_logo:
            continue
        id_to_logo[cid] = entry.get("url")

    return name_index, id_to_logo


def find_logo_for_channel(tvg_id, channel_name, name_index, id_to_logo, threshold):
    # 1. Direct tvg-id match
    if tvg_id and tvg_id in id_to_logo:
        return id_to_logo[tvg_id], "tvg-id"

    # 2. Exact normalized-name match
    norm = normalize(channel_name)
    if norm in name_index:
        cid = name_index[norm]
        if cid in id_to_logo:
            return id_to_logo[cid], "exact-name"

    # 3. Fuzzy name match
    if norm:
        best = difflib.get_close_matches(norm, name_index.keys(), n=1, cutoff=threshold)
        if best:
            cid = name_index[best[0]]
            if cid in id_to_logo:
                return id_to_logo[cid], f"fuzzy:{best[0]}"

    return None, None


def head_ok(url, timeout=6):
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            r = requests.get(url, timeout=timeout, stream=True)
        return r.status_code < 400
    except Exception:
        return False


def parse_playlist(lines):
    """Return list of entries: dicts with extinf_line_idx, attrs, name, url_line_idx."""
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        m = EXTINF_RE.match(line)
        if m:
            attrs = dict(ATTR_RE.findall(m.group("attrs")))
            name = m.group("name").strip()
            # find the following non-comment stream URL line
            url_idx = i + 1
            while url_idx < len(lines) and lines[url_idx].startswith("#"):
                url_idx += 1
            entries.append({
                "extinf_idx": i,
                "attrs": attrs,
                "name": name,
                "url_idx": url_idx if url_idx < len(lines) else None,
            })
        i += 1
    return entries


def rebuild_extinf_line(original_line, attrs, name, duration="-1"):
    attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f"#EXTINF:{duration} {attr_str},{name}"


def main():
    ap = argparse.ArgumentParser(description="Fix missing/broken tvg-logo entries in an M3U playlist using iptv-org data.")
    ap.add_argument("playlist", help="Path to playlist.m3u")
    ap.add_argument("-o", "--output", help="Output path (default: overwrite input; a .bak backup is made first)")
    ap.add_argument("-t", "--threshold", type=float, default=0.82, help="Fuzzy match cutoff 0-1 (default 0.82)")
    ap.add_argument("--verify-existing", action="store_true", help="Also HEAD-check existing tvg-logo URLs and replace dead ones")
    ap.add_argument("--report", default="missing_logos.txt", help="File to list unmatched channels")
    ap.add_argument("--cache-dir", default=".iptv_org_cache", help="Where to cache the downloaded iptv-org JSON")
    args = ap.parse_args()

    playlist_path = Path(args.playlist)
    if not playlist_path.exists():
        sys.exit(f"File not found: {playlist_path}")

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(exist_ok=True)

    channels = fetch_json(CHANNELS_URL, cache_dir / "channels.json")
    logos = fetch_json(LOGOS_URL, cache_dir / "logos.json")
    name_index, id_to_logo = build_indexes(channels, logos)
    print(f"Loaded {len(channels)} channels / {len(id_to_logo)} logos from iptv-org.")

    lines = playlist_path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    entries = parse_playlist(lines)
    print(f"Found {len(entries)} channel entries in playlist.")

    # Decide which entries need a logo lookup
    to_check = []
    for e in entries:
        logo = e["attrs"].get("tvg-logo", "").strip()
        if not logo:
            to_check.append(e)
        elif args.verify_existing:
            e["_existing_logo"] = logo
            to_check.append(e)

    if args.verify_existing:
        print(f"Verifying {sum(1 for e in to_check if e['attrs'].get('tvg-logo'))} existing logo URLs (this can take a while)...")
        broken = set()
        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = {}
            for e in to_check:
                url = e["attrs"].get("tvg-logo", "").strip()
                if url:
                    futures[pool.submit(head_ok, url)] = e["extinf_idx"]
            for fut in as_completed(futures):
                idx = futures[fut]
                if not fut.result():
                    broken.add(idx)
        to_check = [e for e in to_check if not e["attrs"].get("tvg-logo") or e["extinf_idx"] in broken]
        print(f"  {len(broken)} existing logo URLs are dead.")

    fixed, unmatched = 0, []
    for e in to_check:
        tvg_id = e["attrs"].get("tvg-id", "").strip()
        logo_url, method = find_logo_for_channel(tvg_id, e["name"], name_index, id_to_logo, args.threshold)
        if logo_url:
            e["attrs"]["tvg-logo"] = logo_url
            lines[e["extinf_idx"]] = rebuild_extinf_line(lines[e["extinf_idx"]], e["attrs"], e["name"]) + "\n"
            fixed += 1
        else:
            unmatched.append(e["name"])

    out_path = Path(args.output) if args.output else playlist_path
    if out_path == playlist_path:
        backup_path = playlist_path.with_suffix(playlist_path.suffix + ".prelogo.bak")
        shutil.copy2(playlist_path, backup_path)
        print(f"Backup written to {backup_path}")

    out_path.write_text("".join(lines), encoding="utf-8")
    Path(args.report).write_text("\n".join(sorted(set(unmatched))), encoding="utf-8")

    print("\n----- Summary -----")
    print(f"Logos fixed:        {fixed}")
    print(f"Still unmatched:    {len(unmatched)}  (see {args.report})")
    print(f"Playlist written to {out_path}")


if __name__ == "__main__":
    main()
