import fs from 'fs';

const PLAYLIST_FILE = 'playlist.m3u';
const STATE_FILE = 'channel-health.json';
const TIMEOUT = 15000;       // 15s per attempt
const CONCURRENCY = 10;      // avoids provider rate-limiting
const RETRIES = 3;           // attempts within THIS run before calling it a fail today
const RETRY_DELAY = 3000;    // wait 3s between attempts
const FAIL_THRESHOLD = 3;    // must fail this many CONSECUTIVE DAILY runs before permanent removal

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function loadState() {
    if (!fs.existsSync(STATE_FILE)) return {};
    try {
        return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    } catch (e) {
        console.log('Warning: could not parse channel-health.json, starting fresh.');
        return {};
    }
}

function saveState(state) {
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2), 'utf8');
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

    const state = loadState();
    let validEntries = [];
    let removedCount = 0;
    let atRiskCount = 0;

    for (let i = 0; i < entries.length; i += CONCURRENCY) {
        const batch = entries.slice(i, i + CONCURRENCY);
        const results = await Promise.all(
            batch.map(async (entry) => {
                const isValid = await checkUrl(entry.url);
                return { entry, isValid };
            })
        );

        for (const { entry, isValid } of results) {
            if (isValid) {
                if (state[entry.url]) delete state[entry.url];
                validEntries.push(entry);
                continue;
            }

            const fails = (state[entry.url]?.fails || 0) + 1;

            if (fails >= FAIL_THRESHOLD) {
                delete state[entry.url];
                removedCount++;
                console.log(`REMOVED (failed ${fails} consecutive days): ${entry.url}`);
            } else {
                state[entry.url] = { fails, lastFailedAt: new Date().toISOString() };
                validEntries.push(entry);
                atRiskCount++;
                console.log(`AT RISK (${fails}/${FAIL_THRESHOLD} consecutive fails, kept): ${entry.url}`);
            }
        }

        console.log(`Checked ${Math.min(i + CONCURRENCY, entries.length)} / ${entries.length}`);
    }

    let newM3U = '#EXTM3U\n';
    validEntries.forEach(entry => {
        newM3U += `${entry.inf}\n`;
        entry.extras.forEach(e => { newM3U += `${e}\n`; });
        newM3U += `${entry.url}\n`;
    });

    fs.writeFileSync(PLAYLIST_FILE, newM3U, 'utf8');
    saveState(state);

    console.log(`Cleanup complete. Valid channels remaining: ${validEntries.length} / ${entries.length}`);
    console.log(`Removed permanently (${FAIL_THRESHOLD}+ consecutive daily fails): ${removedCount}`);
    console.log(`At risk (failed today, kept pending confirmation): ${atRiskCount}`);
}

processPlaylist();
