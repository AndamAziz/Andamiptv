import os

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
    kurdish_keywords = ["kurd", "rudaw", "nrt", "ava", "kurdistan", "k24", "GKurd", "Zagros"]
    if any(kw in extinf_lower for kw in kurdish_keywords):
        return "Kurdish Channels"
        
    # پۆلێنی وەرزشی
    sports_keywords = ["bein", "ssc", "sport", "channellive", "bt sport", "espn"]
    if any(kw in extinf_lower for kw in sports_keywords):
        return "Sports"
        
    # ئەگەر هیچیان نەبوو، دەتوانێت بچێتە گرووپی گشتی یان ئەوەی خۆی هەیە بێگۆڕان بمێنێت
    return None

def clean_playlist(input_file="playlist.m3u"):
    """پاککردنەوەی کەناڵە قەدەغەکراوەکان و سڕینەوەی کەناڵە دووبارەکان و پۆلێنکردن"""
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
    
    seen_urls = set() # بۆ گرتنی لینکی کەناڵە دووبارەکان
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # گرتنی هێڵی سەرەتایی مێو ئەگەر هەبێت
        if line.startswith("#EXTM3U"):
            new_lines.append(line)
            i += 1
            continue
        
        # پشکنینی هێڵی زانیاری کەناڵ (#EXTINF)
        if line.startswith("#EXTINF:"):
            if i + 1 < len(lines):
                extinf_line = line
                url_line = lines[i+1]
                
                extinf_lower = extinf_line.lower()
                clean_url = url_line.strip()
                
                # 1. پشکنینی بلۆکلیست (Blocklist)
                is_blocked = any(keyword in extinf_lower for keyword in blocklist)
                if is_blocked:
                    skipped_blocked += 1
                    i += 2 # تێپەڕاندنی زانیاری و لینکەکە
                    continue
                    
                # 2. پشکنینی کەناڵی دووبارە (Duplicates بە پێی لینکەکەیان)
                if clean_url in seen_urls:
                    skipped_duplicates += 1
                    i += 2 # تێپەڕاندنی کەناڵی دووبارە
                    continue
                    
                # 3. پۆلێنکردنی خۆکار (Auto-Categorization) و گۆڕینی group-title
                category = categorize_channel(extinf_line)
                if category:
                    if "group-title=" in extinf_line:
                        # ئەگەر group-title هەبوو، نوێی بکەرەوە بۆ گرووپی نوێ
                        import re
                        extinf_line = re.sub(r'group-title="[^"]*"', f'group-title="{category}"', extinf_line)
                    else:
                        # ئەگەر نەبوو، زیادی بکە بۆ ناو مێتاکە
                        extinf_line = extinf_line.replace("#EXTINF:", f'#EXTINF:-1 group-title="{category}",')

                # ئەگەر پاک بوو و دووبارە نەبوو، زیادی بکە
                seen_urls.add(clean_url)
                new_lines.append(extinf_line)
                new_lines.append(url_line)
                i += 2
            else:
                i += 1
        else:
            new_lines.append(line)
            i += 1

    # نووسینەوەی فایلی پاککراوەوە
    with open(input_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"سەرکەوتبوو: {skipped_blocked} کەناڵی بلوککراو و {skipped_duplicates} کەناڵی دووبارە سڕرانەوە.")

if __name__ == "__main__":
    clean_playlist()
