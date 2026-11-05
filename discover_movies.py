#!/usr/bin/env python3
"""New-movie discovery and import (dry run by default).

Only AUTHORIZED sources (see sources/), only recent movies (default: released in the last 2 years, secondary pool up to
5 years, older rejected), only verified Full HD / 4K (both dimensions checked), never a duplicate (TMDB id, then
normalized title + year, URL, source id), always a report first. The playlist is written only with --apply and only when
validation succeeds (existing lines untouched, new blocks well-formed).

TMDB_API_KEY is REQUIRED for release dates, ratings and duplicate checks by TMDB id (use --allow-no-tmdb only for tests).
Usage: python3 discover_movies.py [--apply] [--max-items 20] [--primary-years 2] [--secondary-years 5] [--min-height 1080]
"""
import argparse, datetime, json, os, re, sys, urllib.parse
from concurrent.futures import ThreadPoolExecutor

sys.dont_write_bytecode = True
import archive_add as A
import movie_engine as E
from sources import get_sources

REJECT_TEXT = {
    "license_not_permitted": "license does not permit distribution", "format_not_allowed": "format not allowed (mp4/m3u8 only)",
    "not_https": "link is not https", "missing_title": "missing title", "too_short": "shorter than a feature film",
    "unknown_quality": "resolution could not be verified", "resolution_below_1080p": "below the minimum resolution",
    "no_tmdb_match": "no exact TMDB match (release date/rating unavailable)", "older_than_limit": "older than the allowed years",
    "unreleased": "not released yet", "rating_too_low": "rating below the minimum", "too_few_votes": "too few TMDB votes",
    "link_failed": "video URL not accessible / no Range support", "resolution_mismatch": "stream resolution differs from metadata",
    "no_mp4_file": "no usable video file", "metadata_unavailable": "metadata unavailable", "excluded_content": "family filter",
}


class Tmdb:
    def __init__(self, key=None):
        self.key = key if key is not None else os.environ.get("TMDB_API_KEY", "")
        self.cache = {}

    @property
    def available(self):
        return bool(self.key)

    def lookup(self, title, year):
        """Exact (normalized) title match, year +-1 when known. Returns None or a dict with id/year/rating/votes/popularity/genres."""
        if not self.available:
            return None
        k = (E.normalize_title(title), str(year))
        if k in self.cache:
            return self.cache[k]
        res = None
        years = [str(year), str(int(year) + 1), str(int(year) - 1)] if str(year).isdigit() else [None]
        for y in years:
            p = {"api_key": self.key, "query": title}
            if y:
                p["year"] = y
            try:
                results = A.get_json("https://api.themoviedb.org/3/search/movie?" + urllib.parse.urlencode(p), 20).get("results", [])
            except Exception:
                continue
            for r in results[:6]:
                if E.normalize_title(r.get("title")) == k[0] or E.normalize_title(r.get("original_title")) == k[0]:
                    try:
                        det = A.get_json("https://api.themoviedb.org/3/movie/%d?api_key=%s" % (r["id"], self.key), 20)
                    except Exception:
                        det = r
                    res = dict(id=r["id"], title=det.get("title") or r.get("title"), release=(det.get("release_date") or "")[:10],
                               year=(det.get("release_date") or "")[:4], vote_average=det.get("vote_average") or 0,
                               vote_count=det.get("vote_count") or 0, popularity=det.get("popularity") or 0,
                               genres=[g["name"] for g in det.get("genres", [])], poster=det.get("poster_path") or r.get("poster_path"))
                    break
            if res:
                break
        self.cache[k] = res
        return res


def evaluate(c, opts, tmdb, idx):
    """Run ONE candidate through every rule. Returns (accepted_dict | None, reason | None). Cheap checks first, network last."""
    why = E.validate_source_candidate(c, opts.allowed_licenses, opts.formats, require_https=True)
    if why:
        return None, why
    if opts.exclude_words and re.search(r"\b(%s)\b" % opts.exclude_words, c["title"], re.I):
        return None, "excluded_content"
    if (c["minutes"] or 0) < opts.min_minutes:
        return None, "too_short"
    verdict = E.classify_resolution(c["width"], c["height"], opts.min_height)
    if verdict == "unknown":
        return None, "unknown_quality"
    if verdict == "reject_low":
        return None, "resolution_below_1080p"
    info = tmdb.lookup(c["title"], c["year"])
    if not info and not opts.allow_no_tmdb:
        return None, "no_tmdb_match"
    year = info["year"] if info else c["year"]
    tier = E.release_tier(year, opts.this_year, opts.primary_years, opts.secondary_years)
    if tier in ("too_old", "unreleased"):
        return None, "older_than_limit" if tier == "too_old" else "unreleased"
    if tier == "unknown" and not opts.allow_no_tmdb:
        return None, "no_tmdb_match"
    if info and info["vote_average"] < opts.min_rating:
        return None, "rating_too_low"
    if info and info["vote_count"] < opts.min_votes:
        return None, "too_few_votes"
    dup = E.duplicate_reason(idx, tmdb_id=info["id"] if info else None, title=(info or {}).get("title") or c["title"], year=year,
                             url=c["url"], source_id=c["sid"])
    if dup:
        return None, dup
    ok, _ = A.check_range(c["url"]) if c["fmt"] in ("mp4", "webm") else (True, 0)
    if not ok:
        return None, "link_failed"
    probed = A.probe_resolution(c["url"]) if opts.min_height > 0 else None
    if probed and E.classify_resolution(probed[0], probed[1], opts.min_height) in ("reject_low", "unknown"):
        return None, "resolution_mismatch"
    if probed:
        c["width"], c["height"] = probed
        verdict = E.classify_resolution(probed[0], probed[1], opts.min_height)
    res = "2160p" if verdict == "accept_4k" else ("1080p" if verdict == "accept_1080p" else "%dx%d" % (c["width"], c["height"]))
    out = dict(c, verdict=verdict, tier=tier, res=res, release_year=year, tmdb=info,
               vote_average=(info or {}).get("vote_average", 0), vote_count=(info or {}).get("vote_count", 0), popularity=(info or {}).get("popularity", 0))
    return out, None


def run(opts, text, snapshot_text, tmdb=None, sources=None):
    tmdb = tmdb or Tmdb()
    sources = sources if sources is not None else get_sources(opts.source_names)
    idx = E.ExistingIndex.from_m3u(text, snapshot_text)
    rejected, accepted, scanned = [], [], 0
    reasons = {}
    for src in sources:
        opts.allowed_licenses = src.allowed_licenses
        cands = []
        for kind, obj in src.discover(opts):
            scanned += 1
            if kind == "reject":
                rejected.append((src.name, obj.get("title"), obj["reason"])); reasons[obj["reason"]] = reasons.get(obj["reason"], 0) + 1
            else:
                cands.append(obj)
        for c in cands:
            res, why = evaluate(c, opts, tmdb, idx)
            if res is None:
                rejected.append((src.name, c["title"], why)); reasons[why] = reasons.get(why, 0) + 1; continue
            # same movie from two sources (or twice): keep only the first, the engine remembers it
            idx.add(name=(res["tmdb"] or {}).get("title") or res["title"], url=res["url"], tmdb_id=(res["tmdb"] or {}).get("id"),
                    year=res["release_year"], source_id=res["sid"])
            accepted.append(res)
    accepted.sort(key=E.rank_key)
    accepted = accepted[:opts.max_items]
    return accepted, rejected, reasons, scanned


def report_lines(opts, accepted, rejected, reasons, scanned, tmdb_available):
    n = lambda k: reasons.get(k, 0)
    lines = ["# New-movie discovery report (%s)" % ("APPLY" if opts.apply else "DRY RUN, nothing changed"), "",
             "Sources: %s | years: last %d (primary) / last %d (secondary), older rejected | minimum resolution: %s (both dimensions) | min length %d min"
             % (", ".join(opts.source_names), opts.primary_years, opts.secondary_years, ("%dp" % opts.min_height) if opts.min_height else "none", opts.min_minutes), ""]
    if not tmdb_available:
        lines += ["> **TMDB_API_KEY is missing**: release dates, ratings and TMDB duplicate checks are unavailable, so nothing can be accepted. Add the key as a repository secret.", ""]
    lines += ["| Statistic | Count |", "|---|---|", "| Candidates examined | %d |" % scanned,
              "| **Accepted** (primary / secondary) | **%d** (%d / %d) |" % (len(accepted), sum(a["tier"] == "primary" for a in accepted), sum(a["tier"] == "secondary" for a in accepted)),
              "| Accepted 4K / 1080p | %d / %d |" % (sum(a["verdict"] == "accept_4k" for a in accepted), sum(a["verdict"] == "accept_1080p" for a in accepted)),
              "| Rejected: below 1080p | %d |" % n("resolution_below_1080p"), "| Rejected: unknown resolution | %d |" % n("unknown_quality"),
              "| Rejected: license / source policy | %d |" % (n("license_not_permitted") + n("excluded_content")),
              "| Rejected: format not allowed (webm...) | %d |" % n("format_not_allowed"),
              "| Rejected: older than allowed years | %d |" % n("older_than_limit"), "| Rejected: no TMDB match | %d |" % n("no_tmdb_match"),
              "| Rejected: duplicates | %d |" % sum(v for k, v in reasons.items() if k.startswith("duplicate")),
              "| Rejected: too short / low rating / few votes | %d / %d / %d |" % (n("too_short"), n("rating_too_low"), n("too_few_votes")),
              "| Rejected: link failed / resolution mismatch | %d / %d |" % (n("link_failed"), n("resolution_mismatch")),
              "| Rejected: no usable video file / metadata unavailable | %d |" % (n("no_mp4_file") + n("metadata_unavailable")), ""]
    lines += ["## Accepted (ranked)", "", "| # | Title | Released | Tier | Source | Res | Rating (votes) | License | Link |", "|---|---|---|---|---|---|---|---|---|"]
    for i, a in enumerate(accepted, 1):
        lines.append("| %d | %s | %s | %s | %s | %s | %.1f (%d) | %s | %s |" % (i, (a["tmdb"] or {}).get("title") or a["title"], a["release_year"], a["tier"], a["source"], a["res"],
                                                                         a["vote_average"], a["vote_count"], a["license"], a["url"]))
    if not accepted:
        lines.append("| - | none | | | | | | | |")
    lines += ["", "## Rejected (first 150, with the reason)", "", "| Source | Title | Reason |", "|---|---|---|"]
    for s, t, why in rejected[:150]:
        lines.append("| %s | %s | %s |" % (s, str(t)[:70].replace("|", "/"), REJECT_TEXT.get(why, why)))
    return lines


def apply_to_playlist(opts, accepted, tmdb):
    with open(opts.playlist, encoding="utf-8") as fh:
        before = fh.read().split("\n")
    blocks = []
    for a in accepted:
        info = a["tmdb"]
        name = "%s {tmdb-%d}" % (info["title"], info["id"]) if info else "%s (%s)" % (a["title"], a["release_year"])
        logo = ("https://media.themoviedb.org/t/p/w600_and_h900_face" + info["poster"]) if info and info.get("poster") else (a["logo"] or "")
        group = A.genre_group(info["genres"], opts.group) if info else opts.group
        blocks.append(['#EXTINF:-1 tvg-name="%s"tvg-id=""tvg-logo="%s"tvg-chno=""tvg-type="movie"group-title="%s":http-referrer="",%s' % (name, logo, group, name), a["url"]])
    after = list(before)
    first_series = next((i for i, l in enumerate(after) if l.startswith("#EXTINF") and 'tvg-type="series"' in l), len(after))
    last = None
    for i, l in enumerate(after[:first_series]):
        if l.startswith("#EXTINF") and 'tvg-type="movie"' in l:
            j = i + 1
            while j < len(after) and after[j].startswith("#"):
                j += 1
            last = j
    pos = (last + 1) if last is not None else first_series
    new_after = after[:pos] + [l for b in blocks for l in b] + after[pos:]
    problems = E.validate_write(before, new_after, blocks)
    if problems:
        return problems
    with open(opts.playlist, "w", encoding="utf-8") as fh:
        fh.write("\n".join(new_after))
    return []


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="internet_archive,wikimedia", help="comma separated adapters (see sources/)")
    ap.add_argument("--playlist", default="playlist.m3u")
    ap.add_argument("--snapshot", default="library/playlist.snapshot.m3u")
    ap.add_argument("--max-items", type=int, default=20)
    ap.add_argument("--primary-years", type=int, default=2)
    ap.add_argument("--secondary-years", type=int, default=5)
    ap.add_argument("--min-height", type=int, default=1080)
    ap.add_argument("--min-minutes", type=float, default=40)
    ap.add_argument("--min-rating", type=float, default=0.0)
    ap.add_argument("--min-votes", type=int, default=0)
    ap.add_argument("--group", default="Recent Movies")
    ap.add_argument("--collection", default="")
    ap.add_argument("--query", default="")
    ap.add_argument("--max-scan", type=int, default=2000)
    ap.add_argument("--allow-cc-by", action="store_true")
    ap.add_argument("--allow-webm", action="store_true", help="also accept webm/ogv (Wikimedia Commons only has these)")
    ap.add_argument("--allow-no-tmdb", action="store_true", help="TESTING ONLY: skip the TMDB requirement")
    ap.add_argument("--exclude-words", default=r"naked|nude|sex|sexy|erotic|porn|strip(per|tease)?|burlesque|bikini|topless|lust|orgy|harem")
    ap.add_argument("--apply", action="store_true", help="write the playlist (default: dry run, report only)")
    ap.add_argument("--report", default="archive-report.md")
    o = ap.parse_args(argv)
    o.source_names = [s.strip() for s in o.sources.split(",") if s.strip()]
    o.this_year = datetime.date.today().year
    o.formats = ("mp4", "m3u8", "webm", "ogv") if o.allow_webm else ("mp4", "m3u8")
    return o


def main(argv=None):
    opts = parse_args(argv)
    def read(path, default=""):
        if not os.path.exists(path):
            return default
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    text, snap = read(opts.playlist, "#EXTM3U\n"), read(opts.snapshot)
    tmdb = Tmdb()
    accepted, rejected, reasons, scanned = run(opts, text, snap, tmdb)
    lines = report_lines(opts, accepted, rejected, reasons, scanned, tmdb.available)
    with open(opts.report, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    if opts.apply and accepted:
        problems = apply_to_playlist(opts, accepted, tmdb)
        if problems:
            print("VALIDATION FAILED, playlist NOT modified:", *problems, sep="\n  - ")
            return 2
        print("Added %d movies to %s" % (len(accepted), opts.playlist))
    elif opts.apply:
        print("Nothing accepted: playlist not modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
