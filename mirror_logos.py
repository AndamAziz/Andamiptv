#!/usr/bin/env python3
"""
mirror_logos.py - make live-channel logos visible in regions where imgur is blocked.

Problem: i.imgur.com answers "Content not viewable in your region" in some countries
(Kurdistan / Iraq included), so every live channel whose tvg-logo points at imgur shows
a purple placeholder in the app.

What this does (LIVE channels only - movies/series are never touched):
  1. For every live channel whose tvg-logo is on imgur, download the image once
     (small, 160px max, 8-bit PNG) into  logos/<imgur-id>.png  inside this repository.
  2. Rewrite that channel's tvg-logo to the raw.githubusercontent.com URL of the
     mirrored file (same host the playlist itself is served from).
  3. If a channel has NO logo at all, reuse the logo of a same-name channel in the
     playlist (exact normalised name match only; never fuzzy).

Safety:
  * Logos you set yourself (postimg, wikimedia, ...) are never changed.
  * A URL is only rewritten when its mirrored file exists and is a valid image.
  * Idempotent: running twice changes nothing the second time.
  * Only the tvg-logo="..." value is edited; every other byte of the line is kept.
  * --dry-run reports without writing.

Usage:
  python3 mirror_logos.py playlist.m3u [--dry-run] [--max-new N] [--workers N]
"""
import argparse
import io
import re
import sys
import time
import unicodedata
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAW_BASE = "https://raw.githubusercontent.com/AndamAziz/Andamiptv/main/logos/"
LOGO_RE = re.compile(r'tvg-logo="([^"]*)"')
IMGUR_RE = re.compile(r'^https?://(?:i\.)?imgur\.com/([A-Za-z0-9]+)\.(?:png|jpe?g|gif|webp)$', re.I)
MAX_SIDE = 160
MIN_BYTES = 200          # smaller than this is not a real logo
UA = "Mozilla/5.0 (compatible; AndamIPTV-logo-mirror)"


def is_vod(line):
    return 'tvg-type="movie"' in line or 'tvg-type="series"' in line


def norm(name):
    s = unicodedata.normalize("NFKD", name).lower()
    return re.sub(r"[^a-z0-9؀-ۿ]+", "", s)


def fetch(url, tries=4):
    delay = 2
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            if e.code == 429:
                time.sleep(delay * 3)
        except Exception:
            pass
        time.sleep(delay)
        delay *= 2
    return None


def to_small_png(data):
    """Return PNG bytes (<=256px) or None when the data is not a usable image."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.seek(0)
        im = im.convert("RGBA")
        if im.width < 8 or im.height < 8:
            return None
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        try:   # 8-bit palette keeps transparency and cuts the size ~4x
            im.quantize(256, method=Image.Quantize.FASTOCTREE).save(out, "PNG", optimize=True)
        except Exception:
            out = io.BytesIO()
            im.save(out, "PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return None


def mirror_one(img_id, url, logos_dir):
    target = logos_dir / f"{img_id}.png"
    if target.exists() and target.stat().st_size >= MIN_BYTES:
        return img_id, "have"
    data = fetch(url)
    if not data or len(data) < MIN_BYTES:
        return img_id, "missing"
    png = to_small_png(data)
    if not png:
        return img_id, "bad"
    target.write_bytes(png)
    return img_id, "new"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("playlist")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-new", type=int, default=0, help="download at most N new images (0 = all)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--logos-dir", default="logos")
    a = ap.parse_args()

    pl = Path(a.playlist)
    logos_dir = Path(a.logos_dir)
    logos_dir.mkdir(exist_ok=True)
    lines = pl.read_text(encoding="utf-8").split("\n")

    # ---- collect imgur logos of live channels
    todo = {}
    named_logo = {}      # normalised name -> a good (non-imgur) logo already in the playlist
    for l in lines:
        if not l.startswith("#EXTINF") or is_vod(l):
            continue
        m = LOGO_RE.search(l)
        url = m.group(1).strip() if m else ""
        name = l.rsplit(",", 1)[-1].strip()
        im = IMGUR_RE.match(url) if url else None
        if im:
            todo[im.group(1)] = url
        elif url:
            named_logo.setdefault(norm(name), url)

    ids = sorted(todo)
    if a.max_new:
        ids = [i for i in ids if not (logos_dir / f"{i}.png").exists()][: a.max_new] + \
              [i for i in ids if (logos_dir / f"{i}.png").exists()]
    print(f"live channels with an imgur logo: {len(todo)} unique images")

    stats = {"have": 0, "new": 0, "missing": 0, "bad": 0}
    if not a.dry_run:
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            for n, (img_id, st) in enumerate(ex.map(lambda i: mirror_one(i, todo[i], logos_dir), ids), 1):
                stats[st] += 1
                if n % 250 == 0:
                    print(f"  ...{n}/{len(ids)}  {stats}", flush=True)
    print("mirror:", stats)

    # ---- rewrite live lines
    out = []
    n_imgur = n_fill = n_keep = 0
    for l in lines:
        if l.startswith("#EXTINF") and not is_vod(l):
            m = LOGO_RE.search(l)
            url = m.group(1).strip() if m else ""
            name = l.rsplit(",", 1)[-1].strip()
            new = None
            im = IMGUR_RE.match(url) if url else None
            if im:
                f = logos_dir / f"{im.group(1)}.png"
                if f.exists() and f.stat().st_size >= MIN_BYTES:
                    new = RAW_BASE + f.name
                    n_imgur += 1
                else:
                    n_keep += 1
            elif m and not url:
                alt = named_logo.get(norm(name))
                if alt:
                    new = alt
                    n_fill += 1
            if new and m:
                l = l[:m.start(1)] + new + l[m.end(1):]
        out.append(l)

    print(f"imgur -> mirror: {n_imgur}   empty -> same-name logo: {n_fill}   imgur kept (no image): {n_keep}")
    if a.dry_run:
        return 0
    pl.write_text("\n".join(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
