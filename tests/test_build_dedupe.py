"""The nightly build must keep a live channel that is listed again in ANOTHER group on purpose."""
import os, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def ext(name, group, kind=''):
    return f'#EXTINF:-1 tvg-name="{name}"tvg-id=""tvg-logo=""tvg-chno=""{kind}group-title="{group}":http-referrer="",{name}'

def build(lines):
    d = tempfile.mkdtemp()
    src, dst = os.path.join(d, 'in.m3u'), os.path.join(d, 'out.m3u')
    open(src, 'w', encoding='utf-8').write('#EXTM3U\n' + '\n'.join(lines) + '\n')
    subprocess.run([sys.executable, os.path.join(ROOT, 'build_playlist.py'), '-i', src, '-o', dst], check=True, capture_output=True, cwd=ROOT)
    return [l for l in open(dst, encoding='utf-8').read().split('\n') if l and not l.startswith('#')]

class BuildDedupe(unittest.TestCase):
    def test_same_stream_in_two_groups_is_kept(self):
        urls = build([ext('BEIN SPORTS 1', 'BEIN SPORTS AR'), 'https://s.example/bein1.m3u8',
                      ext('BEIN SPORTS 1', 'Sports'), 'https://s.example/bein1.m3u8'])
        self.assertEqual(len(urls), 2)

    def test_same_stream_twice_in_one_group_is_one_entry(self):
        urls = build([ext('News A', 'News'), 'https://s.example/n.m3u8',
                      ext('News A copy', 'News'), 'http://s.example:80/n.m3u8/'])
        self.assertEqual(len(urls), 1)

    def test_movies_stay_one_per_stream(self):
        t = 'tvg-type="movie"'
        urls = build([ext('M1', 'Action', t), 'https://v.example/m.mp4', ext('M1', 'Drama', t), 'https://v.example/m.mp4'])
        self.assertEqual(len(urls), 1)

class KeepQualityWords(unittest.TestCase):
    def test_hd_stays_in_the_name_brackets_go(self):
        d = tempfile.mkdtemp()
        src, dst = os.path.join(d, 'in.m3u'), os.path.join(d, 'out.m3u')
        open(src, 'w', encoding='utf-8').write('#EXTM3U\n' + ext('RANYA CITY HD (Backup)', 'Kurdish Channels') + '\nhttps://s.example/r.m3u8\n')
        subprocess.run([sys.executable, os.path.join(ROOT, 'build_playlist.py'), '-i', src, '-o', dst], check=True, capture_output=True, cwd=ROOT)
        names = [l.rsplit(',', 1)[-1] for l in open(dst, encoding='utf-8').read().split('\n') if l.startswith('#EXTINF')]
        self.assertEqual(names, ['RANYA CITY HD'])


class CopyKeepsItsOwnGroup(unittest.TestCase):
    def test_copy_with_a_name_rule_stays_in_the_group_written(self):
        # "nrt" is a Kurdish-Channels keyword, but the owner copied NRT SPORT into Sports on purpose
        urls = build([ext('NRT SPORT', 'Kurdish Channels'), 'https://s.example/nrt.m3u8',
                      ext('NRT SPORT', 'Sports'), 'https://s.example/nrt.m3u8'])
        self.assertEqual(len(urls), 2)
        urls = build([ext('NRT SPORT', 'Kurdish Channels'), 'https://s.example/nrt.m3u8',
                      ext('NRT SPORT', 'Sports'), 'https://s.example/nrt.m3u8'])
        self.assertEqual(len(urls), 2)   # and a second nightly run changes nothing


if __name__ == '__main__':
    unittest.main()
