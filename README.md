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

### Weekly discovery report, quality filter
- The workflow also runs **every Sunday as a REPORT ONLY** (it never changes `playlist.m3u`): open the run → *Summary* / artifact `archive-report` to see new licensed candidates, then run it manually with `dry_run` unchecked to add them.
- `min_height` (0 / 480 / 720 ...) filters by the video height reported by archive.org. Note: almost all archive.org public-domain films are below 720p (in a 80-film sample none reached 720p), so a 720p filter finds nothing; the report shows the resolution (`Res`) so you can judge.
