#!/usr/bin/env python3
"""
showtv_sync.py - keep the series of a playlist group complete, with official broadcaster links.

Sources ("providers"):
  * showtv - Show TV series, official MP4 on vmcdn.ciner.com.tr (found through showtv.com.tr search)
  * tabii  - TRT series, official clear (DRM-free) HLS on eu1.tabii.com (found through tabii's
             public sitemap; IDs can also be set in tabii-series.json)
  * tv8    - TV8 series, official token-free MP4 on video-cdn.tv8.com.tr (found through TV8's
             programme lists; slugs can also be set in tv8-series.json)

For every series in the group (default "Turkish Drama", entries named "Title {tmdb-ID} - SxxEyy"):
  1. find the series at the provider; a series it does not have is left alone;
  2. read the official episode list;
  3. for every episode:
       * already on the provider's official server        -> nothing changes (no request made)
       * in the playlist with another link                -> the URL line is replaced by the official
                                                             link (best quality that plays); when none
                                                             plays, the old link is KEPT
       * not in the playlist yet                          -> added with the same name format, poster
                                                             and group as the series' other episodes,
                                                             only when an official link plays
  4. the episodes of each series are put back in order (S, E); series keep their place.

Nothing is ever deleted. Links with a short-lived token are never written (both providers serve
token-free URLs). Episodes are numbered like the rest of the playlist: S01 + absolute episode number, or per season
(S02E01 ...) for a series whose episodes in the playlist already use seasons.

Usage:
  python showtv_sync.py playlist.m3u                                   # report only, all providers
  python showtv_sync.py playlist.m3u --apply                           # also rewrite playlist.m3u
  python showtv_sync.py playlist.m3u --apply --provider tabii --only "Teşkilat"
"""
import argparse
import html
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _Redirect(HTTPRedirectHandler):
    """Also follow 308 (tabii answers /tr/detail/<id> with 308 -> /tr/detail/<id>/<slug>);
    Python before 3.11 does not."""
    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_302(req, fp, 302, msg, headers)


_OPENER = build_opener(_Redirect())


def urlopen(req, timeout=25):
    return _OPENER.open(req, timeout=timeout)

sys.dont_write_bytecode = True

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NAME_RE = re.compile(r'tvg-name="(.*?) - S(\d+)E(\d+)"')
TMDB_RE = re.compile(r"\s*\{tmdb-\d+\}\s*$")
HERE = Path(__file__).resolve().parent


def key(s):
    s = unicodedata.normalize("NFKD", s.replace("ı", "i").replace("İ", "I"))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)).lower())


# ---------------------------------------------------------------- network (patched in tests)
def fetch(url, timeout=25, tries=3):
    for i in range(tries):
        try:
            with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def link_ok(url, timeout=25, tries=3):
    """True when the server answers with media (a short network hiccup is retried)."""
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1023"})
            with urlopen(req, timeout=timeout) as r:
                body = r.read(1024)
                if r.status in (200, 206) and body and (".m3u8" not in url or body.lstrip().startswith(b"#EXTM3U")):
                    return True
        except Exception:
            pass
        if i < tries - 1:
            time.sleep(2 * (i + 1))
    return False


def next_data(page_html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_html, re.S)
    return json.loads(m.group(1)) if m else {}


# ---------------------------------------------------------------- providers
class ShowTV:
    name, config = "showtv", "showtv-series.json"
    SITE = "https://www.showtv.com.tr"
    CDN = "vmcdn.ciner.com.tr"
    PAGE_RE = re.compile(r"^/(dizi|programlar)/tanitim/([a-z0-9-]+)/\d+$")
    TITLE_SUFFIXES = ("", "sonbolum", "finalbolumu")

    def __init__(self, overrides=None):
        self.overrides = overrides or {}

    def is_official(self, url):
        return self.CDN in url

    def find(self, title):
        """Path of the series page (/dizi/tanitim/slug/id), or None when it is not a Show TV series."""
        if title in self.overrides:
            return self.overrides[title] or None
        try:
            items = json.loads(fetch(f"{self.SITE}/arama/oneriler?q={quote(title)}")).get("items", [])
        except Exception:
            return None
        want = {key(title) + s for s in self.TITLE_SUFFIXES}
        for it in items:
            if self.PAGE_RE.match(it.get("url", "")) and key(it.get("title", "")) in want:
                return it["url"]
        return None

    def episodes(self, page):
        """{episode number: episode page path} from the series page's episode selector."""
        return self.episode_list(fetch(self.SITE + page), page)

    def episode_list(self, page_html, page_path):
        kind, slug = self.PAGE_RE.match(page_path).groups()
        sub = "dizi/tum_bolumler" if kind == "dizi" else "programlar/videolar"
        rx = re.compile(rf'/{sub}/{re.escape(slug)}-sezon-(\d+)-bolum-(\d+)-izle/\d+')
        eps, self.seasons = {}, {}
        for m in rx.finditer(page_html):
            eps.setdefault(int(m.group(2)), m.group(0))
            self.seasons.setdefault(int(m.group(2)), int(m.group(1)))
        return eps

    def links(self, ref):
        return self.episode_mp4s(fetch(self.SITE + ref))

    def episode_mp4s(self, page_html):
        """MP4 links of the page's main player, best quality first."""
        t = html.unescape(page_html)
        m = re.search(r'"mp4"\s*:\s*(\[.*?\])', t, re.S)
        if not m:
            return []
        try:
            srcs = json.loads(m.group(1))
        except ValueError:
            return []
        def q(s):
            n = re.search(r"\d+", s.get("label", ""))
            return int(n.group()) if n else 0
        return [s["src"] for s in sorted(srcs, key=q, reverse=True) if self.CDN in s.get("src", "")]


class Tabii:
    name, config = "tabii", "tabii-series.json"
    SITE = "https://www.tabii.com"
    MEDIA = "https://eu1.tabii.com/apigateway/pbr/v1/media"
    DETAIL_RE = re.compile(r"https://www\.tabii\.com/tr/detail/(\d+)/([a-z0-9-]+)")

    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self._sitemap = None

    def is_official(self, url):
        return url.startswith(self.MEDIA + "/") or "eu1.tabii.com/apigateway/pbr/v1/media/" in url

    def sitemap(self):
        if self._sitemap is None:
            self._sitemap = {}
            try:
                for m in self.DETAIL_RE.finditer(fetch(f"{self.SITE}/sitemap-tr.xml")):
                    self._sitemap.setdefault(key(m.group(2)), m.group(1))
            except Exception:
                pass
        return self._sitemap

    def find(self, title):
        """tabii series id (str), or None."""
        if title in self.overrides:
            v = self.overrides[title]
            return str(v) if v else None
        return self.sitemap().get(key(title))

    def episodes(self, sid):
        """{absolute episode number: [clear HLS urls]} from the public series page."""
        data = next_data(fetch(f"{self.SITE}/tr/detail/{sid}")).get("props", {}).get("pageProps", {}).get("data") or {}
        if data.get("contentType") != "series":
            return {}
        rows = []
        for s in data.get("seasons") or []:
            for e in s.get("episodes") or []:
                urls = [f"{self.MEDIA}{m['url']}" for m in e.get("media") or []
                        if m.get("type") == "hls" and m.get("drmSchema") == "clear" and m.get("url", "").endswith(".m3u8")]
                rows.append((s.get("seasonNumber", 0), e.get("episodeNumber", 0), urls))
        nums = [n for _, n, _ in rows]
        if len(set(nums)) != len(nums):                         # numbering restarts every season
            rows.sort(key=lambda r: (r[0], r[1]))
            eps = {i: r[2] for i, r in enumerate(rows, 1)}
            self.seasons = {i: r[0] for i, r in enumerate(rows, 1)}
        else:
            eps = {n: u for _, n, u in rows}
            self.seasons = {n: s for s, n, _ in rows}
        self.owner = {u.replace("//apigateway", "/apigateway"): n for n, us in eps.items() for u in us}
        return eps

    def links(self, ref):
        return ref


class TV8:
    """TV8 series: official token-free MP4 on video-cdn.tv8.com.tr (<hash>-720p.mp4 ...).

    Only full episodes whose page is named "<series slug>-<N>-bolum-..." are used; trailers,
    clips and date-named programmes (MasterChef, Yemekteyiz: no episode number) are ignored."""
    name, config = "tv8", "tv8-series.json"
    SITE = "https://www.tv8.com.tr"
    CDN = "video-cdn.tv8.com.tr/"
    INDEX = ("/programlar", "/diziler", "/yarismalar")
    SKIP = ("tanitim", "fragman", "ozet", "kamera-arkasi", "kisa-video")
    QUALITIES = ("1080p", "720p", "480p")

    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self._index = None

    def is_official(self, url):
        return self.CDN in url and "?" not in url

    def index(self):
        """{key(programme name): slug} from TV8's programme lists."""
        if self._index is None:
            self._index = {}
            for page in self.INDEX:
                try:
                    t = fetch(self.SITE + page)
                except Exception:
                    continue
                for m in re.finditer(r'href="/([a-z0-9-]+)"[^>]*class="now-thumb-prog[^"]*"[^>]*>([^<]+)<', t):
                    self._index.setdefault(key(html.unescape(m.group(2))), m.group(1))
        return self._index

    def find(self, title):
        if title in self.overrides:
            return self.overrides[title] or None
        return self.index().get(key(title))

    def episodes(self, slug):
        """{episode number: episode page path} from the series' "tüm bölümler" list (all pages)."""
        rx = re.compile(rf'/{re.escape(slug)}/{re.escape(slug)}-(\d+)-bolum-[a-z0-9-]*?-?\d+-video\.htm')
        eps = {}
        for page in range(1, 100):
            d = json.loads(fetch(f"{self.SITE}/{slug}/tum-bolumler?page={page}&ajax=1"))
            for m in rx.finditer(d.get("html", "")):
                if not any(s in m.group(0) for s in self.SKIP):
                    eps.setdefault(int(m.group(1)), m.group(0))
            if not d.get("hasMore"):
                break
        return eps

    def links(self, ref):
        m = re.search(r"video-cdn\.tv8\.com\.tr/\d{4}/\d{2}/\d{2}/[0-9a-f]{32,40}", fetch(self.SITE + ref))
        return [f"https://{m.group(0)}-{q}.mp4" for q in self.QUALITIES] if m else []


PROVIDERS = {"showtv": ShowTV, "tabii": Tabii, "tv8": TV8}


# ---------------------------------------------------------------- playlist
def split_entries(text):
    lines = text.split("\n")
    trail = text.endswith("\n")
    if trail:
        lines = lines[:-1]
    head, entries, cur = [], [], None
    for ln in lines:
        if ln.startswith("#EXTINF"):
            cur = [ln]
            entries.append(cur)
        elif cur is None:
            head.append(ln)
        else:
            cur.append(ln)
    return head, entries, trail


def group_of(e):
    m = re.search(r'group-title="([^"]*)"', e[0])
    return m.group(1) if m else ""


def ep_key(e):
    m = NAME_RE.search(e[0])
    return (m.group(1), int(m.group(2)), int(m.group(3))) if m else None


def sync(text, group, provider, only=None, pause=0.3, log=print):
    head, entries, trail = split_entries(text)
    idx = [i for i, e in enumerate(entries) if group_of(e) == group and 'tvg-type="series"' in e[0] and ep_key(e)]
    stats = {"replaced": 0, "added": 0, "kept_no_link": 0, "missing_no_link": 0}
    if not idx:
        return text, stats
    if idx != list(range(idx[0], idx[-1] + 1)):
        raise SystemExit(f'group "{group}" is not one block in the playlist; not touching it')
    block = [entries[i] for i in idx]
    used = {e[-1].strip() for e in entries}      # a link is never written for a second episode
    shows = list(dict.fromkeys(ep_key(e)[0] for e in block))
    for show in shows:
        title = TMDB_RE.sub("", show)
        if only and title not in only and show not in only:
            continue
        ref = provider.find(title)
        if not ref:
            continue
        try:
            eps = provider.episodes(ref)
        except Exception as ex:
            log(f"- [{provider.name}] {title}: series page failed ({ex}), left as is")
            continue
        if not eps:
            log(f"- [{provider.name}] {title}: no episodes found, left as is")
            continue
        # S00 = extras without a known episode number (e.g. 'son bölüm' videos): never matched or touched
        own = [e for e in block if ep_key(e)[0] == show and ep_key(e)[1] != 0]
        if not own:
            continue
        # "S01E147" (absolute numbering) or "S02E01" (per season, when the playlist already has a
        # season above 1): per-season entries are matched through the provider's season list.
        seasons = getattr(provider, "seasons", None) or {}
        start = {}
        for a, s in seasons.items():
            start[s] = min(start.get(s, a), a)
        s1_last = max((a for a, s in seasons.items() if s == 1), default=0)
        # per season when the playlist already uses a season above 1, or when the provider has
        # several seasons and no S01 entry carries an absolute number past season 1
        seasonal = any(ep_key(e)[1] > 1 for e in own) or (
            len(start) > 1 and not any(ep_key(e)[1] == 1 and ep_key(e)[2] > s1_last for e in own))
        if seasonal and not start:
            log(f"- [{provider.name}] {title}: per-season numbering but no season list there, left as is")
            continue
        def absolute(e):
            _, s, x = ep_key(e)
            return (start[s] + x - 1 if s in start else None) if seasonal else x
        mine = {absolute(e): e for e in own if absolute(e) is not None}
        if not mine:
            # e.g. the provider no longer lists the seasons the playlist has: never guess
            log(f"- [{provider.name}] {title}: the playlist's seasons are not in the list there, left as is")
            continue
        if title not in provider.overrides and not any(provider.is_official(e[-1]) for e in mine.values()) \
                and max(eps) < max(mine):
            # same title, but far fewer episodes than the playlist has: another production
            # (e.g. a 1975 TRT "Aşk-ı Memnu" vs the Kanal D series). Set it in the json to force it.
            log(f"- [{provider.name}] {title}: skipped, the {len(eps)}-episode series there looks like "
                f"another production (playlist has up to E{max(mine)})")
            continue
        template = next(iter(mine.values()))
        _, t_season, t_ep = ep_key(template)
        done = []
        for n in sorted(eps):
            cur = mine.get(n)
            if cur is not None and provider.is_official(cur[-1]):
                # an official link that the provider itself lists under ANOTHER episode is a wrong
                # link (e.g. E73 carrying E72's video): correct it. Other official links stay.
                belongs = getattr(provider, "owner", {}).get(cur[-1].strip().replace("//apigateway", "/apigateway"))
                if belongs in (None, n) or not eps[n]:
                    continue
            if eps[n]:
                time.sleep(pause)                     # only before a real request
            try:
                links = provider.links(eps[n]) if eps[n] else []
            except Exception:
                links = []
            good = next((u for u in links if u not in used and link_ok(u)), None)
            if good:
                used.add(good)
            if cur is not None:
                if good:
                    cur[-1] = good
                    stats["replaced"] += 1
                    done.append(f"E{n} link->official")
                else:
                    stats["kept_no_link"] += 1
                    done.append(f"E{n} kept (no official link plays)")
            elif good:
                s, x = (seasons[n], n - start[seasons[n]] + 1) if seasonal else (t_season, n)
                old = f"{show} - S{t_season:02d}E{t_ep:02d}"
                new = f"{show} - S{s:02d}E{x:02d}"
                block.append([template[0].replace(old, new), good])
                stats["added"] += 1
                done.append(f"E{n} added")
            else:
                stats["missing_no_link"] += 1
                done.append(f"E{n} missing (no official link plays)")
        log(f"- [{provider.name}] {title}: {len(eps)} episodes" + (": " + ", ".join(done) if done else ", all up to date"))
    order = {s: i for i, s in enumerate(shows)}
    block.sort(key=lambda e: (order[ep_key(e)[0]], ep_key(e)[1], ep_key(e)[2]))
    entries[idx[0]:idx[-1] + 1] = block
    out = "\n".join(head + [x for e in entries for x in e]) + ("\n" if trail else "")
    return out, stats


def load_overrides(name):
    p = HERE / name
    return json.loads(p.read_text(encoding="utf-8")).get("series", {}) if p.exists() else {}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("playlist")
    ap.add_argument("--group", action="append", help='playlist group (repeatable); default: "Turkish Drama", "Documentary Series" and "Kids Series"')
    ap.add_argument("--provider", action="append", choices=sorted(PROVIDERS), help="default: all")
    ap.add_argument("--only", action="append", help="limit to this series title (repeatable)")
    ap.add_argument("--apply", action="store_true", help="rewrite the playlist")
    ap.add_argument("--report", help="also write the report to this file")
    ap.add_argument("--pause", type=float, default=0.3, help="seconds between episode requests")
    a = ap.parse_args(argv)
    lines = []
    def log(s):
        print(s)
        lines.append(s)
    text = Path(a.playlist).read_text(encoding="utf-8")
    out = text
    for name in a.provider or sorted(PROVIDERS, reverse=True):          # tv8, tabii, showtv
        cls = PROVIDERS[name]
        for group in a.group or ["Turkish Drama", "Documentary Series", "Kids Series"]:
            out, stats = sync(out, group, cls(load_overrides(cls.config)), set(a.only or []) or None, a.pause, log)
            log(f"[{name}] {group} summary: {stats}")
    if a.apply and out != text:
        Path(a.playlist).write_text(out, encoding="utf-8")
        log("playlist updated")
    elif not a.apply:
        log("report only (use --apply to write)")
    if a.report:
        Path(a.report).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
