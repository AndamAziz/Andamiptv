#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stream Inspector - checks that live/VOD stream links really PLAY, not just answer 200.

You give it the links (no links are written inside the script):
    python stream_inspector.py "http://host/play/a006/index.m3u8"
    python stream_inspector.py "URL1" "URL2" --name "Fox Sports 2" --name "Fox Sports 5"
    python stream_inspector.py -f my_list.m3u          (keeps names, logos, groups)
    python stream_inspector.py -f links.txt            (one link per line, or "Name|URL")
    python stream_inspector.py                          (asks you to paste links, empty line = start)

For every link it follows the stream down to real video bytes:
  * HLS master playlist -> best variant -> media playlist -> newest segment (or EXT-X-MAP init)
  * direct MPEG-TS (.ts / no extension): checks the 0x47 TS sync bytes
  * MP4 / fMP4: checks the "ftyp" box;  DASH (.mpd): checks the manifest
It follows redirects, measures response time and segment download speed, reads resolution and
bitrate from the master playlist, and tells you when a channel is offline (empty playlist).

Output (in the current folder, or --out DIR):
  active.m3u   only the working links, ready to import (names/logos/groups kept)
  report.csv   one row per link: status, type, resolution, ms, speed, error
  failed.txt   the links that did not work and why

Only uses the Python standard library (Python 3.8+). Works in Windows PowerShell, macOS, Linux.
Check only links you are allowed to use.
"""
import argparse
import csv
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

UA_DEFAULT = ("Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120 Mobile Safari/537.36")
MAX_PLAYLIST = 2 * 1024 * 1024   # never read more than 2 MB of a playlist
SEGMENT_BYTES = 512 * 1024       # bytes read from a segment / direct stream to measure speed

# ---------------------------------------------------------------- console colours
if os.name == "nt":
    os.system("")                 # turns on ANSI colours in Windows 10+ consoles
for _stream in (sys.stdout, sys.stderr):
    try:                          # Kurdish/Arabic names must not crash an old Windows console
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
G, R, Y, C, D, N = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"


# ---------------------------------------------------------------- input
def parse_m3u(text):
    """[{name, logo, group, url, extinf}] from an M3U; keeps the original #EXTINF line."""
    out, extinf, extra = [], None, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            extinf, extra = line, []
        elif line.startswith("#EXTVLCOPT") or line.startswith("#KODIPROP"):
            extra.append(line)
        elif not line.startswith("#"):
            item = {"url": line, "name": "", "logo": "", "group": "", "extinf": extinf, "extra": extra}
            if extinf:
                item["name"] = extinf.rsplit(",", 1)[-1].strip()
                m = re.search(r'tvg-logo="([^"]*)"', extinf)
                item["logo"] = m.group(1) if m else ""
                m = re.search(r'group-title="([^"]*)"', extinf)
                item["group"] = m.group(1) if m else ""
                m = re.search(r'http-referrer="([^"]*)"', extinf)
                item["referer"] = m.group(1) if m and m.group(1) else ""
            for opt in extra:
                m = re.match(r"#EXTVLCOPT:http-(referrer|user-agent)=(.+)", opt, re.I)
                if m:
                    item["referer" if m.group(1).lower() == "referrer" else "ua"] = m.group(2).strip()
            out.append(item)
            extinf, extra = None, []
    return out


def read_inputs(args):
    items = []
    for f in args.file or []:
        if not Path(f).is_file():
            sys.exit(f"{R}File not found: {f}{N}\n  Put the file in this folder ({Path.cwd()}) "
                     f"or give its full path, e.g.  -f \"C:\\Users\\you\\Desktop\\list.m3u\"")
        text = Path(f).read_text(encoding="utf-8-sig", errors="replace")
        if "#EXTINF" in text:
            items += parse_m3u(text)
        else:
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name, url = (line.split("|", 1) if "|" in line else ("", line))
                items.append({"url": url.strip(), "name": name.strip(), "logo": "", "group": "", "extinf": None, "extra": []})
    names = args.name or []
    for i, url in enumerate(args.urls or []):
        items.append({"url": url.strip(), "name": names[i] if i < len(names) else "",
                      "logo": args.logo or "", "group": args.group or "", "extinf": None, "extra": []})
    if not items and sys.stdin.isatty():
        print(f"{C}Paste links (one per line, or Name|URL), then press Enter on an empty line to start:{N}")
        while True:
            try:
                line = input().strip()
            except EOFError:
                break
            if not line:
                break
            name, url = (line.split("|", 1) if "|" in line else ("", line))
            items.append({"url": url.strip(), "name": name.strip(), "logo": "", "group": "", "extinf": None, "extra": []})
    for it in items:
        it["url"] = it["url"].strip().strip('"').strip("'").strip()
    for k, it in enumerate(items, 1):
        it["n"] = k
        if not it["name"]:
            p = urlparse(it["url"])
            it["name"] = (p.path.strip("/").replace("/index.m3u8", "").split("/")[-1] or p.hostname or f"Link {k}")
    # same URL twice -> check once
    seen, uniq = set(), []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        uniq.append(it)
    return uniq


# ---------------------------------------------------------------- network
class Fetcher:
    def __init__(self, timeout, retries, ua, referer, headers):
        self.timeout, self.retries = timeout, retries
        self.base = {"User-Agent": ua, "Accept": "*/*"}
        if referer:
            self.base["Referer"] = referer
        for h in headers or []:
            k, _, v = h.partition(":")
            if k.strip():
                self.base[k.strip()] = v.strip()

    def get(self, url, limit, item=None):
        """-> (bytes, final_url, content_type, seconds) ; raises RuntimeError(code).
        seconds = time to first byte; self.last_read = time spent downloading the body."""
        h = dict(self.base)
        if item:
            if item.get("referer"):
                h["Referer"] = item["referer"]
            if item.get("ua"):
                h["User-Agent"] = item["ua"]
        err = "ERROR"
        for attempt in range(self.retries + 1):
            t = time.perf_counter()
            try:
                with urlopen(Request(url, headers=h), timeout=self.timeout) as r:
                    ttfb = time.perf_counter() - t
                    t2 = time.perf_counter()
                    data = r.read(limit)
                    read = time.perf_counter() - t2
                    return data, r.geturl(), (r.headers.get("Content-Type") or "").lower(), ttfb, read
            except HTTPError as e:
                err = f"HTTP {e.code}"
                if e.code in (400, 401, 403, 404, 410, 451, 452):
                    break                      # retrying will not help
            except URLError as e:
                reason = str(e.reason)
                err = ("TIMEOUT" if "timed out" in reason else
                       "DNS (host not found)" if "Name or service" in reason or "getaddrinfo" in reason else
                       "REFUSED" if "refused" in reason.lower() else
                       "SSL" if "SSL" in reason or "certificate" in reason.lower() else
                       "CONNECTION: " + reason[:40])
            except TimeoutError:
                err = "TIMEOUT"
            except Exception as e:             # reset by peer, bad status line ...
                err = type(e).__name__
            if attempt < self.retries:
                time.sleep(0.7)
        raise RuntimeError(err)


# ---------------------------------------------------------------- HLS helpers
def playlist_lines(data):
    text = data.decode("utf-8-sig", errors="replace")
    return text, [l.strip() for l in text.splitlines() if l.strip()]


def best_variant(lines):
    """highest-bandwidth variant of a master playlist -> (uri, info)"""
    best = None
    for i, l in enumerate(lines):
        if l.startswith("#EXT-X-STREAM-INF"):
            bw = int((re.search(r"BANDWIDTH=(\d+)", l) or [0, 0])[1] or 0)
            res = (re.search(r"RESOLUTION=(\d+x\d+)", l) or [0, ""])[1]
            uri = next((x for x in lines[i + 1:] if not x.startswith("#")), None)
            if uri and (best is None or bw > best[1]["bw"]):
                best = (uri, {"bw": bw, "res": res})
    return best


def media_segment(text, lines):
    """newest segment of a media playlist (live edge); falls back to the init segment"""
    segs = [l for l in lines if not l.startswith("#")]
    if segs:
        return segs[-1]
    m = re.search(r'#EXT-X-MAP:[^\n]*URI="([^"]+)"', text)
    return m.group(1) if m else None


def looks_like_media(data, ctype):
    if len(data) >= 188 * 3 and data[0] == 0x47 and data[188] == 0x47:
        return "MPEG-TS"
    if b"ftyp" in data[:64] or b"moof" in data[:4096] or b"styp" in data[:64]:
        return "MP4/fMP4"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "AUDIO"
    if ctype.startswith(("video/", "audio/")) and len(data) > 4096:
        return ctype.split(";")[0]
    return None


# ---------------------------------------------------------------- one link
def inspect(item, f):
    res = {"n": item["n"], "name": item["name"], "url": item["url"], "status": "FAILED", "type": "",
           "resolution": "", "bitrate_kbps": "", "ms": "", "speed_kbps": "", "redirect": "", "error": ""}
    url = item["url"]
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        res["error"] = "NOT A LINK - put a real http(s)://... address here"
        return res
    t0 = time.perf_counter()
    try:
        data, final, ctype, dt, rd = f.get(url, MAX_PLAYLIST if (".m3u" in url.lower() or ".mpd" in url.lower()) else SEGMENT_BYTES, item)
        res["ms"] = round(dt * 1000)
        if urlparse(final).hostname != p.hostname:
            res["redirect"] = urlparse(final).hostname
        head = data.lstrip()[:7]

        if head.startswith(b"#EXTM3U"):                           # ---- HLS
            text, lines = playlist_lines(data)
            seg_base = final
            if any(l.startswith("#EXT-X-STREAM-INF") for l in lines):
                uri, info = best_variant(lines)
                res["resolution"] = info["res"]
                res["bitrate_kbps"] = round(info["bw"] / 1000) if info["bw"] else ""
                child = urljoin(final, uri)
                data, seg_base, _, _, _ = f.get(child, MAX_PLAYLIST, item)
                if not data.lstrip().startswith(b"#EXTM3U"):
                    raise RuntimeError("VARIANT IS NOT A PLAYLIST")
                text, lines = playlist_lines(data)
                res["type"] = "HLS (master)"
            else:
                res["type"] = "HLS"
            seg = media_segment(text, lines)
            if not seg:
                m = re.search(r"#EXT-X-ERROR:\s*(.+)", text)
                raise RuntimeError("OFFLINE" + (f" ({m.group(1).strip()[:50]})" if m else " (playlist has no segments)"))
            sdata, _, sctype, _, sdt = f.get(urljoin(seg_base, seg), SEGMENT_BYTES, item)
            kind = looks_like_media(sdata, sctype)
            if not kind and len(sdata) < 1000:
                raise RuntimeError("SEGMENT EMPTY / NOT VIDEO")
            res["speed_kbps"] = round(len(sdata) * 8 / 1000 / max(sdt, 0.001))
            res["type"] += f" / {kind or 'segment'}"
        elif head.startswith(b"<?xml") or b"<MPD" in data[:512]:  # ---- DASH
            if b"<MPD" not in data[:4096]:
                raise RuntimeError("NOT A DASH MANIFEST")
            res["type"] = "DASH"
        else:                                                     # ---- direct stream
            kind = looks_like_media(data, ctype)
            if not kind:
                low = data[:300].lower()
                raise RuntimeError("WEB PAGE, NOT A STREAM" if b"<html" in low or b"<!doctype" in low
                                   else f"NOT VIDEO ({ctype or 'unknown type'})")
            res["type"] = kind
            res["speed_kbps"] = round(len(data) * 8 / 1000 / max(rd, 0.001))
        res["status"] = "ACTIVE"
        if res["bitrate_kbps"] and res["speed_kbps"] and res["speed_kbps"] < 0.8 * res["bitrate_kbps"]:
            res["status"] = "SLOW"                                # plays, but will probably buffer
    except RuntimeError as e:
        res["error"] = str(e)
    if not res["ms"]:
        res["ms"] = round((time.perf_counter() - t0) * 1000)
    return res


# ---------------------------------------------------------------- output
def hide(url):
    p = urlparse(url)
    return f"{p.scheme}://{p.hostname}{':' + str(p.port) if p.port else ''}/..."


def write_outputs(items, results, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    by_url = {r["url"]: r for r in results}
    with open(out_dir / "active.m3u", "w", encoding="utf-8") as fh:
        fh.write("#EXTM3U\n")
        for it in items:
            r = by_url[it["url"]]
            if r["status"] not in ("ACTIVE", "SLOW"):
                continue
            if it.get("extinf"):
                fh.write(it["extinf"] + "\n")
            else:
                attrs = f'tvg-name="{it["name"]}" tvg-logo="{it["logo"]}"'
                if it["group"]:
                    attrs += f' group-title="{it["group"]}"'
                fh.write(f'#EXTINF:-1 {attrs},{it["name"]}\n')
            for x in it.get("extra") or []:
                fh.write(x + "\n")
            fh.write(it["url"] + "\n")
    fields = ["n", "name", "status", "type", "resolution", "bitrate_kbps", "ms", "speed_kbps", "redirect", "error", "url"]
    with open(out_dir / "report.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in sorted(results, key=lambda r: r["n"]):
            w.writerow({k: r[k] for k in fields})
    with open(out_dir / "failed.txt", "w", encoding="utf-8") as fh:
        for r in sorted(results, key=lambda r: r["n"]):
            if r["status"] == "FAILED":
                fh.write(f'{r["name"]} | {r["error"]} | {r["url"]}\n')


def main():
    ap = argparse.ArgumentParser(description="Check that stream links really play (HLS / TS / MP4 / DASH).",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog='examples:\n  python stream_inspector.py "http://host/live/index.m3u8"\n'
                                        '  python stream_inspector.py -f channels.m3u --workers 8\n'
                                        '  python stream_inspector.py URL --name "ESPN 6" --group Sports --logo https://...')
    ap.add_argument("urls", nargs="*", help="one or more stream links")
    ap.add_argument("-f", "--file", action="append", help="M3U or text file with links (can repeat)")
    ap.add_argument("--name", action="append", help="name for the URL at the same position (repeat for each URL)")
    ap.add_argument("--logo", help="logo for the URLs given on the command line")
    ap.add_argument("--group", help="group-title for the URLs given on the command line")
    ap.add_argument("--workers", type=int, default=6, help="parallel checks (1-16, default 6)")
    ap.add_argument("--timeout", type=float, default=12, help="seconds per request (default 12)")
    ap.add_argument("--retries", type=int, default=1, help="extra tries on network errors (default 1)")
    ap.add_argument("--user-agent", default=UA_DEFAULT)
    ap.add_argument("--referer", default="")
    ap.add_argument("--header", action="append", help='extra header, e.g. --header "Origin: https://site"')
    ap.add_argument("--out", default=".", help="folder for active.m3u / report.csv / failed.txt")
    ap.add_argument("--hide-urls", action="store_true", help="show only host names on screen")
    args = ap.parse_args()
    if not 1 <= args.workers <= 16:
        ap.error("--workers must be 1-16")

    items = read_inputs(args)
    if not items:
        ap.error("no links: give URLs, -f FILE, or paste them when asked")
    f = Fetcher(args.timeout, args.retries, args.user_agent, args.referer, args.header)

    print(f"\n{C}{'=' * 64}\n  STREAM INSPECTOR  -  {len(items)} link(s), {args.workers} worker(s)\n{'=' * 64}{N}")
    results, t0 = [], time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(inspect, it, f) for it in items]
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            shown = hide(r["url"]) if args.hide_urls else r["url"]
            if r["status"] == "ACTIVE":
                extra = " ".join(x for x in (r["type"], r["resolution"], f'{r["ms"]} ms',
                                             f'{r["speed_kbps"]} kbit/s' if r["speed_kbps"] else "") if x)
                print(f"{G}[ OK ]{N} {r['name']}  {D}{extra}{N}\n       {D}{shown}{N}")
            elif r["status"] == "SLOW":
                print(f"{Y}[SLOW]{N} {r['name']}  {D}{r['type']} {r['resolution']} "
                      f"{r['speed_kbps']} < {r['bitrate_kbps']} kbit/s (may buffer){N}\n       {D}{shown}{N}")
            else:
                print(f"{R}[FAIL]{N} {r['name']}  {R}{r['error']}{N}\n       {D}{shown}{N}")

    out = Path(args.out)
    write_outputs(items, results, out)
    ok = sum(r["status"] == "ACTIVE" for r in results)
    slow = sum(r["status"] == "SLOW" for r in results)
    bad = len(results) - ok - slow
    print(f"\n{C}{'=' * 64}{N}\n  Working: {G}{ok}{N}   Slow: {Y}{slow}{N}   Not working: {R}{bad}{N}"
          f"   ({round(time.perf_counter() - t0, 1)} s)")
    print(f"  {out / 'active.m3u'}\n  {out / 'report.csv'}\n  {out / 'failed.txt'}\n{C}{'=' * 64}{N}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
