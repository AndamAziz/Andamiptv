#!/usr/bin/env python3
"""Add LICENSED movies from the Internet Archive to playlist.m3u (no storage needed on your side).

Only items whose license is public domain / CC0 (and, with --allow-cc-by, CC-BY / CC-BY-SA) are used,
NON-commercial (-nc) licenses are always skipped. Optional: --include-pre1930 adds films made in 1929 or
earlier that carry no license field (public domain by age in the US) - they are marked "age-based" in the report.

Every candidate is checked: it must have an .mp4 (h.264) file, a real feature length, and the link must answer
a Range request with HTTP 206 (so seeking works). Nothing is added unless --apply is given (default = report only).

Optional env TMDB_API_KEY: adds the {tmdb-ID} tag, the TMDB poster and puts every movie in its GENRE group
(Action, Comedy, Horror, Romance ...) when the title/year match exactly; without the key movies go to --group.
Usage: python3 archive_add.py --collection feature_films --max-items 10 [--apply]
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request, urllib.error

UA = {"User-Agent": "AndamIPTV-archive-tool/1.0"}
PD_RE = re.compile(r"creativecommons\.org/(publicdomain/(mark|zero)|licenses/publicdomain|publicdomain)", re.I)
CC_RE = re.compile(r"creativecommons\.org/licenses/(by|by-sa)/", re.I)


def get_json(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def search(collection, query, rows, page):
    q = "mediatype:movies"
    if collection:
        q += f" AND collection:({collection})"
    if query:
        q += f" AND ({query})"
    fl = ["identifier", "title", "year", "licenseurl", "downloads", "creator", "language", "subject"]
    params = [("q", q), ("rows", rows), ("page", page), ("output", "json"), ("sort[]", "downloads desc")] + [("fl[]", f) for f in fl]
    data = get_json("https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params))
    return data["response"]["docs"], data["response"]["numFound"]


def license_ok(doc, allow_cc_by, include_pre1930):
    lic = doc.get("licenseurl") or ""
    if isinstance(lic, list):
        lic = lic[0] if lic else ""
    if "-nc" in lic.lower():
        return None
    if PD_RE.search(lic):
        return "public domain"
    if allow_cc_by and CC_RE.search(lic):
        return "CC-BY (credit the creator)"
    if include_pre1930 and not lic:
        try:
            y = int(str(doc.get("year") or "")[:4])
        except ValueError:
            return None
        if 1890 <= y <= 1929:
            return "age-based (made in %d)" % y
    return None


def runtime_minutes(meta):
    rt = meta.get("runtime") or meta.get("length") or ""
    if isinstance(rt, list):
        rt = rt[0]
    rt = str(rt).strip()
    if re.fullmatch(r"\d+(\.\d+)?", rt):
        return float(rt) / 60
    parts = rt.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    sec = 0
    for n in nums:
        sec = sec * 60 + n
    return sec / 60


def file_dims(f):
    """(width, height) from the archive.org file metadata, 0 when missing."""
    def num(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0
    return num(f.get("width")), num(f.get("height"))


from movie_engine import classify_resolution  # noqa: E402  (single, orientation-aware definition)


def pick_file(files, min_size=20_000_000, min_height=0):
    """Best .mp4: when min_height is set a file that meets it wins; otherwise the usual h.264 derivative."""
    best = None
    for f in files:
        n = f.get("name", "")
        if not n.lower().endswith(".mp4") or "/" in n:
            continue
        size = int(f.get("size") or 0)
        if not (min_size <= size <= 6_000_000_000):
            continue
        w, h = file_dims(f)
        meets = 1 if (min_height and classify_resolution(w, h, min_height).startswith("accept")) else 0
        score = (meets, h, 1 if f.get("format", "").lower() == "h.264" else 0, 1 if f.get("source") == "derivative" else 0, -size)
        if best is None or score > best[0]:
            best = (score, f)
    return best[1] if best else None


def probe_resolution(url):
    """Optional second opinion straight from the video stream (needs ffprobe, e.g. on GitHub runners). None if unavailable."""
    import shutil, subprocess
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0:s=x", url], capture_output=True, text=True, timeout=45)
        m = re.match(r"^(\d+)x(\d+)", r.stdout.strip())
        return (int(m.group(1)), int(m.group(2))) if m else None
    except Exception:
        return None


def check_range(url):
    req = urllib.request.Request(url, headers={**UA, "Range": "bytes=0-1023"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ok = r.status in (200, 206) and "video" in (r.headers.get("Content-Type") or "").lower()
            return ok and r.status == 206, r.status
    except urllib.error.HTTPError as e:
        return False, e.code
    except Exception:
        return False, 0


def clean_title(t, year):
    t = str(t)
    t = re.sub(r"\s*[\(\[]\s*(19|18)\d\d\s*[\)\]]", "", t)
    t = re.sub(r"\s*[-|:]\s*(public domain|full movie|full film|free|hd|restored).*$", "", t, flags=re.I)
    m = re.match(r"^(.*?),\s*(The|A|An)$", t.strip(), re.I)      # "Little Princess, The" -> "The Little Princess"
    if m:
        t = m.group(2) + " " + m.group(1)
    m = re.match(r"^(.*?)\s+\((The|A|An)\)$", t.strip(), re.I)  # "Little Princess (The)"
    if m:
        t = m.group(2) + " " + m.group(1)
    t = re.sub(r"[\",]", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -_")
    return t


GENERIC = {"Drama", "Adventure", "TV Movie", "Music", "Family"}
SUBJECT_GENRES = [  # (regex on the archive.org subject tags, group) - first match wins
    (r"horror|monster|zombie|vampire|ghost", "Horror"), (r"sci-?fi|science fiction|space|alien", "Science Fiction"),
    (r"western|cowboy", "Western"), (r"film-?noir|noir|crime|gangster|detective", "Crime"),
    (r"mystery|murder|suspense", "Mystery"), (r"thriller", "Thriller"), (r"\bwar\b|wwii|world war", "War"),
    (r"romance|romantic", "Romance"), (r"comedy|slapstick|stooges|chaplin|keaton|laurel", "Comedy"),
    (r"musical|music", "Music"), (r"fantasy", "Fantasy"), (r"action", "Action"), (r"adventure|serial", "Adventure"),
    (r"cartoon|animat", "Animation"), (r"documentary", "Documentary"), (r"drama", "Drama"),
]


def subject_group(doc, default):
    sub = doc.get("subject") or []
    sub = [sub] if isinstance(sub, str) else sub
    text = " ; ".join(str(x) for x in sub).lower()
    for rx, g in SUBJECT_GENRES:
        if re.search(rx, text):
            return g
    return default


def genre_group(genres, default):
    """First specific TMDB genre (Drama/Adventure/Family/Music are only used when nothing else fits)."""
    for g in genres:
        if g not in GENERIC:
            return g
    return genres[0] if genres else default


def tmdb_lookup(title, year):
    """Needs the free TMDB_API_KEY. Returns (id, poster_url, genres) only for an exact title + year match."""
    key = os.environ.get("TMDB_API_KEY")
    if not key or not year:
        return None
    q = urllib.parse.urlencode({"api_key": key, "query": title, "year": year})
    try:
        res = get_json("https://api.themoviedb.org/3/search/movie?" + q, 20).get("results", [])
    except Exception:
        return None
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    for r in res[:5]:
        if norm(r.get("title", "")) == norm(title) or norm(r.get("original_title", "")) == norm(title):
            try:
                det = get_json("https://api.themoviedb.org/3/movie/%d?api_key=%s" % (r["id"], key), 20)
                genres = [g["name"] for g in det.get("genres", [])]
            except Exception:
                genres = []
            poster = ("https://media.themoviedb.org/t/p/w600_and_h900_face" + r["poster_path"]) if r.get("poster_path") else None
            return r["id"], poster, genres
    return None


STAT_KEYS = ["scanned", "accepted_1080p", "accepted_4k", "accepted_below", "rejected_low", "unknown_quality",
             "bad_link", "license_rejected", "duplicates", "too_short", "no_mp4", "low_popularity"]


def source_internet_archive(a, ctx):
    """Source plug-in: returns (candidates, stats). Add other legitimate, licensed sources the same way (see SOURCES).
    Scans page by page and verifies every page right away, so it keeps looking until enough candidates are found or the
    search is exhausted (up to 4000 items) - an empty result therefore really means 'nothing qualifies'."""
    stats = dict.fromkeys(STAT_KEYS, 0)

    def verify(d):
        lic = license_ok(d, a.allow_cc_by, a.include_pre1930)
        try:
            meta = get_json("https://archive.org/metadata/" + urllib.parse.quote(d["identifier"]))
        except Exception:
            return None, "no_mp4"
        f = pick_file(meta.get("files", []), min_height=a.min_height)
        if not f:
            return None, "no_mp4"
        mins = runtime_minutes(meta.get("metadata", {}))
        if mins is None or mins < a.min_minutes:
            return None, "too_short"
        width, height = file_dims(f)                       # reliable archive.org file metadata
        verdict = classify_resolution(width, height, a.min_height)
        url = "https://archive.org/download/%s/%s" % (urllib.parse.quote(d["identifier"]), urllib.parse.quote(f["name"]))
        if a.min_height > 0 and verdict.startswith("accept"):
            probed = probe_resolution(url)                 # second opinion from the real stream when ffprobe exists
            if probed:
                width, height = probed
                verdict = classify_resolution(width, height, a.min_height)
        if a.min_height > 0 and verdict == "unknown":
            return None, "unknown_quality"
        if a.min_height > 0 and verdict == "reject_low":
            return None, "rejected_low"
        ok, st = check_range(url)
        if not ok:
            return None, "bad_link"
        year = str(d.get("year") or "")[:4]
        title = clean_title(d.get("title"), year)
        tm = tmdb_lookup(title, year)
        name = title + (" (%s)" % year if year and not tm else "") + (" {tmdb-%d}" % tm[0] if tm else "")
        grp = genre_group(tm[2], a.group) if tm else subject_group(d, a.group)
        logo = tm[1] if tm and tm[1] else "https://archive.org/services/img/" + urllib.parse.quote(d["identifier"])
        res = "2160p" if verdict == "accept_4k" else ("1080p" if verdict == "accept_1080p" else ("%dp" % height if height else "?"))
        return dict(id=d["identifier"], name=name, group=grp, logo=logo, url=url, license=lic, year=year, verdict=verdict,
                    minutes=round(mins), res=res, width=width, height=height, mb=round(int(f["size"]) / 1e6),
                    downloads=int(d.get("downloads") or 0)), None

    from concurrent.futures import ThreadPoolExecutor
    found, names, seen_ids, page = [], set(ctx["known_names"]), set(), 1
    with ThreadPoolExecutor(max_workers=8) as ex:
        while len(found) < a.max_items and page <= 40:
            docs, total = search(a.collection, a.query, 100, page)
            if not docs:
                break
            batch = []
            for d in docs:
                stats["scanned"] += 1
                if d["identifier"] in seen_ids:
                    continue
                seen_ids.add(d["identifier"])
                if not license_ok(d, a.allow_cc_by, a.include_pre1930):
                    stats["license_rejected"] += 1; continue
                if a.exclude_words and re.search(r"\b(%s)\b" % a.exclude_words, str(d.get("title") or ""), re.I):
                    stats["license_rejected"] += 1; continue
                subj = d.get("subject") or []
                subj = " ; ".join(subj if isinstance(subj, list) else [subj])
                if a.exclude_subjects and re.search(a.exclude_subjects, subj, re.I):
                    stats["license_rejected"] += 1; continue
                if d["identifier"] in ctx["known_ids"]:
                    stats["duplicates"] += 1; continue
                if int(d.get("downloads") or 0) < a.min_downloads:
                    stats["low_popularity"] += 1; continue
                batch.append(d)
            for r, why in ex.map(verify, batch):
                if r is None:
                    stats[why] += 1; continue
                if r["name"].lower() in names or ctx["norm_t"](r["name"]) in ctx["known_titles"]:
                    stats["duplicates"] += 1; continue
                if len(found) >= a.max_items:
                    break
                names.add(r["name"].lower()); ctx["known_titles"].add(ctx["norm_t"](r["name"]))
                stats["accepted_4k" if r["verdict"] == "accept_4k" else ("accepted_1080p" if r["verdict"] == "accept_1080p" else "accepted_below")] += 1
                found.append(r)
            page += 1
    return found, stats


SOURCES = {"internet_archive": source_internet_archive}   # register further licensed sources here (same signature)


def build_report(found, stats, a):
    rep = ["# Movie import report (%s)" % ("APPLIED" if a.apply else "DRY RUN, nothing changed"), "",
           "Source: %s | collection: %s | minimum resolution: %s | min length: %d min" % (a.source, a.collection or "all",
           ("%dp (1920x1080)" % a.min_height) if a.min_height else "none", a.min_minutes), "",
           "| Statistic | Count |", "|---|---|",
           "| Total scanned movies | %d |" % stats["scanned"],
           "| Accepted 1080p | %d |" % stats["accepted_1080p"],
           "| Accepted 4K | %d |" % stats["accepted_4k"],
           "| Accepted (resolution filter off) | %d |" % stats["accepted_below"],
           "| Rejected 720p and lower | %d |" % stats["rejected_low"],
           "| Unknown resolution (excluded) | %d |" % stats["unknown_quality"],
           "| Invalid or inaccessible links | %d |" % stats["bad_link"],
           "| License / content-filter rejections | %d |" % stats["license_rejected"],
           "| Duplicates | %d |" % stats["duplicates"],
           "| Too short / no mp4 / low popularity | %d / %d / %d |" % (stats["too_short"], stats["no_mp4"], stats["low_popularity"]), "",
           "| # | Title | Group | Year | Min | Res | MB | License | Link |", "|---|---|---|---|---|---|---|---|---|"]
    for i, f in enumerate(found, 1):
        rep.append("| %d | %s | %s | %s | %s | %s | %s | %s | %s |" % (i, f["name"], f["group"], f["year"], f["minutes"], f["res"], f["mb"], f["license"], f["url"]))
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="internet_archive", choices=sorted(SOURCES))
    ap.add_argument("--playlist", default="playlist.m3u")
    ap.add_argument("--collection", default="feature_films")
    ap.add_argument("--query", default="")
    ap.add_argument("--max-items", type=int, default=10)
    ap.add_argument("--min-downloads", type=int, default=2000)
    ap.add_argument("--min-minutes", type=float, default=40)
    ap.add_argument("--min-height", type=int, default=1080,
                    help="minimum VERIFIED resolution (1080 = Full HD; 4K also passes); files with unknown resolution are excluded; 0 = no filter")
    ap.add_argument("--group", default="Free Classics")
    ap.add_argument("--allow-cc-by", action="store_true")
    ap.add_argument("--include-pre1930", action="store_true")
    ap.add_argument("--exclude-words", default=r"naked|nude|sex|sexy|erotic|porn|strip(per|tease)?|burlesque|bikini|topless|lust|orgy|vice|harem|girls",
                    help="regex: titles matching it are skipped (family-friendly filter)")
    ap.add_argument("--exclude-subjects", default=r"exploitation|grindhouse|burlesque|sexploitation|nudie|adult|erotic|trailers?",
                    help="regex on the archive.org subject tags: matching films are skipped")
    ap.add_argument("--apply", action="store_true", help="write to the playlist (default is a dry run that only writes the report)")
    ap.add_argument("--report", default="archive-report.md")
    a = ap.parse_args()

    text = open(a.playlist, encoding="utf-8").read() if os.path.exists(a.playlist) else "#EXTM3U\n"
    lines = text.split("\n")
    known_names = {l.rsplit(",", 1)[-1].strip().lower() for l in lines if l.startswith("#EXTINF") and "tvg-type=" in l}
    norm_t = lambda n: re.sub(r"[^a-z0-9]", "", re.sub(r"\{tmdb-\d+\}|\(\d{4}\)", "", n.lower()))
    ctx = dict(known_ids=set(re.findall(r"archive\.org/download/([^/]+)/", text)), known_names=known_names,
               norm_t=norm_t, known_titles={norm_t(n) for n in known_names})

    found, stats = SOURCES[a.source](a, ctx)
    rep = build_report(found, stats, a)
    open(a.report, "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print("\n".join(rep))

    if a.apply and found:
        block = []
        for f in found:
            block += ['#EXTINF:-1 tvg-name="%s"tvg-id=""tvg-logo="%s"tvg-chno=""tvg-type="movie"group-title="%s":http-referrer="",%s' % (f["name"], f["logo"], f["group"], f["name"]), f["url"]]
        # append only: insert after the last movie entry that comes before the first series; nothing existing is moved or removed
        first_series = next((i for i, l in enumerate(lines) if l.startswith("#EXTINF") and 'tvg-type="series"' in l), len(lines))
        last = None
        for i, l in enumerate(lines[:first_series]):
            if l.startswith("#EXTINF") and 'tvg-type="movie"' in l:
                j = i + 1
                while j < len(lines) and lines[j].startswith("#"):
                    j += 1
                last = j
        pos = (last + 1) if last is not None else first_series
        lines[pos:pos] = block
        open(a.playlist, "w", encoding="utf-8").write("\n".join(lines))
        print("Added %d movies to %s (group %s)" % (len(found), a.playlist, a.group))
    return 0


if __name__ == "__main__":
    sys.exit(main())
