"""Offline tests: release-year tiers (configurable) and ranking."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.dont_write_bytecode = True
import movie_engine as E

Y = 2026


class Tiers(unittest.TestCase):
    def test_last_two_years_primary(self):
        for y in (2026, 2025, 2024):
            self.assertEqual(E.release_tier(y, Y), "primary")

    def test_three_to_five_years_secondary(self):
        for y in (2023, 2022, 2021):
            self.assertEqual(E.release_tier(y, Y), "secondary")

    def test_older_rejected(self):
        for y in (2020, 1999, 1940):
            self.assertEqual(E.release_tier(y, Y), "too_old")

    def test_limits_are_configurable(self):
        self.assertEqual(E.release_tier(2022, Y, primary_years=4, secondary_years=6), "primary")
        self.assertEqual(E.release_tier(2018, Y, primary_years=1, secondary_years=10), "secondary")
        self.assertEqual(E.release_tier(2022, Y, primary_years=0, secondary_years=1), "too_old")

    def test_future_and_unknown(self):
        self.assertEqual(E.release_tier(2030, Y), "unreleased")
        self.assertEqual(E.release_tier("", Y), "unknown")
        self.assertEqual(E.release_tier(None, Y), "unknown")


class Ranking(unittest.TestCase):
    def test_primary_before_secondary_then_4k_then_rating(self):
        a = dict(tier="secondary", verdict="accept_4k", vote_average=9, vote_count=9000, popularity=500)
        b = dict(tier="primary", verdict="accept_1080p", vote_average=5, vote_count=10, popularity=1)
        c = dict(tier="primary", verdict="accept_4k", vote_average=5, vote_count=10, popularity=1)
        d = dict(tier="primary", verdict="accept_4k", vote_average=8, vote_count=5000, popularity=100)
        self.assertEqual([x is y for x, y in zip(sorted([a, b, c, d], key=E.rank_key), [d, c, b, a])], [True] * 4)

    def test_well_known_and_well_rated_beats_obscure(self):
        hit = E.usefulness(8.1, 12000, 300)
        obscure = E.usefulness(9.5, 2, 1)
        self.assertGreater(hit, obscure)


if __name__ == "__main__":
    unittest.main()
