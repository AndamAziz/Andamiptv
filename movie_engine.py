"""Pure logic of the movie importer (no network): resolution, release-year tiers, duplicate detection, ranking and
playlist write validation. Everything here is unit-tested in tests/."""
import math, re, unicodedata


# ---------------------------------------------------------------- resolution
def classify_resolution(width, height, min_height=1080):
    """Decide from REAL pixel dimensions (never from a file name or title).

    Both dimensions must meet the threshold, orientation-independent: the long side must be >= 16/9 of min_height and the
    short side >= min_height (1080p = 1920 x 1080 landscape or 1080 x 1920 portrait; 4K = 3840 x 2160).
    Returns 'accept_4k', 'accept_1080p', 'accept_below' (only when the filter is relaxed), 'reject_low' or 'unknown'.
    min_height <= 0 turns the filter off (any KNOWN resolution passes)."""
    try:
        w, h = int(width or 0), int(height or 0)
    except (TypeError, ValueError):
        return "unknown"
    if w <= 0 or h <= 0:
        return "unknown"
    long_, short = max(w, h), min(w, h)
    if long_ >= 3840 and short >= 2160:
        return "accept_4k"
    if long_ >= 1920 and short >= 1080:
        return "accept_1080p"
    if min_height <= 0:
        return "accept_below"
    need_long = round(min_height * 16 / 9)
    if long_ >= need_long and short >= min_height:
        return "accept_below"
    return "reject_low"


# ---------------------------------------------------------------- release year
def release_tier(year, this_year, primary_years=2, secondary_years=5):
    """'primary' (last N years), 'secondary' (last M years), 'too_old', 'unreleased' or 'unknown'."""
    try:
        y = int(str(year)[:4])
    except (TypeError, ValueError):
        return "unknown"
    age = this_year - y
    if age < 0:
        return "unreleased"
    if age <= primary_years:
        return "primary"
    if age <= secondary_years:
        return "secondary"
    return "too_old"


# ---------------------------------------------------------------- duplicates
def normalize_title(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"\{tmdb-\d+\}", " ", t, flags=re.I)
    t = re.sub(r"[\(\[]\s*(18|19|20)\d\d\s*[\)\]]", " ", t)
    t = re.sub(r"\s[-–]\s*S\d+E\d+.*$", " ", t, flags=re.I)
    t = t.lower().replace("&", " and ")
    t = re.sub(r"^(the|a|an)\s+", "", t.strip())
    return re.sub(r"[^a-z0-9]", "", t)


def _norm_url(u):
    return re.sub(r"^https?://", "", str(u or "").strip().lower()).rstrip("/")


class ExistingIndex:
    """Everything already known: playlist movies + snapshot (the 'database') + whatever was accepted in this run."""

    def __init__(self):
        self.tmdb_ids, self.title_year, self.titles_no_year, self.urls, self.source_ids = set(), set(), set(), set(), set()

    def add(self, name=None, url=None, tmdb_id=None, year=None, source_id=None):
        if tmdb_id:
            self.tmdb_ids.add(int(tmdb_id))
        if name:
            n = normalize_title(name)
            if n:
                (self.title_year.add((n, str(year))) if year else self.titles_no_year.add(n))
        if url:
            self.urls.add(_norm_url(url))
        if source_id:
            self.source_ids.add(source_id)

    @classmethod
    def from_m3u(cls, *texts):
        idx = cls()
        for text in texts:
            lines = (text or "").split("\n")
            for i, l in enumerate(lines):
                if not l.startswith("#EXTINF"):
                    continue
                nxt = next((x for x in lines[i + 1:i + 4] if x and not x.startswith("#")), "")
                name = l.rsplit(",", 1)[-1].strip()
                m = re.search(r"\{tmdb-(\d+)\}", name)
                y = re.search(r"[\(\[]\s*((?:18|19|20)\d\d)\s*[\)\]]", name)
                is_movie = 'tvg-type="movie"' in l
                if is_movie:
                    idx.add(name=name, url=nxt, tmdb_id=m.group(1) if m else None, year=y.group(1) if y else None)
                elif nxt:
                    idx.urls.add(_norm_url(nxt))
                am = re.search(r"archive\.org/download/([^/]+)/", nxt)
                if am:
                    idx.source_ids.add(am.group(1))
        return idx


def duplicate_reason(idx, tmdb_id=None, title=None, year=None, url=None, source_id=None):
    """TMDB id first, then normalized title + release year; also URL and source id. Returns a reason or None."""
    if tmdb_id and int(tmdb_id) in idx.tmdb_ids:
        return "duplicate_tmdb_id"
    n = normalize_title(title)
    if n and year and (n, str(year)) in idx.title_year:
        return "duplicate_title_year"
    if n and n in idx.titles_no_year:                # an existing entry without a year: same title = same movie
        return "duplicate_title"
    if url and _norm_url(url) in idx.urls:
        return "duplicate_url"
    if source_id and source_id in idx.source_ids:
        return "duplicate_source_id"
    return None


# ---------------------------------------------------------------- ranking
TIER_RANK = {"primary": 0, "secondary": 1}
RES_RANK = {"accept_4k": 0, "accept_1080p": 1, "accept_below": 2}


def usefulness(vote_average, vote_count, popularity):
    """Well-rated AND well-known beats either alone."""
    return float(vote_average or 0) * math.log10(float(vote_count or 0) + 10) + float(popularity or 0) / 100.0


def rank_key(c):
    """Sort key (ascending): recent tier first, then 4K before 1080p, then the most useful movie first."""
    return (TIER_RANK.get(c["tier"], 9), RES_RANK.get(c["verdict"], 9), -usefulness(c.get("vote_average"), c.get("vote_count"), c.get("popularity")))


# ---------------------------------------------------------------- source validation
def validate_source_candidate(c, allowed_licenses, allowed_formats=("mp4", "m3u8"), require_https=True):
    """Returns a rejection reason or None. A source may only offer content whose license permits streaming/distribution."""
    if not c.get("license") or c["license"] not in allowed_licenses:
        return "license_not_permitted"
    if c.get("fmt") not in allowed_formats:
        return "format_not_allowed"
    if require_https and not str(c.get("url", "")).lower().startswith("https://"):
        return "not_https"
    if not c.get("title"):
        return "missing_title"
    return None


# ---------------------------------------------------------------- safe write
def validate_write(before_lines, after_lines, added_blocks):
    """Problems that must stop a write: existing lines must be untouched and in order, only the new blocks added,
    every new block a well-formed EXTINF + https URL, no duplicate URLs."""
    problems = []
    it = iter(after_lines)
    if not all(any(a == b for a in it) for b in before_lines):
        problems.append("existing playlist lines were removed or reordered")
    expected = len(before_lines) + sum(len(b) for b in added_blocks)
    if len(after_lines) != expected:
        problems.append("unexpected number of lines (%d, expected %d)" % (len(after_lines), expected))
    urls = [l for l in after_lines if l and not l.startswith("#")]
    dups = {u for u in urls if urls.count(u) > 1} - {u for u in before_lines if u and not u.startswith("#") and before_lines.count(u) > 1}
    if dups:
        problems.append("duplicate URLs after the write: %s" % sorted(dups)[:3])
    for b in added_blocks:
        if len(b) != 2 or not b[0].startswith("#EXTINF") or 'tvg-type="movie"' not in b[0] or not b[1].lower().startswith("https://"):
            problems.append("malformed new block: %s" % b[:1])
    return problems
