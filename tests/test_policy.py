"""Owner's policy: only recent (<= 5 years) and Full HD/4K films can be imported."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import discover_movies as D


class Policy(unittest.TestCase):
    def test_defaults_are_allowed(self):
        o = D.parse_args([])
        self.assertEqual((o.min_height, o.secondary_years), (1080, 5))

    def test_low_resolution_is_refused(self):
        with self.assertRaises(SystemExit):
            D.parse_args(["--min-height", "720"])

    def test_old_films_are_refused(self):
        with self.assertRaises(SystemExit):
            D.parse_args(["--secondary-years", "50"])


if __name__ == "__main__":
    unittest.main()
