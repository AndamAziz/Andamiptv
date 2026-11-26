#!/usr/bin/env python3
"""
tmdb_poster_fill.py - a movie / series episode with an EMPTY tvg-logo and a TMDB id in its name
("Title {tmdb-1611767}") gets its poster from TMDB:
    https://media.themoviedb.org/t/p/w600_and_h900_face/<poster_path>.jpg
movie -> /movie/{id}, series episode -> the series poster /tv/{id}. Uses TMDB_API_KEY when set,
otherwise the TMDB web page. Only an empty logo is filled: a poster that is already there, names,
links and groups are never changed, nothing is removed.
Usage: python tmdb_poster_fill.py [playlist.m3u]
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import showtv_sync as ss  # noqa: E402

IMG = "https://media.themoviedb.org/t/p/w600_and_h900_face"
TMDB_RE = re.compile(r"\{tmdb-(\d+)\}")


def curl(url, timeout=30):
    try:
        return subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0", url],
                              capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""


def tmdb_poster(kind, tid):
    """Poster URL of /movie/{tid} or /tv/{tid}, or None."""
    key = os.environ.get("TMDB_API_KEY")
    if key:
        try:
            d = json.loads(curl(f"https://api.themoviedb.org/3/{kind}/{tid}?api_key={key}"))
            if d.get("id"):
                return IMG + d["poster_path"] if d.get("poster_path") else None
        except Exception:
            pass
    page = curl(f"https://www.themoviedb.org/{kind}/{tid}?language=en-US")
    m = re.search(r'<meta property="og:image" content="[^"]*/(?:w\d+|original|w\d+_and_h\d+_[a-z]+)(/[A-Za-z0-9]+\.(?:jpg|png))"', page) \
        or re.search(r"w600_and_h900_(?:face|bestv2)(/[A-Za-z0-9]+\.jpg)", page)
    return IMG + m.group(1) if m else None


def fill(text, poster_for=tmdb_poster, log=print):
    head, entries, trail = ss.split_entries(text)
    cache, changed = {}, 0
    for e in entries:
        kind = "movie" if 'tvg-type="movie"' in e[0] else "tv" if 'tvg-type="series"' in e[0] else ""
        if not kind or 'tvg-logo=""' not in e[0]:
            continue
        m = TMDB_RE.search(e[0].rsplit(",", 1)[-1])
        if not m:
            continue
        k = (kind, m.group(1))
        if k not in cache:
            cache[k] = poster_for(*k)
            if cache[k]:
                log(f"{kind}/{k[1]}: {cache[k]}")
        if cache[k]:
            e[0] = e[0].replace('tvg-logo=""', f'tvg-logo="{cache[k]}"', 1)
            changed += 1
    out = "\n".join(head + [x for e in entries for x in e]) + ("\n" if trail else "")
    return out, changed


def main(argv=None):
    path = Path((argv or sys.argv[1:] or ["playlist.m3u"])[0])
    out, n = fill(path.read_text(encoding="utf-8"))
    if n:
        path.write_text(out, encoding="utf-8")
    print(f"tmdb_poster_fill: {n} empty poster(s) filled from TMDB")


if __name__ == "__main__":
    main()
