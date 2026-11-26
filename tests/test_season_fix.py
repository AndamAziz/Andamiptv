"""season_fix: an overall episode number (S01E24) becomes its real season/episode, only for series
that already use seasons; nothing else changes."""
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import season_fix as sf

L = ('#EXTINF:-1 tvg-name="{n}"tvg-id=""tvg-logo="https://img/p.jpg"tvg-chno=""tvg-type="series"'
     'group-title="Turkish Drama":http-referrer="",{n}')


def pl(*items):
    return "#EXTM3U\n" + "\n".join(L.format(n=n) + "\n" + u for n, u in items) + "\n"


class SeasonFix(unittest.TestCase):
    def test_overall_number_becomes_season_episode(self):
        text = pl(("Yeralti {tmdb-1} - S02E07", "https://x/23.m3u8"), ("Yeralti {tmdb-1} - S01E24", "https://x/24.m3u8"))
        out, n = sf.fix(text, counts_for=lambda tid: {1: 16, 2: 8}, log=lambda s: None)
        self.assertEqual(n, 1)
        self.assertIn('tvg-name="Yeralti {tmdb-1} - S02E08"', out)
        self.assertIn(",Yeralti {tmdb-1} - S02E08\nhttps://x/24.m3u8", out)          # link kept
        self.assertLess(out.index("S02E07"), out.index("S02E08"))

    def test_series_with_overall_numbering_or_existing_name_untouched(self):
        text = pl(("Gonul {tmdb-2} - S01E150", "https://x/150.m3u8"),                   # no season 2 used
                  ("Yeralti {tmdb-1} - S02E08", "https://x/a.m3u8"), ("Yeralti {tmdb-1} - S01E24", "https://x/b.m3u8"))
        out, n = sf.fix(text, counts_for=lambda tid: {1: 16, 2: 8}, log=lambda s: None)
        self.assertEqual(n, 0)                                                         # S02E08 already there
        self.assertEqual(out, text)

    def test_episode_newer_than_tmdb_continues_last_season(self):
        text = pl(("Yeralti {tmdb-1} - S02E08", "https://x/24.m3u8"), ("Yeralti {tmdb-1} - S01E26", "https://x/26.m3u8"),
                  ("Yeralti {tmdb-1} - S01E25", "https://x/25.m3u8"))
        out, n = sf.fix(text, counts_for=lambda tid: {1: 16, 2: 8}, log=lambda s: None)
        self.assertEqual(n, 2)
        self.assertIn(",Yeralti {tmdb-1} - S02E09\nhttps://x/25.m3u8", out)
        self.assertIn(",Yeralti {tmdb-1} - S02E10\nhttps://x/26.m3u8", out)

    def test_newer_than_tmdb_without_previous_episode_is_left(self):
        text = pl(("Yeralti {tmdb-1} - S02E07", "https://x/23.m3u8"), ("Yeralti {tmdb-1} - S01E30", "https://x/30.m3u8"))
        out, n = sf.fix(text, counts_for=lambda tid: {1: 16, 2: 8}, log=lambda s: None)
        self.assertEqual((out, n), (text, 0))


if __name__ == "__main__":
    unittest.main()
