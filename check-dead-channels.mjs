import fs from 'fs';

const PLAYLIST_FILE = 'playlist.m3u';
const TIMEOUT = 15000;       // 15s instead of 5s
const CONCURRENCY = 10;      // 10 instead of 50 - avoids provider rate-limiting
const RETRIES = 3;           // try each URL up to 3 times before declaring it dead
const RETRY_DELAY = 3000;    // wait 3s between retries

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function checkUrlOnce(url) {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), TIMEOUT);
        const response = await fetch(url, {
            method: 'GET',
            headers: { 'User-Agent': 'VLC/3.0.16' },
            signal: controller.signal
        });
        clearTimeout(timeoutId);
        return response.ok;
    } catch (e) {
        return false;
    }
}

async function checkUrl(url) {
    for (let attempt = 1; attempt <= RETRIES; attempt++) {
        const ok = await checkUrlOnce(url);
        if (ok) return true;
        if (attempt < RETRIES) await sleep(RETRY_DELAY);
    }
    return false;
}

async function processPlaylist() {
    if (!fs.existsSync(PLAYLIST_FILE)) {
        console.log('Playlist file not found!');
        process.exitCode = 1;
        return;
    }

    const content = fs.readFileSync(PLAYLIST_FILE, 'utf8');
    const lines = content.split('\n');
    let entries = [];
    let currentInf = '';
    let extras = [];

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (line.startsWith('#EXTINF:')) {
            currentInf = line;
            extras = [];
        } else if (line.startsWith('#') && currentInf) {
            extras.push(line);
        } else if (line && !line.startsWith('#') && currentInf) {
            entries.push({ inf: currentInf, extras, url: line });
            currentInf = '';
            extras = [];
        }
    }

    console.log(`Total channels to check: ${entries.length}`);
    let validEntries = [];
    let deadCount = 0;

    for (let i = 0; i < entries.length; i += CONCURRENCY) {
        const batch = entries.slice(i, i + CONCURRENCY);
        const results = await Promise.all(
            batch.map(async (entry) => {
                const isValid = await checkUrl(entry.url);
                return isValid ? entry : null;
            })
        );
        validEntries.push(...results.filter(Boolean));
        deadCount += results.filter(r => r === null).length;
        console.log(`Checked ${Math.min(i + CONCURRENCY, entries.length)} / ${entries.length}  (dead so far: ${deadCount})`);
    }

    let newM3U = '#EXTM3U\n';
    validEntries.forEach(entry => {
        newM3U += `${entry.inf}\n`;
        entry.extras.forEach(e => { newM3U += `${e}\n`; });
        newM3U += `${entry.url}\n`;
    });

    fs.writeFileSync(PLAYLIST_FILE, newM3U, 'utf8');
    console.log(`Cleanup complete. Valid channels remaining: ${validEntries.length} / ${entries.length}`);
}

processPlaylist();
