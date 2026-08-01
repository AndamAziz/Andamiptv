import os

def load_blocklist(filepath="blocklist.txt"):
    """خوێندنەوەی پەیوە و وشە قەدەغەکراوەکان لە فایلی blocklist.txt"""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]

def clean_playlist(input_file="playlist.m3u"):
    """پشکنین و سڕینەوەی ئەو کەناڵانەی ناوەکەیان لە blocklist دا هەیە"""
    blocklist = load_blocklist()
    print(f"ژمارەی وشە قەدەغەکراوەکان: {len(blocklist)}")

    if not os.path.exists(input_file):
        print(f"فایلی پڵەیلیست نەدۆزراوەتەوە: {input_file}")
        return

    with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    new_lines = []
    skipped_count = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        
        # پشکنینی هێڵی زانیاری کەناڵ (#EXTINF)
        if line.startswith("#EXTINF:"):
            line_lower = line.lower()
            is_blocked = any(keyword in line_lower for keyword in blocklist)
            
            if is_blocked:
                skipped_count += 1
                # سڕینەوەی ئەم هێڵە و هێڵی دووەمی کە لینکی کەناڵەکەیە
                i += 2
                continue
                
        new_lines.append(line)
        i += 1

    # نووسینەوەی فایلی پاککراوەوە
    with open(input_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"پرۆسەکە سەرکەوتبوو. کۆی گشتی {skipped_count} کەناڵی قەدەغکراو سڕرانەوە.")

if __name__ == "__main__":
    clean_playlist()
