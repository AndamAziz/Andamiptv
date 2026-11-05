"""Offline tests for the resolution filter (no network). Run: python -m unittest discover -s tests -v"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.dont_write_bytecode = True
import archive_add as A


class Classify(unittest.TestCase):
    def test_360p_rejected(self):
        self.assertEqual(A.classify_resolution(640, 360, 1080), "reject_low")

    def test_480p_rejected(self):
        self.assertEqual(A.classify_resolution(720, 480, 1080), "reject_low")

    def test_720p_rejected(self):
        self.assertEqual(A.classify_resolution(1280, 720, 1080), "reject_low")

    def test_1080p_accepted(self):
        self.assertEqual(A.classify_resolution(1920, 1080, 1080), "accept_1080p")

    def test_scope_1080_wide_accepted(self):          # 1920x800 letterboxed film is still Full HD
        self.assertEqual(A.classify_resolution(1920, 800, 1080), "accept_1080p")

    def test_2160p_accepted(self):
        self.assertEqual(A.classify_resolution(3840, 2160, 1080), "accept_4k")

    def test_unknown_rejected(self):
        self.assertEqual(A.classify_resolution(0, 0, 1080), "unknown")

    def test_filter_off(self):
        self.assertTrue(A.classify_resolution(640, 360, 0).startswith("accept"))


def f(name, w, h, size=500_000_000, fmt="h.264", src="derivative"):
    return {"name": name, "width": str(w) if w else "", "height": str(h) if h else "", "size": str(size), "format": fmt, "source": src}


class PickFile(unittest.TestCase):
    def test_prefers_file_that_meets_min_height(self):
        files = [f("a_512kb.mp4", 640, 360), f("a_1080.mp4", 1920, 1080), f("a_720.mp4", 1280, 720)]
        self.assertEqual(A.pick_file(files, min_height=1080)["name"], "a_1080.mp4")

    def test_returns_best_available_when_none_meets(self):
        files = [f("a_512kb.mp4", 640, 360), f("a_720.mp4", 1280, 720)]
        w, h = A.file_dims(A.pick_file(files, min_height=1080))
        self.assertEqual(A.classify_resolution(w, h, 1080), "reject_low")

    def test_unknown_resolution_file(self):
        w, h = A.file_dims(A.pick_file([f("a.mp4", 0, 0)], min_height=1080))
        self.assertEqual(A.classify_resolution(w, h, 1080), "unknown")

    def test_ignores_non_mp4_and_tiny_files(self):
        files = [f("a.mkv", 1920, 1080), f("tiny.mp4", 1920, 1080, size=1000)]
        self.assertIsNone(A.pick_file(files, min_height=1080))


if __name__ == "__main__":
    unittest.main()
