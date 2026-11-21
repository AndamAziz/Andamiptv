#!/usr/bin/env python3
"""
showtv_sync.py - keep the Show TV series of a playlist group complete, with official ciner links.

For every series in the group (default "Turkish Drama", entries named "Title {tmdb-ID} - SxxEyy"):
  1. find the series on showtv.com.tr (its search API, or an override in showtv-series.json);
     a series that is not a Show TV series is left alone;
  2. read the official episode list from the series page;
  3. for every episode:
       * already on vmcdn.ciner.com.tr                  -> nothing changes (no request made)
       * in the playlist with another link              -> the URL line is replaced by the official
                                                           ciner MP4 (highest quality that plays);
                                                           when none plays, the old link is KEPT
       * not in the playlist yet                        -> added with the same name format, poster
                                                           and group as the series' other episodes,
                                                           only when an official link plays
  4. the episodes of each series are put back in order (S, E); series keep their place.

Nothing is ever deleted. Only links on vmcdn.ciner.com.tr (Show TV's own server, no token) are written.
Episodes are numbered like the rest of the playlist: S01 + Show TV's absolute episode number.

Usage:
  python showtv_sync.py playlist.m3u                         # report only
  python showtv_sync.py playlist.m3u --apply                 # also rewrite playlist.m3u
  python showtv_sync.py playlist.m3u --apply --only "Muhtemel Aşk"
"""
import argparse
import html
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True

SITE = "https://www.showtv.com.tr"
CDN = "vmcdn.ciner.com.tr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NAME_RE = re.compile(r'tvg-name="(.*?) - S(\d+)E(\d+)"')
TMDB_RE = re.compile(r"\s*\{tmdb-\d+\}\s*$")
PAGE_RE = re.compile(r"^/(dizi|programlar)/tanitim/([a-z0-9-]+)/\d+$")
TITLE_SUFFIXES = ("", "sonbolum", "finalbolumu")


def key(s):
    s = unicodedata.normalize("NFKD", s.replace("ı", "i").replace("İ", "I"))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)).lower())


# ---------------------------------------------------------------- network (patched in tests)
def fetch(url, timeout=25, tries=3):
    for i in range(tries):
        try:
            with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def link_ok(url, timeout=25, tries=3):
    """True when the server answers with video bytes (a short network hiccup is retried)."""
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1023"})
            with urlopen(req, timeout=timeout) as r:
                if r.status in (200, 206) and len(r.read(1024)) > 0:
                    return True
        except Exception:
            pass
        if i < tries - 1:
            time.sleep(2 * (i + 1))
    return False


# ---------------------------------------------------------------- Show TV pages
def find_series_page(title, overrides):
    """Path of the series page (/dizi/tanitim/slug/id), or None when it is not a Show TV series."""
    if title in overrides:
        return overrides[title] or None
    try:
        items = json.loads(fetch(f"{SITE}/arama/oneriler?q={quote(title)}")).get("items", [])
    except Exception:
        return None
    want = {key(title) + s for s in TITLE_SUFFIXES}
    for it in items:
        if PAGE_RE.match(it.get("url", "")) and key(it.get("title", "")) in want:
            return it["url"]
    return None


def episode_list(page_html, page_path):
    """{episode number: episode page path} from the series page's episode selector."""
    kind, slug = PAGE_RE.match(page_path).groups()
    sub = "dizi/tum_bolumler" if kind == "dizi" else "programlar/videolar"
    rx = re.compile(rf'/{sub}/{re.escape(slug)}-sezon-\d+-bolum-(\d+)-izle/\d+')
    eps = {}
    for m in rx.finditer(page_html):
        eps.setdefault(int(m.group(1)), m.group(0))
    return eps


def episode_mp4s(page_html):
    """MP4 links of the page's main player, best quality first."""
    t = html.unescape(page_html)
    m = re.search(r'"mp4"\s*:\s*(\[.*?\])', t, re.S)
    if not m:
        return []
    try:
        srcs = json.loads(m.group(1))
    except ValueError:
        return []
    def q(s):
        n = re.search(r"\d+", s.get("label", ""))
        return int(n.group()) if n else 0
    return [s["src"] for s in sorted(srcs, key=q, reverse=True) if CDN in s.get("src", "")]


# ---------------------------------------------------------------- playlist
def split_entries(text):
    lines = text.split("\n")
    trail = text.endswith("\n")
    if trail:
        lines = lines[:-1]
    head, entries, cur = [], [], None
    for ln in lines:
        if ln.startswith("#EXTINF"):
            cur = [ln]
            entries.append(cur)
        elif cur is None:
            head.append(ln)
        else:
            cur.append(ln)
    return head, entries, trail


def group_of(e):
    m = re.search(r'group-title="([^"]*)"', e[0])
    return m.group(1) if m else ""


def ep_key(e):
    m = NAME_RE.search(e[0])
    return (m.group(1), int(m.group(2)), int(m.group(3))) if m else None


def sync(text, group, overrides, only=None, pause=0.3, log=print):
    head, entries, trail = split_entries(text)
    idx = [i for i, e in enumerate(entries) if group_of(e) == group and 'tvg-type="series"' in e[0] and ep_key(e)]
    if not idx:
        return text, {}
    if idx != list(range(idx[0], idx[-1] + 1)):
        raise SystemExit(f'group "{group}" is not one block in the playlist; not touching it')
    block = [entries[i] for i in idx]
    shows = list(dict.fromkeys(ep_key(e)[0] for e in block))
    stats = {"replaced": 0, "added": 0, "kept_no_link": 0, "missing_no_link": 0}
    for show in shows:
        title = TMDB_RE.sub("", show)
        if only and title not in only and show not in only:
            continue
        page = find_series_page(title, overrides)
        if not page:
            log(f"- {title}: not a Show TV series, left as is")
            continue
        try:
            eps = episode_list(fetch(SITE + page), page)
        except Exception as ex:
            log(f"- {title}: series page failed ({ex}), left as is")
            continue
        mine = {ep_key(e)[2]: e for e in block if ep_key(e)[0] == show}
        template = next(iter(mine.values()))
        season = ep_key(template)[1]
        done = []
        for n in sorted(eps):
            cur = mine.get(n)
            if cur is not None and CDN in cur[-1]:
                continue
            time.sleep(pause)
            try:
                links = episode_mp4s(fetch(SITE + eps[n]))
            except Exception:
                links = []
            good = next((u for u in links if link_ok(u)), None)
            if cur is not None:
                if good:
                    cur[-1] = good
                    stats["replaced"] += 1
                    done.append(f"E{n} link->ciner")
                else:
                    stats["kept_no_link"] += 1
                    done.append(f"E{n} kept (no official link plays)")
            elif good:
                old = f"{show} - S{season:02d}E{ep_key(template)[2]:02d}"
                new = f"{show} - S{season:02d}E{n:02d}"
                block.append([template[0].replace(old, new), good])
                stats["added"] += 1
                done.append(f"E{n} added")
            else:
                stats["missing_no_link"] += 1
                done.append(f"E{n} missing (no official link plays)")
        log(f"- {title}: {len(eps)} episodes on Show TV" + (": " + ", ".join(done) if done else ", all up to date"))
    order = {s: i for i, s in enumerate(shows)}
    block.sort(key=lambda e: (order[ep_key(e)[0]], ep_key(e)[1], ep_key(e)[2]))
    entries[idx[0]:idx[-1] + 1] = block
    out = "\n".join(head + [x for e in entries for x in e]) + ("\n" if trail else "")
    return out, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("playlist")
    ap.add_argument("--group", default="Turkish Drama")
    ap.add_argument("--config", default=str(Path(__file__).with_name("showtv-series.json")))
    ap.add_argument("--only", action="append", help="limit to this series title (repeatable)")
    ap.add_argument("--apply", action="store_true", help="rewrite the playlist")
    ap.add_argument("--report", help="also write the report to this file")
    ap.add_argument("--pause", type=float, default=0.3, help="seconds between episode page requests")
    a = ap.parse_args(argv)
    overrides = {}
    if Path(a.config).exists():
        overrides = json.loads(Path(a.config).read_text(encoding="utf-8")).get("series", {})
    lines = []
    def log(s):
        print(s)
        lines.append(s)
    text = Path(a.playlist).read_text(encoding="utf-8")
    out, stats = sync(text, a.group, overrides, set(a.only or []) or None, a.pause, log)
    log(f"Summary: {stats}")
    if a.apply and out != text:
        Path(a.playlist).write_text(out, encoding="utf-8")
        log("playlist updated")
    elif not a.apply:
        log("report only (use --apply to write)")
    if a.report:
        Path(a.report).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
