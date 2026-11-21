"""showtv_sync: replaces only with working official links, adds missing episodes, never deletes."""
import json, os, sys, unittest
from unittest import mock
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import showtv_sync as ss

L = ('#EXTINF:-1 tvg-name="{n}"tvg-id=""tvg-logo="https://img/p.jpg"tvg-chno=""tvg-type="series"'
     'group-title="{g}":http-referrer="",{n}')


def playlist(*entries):
    out = ["#EXTM3U"]
    for n, g, u in entries:
        out += [L.format(n=n, g=g), u]
    return "\n".join(out) + "\n"


SERIES_PAGE = "".join(
    f'<option value="/dizi/tum_bolumler/demo-dizi-sezon-1-bolum-{n}-izle/{100 + n}">{n}. Bölüm</option>'
    for n in (1, 2, 3, 4)) + '<a href="/dizi/tum_bolumler/other-show-sezon-1-bolum-9-izle/999">x</a>'


def ep_page(n):
    media = {"mp4": [
        {"label": "720p", "src": f"https://vmcdn.ciner.com.tr/ht/x/E{n}_1280x720.mp4"},
        {"label": "1080p", "src": f"https://vmcdn.ciner.com.tr/ht/x/E{n}_1920x1080.mp4"}]}
    return "<div data-player='" + json.dumps({"media": media}).replace('"', "&quot;") + "'></div>"


def fake_fetch(url, timeout=25):
    if "/arama/oneriler" in url:
        if "Demo" in url:
            return json.dumps({"items": [{"title": "Demo Dizi Son Bölüm", "url": "/dizi/tanitim/demo-dizi/1"}]})
        return json.dumps({"items": []})
    if url.endswith("/dizi/tanitim/demo-dizi/1"):
        return SERIES_PAGE
    n = int(url.split("-bolum-")[1].split("-")[0])
    return ep_page(n)


class ShowtvSync(unittest.TestCase):
    def run_sync(self, text, working=lambda u: True):
        with mock.patch.object(ss, "fetch", fake_fetch), mock.patch.object(ss, "link_ok", working):
            return ss.sync(text, "Turkish Drama", {}, pause=0, log=lambda s: None)

    def test_replace_add_keep_order(self):
        G = "Turkish Drama"
        text = playlist(
            ("Other {tmdb-1} - S01E01", G, "https://video.twimg.com/a.m3u8"),
            ("Demo Dizi {tmdb-2} - S01E02", G, "https://video.twimg.com/e2.m3u8"),
            ("Demo Dizi {tmdb-2} - S01E04", G, "https://vmcdn.ciner.com.tr/ht/old/E4_1920x1080.mp4"),
            ("Classic {tmdb-3} - S01E01", "Classic Cartoons", "https://archive.org/c.mp4"))
        out, st = self.run_sync(text)
        lines = out.split("\n")
        names = [l.split('tvg-name="')[1].split('"')[0] for l in lines if l.startswith("#EXTINF")]
        self.assertEqual(names, ["Other {tmdb-1} - S01E01", "Demo Dizi {tmdb-2} - S01E01", "Demo Dizi {tmdb-2} - S01E02",
                                 "Demo Dizi {tmdb-2} - S01E03", "Demo Dizi {tmdb-2} - S01E04", "Classic {tmdb-3} - S01E01"])
        self.assertIn("https://vmcdn.ciner.com.tr/ht/x/E2_1920x1080.mp4", out)      # twimg -> best ciner
        self.assertIn("https://vmcdn.ciner.com.tr/ht/old/E4_1920x1080.mp4", out)    # ciner untouched
        self.assertIn("https://video.twimg.com/a.m3u8", out)                       # non Show TV untouched
        self.assertEqual(st, {"replaced": 1, "added": 2, "kept_no_link": 0, "missing_no_link": 0})
        self.assertIn('tvg-logo="https://img/p.jpg"', lines[lines.index(next(l for l in lines if "S01E03" in l))])

    def test_never_deletes_and_keeps_old_link_without_working_official(self):
        G = "Turkish Drama"
        text = playlist(("Demo Dizi {tmdb-2} - S01E02", G, "https://video.twimg.com/e2.m3u8"))
        out, st = self.run_sync(text, working=lambda u: "1280x720" in u)       # 1080p dead -> 720p
        self.assertIn("E2_1280x720.mp4", out)
        out, st = self.run_sync(text, working=lambda u: False)
        self.assertIn("https://video.twimg.com/e2.m3u8", out)
        self.assertEqual(st["kept_no_link"], 1)
        self.assertEqual(st["added"], 0)

    def test_series_match_is_exact(self):
        with mock.patch.object(ss, "fetch", fake_fetch):
            self.assertIsNone(ss.find_series_page("Demo", {}))
            self.assertEqual(ss.find_series_page("Demo Dizi", {}), "/dizi/tanitim/demo-dizi/1")
            self.assertIsNone(ss.find_series_page("Demo Dizi", {"Demo Dizi": None}))


if __name__ == "__main__":
    unittest.main()
