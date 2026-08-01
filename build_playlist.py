import os

def load_blocklist(filepath="blocklist.txt"):
    """خوێندنەوەی وشە قەدەغەکراوەکان لە فایلی blocklist.txt"""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]

def clean_playlist(input_file="playlist.m3u"):
    """پاککردنەوەی کەناڵە قەدەغەکراوەکان و سڕینەوەی کەناڵە دووبارەکان"""
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
