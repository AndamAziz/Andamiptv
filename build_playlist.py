import os
import re

def load_blocklist(filepath="blocklist.txt"):
    """خوێندنەوەی وشە قەدەغەکراوەکان لە فایلی blocklist.txt"""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]

def categorize_channel(extinf_line):
    """پۆلێنکردنی خۆکار بۆ کەناڵەکان بە پێی ناوەکەیان"""
    extinf_lower = extinf_line.lower()
    
    kurdish_keywords = ["kurd", "rudaw", "nrt", "ava", "kurdistan", "k24", "gkurd", "zagros"]
    if any(kw in extinf_lower for kw in kurdish_keywords):
        return "Kurdish Channels"
        
    sports_keywords = ["bein", "ssc", "sport", "channellive", "bt sport", "espn"]
    if any(kw in extinf_lower for kw in sports_keywords):
        return "Sports"
        
    return "Other"

def clean_name_and_meta(extinf_line):
    """پاککردنەوەی ناوەکان لە هێما و پاشگرە زیادەکان وەک HD و FHD"""
    if ',' in extinf_line:
        meta, name = extinf_line.split(',', 1)
        cleaned_name = re.sub(r'\[.*?\]|\(.*?\)|(1080p|720p|HD|FHD|4K|HEVC|SD)', '', name, flags=re.IGNORECASE)
        cleaned_name = ' '.join(cleaned_name.split())
        if not cleaned_name:
            cleaned_name = name.strip()
        return f"{meta},{cleaned_name}\n"
    return extinf_line

def smart_manage_logo(extinf_line):
    """بەڕێوەبردنی زیرەکی لۆگۆ (ئەگەر هەبوو سکیپ، ئەگەر نەبوو پڕکردنەوە)"""
    extinf_lower = extinf_line.lower()
    has_logo = "tvg-logo=" in extinf_line and 'tvg-logo=""' not in extinf_line and 'tvg-logo=" "' not in extinf_line
    
    if has_logo:
        return extinf_line
        
    logos = {
        "rudaw": "https://raw.githubusercontent.com/AndamAziz/Andamiptv/main/photo_2026-08-02_06-39-02.jpg",
        "k24": "https://upload.wikimedia.org/wikipedia/commons/5/50/Kurdistan24_logo.png",
        "nrt": "https://upload.wikimedia.org/wikipedia/commons/7/74/NRT_Logo.png",
        "trt kurdi": "https://upload.wikimedia.org/wikipedia/commons/9/91/TRT_Kurd%C3%AE_logo_2021.png"
    }
    
    for key, logo_url in logos.items():
        if key in extinf_lower:
            if "group-title=" in extinf_line:
                extinf_line = extinf_line.replace('group-title="', f'tvg-logo="{logo_url}" group-title="')
            else:
                extinf_line = extinf_line.replace("#EXTINF:", f'#EXTINF:-1 tvg-logo="{logo_url}"')
            break
            
    return extinf_line

def clean_playlist(input_file="playlist.m3u"):
    blocklist = load_blocklist()
    print(f"ژمارەی وشە قەدەغەکراوەکان: {len(blocklist)}")

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
                is_blocked = any(keyword in extinf_lower for keyword in blocklist)
                if is_blocked:
                    skipped_blocked += 1
                    i += 2
                    continue
                    
                # 2. پشکنینی دووبارە
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

                # 5. بەڕێوەبردنی زیرەکی لۆگۆ
                extinf_line = smart_manage_logo(extinf_line)

                seen_urls.add(clean_url)
                
                # کۆکردنەوەی کەناڵەکان لە لیستێکدا بۆ ڕیزکردن
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

    # **ڕیزکردنی هۆشمەند (Sorting):** هێنانی کەناڵە کوردییەکان بۆ سەری سەرەوە
    def sort_priority(ch):
        cat = ch['category']
        if cat == "Kurdish Channels":
            return 0  # پلەی یەکەم (لوتكە)
        elif cat == "Sports":
            return 1  # پلەی دووەم
        else:
            return 2  # کەناڵەکانی تر لە خوارەوە

    channels.sort(key=sort_priority)

    # دروستکردنەوەی فایلی کۆتایی پڵەیلیست
    new_lines = ["#EXTM3U\n"]
    for ch in channels:
        new_lines.append(ch['extinf'])
        new_lines.append(ch['url'])

    with open(input_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"سەرکەوتبوو: کەناڵە کوردییەکان هێنرانە سەرەوە و پڵەیلیستەکە ڕێکخرایەوە.")

if __name__ == "__main__":
    clean_playlist()
