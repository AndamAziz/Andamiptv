import os
import re

# ==========================================
# 🛠️ بەشی ڕێکخستنی سەرەکی (Configuration)
# دەتوانیت لە ئایندەدا بە ئاسانی لێرە گۆڕانکاری بکەیت
# ==========================================
BLOCKLIST_FILE = "blocklist.txt"
INPUT_PLAYLIST = "playlist.m3u"


# پۆلێنکردنی کەناڵەکان بە پێی وشەی کلیدی
CATEGORIES = {
    "Kurdish Channels": ["kurd", "rudaw", "nrt", "ava", "kurdistan", "k24", "gkurd", "zagros"],
    "Sky Channels": ["sky cinema", "sky history", "sky arts", "sky nature", "sky kids", "sky one", "sky two", "sky sports"],
    "Sports": ["bein", "ssc", "sport", "channellive", "bt sport", "espn"]
}

# ==========================================
# ⚙️ بەشی لۆژیکی سەرەکی سکریپت (Core Engine)
# ==========================================

def load_blocklist(filepath=BLOCKLIST_FILE):
    """خوێندنەوەی وشە قەدەغەکراوەکان لە فایلی دەرەکی"""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]

def categorize_channel(extinf_line):
    """پۆلێنکردنی خۆکاری کەناڵەکان بە پێی پێکهاتەی ناوەکەیان"""
    extinf_lower = extinf_line.lower()
    for category, keywords in CATEGORIES.items():
        if any(kw in extinf_lower for kw in keywords):
            return category
    return "Other"

def clean_name_and_meta(extinf_line):
    """پاککردنەوەی ناوی کەناڵ لە پاشگرو هێما زیادەکان وەک کواڵیتییەکان"""
    if ',' in extinf_line:
        meta, name = extinf_line.split(',', 1)
        cleaned_name = re.sub(r'\[.*?\]|\(.*?\)|(1080p|720p|HD|FHD|4K|HEVC|SD|60FPS|50FPS)', '', name, flags=re.IGNORECASE)
        cleaned_name = ' '.join(cleaned_name.split())
        if not cleaned_name:
            cleaned_name = name.strip()
        return f"{meta},{cleaned_name}\n"
    return extinf_line

def smart_manage_logo(extinf_line):
    """دانانی لۆگۆی زیرەک بۆ ئەو کەناڵانەی کە لۆگۆیان نییە"""
    extinf_lower = extinf_line.lower()
    has_logo = "tvg-logo=" in extinf_line and 'tvg-logo=""' not in extinf_line and 'tvg-logo=" "' not in extinf_line
    
    if has_logo:
        return extinf_line
        
    for key, logo_url in LOGOS.items():
        if key in extinf_lower:
            if "group-title=" in extinf_line:
                extinf_line = extinf_line.replace('group-title="', f'tvg-logo="{logo_url}" group-title="')
            else:
                extinf_line = extinf_line.replace("#EXTINF:", f'#EXTINF:-1 tvg-logo="{logo_url}"')
            break
            
    return extinf_line

def process_master_playlist(input_file=INPUT_PLAYLIST):
    blocklist = load_blocklist()
    print(f"ژمارەی وشە قەدەغەکراوەکان بارکران: {len(blocklist)}")

    if not os.path.exists(input_file):
        print(f"فایلی پڵەیلیست نەدۆزراوەتەوە: {input_file}")
        return

    with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    channels = []
    skipped_blocked = 0
    skipped_duplicates = 0
    seen_urls = set()
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        if line.startswith("#EXTINF:"):
            if i + 1 < len(lines):
                extinf_line = line
                url_line = lines[i+1]
                
                extinf_lower = extinf_line.lower()
                clean_url = url_line.strip()
                
                # 1. پشکنینی بلۆکلیست
                if any(keyword in extinf_lower for keyword in blocklist):
                    skipped_blocked += 1
                    i += 2
                    continue
                    
                # 2. لابردنی دووبارەکان
                if clean_url in seen_urls:
                    skipped_duplicates += 1
                    i += 2
                    continue
                    
                # 3. پۆلێنکردنی خۆکار
                category = categorize_channel(extinf_line)
                if category != "Other":
                    if "group-title=" in extinf_line:
                        extinf_line = re.sub(r'group-title="[^"]*"', f'group-title="{category}"', extinf_line)
                    else:
                        extinf_line = extinf_line.replace("#EXTINF:", f'#EXTINF:-1 group-title="{category}"')

                # 4. پاککردنەوەی ناوی کەناڵەکان
                extinf_line = clean_name_and_meta(extinf_line)

                # 5. بەڕێوەبردنی لۆگۆ
                extinf_line = smart_manage_logo(extinf_line)

                seen_urls.add(clean_url)
                
                # پاشەکەوتکردن لە لیستدا بۆ ڕیزکردن
                channels.append({
                    'extinf': extinf_line,
                    'url': url_line,
                    'category': category
                })
                
                i += 2
            else:
                i += 1
        else:
            i += 1

    # ڕیزکردنی هۆشمەندی پێشکەوتوو (Sorting Priority)
    def sort_priority(ch):
        cat = ch['category']
        if cat == "Kurdish Channels":
            return 0  # لووتکە (سەری سەرەوە)
        elif cat == "Sky Channels":
            return 1  # پلەی دووەم
        elif cat == "Sports":
            return 2  # پلەی سێیەم
        else:
            return 3  # کەناڵەکانی تر

    channels.sort(key=sort_priority)

    # دروستکردنەوەی فایلی کۆتایی پڵەیلیست
    new_lines = ["#EXTM3U\n"]
    for ch in channels:
        new_lines.append(ch['extinf'])
        new_lines.append(ch['url'])

    with open(input_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"سەرکەوتوو بوو! کەناڵە بلۆککراوەکان: {skipped_blocked} | دووبارەکان: {skipped_duplicates} | کۆی گشتی ماوەکان: {len(channels)}")

if __name__ == "__main__":
    process_master_playlist()
