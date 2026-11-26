#!/usr/bin/env python3
"""
season_fix.py - an episode added with its overall number (e.g. from the web form: season left at 1,
"Yeraltı {tmdb-309328} - S01E24") is renamed to its real season/episode from TMDB ("S02E08").

An episode newer than TMDB knows (TMDB has 16 + 8 episodes, "S01E25" is added) continues the last
season ("S02E09"), but only when the episode before it (S02E08) is in the playlist.

Only series that already use per-season numbering in the playlist (they have an episode in season 2
or later) are touched, and only an S01Exx entry whose number is beyond TMDB's season 1. Series that
use "S01 + overall number" stay as they are. Only the name changes (link, logo, group are kept),
never into a name that already exists; nothing is ever deleted.

Usage: python season_fix.py playlist.m3u [snapshot.m3u]   (writes the file when something was renamed)
       with a snapshot only entries that are not in it yet (new uploads / web form) are looked at.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import showtv_sync as ss  # noqa: E402


def curl(url, timeout=30):
    try:
        return subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0", url],
                              capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""


def season_counts(tid):
    """{season number: episode count} for seasons >= 1, from TMDB (API key if set, else the web page)."""
    key = os.environ.get("TMDB_API_KEY")
    if key:
        try:
            d = json.loads(curl(f"https://api.themoviedb.org/3/tv/{tid}?api_key={key}"))
            return {s["season_number"]: s["episode_count"] for s in d.get("seasons", [])
                    if s.get("season_number", 0) > 0 and s.get("episode_count")}
        except Exception:
            pass
    t = curl(f"https://www.themoviedb.org/tv/{tid}/seasons?language=en-US")
    out, cur = {}, None
    for m in re.finditer(rf'href="/tv/{tid}[^"]*/season/(\d+)\?language=en-US"|(\d+) Episodes?\b', t):
        if m.group(1):
            cur = int(m.group(1))
        elif cur:
            out.setdefault(cur, int(m.group(2)))
            cur = None
    return out


def fix(text, counts_for=season_counts, log=print, only=None):
    """only: set of entry names (EXTINF lines) to look at; None = all."""
    head, entries, trail = ss.split_entries(text)
    shows = {}
    for e in entries:
        k = ss.ep_key(e)
        if k and 'tvg-type="series"' in e[0]:
            shows.setdefault(k[0], []).append(e)
    names = {ss.ep_key(e) for e in entries if ss.ep_key(e)}
    changed = 0
    for show, eps in shows.items():
        m = re.search(r"\{tmdb-(\d+)\}", show)
        keys = [ss.ep_key(e) for e in eps]
        if not m or not any(k[1] >= 2 for k in keys):
            continue
        c, renamed = None, 0
        for e in sorted(eps, key=lambda e: ss.ep_key(e)[2]):   # lowest number first (continuation check)
            _, s, x = ss.ep_key(e)
            if s != 1 or (only is not None and e[0] not in only):
                continue
            if c is None:
                c = counts_for(m.group(1))
            if not c or x <= c.get(1, 10 ** 9):
                continue
            n, target = x, None
            for sn in sorted(c):                     # overall number -> (season, episode)
                if n <= c[sn]:
                    target = (sn, n)
                    break
                n -= c[sn]
            if not target and c:                     # newer than TMDB: continues the last season
                last = max(c)                        # (only right after an episode that is there)
                if (show, last, c[last] + n - 1) in names:
                    target = (last, c[last] + n)
            if not target or (show, *target) in names:
                continue
            old, new = f"{show} - S01E{x:02d}", f"{show} - S{target[0]:02d}E{target[1]:02d}"
            e[0] = e[0].replace(old, new)
            names.add((show, *target))
            changed += 1
            renamed += 1
            log(f"{old} -> {new}")
        if renamed:
            idx = [i for i, e in enumerate(entries) if (ss.ep_key(e) or ("",))[0] == show]
            if idx == list(range(idx[0], idx[-1] + 1)):
                entries[idx[0]:idx[-1] + 1] = sorted(entries[idx[0]:idx[-1] + 1], key=lambda e: ss.ep_key(e)[1:])
    out = "\n".join(head + [x for e in entries for x in e]) + ("\n" if trail else "")
    return out, changed


def main(argv=None):
    args = argv or sys.argv[1:] or ["playlist.m3u"]
    path = Path(args[0])
    text = path.read_text(encoding="utf-8")
    only = None
    if len(args) > 1 and Path(args[1]).exists():
        _, snap, _ = ss.split_entries(Path(args[1]).read_text(encoding="utf-8"))
        known = {e[0] for e in snap}
        _, cur, _ = ss.split_entries(text)
        only = {e[0] for e in cur if e[0] not in known}
    out, n = fix(text, only=only)
    if n:
        path.write_text(out, encoding="utf-8")
    print(f"season_fix: {n} episode(s) renamed")


if __name__ == "__main__":
    main()
