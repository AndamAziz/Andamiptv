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
