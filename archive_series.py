#!/usr/bin/env python3
"""Add LICENSED (public domain) classic cartoon SERIES from the Internet Archive to playlist.m3u.

Each show is a title pattern on archive.org (Betty Boop, Popeye, Superman 1941, Felix the Cat, Private Snafu ...).
Episodes become `Show - S01E01`, `tvg-type="series"` entries in the group "Classic Cartoons". Only public-domain
license items with a verified h.264 mp4 (HTTP 206 on a Range request) are used; nothing is stored on your side.
Usage: python3 archive_series.py [--apply] [--max-per-show 60]
"""
import argparse, os, re, sys, urllib.parse
sys.dont_write_bytecode = True
import archive_add as A
from concurrent.futures import ThreadPoolExecutor

SHOWS = [  # (show name, regex on the archive.org title, extra regex that must NOT match)
    ("Betty Boop", r"^betty boop", r"musical|collection|compilation"),
    ("Popeye the Sailor", r"^popeye", r"collection|compilation|vol\.?\s*\d"),
    ("Superman", r"^superman", r"lois|returns|vs\.?|batman|collection|compilation"),
    ("Felix the Cat", r"^felix", r"collection|compilation"),
    ("Private Snafu", r"snafu", r"collection|compilation"),
    ("Koko the Clown", r"koko|inkwell", r"collection|compilation"),
    ("Bosko", r"bosko", r"collection|compilation"),
    ("Mutt and Jeff", r"mutt (and|&) jeff", r"collection|compilation"),
    ("Krazy Kat", r"krazy", r"collection|compilation"),
    ("Oswald the Lucky Rabbit", r"oswald", r"collection|compilation"),
]
QUERY = {"Koko the Clown": "title:(koko* OR inkwell*)", "Mutt and Jeff": "title:(mutt*)", "Oswald the Lucky Rabbit": "title:(oswald*)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--playlist", default="playlist.m3u")
    ap.add_argument("--group", default="Classic Cartoons")
    ap.add_argument("--max-per-show", type=int, default=60)
    ap.add_argument("--min-minutes", type=float, default=3)
    ap.add_argument("--min-episodes", type=int, default=3, help="skip shows with fewer verified episodes")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="archive-series-report.md")
    a = ap.parse_args()
    text = open(a.playlist, encoding="utf-8").read()
    lines = text.split("\n")
    known_ids = set(re.findall(r"archive\.org/download/([^/]+)/", text))
    block, rep = [], ["# Classic cartoon series candidates", ""]
    for show, rx, bad in SHOWS:
        docs = []
        for page in (1, 2, 3):
            d, _ = A.search("animationandcartoons", QUERY.get(show, "title:(%s*)" % show.split()[0].lower()), 100, page)
            docs += d
            if len(d) < 100:
                break
        seen, cand = set(), []
        for d in docs:
            t = str(d.get("title") or "")
            if not re.search(rx, t, re.I) or re.search(bad, t, re.I) or d["identifier"] in known_ids or d["identifier"] in seen:
                continue
            if not A.license_ok(d, False, False):
                continue
            seen.add(d["identifier"]); cand.append(d)

        def verify(d):
            try:
                meta = A.get_json("https://archive.org/metadata/" + urllib.parse.quote(d["identifier"]))
            except Exception:
                return None
            f = A.pick_file(meta.get("files", []), min_size=3_000_000)
            if not f:
                return None
            mins = A.runtime_minutes(meta.get("metadata", {}))
            if mins is None or not (a.min_minutes <= mins <= 30):
                return None
            url = "https://archive.org/download/%s/%s" % (urllib.parse.quote(d["identifier"]), urllib.parse.quote(f["name"]))
            ok, _ = A.check_range(url)
            return dict(d=d, url=url, mins=round(mins, 1)) if ok else None

        with ThreadPoolExecutor(max_workers=8) as ex:
            ok = [r for r in ex.map(verify, cand) if r]
        norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
        uniq, tseen = [], set()
        for r in sorted(ok, key=lambda r: (str(r["d"].get("year") or "9999")[:4], str(r["d"].get("title")))):
            k = norm(r["d"]["title"])
            if k in tseen:
                continue
            tseen.add(k); uniq.append(r)
        uniq = uniq[:a.max_per_show]
        if len(uniq) < a.min_episodes:
            continue
        rep.append("## %s: %d episodes" % (show, len(uniq)))
        for n, r in enumerate(uniq, 1):
            name = "%s - S01E%02d" % (show, n)
            logo = "https://archive.org/services/img/" + urllib.parse.quote(r["d"]["identifier"])
            rep.append("- %s = %s (%s, %s min)" % (name, A.clean_title(r["d"]["title"], ""), str(r["d"].get("year") or "?")[:4], r["mins"]))
            block += ['#EXTINF:-1 tvg-name="%s"tvg-id=""tvg-logo="%s"tvg-chno=""tvg-type="series"group-title="%s":http-referrer="",%s' % (name, logo, a.group, name), r["url"]]
    open(a.report, "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print("\n".join(rep[:60]))
    if a.apply and block:
        lines = [l for l in lines]
        while lines and lines[-1] == "":
            lines.pop()
        lines += block + [""]
        open(a.playlist, "w", encoding="utf-8").write("\n".join(lines))
        print("Added %d episodes" % (len(block) // 2))


if __name__ == "__main__":
    sys.exit(main())
