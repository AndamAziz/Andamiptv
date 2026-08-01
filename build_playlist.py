import requests
import re

# هەموو سەرچاوەکانی M3U بەپێی سەرچاوە و ناو
SOURCES = {
    "Pluto TV (US)": "https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/refs/heads/main/playlists/plutotv_us.m3u",
    "Pluto TV (Global)": "https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/refs/heads/main/playlists/plutotv_all.m3u",
    "Samsung TV Plus": "https://apsattv.com/ssungusa.m3u",
    "Roku Channel": "https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/refs/heads/main/playlists/roku_all.m3u",
    "LG Channels": "https://www.apsattv.com/uslg.m3u",
    "Tubi TV": "https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/refs/heads/main/playlists/tubi_all.m3u",
    "Plex TV": "https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/refs/heads/main/playlists/plex_all.m3u",
    "Vizio WatchFree": "https://www.apsattv.com/vizio.m3u",
    "DistroTV": "https://www.apsattv.com/distro.m3u",
    "Xiaomi TV": "https://www.apsattv.com/xiaomi.m3u",
    "XUMO": "https://www.apsattv.com/xumo.m3u",
    "Local Now": "https://www.apsattv.com/localnow.m3u",
    "Rakuten TV (UK)": "https://www.apsattv.com/rakutentv-uk.m3u",
    "Rakuten TV (FR)": "https://www.apsattv.com/rakutentv-fr.m3u",
    "Vidaa TV": "https://www.apsattv.com/vidaa.m3u",
    "Amazon Fire TV": "https://www.apsattv.com/firetv.m3u",
    "IPTV-Org Movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "IPTV-Org News": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "IPTV-Org Documentary": "https://iptv-org.github.io/iptv/categories/documentary.m3u",
    "IPTV-Org Music": "https://iptv-org.github.io/iptv/categories/music.m3u",
    "IPTV-Org Comedy": "https://iptv-org.github.io/iptv/categories/comedy.m3u",
    "IPTV-Org USA": "https://iptv-org.github.io/iptv/countries/us.m3u"
}

def fetch_and_merge():
    combined_lines = ["#EXTM3U\n"]
    seen_urls = set()

    for provider, url in SOURCES.items():
        print(f"Fetching {provider}...")
        try:
            res = requests.get(url, timeout=15)
            if res.status_code != 200:
                continue

            lines = res.text.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if line.startswith("#EXTINF"):
                    info_line = line
                    stream_url = lines[i+1].strip() if i+1 < len(lines) else ""

                    # ڕێگری لە لینکە دووبارەکان و بەستەرە خاڵییەکان
                    if stream_url and stream_url not in seen_urls and stream_url.startswith("http"):
                        seen_urls.add(stream_url)
                        
                        # ئەگەر group-title نەبوو یان ویستت سەرچاوەکەی لەگەڵ دیاری بێت:
                        if 'group-title="' not in info_line:
                            info_line = info_line.replace('#EXTINF:-1', f'#EXTINF:-1 group-title="{provider}"')
                        
                        combined_lines.append(f"{info_line}\n{stream_url}\n")
                    i += 1
                i += 1
        except Exception as e:
            print(f"Error fetching {provider}: {e}")

    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.writelines(combined_lines)

    print("Master playlist built successfully!")

if __name__ == "__main__":
    fetch_and_merge()
