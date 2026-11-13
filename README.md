# AndamIPTV 📺

پلەیلیستێکی IPTV (M3U) کە بە شێوەی خۆکار ڕۆژانە پاکژ، پۆلێن، و پشکنین دەکرێت.

![Daily Update](https://github.com/AndamAziz/Andamiptv/actions/workflows/daily-update.yml/badge.svg)

## 🔗 لینکی ڕاستەوخۆ

ئەم لینکە بخەرە ناو هەر IPTV player ـێک (VLC, Tivimate, IPTV Smarters, ...):

```
https://raw.githubusercontent.com/AndamAziz/Andamiptv/main/playlist.m3u
```

## ✨ تایبەتمەندییەکان

- **پاکژکردنەوەی خۆکار ڕۆژانە** — دووبارە لابردنی کەناڵی دووبارە، فلتەرکردنی بلۆکلیست، سڕینەوەی تاگی نەشیاو (1080p, HD, ...)
- **پۆلێنکردنی خۆکار** — کەناڵەکان بەپێی ناو دابەش دەکرێن بۆ گروپی گونجاو (کوردی، Sky، وەرزشی، ...)
- **چێککردنی زیندووبوونی کەناڵ** — هەموو ڕۆژێک هەموو کەناڵەکان تاقی دەکرێنەوە، ئەوانەی کارناکەن دەردەچن
- **زیادکردنی کەناڵی نوێ بە دەستی** — لە ڕێگەی workflow ـی `Add Channels From External Source`

## 📊 پۆلەکان

پۆلبەندی لە `categories.json` ـەوە دیاریدەکرێت. پۆلە سەرەکییەکان:

- کوردی (Kurdish Channels)
- Sky Channels
- Sports

## 🛠️ بۆ گەشەپێدەران

| فایل | کارەکەی |
|---|---|
| `build_playlist.py` | پاکژکردن، پۆلێنکردن، فلتەرکردن (`python3 build_playlist.py --overwrite`) |
| `check-dead-channels.mjs` | چێککردنی زیندووبوونی هەموو کەناڵ (`node check-dead-channels.mjs`) |
| `add-channels.mjs` | زیادکردنی کەناڵی نوێ لە سەرچاوەی دەرەکی |
| `categories.json` | ڕێساکانی پۆلێنکردن |
| `blocklist.txt` | وشەی بلۆککراو بۆ فلتەرکردن |

### Workflow ـەکان

- **Daily Playlist Update** — ڕۆژانە بە شێوەی خۆکار کار دەکات (00:00 UTC)، دەتوانیت بە دەستیش لە ڕێگەی `workflow_dispatch` هەڵیبدەیت
- **Add Channels From External Source** — بە دەستی جێبەجێ دەبێت، سەرچاوەی M3U وەردەگرێت و کەناڵی نوێی بۆ زیاد دەکات

## ⚠️ ڕەچاوکردن

ئەم پلەیلیستە کۆکراوەتەوە لە سەرچاوەی گشتی و بۆ بەکارهێنانی کەسی/تاقیکارییە. مافی هەر کەناڵێک هی خاوەنی ڕاستەقینەیەتی.

## Free (licensed) movies from the Internet Archive

`archive_add.py` + the workflow **Add free movies from Internet Archive** add only movies with a public-domain / CC0 license
(CC-BY optional, non-commercial licenses are always skipped). The files stay on archive.org, so nothing is stored on your VPS or Lovable.

1. GitHub → **Actions** → *Add free movies from Internet Archive* → **Run workflow**.
2. First run with **dry_run = true** (default): open the run → *Summary* to see the table (title, year, minutes, size, license, link).
3. Happy with the list? Run again with **dry_run = false**: the movies are added to `playlist.m3u` (group "Free Classics") and the snapshot is updated.

Checks before a movie is listed: license, real feature length (40+ min), an `.mp4` (h.264) file, and the link answers a Range request (HTTP 206) so seeking works.
Optional (recommended): add a repository secret `TMDB_API_KEY` (free TMDB key) to get the `{tmdb-ID}` tag, the TMDB poster and the GENRE group (Action, Comedy, Horror ...) when the title/year match exactly; without it movies go to the "Free Classics" group.
Run it again any time: titles already in the playlist are skipped.

### Classic cartoon series (public domain)
`python3 archive_series.py` (add `--apply` to write) builds series from archive.org cartoons (Betty Boop, Popeye, Superman 1941, Felix the Cat ...):
episodes are named `Show - S01E01`, group "Classic Cartoons", every link verified (HTTP 206). Shows with fewer than 3 verified episodes are skipped.

### Full HD / 4K quality filter, weekly report, safe imports
- **Quality:** `min_height` defaults to **1080** (Full HD = 1920 px wide or 1080 high; 4K also passes). The resolution comes from the video file metadata (and from `ffprobe` on the stream when available), never from the title. 720p and lower are rejected, **unknown resolution is excluded**, nothing is upscaled/relabelled. `min_height = 0` turns the filter off.
- **Honest limit:** public-domain / licensed films on archive.org are almost all below 720p (80-film sample: none reached 720p), so the Full HD filter currently finds (almost) nothing there. The filter is NOT weakened to get more movies; new licensed Full HD/4K sources can be registered in `SOURCES` (same function signature as `source_internet_archive`).
- **Report first:** every run writes a report (also in the run *Summary* and as artifact `archive-report`) with: scanned, accepted 1080p, accepted 4K, rejected 720p-and-lower, unknown resolution, invalid links, license rejections, duplicates, plus a `Res` column per candidate. `dry_run` is **true** by default; the Sunday schedule is always report-only.
- **Safe writes:** a manual run with `dry_run` unchecked never pushes to `main`: it commits only *appended* movies to a new branch `archive-import-<run>` and opens a pull request for you to review. Existing movies are never deleted or reordered.
- Tests: `python -m unittest discover -s tests -v` (360p/720p rejected, 1080p/2160p accepted, unknown rejected) also run first in the workflow.

## Live-channel logos on imgur (blocked in some regions)

`i.imgur.com` shows "Content not viewable in your region" in Kurdistan, so ~5,000 live
channel logos looked broken. `mirror_logos.py` copies each imgur logo of a **live** channel
into `logos/` (160px, 8-bit PNG) and points `tvg-logo` at
`raw.githubusercontent.com/AndamAziz/Andamiptv/main/logos/<id>.png`. It also fills an empty
logo from an exact same-name channel. Logos you set yourself (postimg, wikimedia…) and all
movies/series are untouched. The `mirror-logos` workflow runs it after every playlist change.

### Finding real logos for channels that have none

`fill_logos.py` fills an empty `tvg-logo` of a **live** channel only from exact sources: the
Xumo channel id inside its stream URL, an exact (unambiguous) name in `tv-logo/tv-logos`, or an
iptv-org channel id equal to its `tvg-id`. Wrong logos are worse than none, so there is no fuzzy
matching. `logo-fill-report.txt` lists what was filled and the channels that still need a logo link.

## New entries go to the top of their group

When you add a movie, series episode or live channel (web form / upload), `categorize_new.py`
(run by the auto-heal workflow) moves it to the **top of its own group**:
a new movie → first movie of its group; a new episode of an existing show → right after that
show's last episode; a brand-new show → first series of its group; a new live channel → first
channel of its group. Only the new entries at the end of the file are touched; a bulk import of
more than 20 entries keeps its order. Covered by `tests/test_new_entries.py`.

## Stream Inspector (check links from your own PC)

`tools/stream_inspector.py` checks that stream links really play (HLS master -> variant ->
segment, MPEG-TS, MP4/fMP4, DASH), following redirects. No links are written in the script:

```powershell
python tools\stream_inspector.py "http://host/play/a006/index.m3u8" --name "Fox Sports 2"
python tools\stream_inspector.py -f channels.m3u --workers 8
python tools\stream_inspector.py            # then paste links (Name|URL), empty line = start
```

It writes `active.m3u` (working links, names/logos/groups kept), `report.csv` and `failed.txt`.
Standard library only (Python 3.8+).
