"""tmdb_poster_fill: only an EMPTY poster of a movie/series with a {tmdb-ID} is filled."""
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tmdb_poster_fill as tp


def ext(name, logo, kind):
    t = f'tvg-type="{kind}"' if kind else ''
    return f'#EXTINF:-1 tvg-name="{name}"tvg-id=""tvg-logo="{logo}"tvg-chno=""{t}group-title="G":http-referrer="",{name}'


POSTERS = {("movie", "1"): "https://img/m1.jpg", ("tv", "2"): "https://img/t2.jpg"}


class PosterFill(unittest.TestCase):
    def test_only_empty_vod_with_tmdb_is_filled(self):
        items = [(ext("Film {tmdb-1}", "", "movie"), "https://v/1"),
                 (ext("Show {tmdb-2} - S01E01", "", "series"), "https://v/2"),
                 (ext("Show {tmdb-2} - S01E02", "", "series"), "https://v/3"),
                 (ext("Other {tmdb-1}", "https://own/p.jpg", "movie"), "https://v/4"),   # own poster kept
                 (ext("No Id Film", "", "movie"), "https://v/5"),                       # no id: left
                 (ext("Unknown {tmdb-9}", "", "movie"), "https://v/6"),                 # TMDB has none: left
                 (ext("Live {tmdb-1}", "", ""), "https://v/7")]                         # live: left
        text = "#EXTM3U\n" + "\n".join(f"{e}\n{u}" for e, u in items) + "\n"
        calls = []
        out, n = tp.fill(text, poster_for=lambda k, t: calls.append((k, t)) or POSTERS.get((k, t)), log=lambda s: None)
        self.assertEqual(n, 3)
        self.assertEqual(len(calls), 3)                                  # one lookup per id
        self.assertIn('tvg-logo="https://img/m1.jpg"tvg-chno=""tvg-type="movie"group-title="G":http-referrer="",Film {tmdb-1}', out)
        self.assertEqual(out.count('tvg-logo="https://img/t2.jpg"'), 2)
        self.assertIn('tvg-logo="https://own/p.jpg"', out)
        for name in ("No Id Film", "Unknown {tmdb-9}", "Live {tmdb-1}"):
            self.assertIn(f'tvg-name="{name}"tvg-id=""tvg-logo=""', out)
        self.assertEqual(out.count("#EXTINF"), len(items))
        for _, u in items:
            self.assertIn(u, out)


if __name__ == "__main__":
    unittest.main()
