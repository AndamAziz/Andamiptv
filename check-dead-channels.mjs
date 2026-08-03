import fs from 'fs';

const PLAYLIST_FILE = 'playlist.m3u';
const TIMEOUT = 5000;
const CONCURRENCY = 50;

async function checkUrl(url) {
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
    for (let i = 0; i < entries.length; i += CONCURRENCY) {
        const batch = entries.slice(i, i + CONCURRENCY);
        const results = await Promise.all(
            batch.map(async (entry) => {
                const isValid = await checkUrl(entry.url);
                return isValid ? entry : null;
            })
        );
        validEntries.push(...results.filter(Boolean));
        console.log(`Checked ${Math.min(i + CONCURRENCY, entries.length)} / ${entries.length}`);
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
