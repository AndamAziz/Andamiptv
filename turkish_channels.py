#!/usr/bin/env python3
"""
turkish_channels.py - keep the official Turkish channels in the Turkey group alive and on top.

The list of channels lives in turkish-channels.json (order = order at the top of the group).
For every channel:
  * already in the Turkey group and its link plays (video + audio)  -> nothing changes
  * in the group but its link does not play -> look for another official link; replace the URL
    line only when the new link plays (name, logo, id are kept). No working link -> kept as is.
  * not in the group yet -> added only if an official link plays.
Then the listed channels are moved to the top of the Turkey group in the json order; every other
Turkey channel keeps its order below them. Nothing outside the Turkey group is touched and
nothing is ever deleted.

Where links come from (only hosts in allowed_hosts = the broadcasters' own servers / FAST partner):
  1. "urls" in the json   2. the broadcaster's live page ("page")   3. iptv-org's Turkey list
Links with a short-lived token (e=, st=, token=, expires=...) are never written: they stop
working within hours.

Usage:
  python turkish_channels.py playlist.m3u                 # report only
  python turkish_channels.py playlist.m3u --apply         # also rewrite playlist.m3u
"""
import argparse
import html
import json
import re
import subprocess
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True
import build_playlist as bp

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
IPTV_ORG = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/tr.m3u"
RAW_BASE = "https://raw.githubusercontent.com/AndamAziz/Andamiptv/main/"
TOKEN = re.compile(r"(?i)[?&](e|exp|expires|st|token|hdnts|hdntl|sig|signature|hash|md5|wmsauthsign)=")
M3U8 = re.compile(r"https?:(?:\\?/){2}[^\s\"'<>]+?\.m3u8[^\s\"'<>]*", re.I)


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def attr(line, key):
    m = re.search(key + r'="([^"]*)"', line)
    return m.group(1) if m else ""


def fetch(url, timeout=15):
    with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
        return r.read(2_000_000).decode("utf-8", "replace")


def host_ok(url, allowed):
    h = urlsplit(url).hostname or ""
    return any(h == a or h.endswith("." + a) for a in allowed)


def plays(url, timeout=45):
    """True when ffprobe reads a video AND an audio stream from the link."""
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-user_agent", UA, "-rw_timeout", "15000000",
                            "-show_entries", "stream=codec_type", "-of", "csv=p=0", url],
                           capture_output=True, text=True, timeout=timeout)
    except Exception:
        return False
    kinds = set(p.stdout.split())
    return "video" in kinds and "audio" in kinds


def page_links(page):
    try:
        t = html.unescape(fetch(page)).replace("\\u0026", "&").replace("\\/", "/")
    except Exception:
        return []
    out = []
    for u in M3U8.findall(t):
        u = u.replace("\\", "")
        if u not in out:
            out.append(u)
    return out


def iptv_org_links():
    links = {}
    try:
        lines = fetch(IPTV_ORG).split("\n")
    except Exception:
        return links
    for i, l in enumerate(lines):
        if l.startswith("#EXTINF"):
            j = i + 1
            while j < len(lines) and lines[j].startswith("#"):
                j += 1
            if j < len(lines) and lines[j].strip():
                cid = attr(l, "tvg-id").split("@")[0]
                links.setdefault(cid, []).append(lines[j].strip())
    return links


def parse(lines):
    """-> list of (start, end) line ranges, one per entry (EXTINF .. URL line inclusive)."""
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            j = i + 1
            while j < len(lines) and lines[j].startswith("#") and not lines[j].startswith("#EXTINF"):
                j += 1
            if j < len(lines):
                out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("playlist")
    ap.add_argument("--config", default="turkish-channels.json")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="turkish-channels-report.txt")
    ap.add_argument("--no-network-sources", action="store_true", help="only use the urls in the json")
    a = ap.parse_args()

    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    group, allowed = cfg["group"], cfg["allowed_hosts"]
    pl = Path(a.playlist)
    lines = pl.read_text(encoding="utf-8").split("\n")
    entries = parse(lines)
    live = [(s, e) for s, e in entries if 'tvg-type="' not in lines[s]]
    in_group = [(s, e) for s, e in live if attr(lines[s], "group-title") == group]
    if not in_group:
        print(f"group {group!r} not found - nothing to do")
        return 1

    # same-name live entries anywhere (to copy name/logo/id for a channel that is new to the group)
    by_name = {}
    for s, e in live:
        by_name.setdefault(norm(lines[s].rsplit(",", 1)[-1]), (s, e))

    org = {} if a.no_network_sources else iptv_org_links()

    # The nightly build (build_playlist.py) re-groups live channels by keyword. A channel is only
    # written into the group when the build will leave it there: either the same stream is also in
    # another group (a copy on purpose keeps its group) or the keyword rules give this group anyway.
    here = Path(a.config).resolve().parent
    cats = bp.load_categories(str(here / bp.DEFAULT_CATEGORIES_FILE))
    fallback = bp.load_fallback(str(here / bp.DEFAULT_FALLBACK_FILE))
    elsewhere = {bp.same_stream_key(lines[e].strip()) for s, e in live if attr(lines[s], "group-title") != group}

    def stays(ext, url):
        if bp.same_stream_key(url) in elsewhere:
            return True
        c = bp.categorize_channel(ext, cats, url)
        if c in (bp.UNCATEGORIZED_KEY, bp.REGROUP_KEY) and fallback:
            c2 = bp.categorize_channel(ext, fallback, url)
            c = c2 if c2 != bp.UNCATEGORIZED_KEY else c
        return c == group

    def candidates(ch, current):
        c = list(ch.get("urls", []))
        if ch.get("page") and not a.no_network_sources:
            c += page_links(ch["page"])
        c += org.get(ch.get("iptv_org", ""), [])
        out = []
        for u in c:
            if u != current and u not in out and host_ok(u, allowed) and not TOKEN.search(u):
                out.append(u)
        return out

    def work(ch):
        keys = {norm(n) for n in ch["names"]}
        mine = [(s, e) for s, e in in_group if norm(lines[s].rsplit(",", 1)[-1]) in keys]
        if mine:
            s, e = mine[0]
            cur = lines[e].strip()
            if plays(cur):
                return ch, mine, "ok", None
            for u in candidates(ch, cur):
                if plays(u):
                    return ch, mine, "replaced", u
            return ch, mine, "dead-kept", None
        for u in candidates(ch, None):
            if plays(u):
                return ch, mine, "added", u
        return ch, mine, "not-added", None

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(work, cfg["channels"]))

    # ---- build the new Turkey block
    top, used = [], set()
    rep = []
    for ch, mine, status, url in results:
        name = ch["names"][0]
        if status in ("ok", "dead-kept", "replaced"):
            s, e = mine[0]
            ent = lines[s:e + 1]
            if status == "replaced" and not stays(ent[0], url):
                status, url = "dead-kept", None     # the build would move the new link to another group
            if status == "replaced":
                ent = ent[:-1] + [url]
            top.append(ent)
            used.add((s, e))
            rep.append(f"{status:10} {name}" + (f"\n           old: {lines[e].strip()}\n           new: {url}" if url else ""))
        elif status == "added":
            src = by_name.get(norm(name)) or next((by_name[norm(n)] for n in ch["names"] if norm(n) in by_name), None)
            if src:     # same channel elsewhere in the playlist: copy its line, only the group changes
                ext = re.sub(r'group-title="[^"]*"', f'group-title="{group}"', lines[src[0]])
            else:
                logo = RAW_BASE + ch["logo"] if ch.get("logo") else ""
                ext = (f'#EXTINF:-1 tvg-name="{name}"tvg-id="{ch.get("id", "")}"tvg-logo="{logo}"'
                       f'tvg-chno=""group-title="{group}":http-referrer="",{name}')
            if not stays(ext, url):
                rep.append(f"{'not-added':10} {name}: plays, but the nightly build would move it to another group")
                continue
            top.append([ext, url])
            rep.append(f"{status:10} {name}\n           url: {url}")
        else:
            why = {"not-added": "no official link plays from here (geo-block / token-only) - not added",
                   "dead-kept": "does not play from here, no working official link - kept as is"}
            rep.append(f"{status:10} {name}: {why.get(status, '')}")
    rest = [lines[s:e + 1] for s, e in in_group if (s, e) not in used]

    new_block = [l for ent in top + rest for l in ent]
    first = in_group[0][0]
    # entries of the group are not always contiguous: rebuild by removing them and inserting the block
    out, inserted = [], False
    skip = set()
    for s, e in in_group:
        skip.update(range(s, e + 1))
    for k, l in enumerate(lines):
        if k == first and not inserted:
            out.extend(new_block)
            inserted = True
        if k in skip:
            continue
        out.append(l)

    from collections import Counter
    summary = dict(Counter(r.split()[0] for r in rep))
    head = f"Turkish channels: {summary}  (group {group!r}: {len(in_group)} -> {len(top) + len(rest)} entries)"
    report = head + "\n\n" + "\n".join(rep) + "\n"
    Path(a.report).write_text(report, encoding="utf-8")
    print(report)
    if a.apply and out != lines:
        pl.write_text("\n".join(out), encoding="utf-8")
        print("playlist updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
