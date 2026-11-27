#!/usr/bin/env python3
"""
m3u_sources.py - the owner's own M3U sources (library/sources.txt), read by series-sync every 3 hours.

Every line of library/sources.txt is an M3U link, optionally with a TMDB id for what it holds:
    https://example.com/list.m3u
    https://example.com/fool-night.m3u   tv=326247
    https://example.com/film.m3u         movie=1611767
For every entry of those lists:
  * an episode ("Name - S01 E01", "Name S01E01" ...) or a movie (tvg-type="movie", a film/movie group,
    or movie=ID on the line) is looked at; live channels are skipped;
  * a link with a token (expires / sig / token ...) is never added (listed in the report);
  * the TMDB id comes from the line, from "{tmdb-ID}" in the name, or from an exact TMDB title match;
    without a TMDB id nothing is added;
  * an episode / movie that is already in the playlist (same link, same episode name, same movie id)
    is skipped - no duplicates, existing links are never touched;
  * the link must play (ffprobe: an episode >= 5 min, a movie >= 40 min);
  * it is added in the playlist format: "Title {tmdb-ID} - S01E01", the TMDB poster, the group of its
    TMDB type (an episode of a series already in the playlist: that series' name and group).
Nothing is ever deleted or changed in the playlist; removing a line from sources.txt only stops reading it.
Links that failed are remembered in library/sources-state.json and tried again a day later.
Usage: python m3u_sources.py playlist.m3u [--apply] [--report file]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.dont_write_bytecode = True
import showtv_sync as ss          # noqa: E402
import vod_group_fix as vg        # noqa: E402
import tmdb_poster_fill as tp     # noqa: E402

SOURCES = "library/sources.txt"
STATE = "library/sources-state.json"
RETRY = 24 * 3600
MAX_TESTS = 200                   # links tested per run; the rest wait for the next run
MIN_EPISODE, MIN_MOVIE = 5 * 60, 40 * 60
TOKEN_RE = re.compile(r"(/expires/\d+|[?&](st|e|token|tok|expires|exp|sig|signature|hdnts|hdntl|wmsAuthSign|md5|auth|key|hash|"
                      r"ttl|validfrom|validto|policy|Signature|Key-Pair-Id)=|/sig/|/token/|__token__)", re.I)
EP_RE = re.compile(r"^(.*?)[\s._:-]*\bS(\d{1,2})[\s._-]*E(\d{1,4})\b", re.I)
MOVIE_WORDS = re.compile(r"film|movie|sinema|cinema|فیلم|فلیم|أفلام|افلام", re.I)
YEAR_RE = re.compile(r"[\s(\[]*\b((?:19|20)\d{2})\b[)\]]*\s*$")
ATTR = lambda a, x: (re.search(rf'{a}="([^"]*)"', x) or [None, ""])[1]


def curl(url, timeout=60):
    try:
        return subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0", url],
                              capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""


def duration(url):
    """Seconds of media at url (0 when it does not play)."""
    args = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0"]
    if url.split("?")[0].endswith(".txt"):
        args += ["-f", "hls"]                      # text/plain HLS (hlszone master.txt)
    try:
        out = subprocess.run(args + [url], capture_output=True, text=True, timeout=120,
                             stdin=subprocess.DEVNULL).stdout.strip().splitlines()
        return float(out[0]) if out and out[0] not in ("", "N/A") else 0.0
    except FileNotFoundError:
        return 3600.0 if ss.link_ok(url) else 0.0  # no ffprobe: "plays" is enough
    except Exception:
        return 0.0


def tmdb_details(kind, tid):
    """{'name', 'genres', 'lang', 'poster'} of /tv or /movie id, {} when unknown."""
    key = os.environ.get("TMDB_API_KEY")
    if key:
        try:
            d = json.loads(curl(f"https://api.themoviedb.org/3/{kind}/{tid}?api_key={key}&language=en-US", 30))
            if d.get("id"):
                return {"name": d.get("name") or d.get("title"), "genres": [g["name"] for g in d.get("genres", [])],
                        "lang": d.get("original_language", ""),
                        "poster": tp.IMG + d["poster_path"] if d.get("poster_path") else None}
        except Exception:
            pass
    info = vg.tmdb_info(kind, tid)
    page = curl(f"https://www.themoviedb.org/{kind}/{tid}?language=en-US", 30)
    m = re.search(r"<title>(.*?) \((?:TV Series )?\d{4}", page)
    if not m:
        return {}
    import html
    return {"name": html.unescape(m.group(1)), "genres": info.get("genres", []), "lang": info.get("lang", ""),
            "poster": tp.tmdb_poster(kind, tid)}


def tmdb_search(kind, title, year=None):
    """TMDB id of the exact title match (name or original name), else None."""
    want = ss.key(title)
    if not want:
        return None
    key = os.environ.get("TMDB_API_KEY")
    rows = []
    if key:
        try:
            y = f"&{'year' if kind == 'movie' else 'first_air_date_year'}={year}" if year else ""
            d = json.loads(curl(f"https://api.themoviedb.org/3/search/{kind}?api_key={key}&query={quote(title)}{y}", 30))
            rows = [(str(r["id"]), {ss.key(r.get("title") or r.get("name") or ""),
                                    ss.key(r.get("original_title") or r.get("original_name") or "")})
                    for r in d.get("results", [])]
        except Exception:
            rows = []
    else:
        t = curl(f"https://www.themoviedb.org/search/{kind}?query={quote(title)}", 30)
        rows = [(m.group(1), {ss.key(m.group(2))}) for m in
                re.finditer(rf'href="/{kind}/(\d+)[^"]*"[^>]*><h2[^>]*><span>([^<]+)</span>', t)]
    return next((i for i, names in rows if want in names), None)


def parse_sources(text):
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split()
        hint = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        out.append((parts[0], {k.lower(): re.sub(r"\D", "", v) for k, v in hint.items()}))
    return out


def parse_m3u(text):
    """[(extinf, url)] of an M3U list."""
    lines, out, ext = text.splitlines(), [], None
    for ln in lines:
        ln = ln.strip()
        if ln.startswith("#EXTINF"):
            ext = ln
        elif ln and not ln.startswith("#") and ext:
            out.append((ext, ln))
            ext = None
    return out


def classify(ext, hint):
    """('series', title, year, s, e) / ('movie', title, year) / None (live channel)."""
    shown = ext.rsplit(",", 1)[-1].strip()
    tid_in_name = re.search(r"\{tmdb-(\d+)\}", shown + ATTR("tvg-name", ext))
    for name in (shown, ATTR("tvg-name", ext)):
        m = EP_RE.search(name)
        if m and m.group(1).strip(" -_.:"):
            title, year = clean(m.group(1))
            return ("series", title, year, int(m.group(2)), int(m.group(3)), tid_in_name and tid_in_name.group(1))
    if 'tvg-type="movie"' in ext or hint.get("movie") or MOVIE_WORDS.search(ATTR("group-title", ext)):
        title, year = clean(shown)
        return ("movie", title, year, 0, 0, tid_in_name and tid_in_name.group(1))
    return None


def clean(t):
    t = re.sub(r"\s*\{tmdb-\d+\}", "", t).strip(" -_.:")
    m = YEAR_RE.search(t)
    year = None
    if m and m.start() > 0:
        year, t = m.group(1), t[:m.start()].strip(" -_.:")
    return t, year


def run(text, sources, state, fetch=curl, probe=duration, details=tmdb_details, search=tmdb_search,
        now=None, log=print, max_tests=MAX_TESTS):
    """Returns (new playlist text, report lines, state)."""
    now = now or time.time()
    head, entries, trail = ss.split_entries(text)
    import build_playlist as bp
    have_urls = {bp.same_stream_key(e[-1].strip()) for e in entries}
    names = {ss.ep_key(e) for e in entries if ss.ep_key(e)}
    show_by_id, group_by_id, movie_ids = {}, {}, set()
    for e in entries:
        nm = e[0].rsplit(",", 1)[-1]
        m = re.search(r"\{tmdb-(\d+)\}", nm)
        if not m:
            continue
        if 'tvg-type="series"' in e[0] and ss.ep_key(e):
            show_by_id.setdefault(m.group(1), ss.ep_key(e)[0])
            group_by_id.setdefault(m.group(1), ss.group_of(e))
        elif 'tvg-type="movie"' in e[0]:
            movie_ids.add(m.group(1))
    groups = {k: {ss.group_of(e) for e in entries if f'tvg-type="{k}"' in e[0]} - {""} for k in ("movie", "series")}
    report, tests, cache, found = [], 0, {}, {}
    new_eps, new_movies = {}, []
    for src, hint in sources:
        items = parse_m3u(fetch(src))
        report.append(f"source {src}: {len(items)} entries")
        for ext, url in items:
            st = state.get(url)
            if st and (st["status"] == "token" or now - st["at"] < RETRY):
                continue
            c = classify(ext, hint)
            if not c:
                continue
            kind, title, year, s, ep, tid = c
            label = f"{title} S{s:02d}E{ep:02d}" if kind == "series" else title
            if bp.same_stream_key(url) in have_urls:
                continue
            if TOKEN_RE.search(url):
                state[url] = {"status": "token", "at": now}
                report.append(f"  token link, not added: {label} {url}")
                continue
            tk = "tv" if kind == "series" else "movie"
            tid = tid or hint.get(tk) or (hint.get("tv") if kind == "series" else None)
            if not tid:
                k = (tk, ss.key(title), year)
                if k not in found:
                    found[k] = search(tk, title, year)
                tid = found[k]
            if not tid:
                state[url] = {"status": "no-tmdb", "at": now}
                report.append(f"  no TMDB match, not added: {label}")
                continue
            if (tk, tid) not in cache:
                cache[(tk, tid)] = details(tk, tid)
            info = cache[(tk, tid)]
            if not info.get("name"):
                state[url] = {"status": "no-tmdb", "at": now}
                report.append(f"  TMDB {tk}/{tid} unknown, not added: {label}")
                continue
            if kind == "series":
                show = show_by_id.get(tid) or f"{ss.TMDB_RE.sub('', info['name']).strip().replace(chr(34), chr(39))} {{tmdb-{tid}}}"
                if (show, s, ep) in names:
                    continue                                   # that episode is there: kept as it is
            elif tid in movie_ids:
                continue
            if tests >= max_tests:
                continue
            tests += 1
            d = probe(url)
            if d < (MIN_EPISODE if kind == "series" else MIN_MOVIE):
                state[url] = {"status": "dead" if d == 0 else "short", "at": now}
                report.append(f"  does not play{' (too short)' if d else ''}, not added: {label} {url}")
                continue
            state.pop(url, None)
            have_urls.add(bp.same_stream_key(url))
            logo = info.get("poster") or ""
            if kind == "series":
                grp = group_by_id.get(tid) or vg.series_group(show, "", info, groups["series"]) or "Foreign Series"
                group_by_id[tid] = grp
                show_by_id.setdefault(tid, show)
                name = f"{show} - S{s:02d}E{ep:02d}"
                names.add((show, s, ep))
                new_eps.setdefault(show, []).append(([f'#EXTINF:-1 tvg-name="{name}"tvg-id=""tvg-logo="{logo}"tvg-chno=""'
                                                      f'tvg-type="series"group-title="{grp}":http-referrer="",{name}', url], grp))
                report.append(f"  + {name} ({grp})")
            else:
                name = f"{ss.TMDB_RE.sub('', info['name']).strip().replace(chr(34), chr(39))} {{tmdb-{tid}}}"
                grp = vg.movie_group(name, "", info, groups["movie"]) or "Drama"
                movie_ids.add(tid)
                new_movies.append(([f'#EXTINF:-1 tvg-name="{name}"tvg-id=""tvg-logo="{logo}"tvg-chno=""'
                                    f'tvg-type="movie"group-title="{grp}":http-referrer="",{name}', url], grp))
                report.append(f"  + {name} ({grp})")
    import series_discover as sd
    for show, eps in new_eps.items():
        eps.sort(key=lambda x: ss.ep_key(x[0])[1:])
        idx = [i for i, e in enumerate(entries) if (ss.ep_key(e) or ("",))[0] == show]
        if idx:                                                # an existing series: sorted into its block
            block = entries[idx[0]:idx[-1] + 1] + [e for e, _ in eps]
            if idx == list(range(idx[0], idx[-1] + 1)):
                block.sort(key=lambda e: ss.ep_key(e)[1:] if ss.ep_key(e) and ss.ep_key(e)[0] == show else (0, 0))
            entries[idx[0]:idx[-1] + 1] = block
        else:
            sd.insert_top(entries, eps[0][1], [e for e, _ in eps])
    for e, grp in new_movies:
        sd.insert_movie(entries, grp, e)
    added = sum(len(v) for v in new_eps.values()) + len(new_movies)
    report.append(f"added: {added} (episodes {added - len(new_movies)}, movies {len(new_movies)}), links tested: {tests}")
    out = "\n".join(head + [x for e in entries for x in e]) + ("\n" if trail else "")
    return out, report, state


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("playlist", nargs="?", default="playlist.m3u")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report")
    ap.add_argument("--sources", default=SOURCES)
    ap.add_argument("--state", default=STATE)
    a = ap.parse_args(argv)
    sources = parse_sources(Path(a.sources).read_text(encoding="utf-8")) if Path(a.sources).exists() else []
    if not sources:
        print("m3u_sources: no sources in", a.sources)
        if a.report:
            Path(a.report).write_text("no sources\n", encoding="utf-8")
        return
    state = json.loads(Path(a.state).read_text(encoding="utf-8")) if Path(a.state).exists() else {}
    path = Path(a.playlist)
    text = path.read_text(encoding="utf-8")
    out, report, state = run(text, sources, state)
    print("\n".join(report))
    if a.report:
        Path(a.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    if a.apply:
        if out != text:
            path.write_text(out, encoding="utf-8")
        Path(a.state).write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
