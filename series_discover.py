#!/usr/bin/env python3
"""
series_discover.py - add NEW drama series to the playlist automatically (showtv_sync.py then keeps
their episodes up to date).

Where new series are found:
  * Show TV - the dramas on showtv.com.tr/diziler (on air) and /diziler/arsivdeki-diziler (archive)
  * TV8     - the dramas on tv8.com.tr/diziler
  * tabii   - series that appear in tabii's public sitemap after the last run (library/tabii-seen.json
              remembers what was already there, so the old catalogue is not imported in one go)

A series is added only when it is not in the playlist yet (same title), is not set to null in the
provider's json, and at least one episode has an official, token-free (DRM-free) link that plays.

Groups: Show TV / TV8 dramas and tabii "Dizi" -> Turkish Drama, tabii "Kids" -> Kids Series,
tabii "Documentary" -> Documentary Series. TV programmes (anything else) are NEVER added (the
owner wants only series and films): they are remembered as seen and named once in the report.

Names: "Title {tmdb-ID} - SxxEyy" (title as the broadcaster writes it, the TMDB tag and poster only on
an exact title match, otherwise the broadcaster's poster), per season when the series has several.
The series' page/id is written into showtv-series.json / tabii-series.json / tv8-series.json, so the
daily sync always finds the same series again. A new series goes to the top of its group.

Usage:
  python series_discover.py playlist.m3u              # report only
  python series_discover.py playlist.m3u --apply      # write playlist + json files
  python series_discover.py playlist.m3u --seed       # only remember tabii's current catalogue
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

sys.dont_write_bytecode = True
import showtv_sync as ss  # noqa: E402

HERE = Path(__file__).resolve().parent
SEEN = HERE / "library" / "tabii-seen.json"
TMDB_IMG = "https://media.themoviedb.org/t/p/w600_and_h900_face"
TABII_IMG = "https://cms-tabii-public-image.tabii.com/int/webp/w600/q85/"
GROUPS = {"Dizi": "Turkish Drama", "Kids": "Kids Series", "Documentary": "Documentary Series"}


# ---------------------------------------------------------------- network (patched in tests)
def curl(url, timeout=30):
    """themoviedb.org refuses Python's urllib, curl is accepted."""
    try:
        return subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0", url],
                              capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""


def tmdb(title, year=None):
    """(tmdb id, poster url) for an exact title match among Turkish TV series, else (None, None)."""
    want = ss.key(title)
    key_ = os.environ.get("TMDB_API_KEY")
    rows = []
    if key_:
        try:
            d = json.loads(ss.fetch(f"https://api.themoviedb.org/3/search/tv?api_key={key_}&language=tr-TR"
                                    f"&query={quote(title)}"))
            rows = [(str(r["id"]), [r.get("name", ""), r.get("original_name", "")], (r.get("first_air_date") or "")[:4],
                     r.get("original_language"), r.get("poster_path")) for r in d.get("results", [])]
        except Exception:
            rows = []
    else:
        t = curl(f"https://www.themoviedb.org/search/tv?query={quote(title)}&language=tr-TR")
        for m in re.finditer(r'href="/tv/(\d+)[^"]*"[^>]*><h2[^>]*><span>([^<]+)</span>.*?release_date[^>]*>([^<]*)<', t, re.S):
            y = re.search(r"(\d{4})", m.group(3))
            rows.append((m.group(1), [html.unescape(m.group(2))], y.group(1) if y else "", None, None))
    hits = [r for r in rows if want in {ss.key(n) for n in r[1]} and r[3] in (None, "tr")]
    if year:
        hits.sort(key=lambda r: abs(int(r[2] or 0) - int(year)))
    if not hits:
        return None, None
    tid, poster = hits[0][0], hits[0][4]
    if not poster:
        m = re.search(r"w600_and_h900_face(/[A-Za-z0-9]+\.jpg)", curl(f"https://www.themoviedb.org/tv/{tid}?language=tr-TR"))
        poster = m.group(1) if m else None
    return tid, (TMDB_IMG + poster if poster else None)


def og_image(page_html):
    m = re.search(r'<meta property="og:image" content="([^"]+)"', page_html or "")
    return html.unescape(m.group(1)) if m else ""


# ---------------------------------------------------------------- candidates
def showtv_candidates():
    t = ss.fetch(ss.ShowTV.SITE + "/diziler")
    try:
        t += ss.fetch(ss.ShowTV.SITE + "/diziler/arsivdeki-diziler")
    except Exception:
        pass
    out = {}
    generic = {"detaylar", "izle", "fragman", "tumbolumler", "bolumler", "fotograflar", "videolar"}
    for tag in re.findall(r"<a\b[^>]*>", t):                      # attributes in any order
        h = re.search(r'href="(/dizi/tanitim/[a-z0-9-]+/\d+)"', tag)
        ti = re.search(r'title="([^"]+)"', tag)
        if h and ti and ss.key(html.unescape(ti.group(1))) not in generic:
            out.setdefault(h.group(1), html.unescape(ti.group(1)).strip())
    return [dict(provider="showtv", ref=p, title=t_, group="Turkish Drama") for p, t_ in out.items()]


def tv8_candidates():
    t = ss.fetch(ss.TV8.SITE + "/diziler")
    out = {}
    for m in re.finditer(r'href="/([a-z0-9-]+)"[^>]*class="now-thumb-prog[^"]*"[^>]*>([^<]+)<', t):
        out.setdefault(m.group(1), html.unescape(m.group(2)).strip())
    return [dict(provider="tv8", ref=s, title=t_, group="Turkish Drama") for s, t_ in out.items()]


def tabii_new_ids(seen):
    return [i for i in sorted(set(ss.Tabii().sitemap().values()), key=int) if i not in seen]


def tabii_info(sid):
    d = ss.next_data(ss.fetch(f"{ss.Tabii.SITE}/tr/detail/{sid}")).get("props", {}).get("pageProps", {}).get("data") or {}
    cats = [c.get("title") if isinstance(c, dict) else c for c in d.get("categories") or []]
    imgs = {i.get("imageType"): i.get("name") for i in d.get("images") or [] if isinstance(i, dict)}
    img = imgs.get("verticalWithLogo") or imgs.get("vertical") or imgs.get("mainWithLogo")
    return dict(type=d.get("contentType"), title=(d.get("title") or "").strip(), cats=cats,
                year=d.get("madeYear"), poster=TABII_IMG + img if img else "")


# ---------------------------------------------------------------- building a series
def best_links(provider, eps):
    """{episode: first official link that plays}"""
    def one(n):
        try:
            links = provider.links(eps[n])
        except Exception:
            links = []
        return next((u for u in links if provider.is_official(u) and ss.link_ok(u)), None)
    with ThreadPoolExecutor(8) as ex:
        got = dict(zip(sorted(eps), ex.map(one, sorted(eps))))
    return {n: u for n, u in got.items() if u}


def entries_for(show, group, logo, good, seasons):
    start = {}
    for a, s in seasons.items():
        start[s] = min(start.get(s, a), a)
    per_season = len(start) > 1
    out = []
    for n, u in sorted(good.items()):
        s, x = (seasons[n], n - start[seasons[n]] + 1) if per_season and n in seasons else (1, n)
        name = f"{show} - S{s:02d}E{x:02d}"
        out.append([f'#EXTINF:-1 tvg-name="{name}"tvg-id=""tvg-logo="{logo}"tvg-chno=""tvg-type="series"'
                    f'group-title="{group}":http-referrer="",{name}', u])
    return out


def existing_titles(entries):
    keys = set()
    for e in entries:
        k = ss.ep_key(e)
        if k:
            t = ss.TMDB_RE.sub("", k[0]).split(" _ ")[0]
            keys.add(ss.key(t))
    return keys


def insert_top(entries, group, new):
    """New series first in its group (series part); a missing group goes after the last series."""
    idx = [i for i, e in enumerate(entries) if ss.group_of(e) == group and 'tvg-type="series"' in e[0]]
    if idx:
        at = idx[0]
    else:
        ser = [i for i, e in enumerate(entries) if 'tvg-type="series"' in e[0]]
        at = ser[-1] + 1 if ser else len(entries)
    entries[at:at] = new


def discover(text, overrides, seen, apply_seen=True, log=print, check_tabii=True):
    """Returns (new text, added [(group, show, n)], pending programmes); fills overrides and seen."""
    head, entries, trail = ss.split_entries(text)
    have = existing_titles(entries)
    for provider in overrides.values():
        have |= {ss.key(t) for t, v in provider.items() if v is None}
    added, pending = [], []
    cands = []
    for name, fn in (("showtv", showtv_candidates), ("tv8", tv8_candidates)):
        try:
            cands += fn()
        except Exception as ex:
            log(f"- [{name}] list failed ({ex}), skipped")
    if check_tabii:
        for sid in tabii_new_ids(seen):
            try:
                info = tabii_info(sid)
            except Exception as ex:
                log(f"- [tabii] {sid}: page failed ({ex}), will retry next run")
                continue
            if info["type"] != "series":
                seen[sid] = info["type"] or "other"
                continue
            group = next((GROUPS[c] for c in info["cats"] if c in GROUPS), None)
            if group is None:
                seen[sid] = "programme"
                pending.append(dict(provider="tabii", id=sid, title=info["title"], categories=info["cats"],
                                    url=f"{ss.Tabii.SITE}/tr/detail/{sid}"))
                continue
            cands.append(dict(provider="tabii", ref=sid, title=info["title"], group=group,
                              year=info["year"], poster=info["poster"]))
    classes = {"showtv": ss.ShowTV, "tabii": ss.Tabii, "tv8": ss.TV8}
    for c in cands:
        if ss.key(c["title"]) in have:
            if c["provider"] == "tabii":
                seen[c["ref"]] = "in-playlist"
            continue
        p = classes[c["provider"]]({})
        try:
            eps = p.episodes(c["ref"])
        except Exception as ex:
            log(f"- [{p.name}] {c['title']}: episode list failed ({ex}), skipped")
            continue
        seasons = dict(getattr(p, "seasons", {}) or {})
        good = best_links(p, eps) if eps else {}
        if not good:
            log(f"- [{p.name}] {c['title']}: no free episode that plays yet, not added")
            if c["provider"] == "tabii":
                seen.pop(c["ref"], None)                 # look again next run
            continue
        page = ""
        if c["provider"] in ("showtv", "tv8"):
            try:
                page = ss.fetch((ss.ShowTV.SITE + c["ref"]) if c["provider"] == "showtv" else f"{ss.TV8.SITE}/{c['ref']}")
            except Exception:
                pass
        tid, poster = tmdb(c["title"], c.get("year"))
        show = f"{c['title']} {{tmdb-{tid}}}" if tid else c["title"]
        logo = poster or c.get("poster") or og_image(page)
        insert_top(entries, c["group"], entries_for(show, c["group"], logo, good, seasons))
        overrides[p.name][c["title"]] = c["ref"] if c["provider"] != "tabii" else int(c["ref"])
        have.add(ss.key(c["title"]))
        if c["provider"] == "tabii":
            seen[c["ref"]] = "added"
        added.append((c["group"], show, len(good)))
        log(f"+ [{p.name}] {show}: {len(good)} episodes -> {c['group']}")
    out = "\n".join(head + [x for e in entries for x in e]) + ("\n" if trail else "")
    return out, added, pending


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("playlist")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--seed", action="store_true", help="remember tabii's current catalogue, add nothing")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    lines = []
    def log(s):
        print(s, flush=True)
        lines.append(s)
    seen = load_json(SEEN, {})
    if a.seed or not seen:
        for sid in ss.Tabii().sitemap().values():
            seen.setdefault(sid, "seen")
        log(f"tabii: {len(seen)} catalogue ids remembered (only series published after this are imported)")
        if a.seed:
            SEEN.write_text(json.dumps(seen, indent=0, sort_keys=True) + "\n", encoding="utf-8")
            return
    files = {"showtv": HERE / ss.ShowTV.config, "tabii": HERE / ss.Tabii.config, "tv8": HERE / ss.TV8.config}
    docs = {k: load_json(f, {"series": {}}) for k, f in files.items()}
    overrides = {k: d.setdefault("series", {}) for k, d in docs.items()}
    text = Path(a.playlist).read_text(encoding="utf-8")
    out, added, pending = discover(text, overrides, seen, log=log)
    for p in pending:
        log(f"- [tabii] {p['title']}: TV programme {p['categories']}, skipped (only series and films are added)")
    log(f"new series added: {len(added)}, episodes: {sum(n for _, _, n in added)}")
    if a.apply:
        if out != text:
            Path(a.playlist).write_text(out, encoding="utf-8")
        for k, f in files.items():
            if added and any(x for x in added):
                f.write_text(json.dumps(docs[k], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        SEEN.write_text(json.dumps(seen, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    else:
        log("report only (use --apply to write)")
    if a.report:
        Path(a.report).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
