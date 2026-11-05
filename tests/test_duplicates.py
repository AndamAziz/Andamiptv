"""Offline tests: duplicate detection (TMDB id first, then normalized title + year; playlist AND snapshot)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.dont_write_bytecode = True
import movie_engine as E

PLAYLIST = '''#EXTM3U
#EXTINF:-1 tvg-name="The Godfather {tmdb-238}"tvg-id=""tvg-logo="x"tvg-chno=""tvg-type="movie"group-title="Crime":http-referrer="",The Godfather {tmdb-238}
https://example.com/godfather.mp4
#EXTINF:-1 tvg-name="His Girl Friday - 1940"tvg-id=""tvg-logo="x"tvg-chno=""tvg-type="movie"group-title="Comedy":http-referrer="",His Girl Friday (1940)
https://archive.org/download/his_girl_friday/his_girl_friday.mp4
#EXTINF:-1 tvg-name="Some Old Film"tvg-id=""tvg-logo="x"tvg-chno=""tvg-type="movie"group-title="Drama":http-referrer="",Some Old Film
https://example.com/old.mp4
#EXTINF:-1 tvg-name="Live Channel"tvg-id=""tvg-logo=""tvg-chno=""group-title="News":http-referrer="",Live Channel
https://example.com/live.m3u8
'''
SNAPSHOT = '''#EXTM3U
#EXTINF:-1 tvg-name="Snapshot Movie {tmdb-777}"tvg-id=""tvg-logo=""tvg-chno=""tvg-type="movie"group-title="Action":http-referrer="",Snapshot Movie {tmdb-777}
https://example.com/snap.mp4
'''


class Duplicates(unittest.TestCase):
    def setUp(self):
        self.idx = E.ExistingIndex.from_m3u(PLAYLIST, SNAPSHOT)

    def test_tmdb_id_checked_first(self):
        self.assertEqual(E.duplicate_reason(self.idx, tmdb_id=238, title="Totally different title", year=1990), "duplicate_tmdb_id")

    def test_snapshot_counts_as_database(self):
        self.assertEqual(E.duplicate_reason(self.idx, tmdb_id=777), "duplicate_tmdb_id")

    def test_normalized_title_and_year(self):
        self.assertEqual(E.duplicate_reason(self.idx, title="HIS GIRL FRIDAY!", year=1940), "duplicate_title_year")
        self.assertEqual(E.duplicate_reason(self.idx, title="His Girl Friday", year="1940"), "duplicate_title_year")

    def test_same_title_other_year_is_a_different_movie(self):
        self.assertIsNone(E.duplicate_reason(self.idx, title="His Girl Friday", year=2021))

    def test_leading_article_and_punctuation_ignored(self):
        self.assertEqual(E.normalize_title("The Godfather {tmdb-238}"), E.normalize_title("Godfather"))
        self.assertEqual(E.normalize_title("Amélie (2001)"), E.normalize_title("amelie"))

    def test_existing_entry_without_year_blocks_same_title(self):
        self.assertEqual(E.duplicate_reason(self.idx, title="Some Old Film", year=2024), "duplicate_title")

    def test_same_url_and_source_id(self):
        self.assertEqual(E.duplicate_reason(self.idx, url="http://example.com/old.mp4/"), "duplicate_url")
        self.assertEqual(E.duplicate_reason(self.idx, source_id="his_girl_friday"), "duplicate_source_id")

    def test_new_movie_is_not_a_duplicate(self):
        self.assertIsNone(E.duplicate_reason(self.idx, tmdb_id=999999, title="A Brand New Film", year=2025, url="https://x.org/new.mp4"))

    def test_live_channels_do_not_block_titles(self):
        self.assertIsNone(E.duplicate_reason(self.idx, title="Live Channel", year=2025))

    def test_accepted_in_this_run_blocks_the_next_one(self):
        self.idx.add(name="Fresh Movie", tmdb_id=4242, year=2025, url="https://x.org/a.mp4")
        self.assertEqual(E.duplicate_reason(self.idx, tmdb_id=4242), "duplicate_tmdb_id")
        self.assertEqual(E.duplicate_reason(self.idx, title="fresh movie", year=2025), "duplicate_title_year")


if __name__ == "__main__":
    unittest.main()
