"""Internet Archive adapter (public-domain / CC0 and, optionally, CC-BY items only)."""
import re, urllib.parse
from concurrent.futures import ThreadPoolExecutor

import archive_add as A
from .base import Source


class InternetArchive(Source):
    name = "internet_archive"
    allowed_licenses = ("public domain", "CC-BY (credit the creator)")
    distribution_policy = "uploader-declared public-domain / CC0 / CC-BY license (non-commercial licenses are rejected)"

    def discover(self, opts):
        y1 = opts.this_year - opts.secondary_years
        yield_budget = opts.max_scan
        query = "year:[%d TO %d]" % (y1, opts.this_year + 1)
        if opts.query:
            query += " AND (%s)" % opts.query
        seen, scanned, page = set(), 0, 1

        def fetch(d):
            try:
                meta = A.get_json("https://archive.org/metadata/" + urllib.parse.quote(d["identifier"]))
            except Exception:
                return d, None
            return d, meta

        with ThreadPoolExecutor(max_workers=8) as ex:
            while scanned < yield_budget:
                try:
                    docs, _ = A.search(opts.collection, query, 100, page)
                except Exception:
                    break
                if not docs:
                    break
                batch = []
                for d in docs:
                    scanned += 1
                    if d["identifier"] in seen:
                        continue
                    seen.add(d["identifier"])
                    lic = A.license_ok(d, opts.allow_cc_by, False)
                    if not lic:
                        yield "reject", {"title": d.get("title"), "reason": "license_not_permitted"}
                        continue
                    d["_license"] = lic
                    batch.append(d)
                for d, meta in ex.map(fetch, batch):
                    if not meta:
                        yield "reject", {"title": d.get("title"), "reason": "metadata_unavailable"}
                        continue
                    f = A.pick_file(meta.get("files", []), min_height=opts.min_height)
                    if not f:
                        yield "reject", {"title": d.get("title"), "reason": "no_mp4_file"}
                        continue
                    w, h = A.file_dims(f)
                    mins = A.runtime_minutes(meta.get("metadata", {})) or 0
                    url = "https://archive.org/download/%s/%s" % (urllib.parse.quote(d["identifier"]), urllib.parse.quote(f["name"]))
                    yield "candidate", self.candidate(
                        source=self.name, sid=d["identifier"], title=A.clean_title(d.get("title"), d.get("year")), year=str(d.get("year") or "")[:4],
                        url=url, fmt="mp4", width=w, height=h, minutes=mins, mb=round(int(f.get("size") or 0) / 1e6),
                        license=d["_license"], logo="https://archive.org/services/img/" + urllib.parse.quote(d["identifier"]),
                        subjects=d.get("subject") or [], downloads=int(d.get("downloads") or 0))
                page += 1
