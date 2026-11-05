"""Offline tests: source validation (license policy, https, format), adapters' license logic, the full pipeline with a fake
source / fake TMDB (no network), and the safe-write validation."""
import os, sys, types, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.dont_write_bytecode = True
import movie_engine as E
import discover_movies as D
from sources.base import Source
from sources import wikimedia, REGISTRY, get_sources

LIC = ("public domain", "CC-BY (credit the creator)")


def cand(**kw):
    c = Source.candidate(source="fake", sid="id1", title="New Film", year="2025", url="https://cdn.example.org/new.mp4", fmt="mp4",
                         width=1920, height=1080, minutes=95, mb=900, license="public domain")
    c.update(kw)
    return c


class SourceValidation(unittest.TestCase):
    def test_valid_candidate(self):
        self.assertIsNone(E.validate_source_candidate(cand(), LIC))

    def test_license_must_be_permitted(self):
        for lic in ("", "unknown", "all rights reserved", "CC-BY-NC"):
            self.assertEqual(E.validate_source_candidate(cand(license=lic), LIC), "license_not_permitted")

    def test_https_required(self):
        self.assertEqual(E.validate_source_candidate(cand(url="http://cdn.example.org/new.mp4"), LIC), "not_https")

    def test_only_mp4_m3u8_by_default(self):
        self.assertEqual(E.validate_source_candidate(cand(fmt="webm"), LIC), "format_not_allowed")
        self.assertIsNone(E.validate_source_candidate(cand(fmt="m3u8"), LIC))
        self.assertIsNone(E.validate_source_candidate(cand(fmt="webm"), LIC, allowed_formats=("mp4", "webm")))


class Adapters(unittest.TestCase):
    def test_registry_has_separate_adapters(self):
        self.assertEqual(sorted(REGISTRY), ["internet_archive", "wikimedia"])
        self.assertEqual([s.name for s in get_sources(["wikimedia"])], ["wikimedia"])
        with self.assertRaises(SystemExit):
            get_sources(["nope"])

    def test_wikimedia_license_labels(self):
        lab = lambda v: wikimedia.license_label({"LicenseShortName": {"value": v}})
        self.assertEqual(lab("Public domain"), "public domain")
        self.assertEqual(lab("CC0"), "public domain")
        self.assertEqual(lab("CC BY 4.0"), "CC-BY (credit the creator)")
        self.assertEqual(lab("CC BY-SA 3.0"), "CC-BY (credit the creator)")
        for bad in ("CC BY-NC 4.0", "CC BY-ND 2.0", "Fair use", "All rights reserved", ""):
            self.assertIsNone(lab(bad), bad)
        self.assertIsNone(wikimedia.license_label({}))


class FakeSource(Source):
    name = "fake"
    allowed_licenses = LIC

    def __init__(self, items):
        self.items = items

    def discover(self, opts):
        for kind, obj in self.items:
            yield kind, obj


class FakeTmdb:
    available = True

    def __init__(self, table):
        self.table = table

    def lookup(self, title, year):
        return self.table.get(E.normalize_title(title))


def info(i, title, year, avg=7.5, votes=1500, pop=80, genres=("Action",)):
    return dict(id=i, title=title, release="%s-06-01" % year, year=str(year), vote_average=avg, vote_count=votes, popularity=pop, genres=list(genres), poster="/p.jpg")


def opts(**kw):
    o = D.parse_args(["--sources", "internet_archive"])
    o.this_year = 2026
    o.allowed_licenses = LIC
    for k, v in kw.items():
        setattr(o, k, v)
    return o


class Pipeline(unittest.TestCase):
    def run_pipeline(self, items, tmdb_table, o=None, text="#EXTM3U\n"):
        o = o or opts()
        with mock.patch.object(D.A, "check_range", return_value=(True, 206)), mock.patch.object(D.A, "probe_resolution", return_value=None):
            return D.run(o, text, "", tmdb=FakeTmdb(tmdb_table), sources=[FakeSource([("candidate", i) for i in items])])

    def test_accepts_recent_full_hd_and_ranks(self):
        items = [cand(sid="a", title="Older Film", year="2022", url="https://x.org/a.mp4"), cand(sid="b", title="Newest Film", year="2025", url="https://x.org/b.mp4", width=3840, height=2160)]
        table = {E.normalize_title("Older Film"): info(1, "Older Film", 2022), E.normalize_title("Newest Film"): info(2, "Newest Film", 2025)}
        acc, rej, reasons, _ = self.run_pipeline(items, table)
        self.assertEqual([a["tmdb"]["id"] for a in acc], [2, 1])                     # primary + 4K first
        self.assertEqual([a["tier"] for a in acc], ["primary", "secondary"])
        self.assertEqual(rej, [])

    def test_rejections_and_reasons(self):
        items = [cand(sid="1", title="Low Res", url="https://x.org/1.mp4", width=1280, height=720),
                 cand(sid="2", title="No Dims", url="https://x.org/2.mp4", width=0, height=0),
                 cand(sid="3", title="Too Old", year="2015", url="https://x.org/3.mp4"),
                 cand(sid="4", title="Http Only", url="http://x.org/4.mp4"),
                 cand(sid="5", title="Webm Film", url="https://x.org/5.webm", fmt="webm"),
                 cand(sid="6", title="Bad License", url="https://x.org/6.mp4", license="CC-BY-NC"),
                 cand(sid="7", title="Short", url="https://x.org/7.mp4", minutes=12),
                 cand(sid="8", title="Unknown To TMDB", url="https://x.org/8.mp4")]
        table = {E.normalize_title("Too Old"): info(3, "Too Old", 2015)}
        acc, rej, reasons, _ = self.run_pipeline(items, table)
        self.assertEqual(acc, [])
        self.assertEqual(reasons, {"resolution_below_1080p": 1, "unknown_quality": 1, "older_than_limit": 1, "not_https": 1, "format_not_allowed": 1,
                                   "license_not_permitted": 1, "too_short": 1, "no_tmdb_match": 1})

    def test_duplicates_never_imported(self):
        text = '#EXTM3U\n#EXTINF:-1 tvg-name="Dup Film {tmdb-5}"tvg-id=""tvg-logo=""tvg-chno=""tvg-type="movie"group-title="X":http-referrer="",Dup Film {tmdb-5}\nhttps://old.example/x.mp4\n'
        items = [cand(sid="d1", title="Dup Film", url="https://x.org/new-copy.mp4"), cand(sid="d2", title="Other", url="https://x.org/o.mp4")]
        table = {E.normalize_title("Dup Film"): info(5, "Dup Film", 2025), E.normalize_title("Other"): info(6, "Other", 2025)}
        acc, rej, reasons, _ = self.run_pipeline(items, table, text=text)
        self.assertEqual([a["tmdb"]["id"] for a in acc], [6])
        self.assertEqual(reasons, {"duplicate_tmdb_id": 1})

    def test_same_movie_from_two_sources_imported_once(self):
        items = [cand(sid="s1", title="Twice", url="https://x.org/t1.mp4"), cand(sid="s2", title="Twice", url="https://y.org/t2.mp4")]
        acc, rej, reasons, _ = self.run_pipeline(items, {E.normalize_title("Twice"): info(9, "Twice", 2025)})
        self.assertEqual(len(acc), 1)
        self.assertEqual(reasons, {"duplicate_tmdb_id": 1})

    def test_year_limits_configurable(self):
        items = [cand(sid="y", title="Mid Film", year="2019", url="https://x.org/y.mp4")]
        table = {E.normalize_title("Mid Film"): info(11, "Mid Film", 2019)}
        self.assertEqual(self.run_pipeline(items, table)[0], [])                       # default: 7 years old -> rejected
        self.assertEqual(len(self.run_pipeline(items, table, o=opts(secondary_years=8))[0]), 1)

    def test_rating_and_votes_thresholds(self):
        items = [cand(sid="r", title="Meh", url="https://x.org/r.mp4")]
        table = {E.normalize_title("Meh"): info(12, "Meh", 2025, avg=4.0, votes=3)}
        self.assertEqual(self.run_pipeline(items, table, o=opts(min_rating=6.0))[2], {"rating_too_low": 1})
        self.assertEqual(self.run_pipeline(items, table, o=opts(min_votes=100))[2], {"too_few_votes": 1})

    def test_dead_link_rejected(self):
        o = opts()
        with mock.patch.object(D.A, "check_range", return_value=(False, 404)), mock.patch.object(D.A, "probe_resolution", return_value=None):
            acc, rej, reasons, _ = D.run(o, "#EXTM3U\n", "", tmdb=FakeTmdb({E.normalize_title("New Film"): info(1, "New Film", 2025)}),
                                         sources=[FakeSource([("candidate", cand())])])
        self.assertEqual((acc, reasons), ([], {"link_failed": 1}))

    def test_stream_resolution_overrides_metadata(self):                              # metadata says 1080p, the real stream is 720p
        o = opts()
        with mock.patch.object(D.A, "check_range", return_value=(True, 206)), mock.patch.object(D.A, "probe_resolution", return_value=(1280, 720)):
            acc, rej, reasons, _ = D.run(o, "#EXTM3U\n", "", tmdb=FakeTmdb({E.normalize_title("New Film"): info(1, "New Film", 2025)}),
                                         sources=[FakeSource([("candidate", cand())])])
        self.assertEqual((acc, reasons), ([], {"resolution_mismatch": 1}))


class SafeWrite(unittest.TestCase):
    before = ["#EXTM3U", '#EXTINF:-1 tvg-name="A"tvg-type="movie"group-title="X",A', "https://a.org/a.mp4", '#EXTINF:-1 tvg-type="series"group-title="S",S - S01E01', "https://a.org/s.mp4"]
    block = ['#EXTINF:-1 tvg-name="B {tmdb-1}"tvg-type="movie"group-title="Y",B {tmdb-1}', "https://b.org/b.mp4"]

    def test_valid_append_passes(self):
        after = self.before[:3] + self.block + self.before[3:]
        self.assertEqual(E.validate_write(self.before, after, [self.block]), [])

    def test_removed_or_reordered_lines_blocked(self):
        after = [self.before[0]] + self.block + self.before[2:]                        # first movie entry lost
        self.assertTrue(E.validate_write(self.before, after, [self.block]))
        reordered = [self.before[0]] + self.before[3:5] + self.before[1:3] + self.block
        self.assertTrue(E.validate_write(self.before, reordered, [self.block]))

    def test_http_or_malformed_block_blocked(self):
        bad = [self.block[0], "http://b.org/b.mp4"]
        self.assertTrue(E.validate_write(self.before, self.before + bad, [bad]))

    def test_apply_refuses_to_write_on_failed_validation(self):
        import tempfile
        d = tempfile.mkdtemp(); p = os.path.join(d, "p.m3u")
        open(p, "w").write("\n".join(self.before))
        o = opts(playlist=p)
        acc = [dict(tmdb=info(1, "B", 2025), title="B", release_year="2025", url="http://insecure.org/b.mp4", logo="", verdict="accept_1080p", tier="primary")]
        self.assertTrue(D.apply_to_playlist(o, acc, None))                              # problems returned
        self.assertEqual(open(p).read(), "\n".join(self.before))                         # file untouched
        acc[0]["url"] = "https://secure.org/b.mp4"
        self.assertEqual(D.apply_to_playlist(o, acc, None), [])
        self.assertIn("https://secure.org/b.mp4", open(p).read())


if __name__ == "__main__":
    unittest.main()
