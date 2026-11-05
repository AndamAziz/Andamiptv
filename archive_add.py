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


def pick_file(files):
    best = None
    for f in files:
        n = f.get("name", "")
        if not n.lower().endswith(".mp4") or "/" in n:
            continue
        size = int(f.get("size") or 0)
        if not (20_000_000 <= size <= 6_000_000_000):
            continue
        score = (1 if f.get("format", "").lower() == "h.264" else 0, 1 if f.get("source") == "derivative" else 0, -size)
        if best is None or score > best[0]:
            best = (score, f)
    return best[1] if best else None


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
    t = re.sub(r"\s*[\(\[]\s*(19|18)\d\d\s*[\)\]]", "", str(t))
    t = re.sub(r"\s*[-|:]\s*(public domain|full movie|full film|free|hd|restored).*$", "", t, flags=re.I)
    t = re.sub(r"[\",]", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -_")
    return t


GENERIC = {"Drama", "Adventure", "TV Movie", "Music", "Family"}
SUBJECT_GENRES = [  # (regex on the archive.org subject tags, group) - first match wins
    (r"horror|monster|zombie|vampire|ghost", "Horror"), (r"sci-?fi|science fiction|space|alien", "Science Fiction"),
    (r"western|cowboy", "Western"), (r"film-?noir|noir|crime|gangster|detective", "Crime"),
    (r"mystery|murder|suspense", "Mystery"), (r"thriller", "Thriller"), (r"\bwar\b|wwii|world war", "War"),
    (r"romance|romantic", "Romance"), (r"comedy|slapstick|stooges|chaplin|keaton|laurel", "Comedy"),
    (r"musical|music", "Musical"), (r"fantasy", "Fantasy"), (r"action", "Action"), (r"adventure|serial", "Adventure"),
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--playlist", default="playlist.m3u")
    ap.add_argument("--collection", default="feature_films")
    ap.add_argument("--query", default="")
    ap.add_argument("--max-items", type=int, default=10)
    ap.add_argument("--min-downloads", type=int, default=2000)
    ap.add_argument("--min-minutes", type=float, default=40)
    ap.add_argument("--group", default="Free Classics")
    ap.add_argument("--allow-cc-by", action="store_true")
    ap.add_argument("--include-pre1930", action="store_true")
    ap.add_argument("--exclude-words", default=r"naked|nude|sex|sexy|erotic|porn|strip(per|tease)?|burlesque|bikini|topless|lust|orgy|vice|harem|girls",
                    help="regex: titles matching it are skipped (family-friendly filter)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="archive-report.md")
    a = ap.parse_args()

    text = open(a.playlist, encoding="utf-8").read() if os.path.exists(a.playlist) else "#EXTM3U\n"
    lines = text.split("\n")
    known_ids = set(re.findall(r"archive\.org/download/([^/]+)/", text))
    known_names = {l.rsplit(",", 1)[-1].strip().lower() for l in lines if l.startswith("#EXTINF") and "tvg-type=" in l}

    skipped = {"license": 0, "known": 0, "downloads": 0, "no mp4": 0, "short": 0, "link": 0}
    pre, scanned, page = [], 0, 1
    seen_ids = set()
    while len(pre) < a.max_items * 2 and page <= 40:
        docs, total = search(a.collection, a.query, 100, page)
        if not docs:
            break
        for d in docs:
            scanned += 1
            if d["identifier"] in seen_ids:
                continue
            seen_ids.add(d["identifier"])
            if not license_ok(d, a.allow_cc_by, a.include_pre1930):
                skipped["license"] += 1; continue
            if a.exclude_words and re.search(r"\b(%s)\b" % a.exclude_words, str(d.get("title") or ""), re.I):
                skipped["license"] += 1; continue
            if d["identifier"] in known_ids:
                skipped["known"] += 1; continue
            if int(d.get("downloads") or 0) < a.min_downloads:
                skipped["downloads"] += 1; continue
            pre.append(d)
        page += 1

    def verify(d):
        lic = license_ok(d, a.allow_cc_by, a.include_pre1930)
        try:
            meta = get_json("https://archive.org/metadata/" + urllib.parse.quote(d["identifier"]))
        except Exception:
            return None, "no mp4"
        f = pick_file(meta.get("files", []))
        if not f:
            return None, "no mp4"
        mins = runtime_minutes(meta.get("metadata", {}))
        if mins is None or mins < a.min_minutes:
            return None, "short"
        url = "https://archive.org/download/%s/%s" % (urllib.parse.quote(d["identifier"]), urllib.parse.quote(f["name"]))
        ok, st = check_range(url)
        if not ok:
            return None, "link"
        year = str(d.get("year") or "")[:4]
        title = clean_title(d.get("title"), year)
        tm = tmdb_lookup(title, year)
        name = title + (" (%s)" % year if year and not tm else "") + (" {tmdb-%d}" % tm[0] if tm else "")
        grp = genre_group(tm[2], a.group) if tm else subject_group(d, a.group)
        logo = tm[1] if tm and tm[1] else "https://archive.org/services/img/" + urllib.parse.quote(d["identifier"])
        return dict(id=d["identifier"], name=name, group=grp, logo=logo, url=url, license=lic, year=year,
                    minutes=round(mins), mb=round(int(f["size"]) / 1e6), downloads=int(d.get("downloads") or 0)), None

    found, names = [], set(known_names)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(verify, pre))
    for r, why in results:
        if r is None:
            skipped[why] += 1; continue
        if r["name"].lower() in names:
            skipped["known"] += 1; continue
        if len(found) >= a.max_items:
            break
        names.add(r["name"].lower()); found.append(r)

    rep = ["# Internet Archive candidates (%s)" % ("APPLIED" if a.apply else "report only"), "",
           "Scanned %d items, %d candidates. Skipped: %s" % (scanned, len(found), skipped), "",
           "| # | Title | Group | Year | Min | MB | License | Downloads | Link |", "|---|---|---|---|---|---|---|---|---|"]
    for i, f in enumerate(found, 1):
        rep.append("| %d | %s | %s | %s | %s | %s | %s | %s | %s |" % (i, f["name"], f["group"], f["year"], f["minutes"], f["mb"], f["license"], f["downloads"], f["url"]))
    open(a.report, "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print("\n".join(rep))

    if a.apply and found:
        block = []
        for f in found:
            block += ['#EXTINF:-1 tvg-name="%s"tvg-id=""tvg-logo="%s"tvg-chno=""tvg-type="movie"group-title="%s":http-referrer="",%s' % (f["name"], f["logo"], f["group"], f["name"]), f["url"]]
        # insert after the last movie entry that comes before the first series (movies sit before series)
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
