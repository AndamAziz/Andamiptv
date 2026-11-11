#!/usr/bin/env python3
"""Check whether live stream URLs really play (real bytes, not just HTTP 200). Used from GitHub Actions,
whose runners can reach every port; the CLI sandbox can only reach :80/:443."""
import sys, json, re, time, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor
UA = "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36"

def get(url, nbytes, timeout=12, referer=None):
    h = {"User-Agent": UA}
    if referer: h["Referer"] = referer
    req = urllib.request.Request(url, headers=h)
    t = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(nbytes)
        return r.status, r.headers.get("content-type", ""), data, time.time() - t, r.geturl()

def check(url):
    try:
        st, ct, data, dt, final = get(url, 200_000 if '.m3u8' in url.lower() or 'playlist' in url.lower() else 65_536)
    except urllib.error.HTTPError as e:
        return {"url": url, "ok": False, "why": f"HTTP {e.code}"}
    except Exception as e:
        return {"url": url, "ok": False, "why": type(e).__name__ + ": " + str(e)[:80]}
    head = data[:16]
    if data.lstrip().startswith(b"#EXTM3U"):
        txt = data.decode("utf-8", "ignore")
        lines = [l.strip() for l in txt.split("\n") if l.strip() and not l.startswith("#")]
        if not lines:
            return {"url": url, "ok": False, "why": "empty m3u8"}
        nxt = urllib.parse.urljoin(final, lines[0])
        try:
            st2, ct2, d2, dt2, f2 = get(nxt, 400_000 if '.m3u8' in nxt.lower() else 65_536)
        except urllib.error.HTTPError as e:
            return {"url": url, "ok": False, "why": f"variant/segment HTTP {e.code}"}
        except Exception as e:
            return {"url": url, "ok": False, "why": "segment " + type(e).__name__}
        if d2.lstrip().startswith(b"#EXTM3U"):          # master -> media playlist -> segment
            l2 = [l.strip() for l in d2.decode("utf-8", "ignore").split("\n") if l.strip() and not l.startswith("#")]
            if not l2:
                return {"url": url, "ok": False, "why": "empty media playlist (channel offline?)"}
            seg = urllib.parse.urljoin(f2, l2[-1])
            try:
                st3, ct3, d3, dt3, f3 = get(seg, 65_536)
            except urllib.error.HTTPError as e:
                return {"url": url, "ok": False, "why": f"segment HTTP {e.code}"}
            except Exception as e:
                return {"url": url, "ok": False, "why": "segment " + type(e).__name__}
            return {"url": url, "ok": len(d3) > 1000, "why": f"hls ok seg={len(d3)}B {dt3:.1f}s", "kind": "hls"}
        return {"url": url, "ok": len(d2) > 1000, "why": f"hls ok seg={len(d2)}B {dt2:.1f}s", "kind": "hls"}
    if len(data) > 1000 and (data[:1] == b"\x47" or b"ftyp" in data[:16] or ct.startswith(("video", "application/octet", "binary"))):
        return {"url": url, "ok": True, "why": f"stream ok {len(data)}B {dt:.1f}s ct={ct[:20]}", "kind": "ts"}
    return {"url": url, "ok": False, "why": f"not a stream (ct={ct[:25]}, {len(data)}B, head={head[:8]!r})"}

if __name__ == "__main__":
    # usage: check_streams.py FILE   (one "name|url" per line). Prints names only - never the URLs.
    rows = [l.rstrip("\n").split("|", 1) for l in open(sys.argv[1], encoding="utf-8") if "|" in l]
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(lambda r: check(r[1].strip()), rows))
    for (name, _), r in zip(rows, res):
        print(("OK  " if r["ok"] else "BAD ") + name.strip() + " | " + re.sub(r"https?://\S+", "<url>", r["why"]))
    print(sum(r["ok"] for r in res), "ok of", len(res))
