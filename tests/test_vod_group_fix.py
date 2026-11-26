"""vod_group_fix: a NEW movie/episode (web form) with a group that does not exist gets its real group;
only group-title changes, old entries and real groups are never touched."""
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import vod_group_fix as vg


def ext(name, group, kind):
    return (f'#EXTINF:-1 tvg-name="{name}"tvg-id=""tvg-logo="https://img/p.jpg"tvg-chno=""tvg-type="{kind}"'
            f'group-title="{group}":http-referrer="",{name}')


OLD = [(ext("Yeralti {tmdb-1} - S02E07", "Turkish Drama", "series"), "https://o/1"),
       (ext("Old Kurd _ کوردی {tmdb-5} - S01E01", "KURDISH-دۆبلاژ", "series"), "https://o/2"),
       (ext("Doc One {tmdb-6} - S01E01", "Documentary Series", "series"), "https://o/3"),
       (ext("Friends {tmdb-7} - S01E01", "Foreign Series", "series"), "https://o/4"),
       (ext("Mr Sunshine {tmdb-13} - S01E01", "Korean Drama", "series"), "https://o/10"),
       (ext("Old Toon {tmdb-14} - S01E01", "Animation Series", "series"), "https://o/11"),
       (ext("Old Kid {tmdb-15} - S01E01", "Kids Series", "series"), "https://o/12"),
       (ext("Old Horror {tmdb-16}", "Horror", "movie"), "https://o/13"),
       (ext("Old Romance {tmdb-17}", "Romance", "movie"), "https://o/14"),
       (ext("Old Film {tmdb-8}", "Action", "movie"), "https://o/5"),
       (ext("Old Drama {tmdb-9}", "Drama", "movie"), "https://o/6"),
       (ext("Ku Film _ فیلم {tmdb-10}", "KURDISH-دۆبلاژ", "movie"), "https://o/7"),
       (ext("Ku Sub _ فیلم {tmdb-11}", "KURDISH-ژێرنوس", "movie"), "https://o/8"),
       (ext("Fa Film {tmdb-12}", "FARSI", "movie"), "https://o/9")]
KNOWN = {u for _, u in OLD}
INFO = {("tv", "20"): {"genres": ["Drama"], "lang": "tr"}, ("tv", "21"): {"genres": ["Drama"], "lang": "ko"},
        ("tv", "22"): {"genres": ["Animation", "Comedy"], "lang": "en"}, ("tv", "23"): {"genres": ["Drama"], "lang": "en"},
        ("movie", "30"): {"genres": ["Drama", "Action"], "lang": "en"},
        ("tv", "40"): {"genres": ["Drama"], "lang": "tr"}, ("tv", "41"): {"genres": ["Animation", "Kids"], "lang": "tr"},
        ("tv", "42"): {"genres": [], "lang": "tr"}, ("movie", "50"): {"genres": ["Horror", "Mystery"], "lang": "tr"},
        ("movie", "51"): {"genres": ["Drama"], "lang": "fa"}}


def run(*new):
    text = "#EXTM3U\n" + "\n".join(f"{e}\n{u}" for e, u in OLD + list(new)) + "\n"
    out, n = vg.fix(text, KNOWN, info_for=lambda k, t: INFO.get((k, t), {}), log=lambda s: None)
    return out, n


class VodGroupFix(unittest.TestCase):
    def test_episode_of_existing_series_takes_its_group(self):
        out, n = run((ext("Yeralti {tmdb-1} - S02E08", "Kurdish Drama", "series"), "https://n/1"))
        self.assertEqual(n, 1)
        self.assertIn('group-title="Turkish Drama":http-referrer="",Yeralti {tmdb-1} - S02E08\nhttps://n/1', out)

    def test_existing_series_typed_in_another_real_group_is_joined(self):
        out, n = run((ext("Friends {tmdb-7} - S01E02", "Turkish Drama", "series"), "https://n/1"))
        self.assertIn('group-title="Foreign Series":http-referrer="",Friends {tmdb-7} - S01E02', out)

    def test_new_series_from_tmdb(self):
        out, n = run((ext("Kara {tmdb-20} - S01E01", "Kurdish Drama", "series"), "https://n/1"),
                     (ext("Kara {tmdb-20} - S01E02", "", "series"), "https://n/2"),
                     (ext("Seoul {tmdb-21} - S01E01", "Kurdish Drama", "series"), "https://n/3"),
                     (ext("Toon {tmdb-22} - S01E01", "Kurdish Drama", "series"), "https://n/4"),
                     (ext("Other {tmdb-23} - S01E01", "Kurdish Drama", "series"), "https://n/5"),
                     (ext("Dub _ دۆبلاژ {tmdb-24} - S01E01", "Kurdish Drama", "series"), "https://n/6"))
        for name, grp in (("Kara {tmdb-20} - S01E01", "Turkish Drama"), ("Kara {tmdb-20} - S01E02", "Turkish Drama"),
                          ("Seoul {tmdb-21} - S01E01", "Korean Drama"), ("Other {tmdb-23} - S01E01", "Foreign Series"),
                          ("Dub _ دۆبلاژ {tmdb-24} - S01E01", "KURDISH-دۆبلاژ"),
                          ("Toon {tmdb-22} - S01E01", "Animation Series")):
            self.assertIn(f'group-title="{grp}":http-referrer="",{name}', out)

    def test_movies(self):
        out, n = run((ext("New Film {tmdb-30}", "Movies", "movie"), "https://n/1"),
                     (ext("Sub Film {tmdb-31}", "KURDI ژێرنوس", "movie"), "https://n/2"),
                     (ext("Dub Film _ فیلم {tmdb-32}", "Movies", "movie"), "https://n/3"),
                     (ext("Farsi Film {tmdb-33}", "FARSI movies", "movie"), "https://n/4"),
                     (ext("Unknown {tmdb-34}", "Movies", "movie"), "https://n/5"),
                     (ext("Real Group {tmdb-35}", "Action", "movie"), "https://n/6"))
        for name, grp in (("New Film {tmdb-30}", "Drama"), ("Sub Film {tmdb-31}", "KURDISH-ژێرنوس"),
                          ("Dub Film _ فیلم {tmdb-32}", "KURDISH-دۆبلاژ"), ("Farsi Film {tmdb-33}", "FARSI"),
                          ("Unknown {tmdb-34}", "Movies"), ("Real Group {tmdb-35}", "Action")):
            self.assertIn(f'group-title="{grp}":http-referrer="",{name}', out)
        self.assertEqual(n, 4)

    def test_old_entries_and_links_untouched_nothing_removed(self):
        new = (ext("Yeralti {tmdb-1} - S02E08", "Kurdish Drama", "series"), "https://n/1")
        out, _ = run(new)
        for e, u in OLD:
            self.assertIn(f"{e}\n{u}", out)
        self.assertEqual(out.count("#EXTINF"), len(OLD) + 1)

    def test_nothing_new_nothing_changes(self):
        text = "#EXTM3U\n" + "\n".join(f"{e}\n{u}" for e, u in OLD) + "\n"
        out, n = vg.fix(text, KNOWN, info_for=lambda k, t: {}, log=lambda s: None)
        self.assertEqual((out, n), (text, 0))

    def test_tmdb_type_wins_over_a_wrong_real_group_kurdish_is_owners_choice(self):
        out, n = run((ext("Mira {tmdb-40} - S01E01", "Foreign Series", "series"), "https://n/1"),
                     (ext("Kurd Dub {tmdb-40} - S01E01", "KURDISH-دۆبلاژ", "series"), "https://n/2"),
                     (ext("Cartoon {tmdb-41} - S01E01", "Kids Series", "series"), "https://n/3"),
                     (ext("No Genre {tmdb-42} - S01E01", "Kids Series", "series"), "https://n/4"),
                     (ext("Scary {tmdb-50}", "Romance", "movie"), "https://n/5"),
                     (ext("Scary Two {tmdb-50}", "Horror", "movie"), "https://n/6"),
                     (ext("Persian {tmdb-51}", "Drama", "movie"), "https://n/7"),
                     (ext("Sub {tmdb-50}", "KURDISH-ژێرنوس", "movie"), "https://n/8"))
        for name, grp in (("Mira {tmdb-40} - S01E01", "Turkish Drama"),
                          ("Kurd Dub {tmdb-40} - S01E01", "KURDISH-دۆبلاژ"),     # owner's Kurdish choice stays
                          ("Cartoon {tmdb-41} - S01E01", "Kids Series"),         # a cartoon group is fine
                          ("No Genre {tmdb-42} - S01E01", "Kids Series"),        # TMDB knows no genre
                          ("Scary {tmdb-50}", "Horror"), ("Scary Two {tmdb-50}", "Horror"),
                          ("Persian {tmdb-51}", "FARSI"), ("Sub {tmdb-50}", "KURDISH-ژێرنوس")):
            self.assertIn(f'group-title="{grp}":http-referrer="",{name}', out)
        self.assertEqual(n, 3)


if __name__ == "__main__":
    unittest.main()
