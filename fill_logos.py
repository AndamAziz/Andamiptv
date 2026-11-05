#!/usr/bin/env python3
"""
fill_logos.py - find a REAL logo for live channels that have none.

Only LIVE channels with an empty tvg-logo are considered; movies/series and every
channel that already has a logo are never touched. Matching is exact on purpose:
a missing logo is better than a wrong one.

Sources, in order (first hit wins):
  1. same normalised name elsewhere in the playlist (already done by mirror_logos.py)
  2. Xumo: the channel id inside the stream URL (xumo_channelId=...) is the id of its
     logo on image.xumo.com                                   -> verified to return an image
  3. tv-logo/tv-logos (public GitHub repo, local clone via --tvlogos DIR): exact
     normalised name; ignored when two different files match
  4. iptv-org database (channels.json + logos.json via --iptv-org-dir DIR): ONLY when the
     playlist's tvg-id (Name.cc@Feed) is an iptv-org channel id. Name-only matches are not
     used: generic names (Classic TV, Zed TV...) matched the wrong channel.

Every logo found is saved to logos/ (160px, 8-bit PNG) and the playlist points at
raw.githubusercontent.com/AndamAziz/Andamiptv/main/logos/<file>, like mirror_logos.py.
A report (logo-fill-report.txt) lists what was filled, from where, and what is still empty.
"""
import argparse
import collections
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import mirror_logos as ml

LOGO_RE = ml.LOGO_RE


def build_tvlogos_index(root):
    idx = collections.defaultdict(set)
    for sub in ("countries", "misc"):
        for d, _, fs in os.walk(os.path.join(root, sub)):
            for f in fs:
                if not f.endswith(".png"):
                    continue
                stem = re.sub(r"-(hd|sd)$", "", f[:-4])
                if sub == "countries":
                    stem = re.sub(r"-[a-z]{2}$", "", stem)
                idx[ml.norm(stem)].add(os.path.join(d, f))
    return idx


def build_iptvorg_index(root):
    ch = json.load(open(os.path.join(root, "channels.json"), encoding="utf-8"))
    lg = json.load(open(os.path.join(root, "logos.json"), encoding="utf-8"))
    logo = {}
    for l in lg:
        logo.setdefault(l["channel"], l["url"])
    by_name = collections.defaultdict(set)
    for c in ch:
        if c["id"] in logo:
            for nm in [c["name"]] + (c.get("alt_names") or []):
                by_name[ml.norm(nm)].add(logo[c["id"]])
    return logo, by_name


def save_png(data, dest):
    png = ml.to_small_png(data)
    if not png or len(png) < ml.MIN_BYTES:
        return False
    dest.write_bytes(png)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("playlist")
    ap.add_argument("--tvlogos", help="local clone of tv-logo/tv-logos")
    ap.add_argument("--iptv-org-dir", help="folder with iptv-org channels.json and logos.json")
    ap.add_argument("--logos-dir", default="logos")
    ap.add_argument("--report", default="logo-fill-report.txt")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    logos_dir = Path(a.logos_dir)
    logos_dir.mkdir(exist_ok=True)
    pl = Path(a.playlist)
    lines = pl.read_text(encoding="utf-8").split("\n")

    tv = build_tvlogos_index(a.tvlogos) if a.tvlogos else {}
    io_logo, io_name = build_iptvorg_index(a.iptv_org_dir) if a.iptv_org_dir else ({}, {})

    filled, empty = [], []
    for i, l in enumerate(lines):
        if not l.startswith("#EXTINF") or ml.is_vod(l):
            continue
        m = LOGO_RE.search(l)
        if not m or m.group(1).strip():
            continue
        name = l.rsplit(",", 1)[-1].strip()
        key = ml.norm(name)
        stream = lines[i + 1] if i + 1 < len(lines) else ""
        tid = (re.search(r'tvg-id="([^"]*)"', l) or [None, ""])[1]
        new, src = None, None

        # 2. Xumo id from the stream URL
        x = re.search(r"xumo_channelId=(\d+)", stream)
        if x:
            f = logos_dir / f"xumo-{x.group(1)}.png"
            if f.exists():
                new, src = f.name, "xumo"
            elif not a.dry_run:
                data = ml.fetch(f"https://image.xumo.com/v1/channels/channel/{x.group(1)}/300x300.webp?type=color_onBlack", tries=2)
                if data and save_png(data, f):
                    new, src = f.name, "xumo"

        # 3. tv-logos, exact + unambiguous
        if not new and key and len(tv.get(key, ())) == 1:
            p = next(iter(tv[key]))
            f = logos_dir / ("tvl-" + re.sub(r"[^a-z0-9]+", "-", os.path.basename(p)[:-4].lower()).strip("-") + ".png")
            if f.exists():
                new, src = f.name, "tv-logos"
            elif not a.dry_run and save_png(open(p, "rb").read(), f):
                new, src = f.name, "tv-logos"

        # 4. iptv-org, by tvg-id then exact name
        if not new:
            url = None
            cid = tid.split("@")[0] if tid else ""
            if cid and cid in io_logo:
                url = io_logo[cid]
            if url:
                f = logos_dir / ("io-" + re.sub(r"[^a-z0-9]+", "-", key)[:60] + ".png")
                if f.exists():
                    new, src = f.name, "iptv-org"
                elif not a.dry_run:
                    data = ml.fetch(url, tries=2)
                    if data and save_png(data, f):
                        new, src = f.name, "iptv-org"

        if new:
            filled.append((name, src, new))
            if not a.dry_run:
                lines[i] = l[:m.start(1)] + ml.RAW_BASE + new + l[m.end(1):]
        else:
            empty.append(name)

    by_src = collections.Counter(s for _, s, _ in filled)
    summary = f"filled {len(filled)} {dict(by_src)}; still without a logo: {len(empty)}"
    print(summary)
    rep = [summary, "", "FILLED (name | source | file)"]
    rep += [f"{n} | {s} | {f}" for n, s, f in filled]
    rep += ["", "STILL EMPTY (needs a logo link from you)"] + sorted(set(empty))
    if not a.dry_run:
        pl.write_text("\n".join(lines), encoding="utf-8")
        Path(a.report).write_text("\n".join(rep) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
