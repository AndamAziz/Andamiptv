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
    
    # پۆلێنی کەناڵە کوردییەکان
    kurdish_keywords = ["kurd", "rudaw", "nrt", "ava", "kurdistan", "k24", "gkurd", "zagros"]
    if any(kw in extinf_lower for kw in kurdish_keywords):
        return "Kurdish Channels"
        
    # پۆلێنی وەرزشی
    sports_keywords = ["bein", "ssc", "sport", "channellive", "bt sport", "espn"]
    if any(kw in extinf_lower for kw in sports_keywords):
        return "Sports"
        
    return None

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

def add_channel_logo(extinf_line):
    """دابینکردن و زیادکردنی لۆگۆی فەرمی بۆ کەناڵە دیارەکان"""
    extinf_lower = extinf_line.lower()
    
    logos = {
        "rudaw": "https://upload.wikimedia.org/wikipedia/commons/2/29/Rudaw_Media_Network_logo.png",
        "k24": "https://upload.wikimedia.org/wikipedia/commons/5/50/Kurdistan24_logo.png",
        "nrt": "https://upload.wikimedia.org/wikipedia/commons/7/74/NRT_Logo.png",
        "trt kurdi": "https://upload.wikimedia.org/wikipedia/commons/9/91/TRT_Kurd%C3%AE_logo_2021.png"
    }
    
    for key, logo_url in logos.items():
        if key in extinf_lower:
            if "tvg-logo=" in extinf_line:
                extinf_line = re.sub(r'tvg-logo="[^"]*"', f'tvg-logo="{logo_url}"', extinf_line)
            else:
                extinf_line = extinf_line.replace("#EXTINF:", f'#EXTINF:-1 tvg-logo="{logo_url}"')
            break
    return extinf_line

def clean_playlist(input_file="playlist.m3u"):
    """پاککردنەوە، پۆلێنکردن، ڕێکخستنی ناوەکان و زیادکردنی لۆگۆ"""
    blocklist = load_blocklist()
    print(f"ژمارەی وشە قەدەغەکراوەکان: {len(blocklist)}")

    if not os.path.exists(input_file):
        print(f"فایلی پڵەیلیست نەدۆزراوەتەوە: {input_file}")
        return

    with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    new_lines = []
    skipped_blocked = 0
    skipped_duplicates = 0
    seen_urls = set()
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        if line.startswith("#EXTM3U"):
            new_lines.append(line)
            i += 1
            continue
        
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
                    
                # 3. پۆلێنکردنی خۆکار (Group Title)
                category = categorize_channel(extinf_line)
                if category:
                    if "group-title=" in extinf_line:
                        extinf_line = re.sub(r'group-title="[^"]*"', f'group-title="{category}"', extinf_line)
                    else:
                        extinf_line = extinf_line.replace("#EXTINF:", f'#EXTINF:-1 group-title="{category}"')

                # 4. پاککردنەوەی ناوی کەناڵەکان
                extinf_line = clean_name_and_meta(extinf_line)

                # 5. زیادکردنی لۆگۆی فەرمی
                extinf_line = add_channel_logo(extinf_line)

                seen_urls.add(clean_url)
                new_lines.append(extinf_line)
                new_lines.append(url_line)
                i += 2
            else:
                i += 1
        else:
            new_lines.append(line)
            i += 1

    with open(input_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"سەرکەوتبوو: {skipped_blocked} بلوککراو، {skipped_duplicates} دووبارە سڕرانەوە، ناوەکان پاککرانەوە و لۆگۆکان دابین کران.")

if __name__ == "__main__":
    clean_playlist()
