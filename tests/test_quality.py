"""Offline tests: video resolution (real pixel dimensions, both sides, any orientation)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.dont_write_bytecode = True
import movie_engine as E
import archive_add as A


class Resolution(unittest.TestCase):
    def test_360p_rejected(self):
        self.assertEqual(E.classify_resolution(640, 360), "reject_low")

    def test_480p_rejected(self):
        self.assertEqual(E.classify_resolution(720, 480), "reject_low")

    def test_720p_rejected(self):
        self.assertEqual(E.classify_resolution(1280, 720), "reject_low")

    def test_1080p_accepted(self):
        self.assertEqual(E.classify_resolution(1920, 1080), "accept_1080p")

    def test_portrait_1080p_accepted(self):             # orientation must not matter
        self.assertEqual(E.classify_resolution(1080, 1920), "accept_1080p")

    def test_2160p_accepted(self):
        self.assertEqual(E.classify_resolution(3840, 2160), "accept_4k")

    def test_portrait_4k_accepted(self):
        self.assertEqual(E.classify_resolution(2160, 3840), "accept_4k")

    def test_both_dimensions_required(self):             # 1920 wide but only 800 high is NOT Full HD
        self.assertEqual(E.classify_resolution(1920, 800), "reject_low")

    def test_tall_but_narrow_rejected(self):
        self.assertEqual(E.classify_resolution(1000, 1080), "reject_low")

    def test_unknown_rejected_by_the_filter(self):
        for dims in ((0, 0), (None, None), (1920, 0), ("x", "y")):
            self.assertEqual(E.classify_resolution(*dims), "unknown")

    def test_filter_off_still_needs_known_dims(self):
        self.assertEqual(E.classify_resolution(640, 360, 0), "accept_below")
        self.assertEqual(E.classify_resolution(0, 0, 0), "unknown")


def f(name, w, h, size=500_000_000, fmt="h.264", src="derivative"):
    return {"name": name, "width": str(w) if w else "", "height": str(h) if h else "", "size": str(size), "format": fmt, "source": src}


class PickFile(unittest.TestCase):
    def test_prefers_file_that_meets_min_height(self):
        files = [f("a_512kb.mp4", 640, 360), f("a_1080.mp4", 1920, 1080), f("a_720.mp4", 1280, 720)]
        self.assertEqual(A.pick_file(files, min_height=1080)["name"], "a_1080.mp4")

    def test_returns_best_available_when_none_meets(self):
        w, h = A.file_dims(A.pick_file([f("a_512kb.mp4", 640, 360), f("a_720.mp4", 1280, 720)], min_height=1080))
        self.assertEqual(E.classify_resolution(w, h), "reject_low")

    def test_unknown_resolution_file(self):
        w, h = A.file_dims(A.pick_file([f("a.mp4", 0, 0)], min_height=1080))
        self.assertEqual(E.classify_resolution(w, h), "unknown")

    def test_file_name_is_never_trusted(self):          # "1080p" in the name but 480p pixels
        w, h = A.file_dims(A.pick_file([f("movie_1080p_FULLHD.mp4", 854, 480)], min_height=1080))
        self.assertEqual(E.classify_resolution(w, h), "reject_low")


if __name__ == "__main__":
    unittest.main()
