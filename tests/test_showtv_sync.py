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
            return ss.sync(text, "Turkish Drama", ss.ShowTV({}), pause=0, log=lambda s: None)

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

    def test_per_season_numbering(self):
        G = "Turkish Drama"
        page = "".join(f'<option value="/dizi/tum_bolumler/demo-dizi-sezon-{s}-bolum-{n}-izle/{100 + n}">{n}</option>'
                       for s, n in ((1, 1), (1, 2), (2, 3), (2, 4)))
        def fetch(url, timeout=25):
            return page if url.endswith("/dizi/tanitim/demo-dizi/1") else fake_fetch(url)
        text = playlist(("Demo Dizi {tmdb-2} - S01E01", G, "https://vmcdn.ciner.com.tr/ht/x/E1_1920x1080.mp4"),
                        ("Demo Dizi {tmdb-2} - S01E02", G, "https://vmcdn.ciner.com.tr/ht/x/E2_1920x1080.mp4"),
                        ("Demo Dizi {tmdb-2} - S02E01", G, "https://video.twimg.com/e3.m3u8"))
        with mock.patch.object(ss, "fetch", fetch), mock.patch.object(ss, "link_ok", lambda u: True):
            out, st = ss.sync(text, G, ss.ShowTV({}), pause=0, log=lambda s: None)
        self.assertIn("Demo Dizi {tmdb-2} - S02E01\nhttps://vmcdn.ciner.com.tr/ht/x/E3_1920x1080.mp4", out)
        self.assertIn("Demo Dizi {tmdb-2} - S02E02\nhttps://vmcdn.ciner.com.tr/ht/x/E4_1920x1080.mp4", out)
        self.assertNotIn("S01E03", out)
        self.assertNotIn("S01E04", out)
        self.assertEqual(st, {"replaced": 1, "added": 1, "kept_no_link": 0, "missing_no_link": 0})
        # only season-1 episodes in the playlist: new ones still go to their own season
        text = playlist(("Demo Dizi {tmdb-2} - S01E02", G, "https://vmcdn.ciner.com.tr/ht/x/E2_1920x1080.mp4"))
        with mock.patch.object(ss, "fetch", fetch), mock.patch.object(ss, "link_ok", lambda u: True):
            out, st = ss.sync(text, G, ss.ShowTV({}), pause=0, log=lambda s: None)
        for name in ("S01E01", "S02E01", "S02E02"):
            self.assertIn("Demo Dizi {tmdb-2} - " + name, out)
        self.assertNotIn("S01E03", out)
        # the provider no longer lists the playlist's season: nothing changes, no crash
        text = playlist(("Demo Dizi {tmdb-2} - S05E01", G, "https://video.twimg.com/s5e1.m3u8"))
        with mock.patch.object(ss, "fetch", fetch), mock.patch.object(ss, "link_ok", lambda u: True):
            out, st = ss.sync(text, G, ss.ShowTV({}), pause=0, log=lambda s: None)
        self.assertEqual(out, text)

    def test_series_match_is_exact(self):
        with mock.patch.object(ss, "fetch", fake_fetch):
            self.assertIsNone(ss.ShowTV({}).find("Demo"))
            self.assertEqual(ss.ShowTV({}).find("Demo Dizi"), "/dizi/tanitim/demo-dizi/1")
            self.assertIsNone(ss.ShowTV({"Demo Dizi": None}).find("Demo Dizi"))


TABII_SITEMAP = ('<url><loc>https://www.tabii.com/tr/detail/77/demo-tabii</loc></url>'
                 '<url><loc>https://www.tabii.com/tr/detail/78/demo-tabii-belgesel</loc></url>')


def tabii_detail():
    def ep(n, drm="clear"):
        return {"episodeNumber": n, "media": [
            {"type": "dash", "drmSchema": "clear", "url": f"/{n}00/{n}02.mpd"},
            {"type": "hls", "drmSchema": drm, "url": f"/{n}00/{n}01.m3u8"}]}
    data = {"contentType": "series", "seasons": [
        {"seasonNumber": 1, "episodes": [ep(1), ep(2)]},
        {"seasonNumber": 2, "episodes": [ep(3, drm="fairplay"), ep(4)]}]}
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(
        {"props": {"pageProps": {"data": data}}}) + "</script>"


def tabii_fetch(url, timeout=25):
    if url.endswith("/sitemap-tr.xml"):
        return TABII_SITEMAP
    if url.endswith("/tr/detail/77"):
        return tabii_detail()
    raise AssertionError(url)


class TabiiSync(unittest.TestCase):
    def test_tabii_add_replace_skip_drm(self):
        G = "Turkish Drama"
        M = "https://eu1.tabii.com/apigateway/pbr/v1/media"
        text = playlist(("Demo Tabii {tmdb-9} - S01E01", G, M + "/100/101.m3u8"),
                        ("Demo Tabii {tmdb-9} - S01E02", G, "https://video.twimg.com/x.m3u8"),
                        ("Demo Tabii {tmdb-9} - S01E03", G, "https://video.twimg.com/drm.m3u8"))
        with mock.patch.object(ss, "fetch", tabii_fetch), mock.patch.object(ss, "link_ok", lambda u: True):
            out, st = ss.sync(text, G, ss.Tabii({}), pause=0, log=lambda s: None)
        self.assertIn(M + "/200/201.m3u8", out)                     # E2 twimg -> official
        self.assertIn("https://video.twimg.com/drm.m3u8", out)      # E3 only DRM -> kept
        self.assertIn("Demo Tabii {tmdb-9} - S01E04", out)          # E4 added
        self.assertNotIn(".mpd", out)
        self.assertEqual(st, {"replaced": 1, "added": 1, "kept_no_link": 1, "missing_no_link": 0})
        with mock.patch.object(ss, "fetch", tabii_fetch):
            self.assertEqual(ss.Tabii({}).find("Demo Tabii"), "77")
            self.assertIsNone(ss.Tabii({}).find("Demo"))
            self.assertEqual(ss.Tabii({"Other": 5}).find("Other"), "5")


    def test_official_link_of_another_episode_is_corrected(self):
        G = "Turkish Drama"
        M = "https://eu1.tabii.com/apigateway/pbr/v1/media"
        text = playlist(("Demo Tabii {tmdb-9} - S01E01", G, M + "/100/101.m3u8"),
                        ("Demo Tabii {tmdb-9} - S01E02", G, M + "/100/101.m3u8"),      # carries E1's video
                        ("Demo Tabii {tmdb-9} - S01E04", G, M + "/999/998.m3u8"))      # other version: kept
        with mock.patch.object(ss, "fetch", tabii_fetch), mock.patch.object(ss, "link_ok", lambda u: True):
            out, st = ss.sync(text, G, ss.Tabii({}), pause=0, log=lambda s: None)
        self.assertIn(M + "/200/201.m3u8", out)
        self.assertIn(M + "/999/998.m3u8", out)
        self.assertEqual(out.count(M + "/100/101.m3u8"), 1)
        self.assertEqual(st["replaced"], 1)

    def test_other_production_with_same_title_is_skipped(self):
        G = "Turkish Drama"
        text = playlist(("Demo Tabii {tmdb-9} - S01E10", G, "https://kanaldvod.duhnet.tv/x.mp4"))
        with mock.patch.object(ss, "fetch", tabii_fetch), mock.patch.object(ss, "link_ok", lambda u: True):
            out, st = ss.sync(text, G, ss.Tabii({}), pause=0, log=lambda s: None)
        self.assertEqual(out, text)                                  # 4 episodes there < E10 here
        with mock.patch.object(ss, "fetch", tabii_fetch), mock.patch.object(ss, "link_ok", lambda u: True):
            out, st = ss.sync(text, G, ss.Tabii({"Demo Tabii": 77}), pause=0, log=lambda s: None)
        self.assertEqual(st["added"], 3)                             # forced in the json


TV8_INDEX = '<a href="/demo-dizi" class="now-thumb-prog text-decoration-none">Demo Dizi</a>'


def tv8_fetch(url, timeout=25):
    if url.endswith("/programlar"):
        return TV8_INDEX
    if url.endswith("/diziler") or url.endswith("/yarismalar"):
        return ""
    if "/tum-bolumler?page=" in url:
        page = int(url.split("page=")[1].split("&")[0])
        links = {1: ["demo-dizi-1-bolum-6-nisan-2022-11-video.htm",
                     "demo-dizi-dizisinin-2-bolum-tanitimi-yayinlandi-12-video.htm",   # trailer: ignored
                     "demo-dizi-2-bolum-tanitimi-13-video.htm"],                      # trailer: ignored
                 2: ["demo-dizi-2-bolum-13-nisan-2022-14-video.htm",
                     "demo-dizi-3-bolum-20-nisan-2022-15-video.htm"]}[page]
        h = "".join(f'<a href="/demo-dizi/{l}">x</a>' for l in links)
        return json.dumps({"html": h, "hasMore": page == 1})
    n = url.split("-video.htm")[0].rsplit("-", 1)[1]
    return f'<video src="https://video-cdn.tv8.com.tr/2022/04/0{n[-1]}/{n * 16}-480p.mp4?st=x&e=1"></video>'


class Tv8Sync(unittest.TestCase):
    def test_tv8_add_replace_skip_trailers(self):
        G = "Turkish Drama"
        text = playlist(("Demo Dizi {tmdb-5} - S01E01", G, "https://video-cdn.tv8.com.tr/2022/04/01/old-720p.mp4"),
                        ("Demo Dizi {tmdb-5} - S01E03", G, "https://video.twimg.com/e3.m3u8"))
        with mock.patch.object(ss, "fetch", tv8_fetch), mock.patch.object(ss, "link_ok", lambda u: "-720p.mp4" in u):
            t = ss.TV8({})
            self.assertEqual(sorted(t.episodes("demo-dizi")), [1, 2, 3])
            out, st = ss.sync(text, G, t, pause=0, log=lambda s: None)
        self.assertIn("https://video-cdn.tv8.com.tr/2022/04/01/old-720p.mp4", out)                       # E1 untouched
        self.assertIn("Demo Dizi {tmdb-5} - S01E02\nhttps://video-cdn.tv8.com.tr/2022/04/04/" + "14" * 16 + "-720p.mp4", out)
        self.assertIn("https://video-cdn.tv8.com.tr/2022/04/05/" + "15" * 16 + "-720p.mp4", out)        # E3 twimg -> TV8
        self.assertNotIn("?st=", out)                                                                     # never a token
        self.assertEqual(st, {"replaced": 1, "added": 1, "kept_no_link": 0, "missing_no_link": 0})


if __name__ == "__main__":
    unittest.main()
