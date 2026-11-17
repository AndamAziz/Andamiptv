#!/usr/bin/env python3
"""
find_master_links.py - for LIVE channels, replace a single-quality HLS link with its MASTER link
when the server has one (adaptive quality: the player picks the best quality the connection allows).

For every live channel whose URL is an HLS *media* playlist (it lists segments, not qualities):
  1. build a few candidate master URLs from the link itself, e.g.
       .../tracks-v1a1/mono.ts.m3u8   -> .../index.m3u8          (Flussonic)
       .../playlist480p.m3u8          -> .../playlist.m3u8       (Amagi, quality suffix removed)
       .../1280x720_2657600/index.m3u8-> .../playlist.m3u8       (parent folder)
       .../chunks.m3u8 / chunklist_*  -> .../playlist.m3u8       (Nimble / Wowza)
  2. a candidate is accepted ONLY if it is a real master playlist (#EXT-X-STREAM-INF) AND one of its
     qualities is the channel's current link (same URL, or for Wowza the same folder + chunklist).
     So the master always contains the stream that already works.
If no candidate passes, the link stays exactly as it is. Movies/series are never touched.
Name, logo, group and position are never changed; only the URL line.

Usage:
  python find_master_links.py playlist.m3u              # dry run: report only
  python find_master_links.py playlist.m3u --apply      # also rewrite playlist.m3u (+ --snapshot)
"""
import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36"
MASTER_NAMES = ("index.m3u8", "playlist.m3u8", "master.m3u8")
QUALITY = re.compile(r"(?i)[_-]?(?:\d{3,4}p|\d{3,4}x\d{3,4}(?:_\d+)?|hd|sd|fhd|uhd|low|mid|high)(?=\.m3u8$)")


def fetch(url, timeout):
    req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urlopen(req, timeout=timeout) as r:
        data = r.read(512 * 1024)
        if data[:2] == b"\x1f\x8b":
            import gzip
            try:
                data = gzip.decompress(data)
            except Exception:
                import zlib
                data = zlib.decompressobj(31).decompress(data)
        return data.decode("utf-8-sig", "replace"), r.geturl()


def is_master(text):
    return "#EXT-X-STREAM-INF" in text


def variants(text, base):
    out, lines = [], [l.strip() for l in text.splitlines() if l.strip()]
    for i, l in enumerate(lines):
        if l.startswith("#EXT-X-STREAM-INF"):
            nxt = next((x for x in lines[i + 1:] if not x.startswith("#")), None)
            if nxt:
                out.append(urljoin(base, nxt))
    return out


def no_query(u):
    p = urlsplit(u)
    return urlunsplit((p.scheme, p.netloc.lower(), p.path, "", ""))


def candidates(url):
    p = urlsplit(url)
    path, q = p.path, p.query
    folder, name = path.rsplit("/", 1)
    parent = folder.rsplit("/", 1)[0] if "/" in folder.strip("/") else folder
    cands = []
    stripped = QUALITY.sub("", name)
    if stripped != name and stripped.endswith(".m3u8"):
        cands.append(f"{folder}/{stripped}")
    if name.lower() in ("chunks.m3u8",) or name.lower().startswith("chunklist"):
        cands.append(f"{folder}/playlist.m3u8")
    for n in MASTER_NAMES:
        if n != name.lower():
            cands.append(f"{folder}/{n}")
    if parent != folder:
        for n in MASTER_NAMES:
            cands.append(f"{parent}/{n}")
    seen, out = set(), []
    for c in cands:
        for qq in ((q, "") if q else ("",)):
            u = urlunsplit((p.scheme, p.netloc, c, qq, ""))
            if u not in seen and no_query(u) != no_query(url):
                seen.add(u)
                out.append(u)
    return out[:10]


def contains(master_variants, url):
    key = no_query(url)
    folder = key.rsplit("/", 1)[0]
    name = key.rsplit("/", 1)[1].lower()
    for v in master_variants:
        vk = no_query(v)
        if vk == key:
            return True
        if name.startswith("chunklist") and vk.rsplit("/", 1)[0] == folder and vk.rsplit("/", 1)[1].lower().startswith("chunklist"):
            return True
    return False


def check(url, timeout):
    """-> (status, master_url or None, info)"""
    try:
        text, final = fetch(url, timeout)
    except Exception as e:
        return "unreachable", None, type(e).__name__
    if not text.lstrip().startswith("#EXTM3U"):
        return "not-hls", None, ""
    if is_master(text):
        return "already-master", None, ""
    for c in candidates(url):
        try:
            mt, mfinal = fetch(c, timeout)
        except Exception:
            continue
        if mt.lstrip().startswith("#EXTM3U") and is_master(mt):
            vs = variants(mt, mfinal)
            if contains(vs, url) or contains(vs, final):
                return "found", c, f"{len(vs)} qualit{'y' if len(vs) == 1 else 'ies'}"
    return "no-master", None, ""


def entries(lines):
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            j = i + 1
            while j < len(lines) and lines[j].startswith("#") and not lines[j].startswith("#EXTINF"):
                j += 1
            if j < len(lines):
                yield i, j
            i = j + 1
        else:
            i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("playlist")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--snapshot", default="library/playlist.snapshot.m3u")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--timeout", type=float, default=8)
    ap.add_argument("--report", default="master-links-report.txt")
    a = ap.parse_args()

    pl = Path(a.playlist)
    lines = pl.read_text(encoding="utf-8").split("\n")
    urls = []
    for i, j in entries(lines):
        if 'tvg-type="' in lines[i]:
            continue                                  # movies / series: never touched
        u = lines[j].strip()
        if ".m3u8" in u.lower() and u not in urls:
            urls.append(u)
    print(f"live HLS links to check: {len(urls)}", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = dict(zip(urls, ex.map(lambda u: check(u, a.timeout), urls)))
    found = {u: r[1] for u, r in res.items() if r[0] == "found"}
    from collections import Counter
    print("result:", dict(Counter(r[0] for r in res.values())), f"({time.time() - t0:.0f}s)")

    names = {}
    for i, j in entries(lines):
        if lines[j].strip() in found:
            names.setdefault(lines[j].strip(), lines[i].rsplit(",", 1)[-1].strip())
    rep = [f"master links found: {len(found)} (live HLS links checked: {len(urls)})", ""]
    rep += [f"{names.get(u, '?')}\n  old: {u}\n  new: {m}  [{res[u][2]}]" for u, m in found.items()]
    Path(a.report).write_text("\n".join(rep) + "\n", encoding="utf-8")
    for line in rep[:40]:
        print(line)

    if a.apply and found:
        for path in (pl, Path(a.snapshot)):
            if not path.exists():
                continue
            ls = path.read_text(encoding="utf-8").split("\n")
            for i, j in entries(ls):
                if 'tvg-type="' not in ls[i] and ls[j].strip() in found:
                    ls[j] = found[ls[j].strip()]
            path.write_text("\n".join(ls), encoding="utf-8")
        print(f"applied {len(found)} replacement(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
