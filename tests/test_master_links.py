"""find_master_links: candidate masters and the 'master really contains this stream' check."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import find_master_links as f


class MasterLinks(unittest.TestCase):
    def test_flussonic_track_points_to_index(self):
        c = f.candidates("http://h/live/x/bein_1_hd/tracks-v1a1/mono.ts.m3u8")
        self.assertIn("http://h/live/x/bein_1_hd/index.m3u8", c)

    def test_quality_suffix_is_removed(self):
        self.assertEqual(f.candidates("https://h/playlist480p.m3u8")[0], "https://h/playlist.m3u8")

    def test_wowza_chunklist(self):
        self.assertIn("https://h/app/stream/playlist.m3u8", f.candidates("https://h/app/stream/chunklist_w123.m3u8"))

    def test_master_must_contain_current_stream(self):
        master = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\ntracks-v1a1/mono.ts.m3u8\n"
        vs = f.variants(master, "http://h/a/index.m3u8")
        self.assertTrue(f.contains(vs, "http://h/a/tracks-v1a1/mono.ts.m3u8"))
        self.assertFalse(f.contains(vs, "http://h/b/tracks-v1a1/mono.ts.m3u8"))

    def test_query_is_ignored_when_matching(self):
        vs = ["https://h/p/720.m3u8?token=1"]
        self.assertTrue(f.contains(vs, "https://h/p/720.m3u8?token=2"))


if __name__ == "__main__":
    unittest.main()
