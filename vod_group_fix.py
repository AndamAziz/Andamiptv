#!/usr/bin/env python3
"""
vod_group_fix.py - a NEW movie / series episode (its link is not in the snapshot yet, e.g. added with
the web form) gets the group of its TMDB type. Only the two Kurdish groups (KURDISH-دۆبلاژ /
KURDISH-ژێرنوس) are the owner's choice and always stay; for the rest:

  * an episode of a series that is already in the playlist -> the group of that series' episodes
    (also when another group was typed: one series name in two groups splits it in the app);
  * a brand-new series -> from TMDB: Documentary Series; a cartoon -> Kids / Animation Series (or
    Classic Cartoons when typed); else by original language Turkish / Arabic / Korean / Asian Drama,
    else Foreign Series (also when another group was typed). A Kurdish name with no real group typed
    -> KURDISH-دۆبلاژ;
  * a movie -> FARSI / KURDISH-ژێرنوس / KURDISH-دۆبلاژ when the typed group says so, FARSI for a
    Persian film; else the typed genre when it is one of the film's TMDB genres, otherwise its first
    TMDB genre (Action, Drama ...). With no TMDB genre a real typed group stays.

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


def series_group(name, typed, info, groups):
    """Group for a NEW series. KURDISH-دۆبلاژ typed by the owner stays; otherwise the TMDB type decides."""
    if typed == KURDISH_DUB:
        return KURDISH_DUB
    if not info or not (info.get("genres") or info.get("lang")):
        if typed in groups:
            return typed
        return KURDISH_DUB if has_kurdish(name) and KURDISH_DUB in groups else None
    g = set(info.get("genres", []))
    if not g and typed in groups:                 # TMDB knows no genre: the typed real group stays
        return typed
    if "Documentary" in g:
        ok, default = {"Documentary Series"}, "Documentary Series"
    elif "Kids" in g or "Animation" in g:         # cartoons: any of the three cartoon groups is fine
        ok, default = {"Kids Series", "Animation Series", "Classic Cartoons"}, ("Kids Series" if "Kids" in g else "Animation Series")
    else:
        lang = info.get("lang", "")
        default = LANG_GROUP.get(lang) or ("Asian Drama" if lang in ASIAN else "Foreign Series")
        ok = {default}
    if typed in ok and typed in groups:
        return typed
    if typed not in groups and has_kurdish(name) and KURDISH_DUB in groups:
        return KURDISH_DUB
    return default if default in groups else (typed if typed in groups else None)


def movie_group(name, typed, info, groups):
    """Group for a NEW movie. Kurdish dub/subtitle groups are the owner's choice; FARSI by language;
    otherwise a TMDB genre (the typed genre stays when it is one of the film's TMDB genres)."""
    t = typed.upper()
    if typed in (KURDISH_DUB, KURDISH_SUB, "Free Classics") and typed in groups:
        return typed
    if ("FARSI" in t or "فارسی" in typed) and FARSI in groups:
        return FARSI
    if any(w in typed for w in ("ژێرنوس", "ژیرنوس")) or "SUB" in t:
        return KURDISH_SUB if KURDISH_SUB in groups else None
    if any(w in typed for w in ("دۆبلاژ", "دوبلاژ", "کوردی")) or "DUB" in t or "KURD" in t:
        return KURDISH_DUB if KURDISH_DUB in groups else None
    info = info or {}
    if info.get("lang") == "fa" and FARSI in groups:
        return FARSI
    genres = [x for x in info.get("genres", []) if x in groups]
    if typed in genres:
        return typed
    if genres:
        return genres[0]
    if typed in groups:                           # TMDB knows no genre: the typed real group stays
        return typed
    return KURDISH_DUB if has_kurdish(name) and KURDISH_DUB in groups else None


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
            else:
                m = TMDB_RE.search(name_of(e))
                info = cache.setdefault(("tv", m.group(1)), info_for("tv", m.group(1))) if m else {}
                target = series_group(name_of(e), typed, info, groups["series"])
                if target:   # later episodes of the same new series follow it
                    show_groups[show] = Counter({target: 1})
        else:
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
