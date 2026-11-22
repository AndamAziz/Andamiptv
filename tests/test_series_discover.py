"""series_discover: adds new dramas (with working official links) at the top of their group,
never adds TV programmes, never touches series that are already in the playlist."""
import os, sys, unittest
from unittest import mock
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import showtv_sync as ss
import series_discover as sd

L = ('#EXTINF:-1 tvg-name="{n}"tvg-id=""tvg-logo="https://img/p.jpg"tvg-chno=""tvg-type="series"'
     'group-title="{g}":http-referrer="",{n}')


def playlist(*entries):
    out = ["#EXTM3U"]
    for n, g, u in entries:
        out += [L.format(n=n, g=g), u]
    return "\n".join(out) + "\n"


SHOWTV_LIST = ('<a title="Yeni Dizi" href="/dizi/tanitim/yeni-dizi/10">x</a>'
               '<a title="Eski Dizi" href="/dizi/tanitim/eski-dizi/11">x</a>'
               '<a title="Bos Dizi" href="/dizi/tanitim/bos-dizi/12">x</a>')


def fake_fetch(url, timeout=25, tries=3):
    if url.endswith("showtv.com.tr/diziler"):
        return SHOWTV_LIST
    if url.endswith("tv8.com.tr/diziler"):
        return ""
    return '<meta property="og:image" content="https://showtv/poster.jpg">'


def episodes(self, ref):
    if "yeni-dizi" in ref:
        self.seasons = {1: 1, 2: 1, 3: 2}
        return {1: "/e1", 2: "/e2", 3: "/e3"}
    self.seasons = {1: 1}
    return {1: "/b1"}


def links(self, ref):
    return [f"https://vmcdn.ciner.com.tr/ht/x{ref}_1920x1080.mp4"]


class Discover(unittest.TestCase):
    def run_it(self, text, tabii_ids=(), tabii_infos=None, ok=lambda u: "/b1" not in u):
        overrides = {"showtv": {}, "tabii": {}, "tv8": {}}
        seen = {}
        with mock.patch.object(ss, "fetch", fake_fetch), \
                mock.patch.object(ss, "link_ok", ok), \
                mock.patch.object(ss.ShowTV, "episodes", episodes), \
                mock.patch.object(ss.ShowTV, "links", links), \
                mock.patch.object(ss.Tabii, "episodes", lambda self, r: (setattr(self, "seasons", {1: 1}) or {1: [f"https://eu1.tabii.com/apigateway/pbr/v1/media/{r}/1.m3u8"]})), \
                mock.patch.object(sd, "tabii_new_ids", lambda seen: list(tabii_ids)), \
                mock.patch.object(sd, "tabii_info", lambda sid: tabii_infos[sid]), \
                mock.patch.object(sd, "tmdb", lambda t, y=None: ("77", "https://tmdb/p.jpg") if t == "Yeni Dizi" else (None, None)), \
                mock.patch.object(sd, "tmdb_movie", lambda t, y=None: ("55", "https://tmdb/m.jpg", "Comedy") if t == "Komik Film" else (None, None, None)):
            self.films = []
            out, added, pending = sd.discover(text, overrides, seen, log=lambda s: None, films=self.films)
        return out, added, pending, overrides, seen

    def test_new_showtv_drama_added_on_top_with_seasons(self):
        text = playlist(("Eski Dizi {tmdb-5} - S01E01", "Turkish Drama", "https://video.twimg.com/a.m3u8"),
                        ("Cartoon - S01E01", "Kids Series", "https://archive.org/c.mp4"))
        out, added, pending, ov, _ = self.run_it(text)
        names = [l.split('tvg-name="')[1].split('"')[0] for l in out.split("\n") if l.startswith("#EXTINF")]
        self.assertEqual(names[:4], ["Yeni Dizi {tmdb-77} - S01E01", "Yeni Dizi {tmdb-77} - S01E02",
                                     "Yeni Dizi {tmdb-77} - S02E01", "Eski Dizi {tmdb-5} - S01E01"])
        self.assertIn('tvg-logo="https://tmdb/p.jpg"', out)
        self.assertEqual(ov["showtv"], {"Yeni Dizi": "/dizi/tanitim/yeni-dizi/10"})   # sync finds it again
        self.assertEqual(added, [("Turkish Drama", "Yeni Dizi {tmdb-77}", 3)])
        self.assertNotIn("Bos Dizi", out)                                          # no working link
        self.assertIn("https://video.twimg.com/a.m3u8", out)                        # nothing removed

    def test_tabii_programme_is_never_added_kids_go_to_kids(self):
        text = playlist(("Cartoon - S01E01", "Kids Series", "https://archive.org/c.mp4"))
        infos = {"900": dict(type="series", title="Bir Program", cats=["Program"], year=2026, poster=""),
                 "901": dict(type="series", title="Yeni Cizgi", cats=["Kids"], year=2026, poster="https://tabii/p.webp"),
                 "902": dict(type="movie", title="Bir Film", cats=["Sinema"], year=2026, poster="")}
        out, added, pending, ov, seen = self.run_it(text, ("900", "901", "902"), infos, ok=lambda u: "tabii" in u)
        self.assertNotIn("Bir Program", out)
        self.assertEqual([p["title"] for p in pending], ["Bir Program"])
        self.assertIn('tvg-name="Yeni Cizgi - S01E01"', out)
        line = next(l for l in out.split("\n") if 'tvg-name="Yeni Cizgi - S01E01"' in l)
        self.assertIn('group-title="Kids Series"', line)
        self.assertIn('tvg-logo="https://tabii/p.webp"', line)
        self.assertEqual(ov["tabii"], {"Yeni Cizgi": 901})
        self.assertEqual((seen["900"], seen["901"], seen["902"]), ("programme", "added", "not-a-film"))

    def test_tabii_films(self):
        M = "https://eu1.tabii.com/apigateway/pbr/v1/media"
        text = playlist(("Cartoon - S01E01", "Kids Series", "https://archive.org/c.mp4"))
        text += L.format(n="Old Film {tmdb-1}", g="Drama").replace('"series"', '"movie"') + "\nhttps://x/old.mp4\n"
        def film(title, cats, genres, dur=6000, clear=True):
            return dict(type="movie", title=sd.clean_title(title), cats=cats, genres=genres, year=2016,
                        duration=dur, clear=[f"{M}/1/{sd.ss.key(title)}.m3u8"] if clear else [], poster="https://tabii/f.webp")
        infos = {"1": film("Komik Film", ["Film"], ["Komedi"]),
                 "2": film('Gönül Dağı "Kurban" 2', ["Film"], ["Aile"]),
                 "3": film("Kısa Özel", ["Film"], ["Animasyon"], dur=900),
                 "4": film("Belgesel Film", ["Documentary"], ["TRT Belgesel"]),
                 "5": film("Bir Söyleşi", ["Program"], ["Söyleşi"]),
                 "6": film("Old Film", ["Film"], ["Dram"]),
                 "7": film("DRM Film", ["Film"], ["Dram"], clear=False)}
        out, added, pending, ov, seen = self.run_it(text, tuple(infos), infos, ok=lambda u: "tabii" in u)
        lines = [l for l in out.split("\n") if 'tvg-type="movie"' in l]
        names = {l.split('tvg-name="')[1].split('"')[0]: l.split('group-title="')[1].split('"')[0] for l in lines}
        self.assertEqual(names, {"Komik Film {tmdb-55}": "Comedy", "Gönül Dağı 'Kurban' 2": "Family",
                                 "Belgesel Film": "Documentary", "Old Film {tmdb-1}": "Drama"})
        self.assertEqual((seen["3"], seen["5"], seen["6"]), ("short", "not-a-film", "in-playlist"))
        self.assertNotIn("7", seen)                                  # no free link yet: look again next run
        self.assertEqual(len(self.films), 3)
        self.assertEqual(out.count("https://x/old.mp4"), 1)          # nothing removed


if __name__ == "__main__":
    unittest.main()
