"""m3u_sources: the owner's M3U sources add only new, playing, token-free episodes/movies with a TMDB id,
in the playlist format; nothing in the playlist is removed or changed."""
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import m3u_sources as ms


def ext(name, group, kind, logo="https://img/p.jpg"):
    return (f'#EXTINF:-1 tvg-name="{name}"tvg-id=""tvg-logo="{logo}"tvg-chno=""tvg-type="{kind}"'
            f'group-title="{group}":http-referrer="",{name}')


PLAYLIST = "#EXTM3U\n" + "\n".join(f"{e}\n{u}" for e, u in [
    (ext("Show A {tmdb-1} - S01E01", "Turkish Drama", "series"), "https://o/a1"),
    (ext("Show A {tmdb-1} - S01E02", "Turkish Drama", "series"), "https://o/a2"),
    (ext("Anime X {tmdb-9} - S01E01", "Animation Series", "series"), "https://o/x1"),
    (ext("Old Film {tmdb-5}", "Drama", "movie"), "https://o/m5"),
    (ext("Horror Film {tmdb-8}", "Horror", "movie"), "https://o/m8")]) + "\n"
SOURCE = """#EXTM3U
#EXTINF:-1 group-title="Show A" tvg-name="Show A S01E03",Show A - S01 E03
https://n/a3.m3u8
#EXTINF:-1 group-title="Show A",Show A - S01 E02
https://n/a2-other.m3u8
#EXTINF:-1 group-title="Show A",Show A - S01 E04
https://n/a4.m3u8?token=xyz
#EXTINF:-1 group-title="Show A",Show A - S01 E05
https://n/dead.m3u8
#EXTINF:-1 group-title="New",Brand New S01E01
https://n/b1.m3u8
#EXTINF:-1 group-title="News",Live News HD
https://n/live.m3u8
#EXTINF:-1 group-title="Movies",Old Film (2020)
https://n/m5-other.mp4
#EXTINF:-1 group-title="Movies",New Film (2026)
https://n/m6.mp4
#EXTINF:-1 group-title="Movies",Nobody Knows This
https://n/m7.mp4
#EXTINF:-1 group-title="Show A",Show A - S01 E01
https://o/a1
"""
DETAILS = {("tv", "1"): {"name": "Show A", "genres": ["Drama"], "lang": "tr", "poster": "https://img/a.jpg"},
           ("tv", "2"): {"name": "Brand New", "genres": ["Drama"], "lang": "tr", "poster": "https://img/b.jpg"},
           ("movie", "5"): {"name": "Old Film", "genres": ["Drama"], "lang": "en", "poster": "https://img/5.jpg"},
           ("movie", "6"): {"name": "New Film", "genres": ["Horror"], "lang": "en", "poster": "https://img/6.jpg"}}
SEARCH = {("tv", "showa"): "1", ("tv", "brandnew"): "2", ("movie", "oldfilm"): "5", ("movie", "newfilm"): "6"}


def go(state=None, now=1000.0):
    import showtv_sync as ss
    return ms.run(PLAYLIST, [("https://src/list.m3u", {})], state if state is not None else {},
                  fetch=lambda u: SOURCE, probe=lambda u: 0.0 if "dead" in u else (6000.0 if "/m" in u else 2400.0),
                  details=lambda k, t: DETAILS.get((k, t), {}), search=lambda k, t, y: SEARCH.get((k, ss.key(t))),
                  now=now, log=lambda s: None)


class M3USources(unittest.TestCase):
    def test_adds_only_new_playing_tokenfree_vod_with_tmdb(self):
        out, rep, state = go()
        self.assertIn(',Show A {tmdb-1} - S01E03\nhttps://n/a3.m3u8', out)               # existing show, next ep
        self.assertIn('group-title="Turkish Drama":http-referrer="",Show A {tmdb-1} - S01E03', out)
        self.assertNotIn("a2-other", out)                                                 # episode exists: kept
        self.assertNotIn("token=xyz", out)
        self.assertNotIn("dead.m3u8", out)
        self.assertIn('tvg-logo="https://img/b.jpg"tvg-chno=""tvg-type="series"group-title="Turkish Drama"'
                      ':http-referrer="",Brand New {tmdb-2} - S01E01\nhttps://n/b1.m3u8', out)
        self.assertNotIn("live.m3u8", out)                                                # live channel skipped
        self.assertNotIn("m5-other", out)                                                 # movie id exists
        self.assertIn('group-title="Horror":http-referrer="",New Film {tmdb-6}\nhttps://n/m6.mp4', out)
        self.assertNotIn("m7.mp4", out)                                                   # no TMDB match
        self.assertEqual(state["https://n/a4.m3u8?token=xyz"]["status"], "token")
        self.assertEqual(state["https://n/dead.m3u8"]["status"], "dead")
        self.assertTrue(any("token link" in r for r in rep))
        # order: S01E03 right after S01E02 of the same series
        self.assertLess(out.index("Show A {tmdb-1} - S01E02"), out.index("Show A {tmdb-1} - S01E03"))
        self.assertLess(out.index("Show A {tmdb-1} - S01E03"), out.index("Anime X"))
        self.assertLess(out.index("New Film {tmdb-6}"), out.index("Horror Film {tmdb-8}"))   # first in its group

    def test_nothing_removed_and_second_run_adds_nothing(self):
        out, _, state = go()
        for ln in PLAYLIST.strip().split("\n"):
            self.assertIn(ln, out)
        out2, _, _ = ms.run(out, [("s", {})], state, fetch=lambda u: SOURCE, probe=lambda u: 6000.0,
                            details=lambda k, t: DETAILS.get((k, t), {}), search=lambda k, t, y: None,
                            now=1000.0 + 3600, log=lambda s: None)
        self.assertEqual(out2, out)

    def test_failed_links_wait_a_day_tokens_forever(self):
        _, _, state = go()
        tried = []
        ms.run(PLAYLIST, [("s", {})], state, fetch=lambda u: SOURCE, probe=lambda u: tried.append(u) or 0.0,
               details=lambda k, t: DETAILS.get((k, t), {}), search=lambda k, t, y: SEARCH.get((k, ms.ss.key(t))),
               now=1000.0 + 25 * 3600, log=lambda s: None)
        self.assertIn("https://n/dead.m3u8", tried)
        self.assertNotIn("https://n/a4.m3u8?token=xyz", tried)

    def test_tmdb_hint_on_the_source_line(self):
        self.assertEqual(ms.parse_sources("# c\n\nhttps://a/b.m3u  tv=326247\nhttps://c/d.m3u movie=12\n"),
                         [("https://a/b.m3u", {"tv": "326247"}), ("https://c/d.m3u", {"movie": "12"})])
        out, _, _ = ms.run(PLAYLIST, [("s", {"tv": "2"})], {},
                           fetch=lambda u: '#EXTM3U\n#EXTINF:-1,Whatever Name - S01 E07\nhttps://n/w7.m3u8\n',
                           probe=lambda u: 2400.0, details=lambda k, t: DETAILS.get((k, t), {}),
                           search=lambda k, t, y: None, now=1.0, log=lambda s: None)
        self.assertIn(",Brand New {tmdb-2} - S01E07\nhttps://n/w7.m3u8", out)


if __name__ == "__main__":
    unittest.main()
