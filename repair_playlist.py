#!/usr/bin/env python3
"""Auto-heal playlist.m3u after an upload of the reseller panel's "Download .m3u".

The panel export drops tvg-id / tvg-chno / tvg-type and rewrites group-titles, which mixes
movies, series and live channels. This script restores them from library/playlist.snapshot.m3u
(the last healthy playlist), matching entries by stream URL:

  * entry already has tvg-chno= or tvg-type=  -> healthy, left untouched
  * damaged VOD entry (URL is movie/series in snapshot) -> snapshot line restored completely
  * damaged live entry -> snapshot line restored, but the name and logo from the upload are kept
  * URL unknown to the snapshot -> left as is (treated as a live channel by build_playlist.py)

Usage: python3 repair_playlist.py [playlist.m3u] [snapshot.m3u]
After repairing, run build_playlist.py --overwrite, then --update-snapshot to refresh the snapshot.
"""
import re, sys
from collections import defaultdict, deque

TAIL = re.compile(r'group-title="[^"]*"(?::http-referrer="[^"]*")?,(.*)$')

def parse(text):
    head, blocks, cur = [], [], None
    for line in text.splitlines():
        if line.startswith('#EXTINF'):
            cur = {'extinf': line, 'extras': []}
        elif cur is not None and line.startswith('#'):
            cur['extras'].append(line)
        elif cur is not None and line.strip():
            cur['url'] = line.strip()
            blocks.append(cur)
            cur = None
        elif cur is None and not blocks:
            head.append(line)
    return head, blocks

def attr(extinf, key):
    m = re.search(key + r'="([^"]*)"', extinf)
    return m.group(1) if m else ''

def is_vod(extinf):
    return 'tvg-type="movie"' in extinf or 'tvg-type="series"' in extinf

def healthy(extinf):
    return 'tvg-chno=' in extinf or 'tvg-type=' in extinf

def swap(extinf, key, value):
    return re.sub(key + r'="[^"]*"', lambda m: '%s="%s"' % (key, value), extinf, count=1)

def repair(cur_text, snap_text):
    head, cur = parse(cur_text)
    _, snap = parse(snap_text)
    by_url = defaultdict(deque)
    for b in snap:
        by_url[b['url']].append(b)
    stats = {'kept': 0, 'vod': 0, 'live': 0, 'unknown': 0}
    for b in cur:
        if healthy(b['extinf']):
            stats['kept'] += 1
            continue
        q = by_url.get(b['url'])
        if not q:
            stats['unknown'] += 1
            continue
        s = q.popleft() if len(q) > 1 else q[0]
        if is_vod(s['extinf']):
            b['extinf'] = s['extinf']
            stats['vod'] += 1
        else:
            name, logo = attr(b['extinf'], 'tvg-name'), attr(b['extinf'], 'tvg-logo')
            m = TAIL.search(b['extinf'])
            disp = (m.group(1) if m else '').strip() or name
            e = s['extinf']
            if name:
                e = swap(e, 'tvg-name', name)
            if logo:
                e = swap(e, 'tvg-logo', logo)
            mt = TAIL.search(e)
            if mt and disp:
                e = e[:mt.start(1)] + disp
            b['extinf'] = e
            stats['live'] += 1
    out = list(head) or ['#EXTM3U']
    for b in cur:
        out.append(b['extinf']); out.extend(b['extras']); out.append(b['url'])
    return '\n'.join(out) + '\n', stats

def counts(text):
    _, bl = parse(text)
    return {'total': len(bl),
            'movies': sum('tvg-type="movie"' in b['extinf'] for b in bl),
            'series': sum('tvg-type="series"' in b['extinf'] for b in bl),
            'with_id': sum('tvg-id=' in b['extinf'] for b in bl)}

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    pl = args[0] if len(args) > 0 else 'playlist.m3u'
    sn = args[1] if len(args) > 1 else 'library/playlist.snapshot.m3u'
    if '--update-snapshot' in sys.argv:
        t = open(pl, encoding='utf-8').read(); c = counts(t)
        sc = counts(open(sn, encoding='utf-8').read())
        if c['movies'] > 0 and c['series'] > 0 and c['with_id'] > c['total'] * 0.9 and c['total'] > sc['total'] * 0.5:
            open(sn, 'w', encoding='utf-8').write(t); print('snapshot updated', c)
        else:
            print('playlist not healthy, snapshot NOT updated', c)
        sys.exit(0)
    new, st = repair(open(pl, encoding='utf-8').read(), open(sn, encoding='utf-8').read())
    open(pl, 'w', encoding='utf-8').write(new)
    print('repair:', st, counts(new))
