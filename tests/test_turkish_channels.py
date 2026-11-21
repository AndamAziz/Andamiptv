"""turkish_channels: never deletes, replaces only with a working official link, keeps the order."""
import json, os, sys, tempfile, unittest
from unittest import mock
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import turkish_channels as tc

L = '#EXTINF:-1 tvg-name="{n}"tvg-id="X.tr@SD"tvg-logo=""tvg-chno=""group-title="{g}":http-referrer="",{n}'


def playlist(*entries):
    out = ["#EXTM3U"]
    for n, g, u in entries:
        out += [L.format(n=n, g=g), u]
    return "\n".join(out) + "\n"


class TurkishChannels(unittest.TestCase):
    def run_tool(self, text, channels, working):
        d = tempfile.mkdtemp()
        cfg = {"group": "Turkey", "allowed_hosts": ["medya.trt.com.tr", "daioncdn.net"], "channels": channels}
        for f in ("categories.json", "categories-fallback.json"):
            with open(os.path.join(ROOT, f), encoding="utf-8") as src, open(os.path.join(d, f), "w", encoding="utf-8") as dst:
                dst.write(src.read())
        with open(os.path.join(d, "c.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        p = os.path.join(d, "p.m3u")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        argv = ["x", p, "--config", os.path.join(d, "c.json"), "--apply", "--no-network-sources",
                "--report", os.path.join(d, "r.txt")]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(tc, "plays", lambda u: u in working), \
                mock.patch("builtins.print"):
            tc.main()
        with open(p, encoding="utf-8") as f:
            return f.read()

    def names(self, text):
        return [l.rsplit(",", 1)[-1] for l in text.splitlines() if 'group-title="Turkey"' in l]

    def test_listed_channels_go_on_top_in_order_rest_keeps_order(self):
        t = playlist(("Zeta", "Turkey", "http://z/1"), ("ATV", "Turkey", "https://a.daioncdn.net/atv.m3u8"),
                     ("Alpha", "Turkey", "http://a/1"), ("TRT 1", "Turkey", "https://tv-trt1.medya.trt.com.tr/m.m3u8"))
        out = self.run_tool(t, [{"names": ["TRT 1"]}, {"names": ["ATV"]}],
                            {"https://tv-trt1.medya.trt.com.tr/m.m3u8", "https://a.daioncdn.net/atv.m3u8"})
        self.assertEqual(self.names(out), ["TRT 1", "ATV", "Zeta", "Alpha"])

    def test_dead_link_is_kept_when_nothing_better_plays(self):
        t = playlist(("TV 8", "Turkey", "https://tv8.daioncdn.net/old.m3u8"))
        out = self.run_tool(t, [{"names": ["TV 8"], "urls": ["https://tv8.daioncdn.net/new.m3u8"]}], set())
        self.assertIn("https://tv8.daioncdn.net/old.m3u8", out)
        self.assertNotIn("new.m3u8", out)

    def test_dead_link_is_replaced_only_by_a_working_official_one(self):
        t = playlist(("TV 8", "Turkey", "https://tv8.daioncdn.net/old.m3u8"))
        ch = [{"names": ["TV 8"], "urls": ["http://random.example/tv8.m3u8", "https://tv8.daioncdn.net/new.m3u8"]}]
        out = self.run_tool(t, ch, {"http://random.example/tv8.m3u8", "https://tv8.daioncdn.net/new.m3u8"})
        self.assertIn("https://tv8.daioncdn.net/new.m3u8", out)
        self.assertNotIn("random.example", out)
        self.assertNotIn("old.m3u8", out)

    def test_token_links_are_never_used(self):
        t = playlist(("Alpha", "Turkey", "http://a/1"))
        u = "https://ciner.daioncdn.net/showtv/showtv.m3u8?e=1795226752&st=abc"
        out = self.run_tool(t, [{"names": ["Show TV"], "urls": [u]}], {u})
        self.assertNotIn("Show TV", out)

    def test_allow_token_uses_a_token_link_whose_server_ignores_it(self):
        u = "https://ciner.daioncdn.net/showtv/showtv.m3u8?st=old&e=1664766175"
        t = playlist(("SHOW TV", "Reality & Game Shows", u), ("Alpha", "Turkey", "http://a/1"))
        out = self.run_tool(t, [{"names": ["Show TV", "SHOW TV"], "allow_token": True, "urls": [u]}], {u})
        self.assertEqual(self.names(out), ["SHOW TV", "Alpha"])

    def test_copy_of_a_channel_from_another_group_keeps_that_entry(self):
        u = "https://halktv-live.daioncdn.net/halktv/halktv.m3u8"
        t = playlist(("Halk TV", "News", u), ("Alpha", "Turkey", "http://a/1"))
        out = self.run_tool(t, [{"names": ["Halk TV"], "urls": [u]}], {u})
        self.assertIn('group-title="News"', out)
        self.assertEqual(self.names(out), ["Halk TV", "Alpha"])

    def test_nothing_outside_the_group_changes_and_second_run_is_a_no_op(self):
        u = "https://tv-trt1.medya.trt.com.tr/m.m3u8"
        t = playlist(("Kanal X", "News", "http://n/1"), ("Alpha", "Turkey", "http://a/1"))
        once = self.run_tool(t, [{"names": ["TRT 1"], "urls": [u]}], {u})
        self.assertIn(L.format(n="Kanal X", g="News"), once)
        self.assertEqual(self.run_tool(once, [{"names": ["TRT 1"], "urls": [u]}], {u}), once)

    def test_not_added_when_the_nightly_build_would_move_it(self):
        # "drama" sends a stand-alone entry to "Series & Drama" in the build: adding it would flip-flop
        u = "https://x.daioncdn.net/kanald-drama.m3u8"
        t = playlist(("Alpha", "Turkey", "http://a/1"))
        out = self.run_tool(t, [{"names": ["Kanal D Drama"], "urls": [u]}], {u})
        self.assertNotIn("Kanal D Drama", out)


if __name__ == "__main__":
    unittest.main()
