"""New movies/series/live channels added by the web form go to the TOP of their group."""
import os, re, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def ext(name, group, kind=None):
    t = f'tvg-type="{kind}"' if kind else ''
    return f'#EXTINF:-1 tvg-name="{name}"tvg-id=""tvg-logo=""tvg-chno=""{t}group-title="{group}":http-referrer="",{name}'

def run(known_lines, all_lines):
    d = tempfile.mkdtemp()
    pl, sn = os.path.join(d, 'p.m3u'), os.path.join(d, 's.m3u')
    open(pl, 'w', encoding='utf-8').write('#EXTM3U\n' + '\n'.join(all_lines) + '\n')
    open(sn, 'w', encoding='utf-8').write('#EXTM3U\n' + '\n'.join(known_lines) + '\n')
    subprocess.run([sys.executable, os.path.join(ROOT, 'categorize_new.py'), pl, sn], check=True, capture_output=True)
    return [l.rsplit(',', 1)[-1] for l in open(pl, encoding='utf-8').read().split('\n') if l.startswith('#EXTINF')]

BASE = [ext('Live A', 'Sports'), 'http://x/a', ext('Live B', 'Sports'), 'http://x/b',
        ext('Movie 1', 'Horror', 'movie'), 'http://v/1', ext('Movie 2', 'Horror', 'movie'), 'http://v/2',
        ext('Show - S01E01', 'Drama', 'series'), 'http://v/s1', ext('Show - S01E02', 'Drama', 'series'), 'http://v/s2',
        ext('Other - S01E01', 'Drama', 'series'), 'http://v/o1']

class NewEntries(unittest.TestCase):
    def test_new_movie_goes_to_top_of_its_group(self):
        n = run(BASE, BASE + [ext('Movie New', 'Horror', 'movie'), 'http://v/new'])
        self.assertEqual(n[2:5], ['Movie New', 'Movie 1', 'Movie 2'])

    def test_new_episode_of_existing_show_goes_after_its_last_episode(self):
        n = run(BASE, BASE + [ext('Show - S01E03', 'Drama', 'series'), 'http://v/s3'])
        self.assertEqual(n[n.index('Show - S01E02') + 1], 'Show - S01E03')

    def test_new_show_goes_to_top_of_series_group(self):
        n = run(BASE, BASE + [ext('Fresh - S01E01', 'Drama', 'series'), 'http://v/f1'])
        self.assertEqual(n[n.index('Show - S01E01') - 1], 'Fresh - S01E01')

    def test_new_live_channel_goes_to_top_of_its_group(self):
        n = run(BASE, BASE + [ext('Live New', 'Sports'), 'http://x/new'])
        self.assertEqual(n[:3], ['Live New', 'Live A', 'Live B'])

    def test_bulk_import_is_left_alone(self):
        many = [x for i in range(25) for x in (ext(f'Bulk {i}', 'Horror', 'movie'), f'http://v/b{i}')]
        n = run(BASE, BASE + many)
        self.assertEqual(n[-1], 'Bulk 24')

    def test_nothing_changes_without_new_entries(self):
        n = run(BASE, BASE)
        self.assertEqual(n, ['Live A', 'Live B', 'Movie 1', 'Movie 2', 'Show - S01E01', 'Show - S01E02', 'Other - S01E01'])

if __name__ == '__main__':
    unittest.main()
