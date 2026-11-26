#!/usr/bin/env python3
"""
vod_group_fix.py - a NEW movie / series episode (its link is not in the snapshot yet, e.g. added with
the web form) whose group-title is not a real group of the playlist ("Kurdish Drama", "Movies", empty,
"KURDI" ...) gets the right group:

  * an episode of a series that is already in the playlist -> the group of that series' episodes
    (also when another group was typed: one series name in two groups splits it in the app);
  * a brand-new series -> from TMDB: Documentary Series / Kids Series / Animation Series, or by
    original language Turkish Drama / Arabic Drama / Korean Drama / Asian Drama, else Foreign Series;
    a name with a Kurdish part ("English _ Kurdish {tmdb-ID}") -> KURDISH-دۆبلاژ;
  * a movie -> FARSI / KURDISH-ژێرنوس / KURDISH-دۆبلاژ when the typed group says so (or the name has a
    Kurdish part), else its first TMDB genre (Action, Drama ...) when that group exists.

Only group-title changes (name, link, logo are kept); nothing is ever deleted. When TMDB gives no
answer the entry is left as it is.
Usage: python vod_group_fix.py playlist.m3u [snapshot.m3u]
"""
import html
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
import showtv_sync as ss  # noqa: E402

KURDISH_DUB, KURDISH_SUB, FARSI = "KURDISH-دۆبلاژ", "KURDISH-ژێرنوس", "FARSI"
ASIAN = {"ja", "zh", "cn", "th", "vi", "id", "ms", "tl", "hi", "ta", "te", "ur", "bn"}
LANG_GROUP = {"tr": "Turkish Drama", "ar": "Arabic Drama", "ko": "Korean Drama"}
GROUP_RE = re.compile(r'group-title="([^"]*)"')
TMDB_RE = re.compile(r"\{tmdb-(\d+)\}")


def curl(url, timeout=30):
    try:
        return subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0", url],
                              capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""


def tmdb_info(kind, tid):
    """{'genres': [English names], 'lang': original language code} from TMDB, {} when unknown."""
    key = os.environ.get("TMDB_API_KEY")
    if key:
        try:
            d = json.loads(curl(f"https://api.themoviedb.org/3/{kind}/{tid}?api_key={key}&language=en-US"))
            if d.get("id"):
                return {"genres": [g["name"] for g in d.get("genres", [])], "lang": d.get("original_language", "")}
        except Exception:
            pass
    page = curl(f"https://www.themoviedb.org/{kind}/{tid}?language=en-US")
    genres = [html.unescape(g) for g in re.findall(rf'href="/genre/\d+[^"]*/{kind}[^"]*"[^>]*>([^<]+)<', page)]
    if not genres:
        return {}
    m = re.search(r'data-original-language="([a-z]{2})"|<bdi>Original Language</bdi></strong>\s*([^<]+)<', page)
    lang = ""
    if m:
        lang = m.group(1) or {"turkish": "tr", "arabic": "ar", "korean": "ko", "japanese": "ja", "chinese": "zh",
                              "thai": "th", "hindi": "hi"}.get(m.group(2).strip().lower(), m.group(2).strip()[:2].lower())
    return {"genres": genres, "lang": lang}


def has_kurdish(name):
    """'English _ Kurdish {tmdb-ID}': the part after ' _ ' is written in Arabic script."""
    part = name.split(" _ ", 1)[1] if " _ " in name else ""
    return bool(re.search(r"[؀-ۿ]", part))


def group_of(e):
    m = GROUP_RE.search(e[0])
    return m.group(1) if m else ""


def set_group(e, g):
    e[0] = GROUP_RE.sub(f'group-title="{g}"', e[0], count=1) if GROUP_RE.search(e[0]) else e[0]


def kind_of(e):
    return "series" if 'tvg-type="series"' in e[0] else "movie" if 'tvg-type="movie"' in e[0] else ""


def name_of(e):
    return e[0].rsplit(",", 1)[-1].strip()


def series_group(name, info, groups):
    if has_kurdish(name) and KURDISH_DUB in groups:
        return KURDISH_DUB
    if not info:
        return None
    g = set(info.get("genres", []))
    for genre, grp in (("Documentary", "Documentary Series"), ("Kids", "Kids Series"), ("Animation", "Animation Series")):
        if genre in g and grp in groups:
            return grp
    lang = info.get("lang", "")
    grp = LANG_GROUP.get(lang) or ("Asian Drama" if lang in ASIAN else "Foreign Series")
    return grp if grp in groups else None


def movie_group(name, typed, info, groups):
    t = typed.upper()
    if ("FARSI" in t or "فارسی" in typed) and FARSI in groups:
        return FARSI
    if any(w in typed for w in ("ژێرنوس", "ژیرنوس")) or "SUB" in t:
        return KURDISH_SUB if KURDISH_SUB in groups else None
    if any(w in typed for w in ("دۆبلاژ", "دوبلاژ", "کوردی")) or "DUB" in t or "KURD" in t or has_kurdish(name):
        return KURDISH_DUB if KURDISH_DUB in groups else None
    for genre in (info or {}).get("genres", []):
        if genre in groups:
            return genre
    return None


def fix(text, known_urls=None, info_for=tmdb_info, log=print):
    """known_urls: links already in the snapshot (only other entries are looked at); None = all."""
    head, entries, trail = ss.split_entries(text)
    is_new = lambda e: known_urls is None or (e[-1].strip() not in known_urls)
    old = [e for e in entries if kind_of(e) and not is_new(e)]
    groups = {k: {group_of(e) for e in old if kind_of(e) == k} - {""} for k in ("movie", "series")}
    show_groups = {}
    for e in old:
        k = ss.ep_key(e)
        if k and kind_of(e) == "series":
            show_groups.setdefault(k[0].lower(), Counter())[group_of(e)] += 1
    cache, changed = {}, 0
    for e in entries:
        kind = kind_of(e)
        if not kind or not is_new(e):
            continue
        typed, target = group_of(e), None
        if kind == "series":
            k = ss.ep_key(e)
            show = (k[0] if k else re.sub(r"\s*-\s*S\d+E\d+\s*$", "", name_of(e))).lower()
            if show in show_groups:
                target = show_groups[show].most_common(1)[0][0]
            elif typed not in groups["series"]:
                m = TMDB_RE.search(name_of(e))
                info = cache.setdefault(("tv", m.group(1)), info_for("tv", m.group(1))) if m else {}
                target = series_group(name_of(e), info, groups["series"])
                if target:   # later episodes of the same new series follow it
                    show_groups[show] = Counter({target: 1})
        elif typed not in groups["movie"]:
            m = TMDB_RE.search(name_of(e))
            info = cache.setdefault(("movie", m.group(1)), info_for("movie", m.group(1))) if m else {}
            target = movie_group(name_of(e), typed, info, groups["movie"])
        if target and target != typed:
            set_group(e, target)
            changed += 1
            log(f'{name_of(e)}: "{typed}" -> "{target}"')
        elif not target and typed not in groups[kind]:
            log(f'{name_of(e)}: "{typed}" left as is (TMDB gave no group)')
    out = "\n".join(head + [x for e in entries for x in e]) + ("\n" if trail else "")
    return out, changed


def main(argv=None):
    args = argv or sys.argv[1:] or ["playlist.m3u"]
    path = Path(args[0])
    text = path.read_text(encoding="utf-8")
    known = None
    if len(args) > 1 and Path(args[1]).exists():
        _, snap, _ = ss.split_entries(Path(args[1]).read_text(encoding="utf-8"))
        known = {e[-1].strip() for e in snap}
    out, n = fix(text, known)
    if n:
        path.write_text(out, encoding="utf-8")
    print(f"vod_group_fix: {n} new movie/episode group(s) fixed")


if __name__ == "__main__":
    main()
