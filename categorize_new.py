#!/usr/bin/env python3
"""Categorize ONLY brand-new live channels. Never removes, renames or re-sorts anything else.

A "new" entry is a live (no tvg-type) entry whose stream URL is not in the snapshot
(library/playlist.snapshot.m3u). For each one:
  * if its group-title is empty / unknown (not an existing group), it gets a group from the
    keyword rules (categories.json, then categories-fallback.json);
  * if it sits after the first movie/series (e.g. appended by the web form), it is moved to the
    end of its group's live block. Entries placed by hand in the live section stay where they are.
Usage: python3 categorize_new.py [playlist.m3u] [snapshot.m3u]
"""
import os, re, sys
sys.dont_write_bytecode = True
import build_playlist as bp

MAX_TAIL = 20   # a bigger batch is a bulk import: leave its order alone

def _show(e):
    name = e['lines'][0].rsplit(',', 1)[-1].strip()
    return re.sub(r'\s*[-–]\s*S\d+\s*E\d+.*$', '', name, flags=re.I).strip().lower()

def move_new_vod_to_top(entries, known, is_vod):
    """Movies/series appended at the END of the file (the web form does this) go to the top of
    their own group: a new movie -> first movie of its group; an episode of a show that already
    exists -> right after that show's last episode; a brand-new show -> first series of the group.
    Only the unbroken run of new entries at the very end of the file is touched."""
    if not known: return []
    last_known = max((k for k, e in enumerate(entries) if bp.same_stream_key(e['url']) in known), default=-1)
    tail = [e for e in entries[last_known + 1:] if is_vod(e)]
    if not tail or len(tail) > MAX_TAIL or any(not is_vod(e) for e in entries[last_known + 1:]): return []
    moved = []
    for e in reversed(tail):                      # reversed: several new ones keep their file order
        del entries[next(i for i, x in enumerate(entries) if x is e)]
        g, t = bp.get_group_title(e['lines'][0]), bp.vod_type(e['lines'][0])
        same = [p for p, o in enumerate(entries) if is_vod(o) and bp.vod_type(o['lines'][0]) == t and bp.get_group_title(o['lines'][0]) == g]
        pos = None
        if same and t == 'series':
            eps = [p for p in same if _show(entries[p]) == _show(e)]
            pos = (max(eps) + 1) if eps else same[0]
        elif same:
            pos = same[0]
        if pos is None: entries.append(e)         # new group: stays where it is
        else: entries.insert(pos, e); moved.append(e)
    return moved

def main(pl='playlist.m3u', sn='library/playlist.snapshot.m3u'):
    base = os.path.dirname(os.path.abspath(bp.__file__))
    cats = bp.load_categories(os.path.join(base, bp.DEFAULT_CATEGORIES_FILE))
    fb = bp.load_fallback(os.path.join(base, bp.DEFAULT_FALLBACK_FILE))
    logos = bp.load_category_logos(os.path.join(base, bp.DEFAULT_LOGOS_FILE))
    lines = open(pl, encoding='utf-8-sig', errors='ignore').read().split('\n')
    header, entries = [], []   # entry: dict(lines=[extinf, extras..., url], extinf, url)
    i = 0
    while i < len(lines):
        if lines[i].startswith('#EXTINF:'):
            j = i + 1
            while j < len(lines) and lines[j].startswith('#') and not lines[j].startswith('#EXTINF:'):
                j += 1
            if j < len(lines) and lines[j].strip():
                entries.append({'lines': lines[i:j + 1], 'url': lines[j].strip()}); i = j + 1; continue
        elif not entries: header.append(lines[i])
        i += 1
    known = set()
    if os.path.exists(sn):
        for l in open(sn, encoding='utf-8-sig', errors='ignore').read().split('\n'):
            if l.strip() and not l.startswith('#'): known.add(bp.same_stream_key(l.strip()))
    is_vod = lambda e: bool(bp.vod_type(e['lines'][0]))
    groups = {bp.get_group_title(e['lines'][0]) for e in entries if not is_vod(e) and bp.same_stream_key(e['url']) in known} | set(cats) | set(fb)
    first_vod = next((k for k, e in enumerate(entries) if is_vod(e)), len(entries))
    moved, changed = [], 0
    for k, e in enumerate(entries):
        if is_vod(e) or bp.same_stream_key(e['url']) in known: continue
        x = e['lines'][0]
        grp = bp.get_group_title(x) if 'group-title="' in x else ''
        if grp not in groups or grp in ('', bp.UNCATEGORIZED_LABEL):
            c = bp.categorize_channel(x, cats, e['url'])
            if c in (bp.UNCATEGORIZED_KEY, bp.REGROUP_KEY) and fb:
                s = bp.categorize_channel(x, fb, e['url'])
                if s != bp.UNCATEGORIZED_KEY: c = s
            label = bp.UNCATEGORIZED_LABEL if c == bp.UNCATEGORIZED_KEY else c
            x = bp.set_group_title(x, label)
            if c in logos and not re.search(r'tvg-logo="[^"]+"', x): x = bp.apply_default_logo(x, logos[c])
            e['lines'][0] = x; changed += 1
        if k >= first_vod: moved.append(k)
    pulled = [entries.pop(k) for k in sorted(moved, reverse=True)][::-1]
    for e in pulled:
        g = bp.get_group_title(e['lines'][0])
        # newest live channel goes to the TOP of its group's live block
        pos = min((p for p, o in enumerate(entries) if not is_vod(o) and bp.get_group_title(o['lines'][0]) == g), default=None)
        if pos is None: pos = next((p for p, o in enumerate(entries) if is_vod(o)), len(entries))
        entries.insert(pos, e)
    vod_moved = move_new_vod_to_top(entries, known, is_vod)
    moved = moved + vod_moved
    out = header + [l for e in entries for l in e['lines']]
    open(pl, 'w', encoding='utf-8').write('\n'.join(out) + ('' if out and out[-1] == '' else '\n'))
    print(f'categorize_new: {changed} new channel(s) categorized, {len(moved)} moved to the top')

if __name__ == '__main__':
    a = [x for x in sys.argv[1:]]
    main(*a)
