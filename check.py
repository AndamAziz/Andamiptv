import subprocess
import os

def check_url(url):
    try:
        # بەکارهێنانی ffmpeg بۆ پشکنینی ڕاستەوخۆی ستریمەکە
        cmd = [
            'ffmpeg',
            '-v', 'error',
            '-i', url,
            '-t', '2',
            '-f', 'null',
            '-'
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        return result.returncode == 0
    except Exception:
        return False

def clean_playlist():
    playlist_path = 'playlist.m3u'
    if not os.path.exists(playlist_path):
        print("playlist.m3u not found!")
        return

    with open(playlist_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    alive_content = ["#EXTM3U\n"]
    current_extinf = ""
    checked_count = 0
    alive_count = 0

    for line in lines:
        line_str = line.strip()
        if line_str.startswith("#EXTINF:"):
            current_extinf = line_str
        elif line_str.startswith("http://") or line_str.startswith("https://"):
            checked_count += 1
            print(f"Checking [{checked_count}]: {line_str}")
            if check_url(line_str):
                print(" -> ACTIVE ✅")
                alive_content.append(f"{current_extinf}\n{line_str}\n")
                alive_count += 1
            else:
                print(" -> DEAD ❌")
            current_extinf = ""

    with open(playlist_path, 'w', encoding='utf-8') as f:
        f.writelines(alive_content)

    print(f"\nDone! Active channels: {alive_count} / {checked_count}")

if __name__ == "__main__":
    clean_playlist()
