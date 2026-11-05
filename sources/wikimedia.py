"""Wikimedia Commons adapter: videos with a machine-readable free license (public domain / CC0 / CC-BY(-SA)).
Commons only hosts open formats (webm/ogv), so candidates are rejected as 'format_not_allowed' unless --allow-webm."""
import json, re, urllib.parse, urllib.request

from .base import Source

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "AndamIPTV-import-tool/1.0 (movie discovery; contact: repository owner)"}
FREE = re.compile(r"^(public domain|cc0|pd[- ]|cc[- ]by(?!-nc)|cc[- ]by-sa(?!-nc))", re.I)
NONFREE = re.compile(r"\b(nc|nd|fair use|all rights reserved)\b", re.I)


def license_label(extmeta):
    """Return our license label or None; unknown / non-free / NC licenses are never accepted."""
    short = (extmeta.get("LicenseShortName") or {}).get("value", "") or ""
    if not short or NONFREE.search(short):
        return None
    if re.match(r"^(public domain|cc0|pd)", short, re.I):
        return "public domain"
    if FREE.match(short):
        return "CC-BY (credit the creator)"
    return None


def api(**p):
    p["format"] = "json"
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(p), headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


class WikimediaCommons(Source):
    name = "wikimedia"
    allowed_licenses = ("public domain", "CC-BY (credit the creator)")
    distribution_policy = "free licenses recorded in the file page metadata (public domain, CC0, CC-BY, CC-BY-SA)"

    def discover(self, opts):
        years = " OR ".join(str(y) for y in range(opts.this_year - opts.secondary_years, opts.this_year + 1))
        terms = [opts.query] if opts.query else ["feature film %s" % years, "full movie %s" % years, "film %s" % years]
        seen = set()
        for term in terms:
            offset = 0
            for _ in range(6):
                try:
                    r = api(action="query", generator="search", gsrsearch="filetype:video " + term, gsrnamespace=6, gsrlimit=50,
                            gsroffset=offset, prop="imageinfo", iiprop="url|size|mime|extmetadata",
                            iiextmetadatafilter="LicenseShortName|ImageDescription")
                except Exception:
                    break
                pages = (r.get("query") or {}).get("pages") or {}
                for pid, pg in pages.items():
                    if pg["title"] in seen or not pg.get("imageinfo"):
                        continue
                    seen.add(pg["title"])
                    ii = pg["imageinfo"][0]
                    lab = license_label(ii.get("extmetadata", {}))
                    title = re.sub(r"^File:|\.(webm|ogv|ogg|mp4)$", "", pg["title"], flags=re.I)
                    if not lab:
                        yield "reject", {"title": title, "reason": "license_not_permitted"}
                        continue
                    mime = ii.get("mime", "")
                    fmt = "webm" if "webm" in mime else ("ogv" if "ogg" in mime else ("mp4" if "mp4" in mime else mime))
                    y = re.search(r"\b((?:19|20)\d\d)\b", title)
                    yield "candidate", self.candidate(
                        source=self.name, sid=pg["title"], title=re.sub(r"\s*[\(\[]?\b(?:19|20)\d\d\b[\)\]]?\s*$", "", title).strip(),
                        year=y.group(1) if y else "", url=ii.get("url", ""), fmt=fmt, width=ii.get("width") or 0, height=ii.get("height") or 0,
                        minutes=float(ii.get("duration") or 0) / 60, mb=round((ii.get("size") or 0) / 1e6), license=lab)
                if "continue" not in r:
                    break
                offset = r["continue"].get("gsroffset", offset + 50)
