import fs from 'fs';

const PLAYLIST_FILE = 'playlist.m3u';
const STATE_FILE = 'channel-health.json';
const REPORT_FILE = 'dead-channels.txt';
const TIMEOUT = 15000;       // 15s per attempt
const CONCURRENCY = 10;      // avoids provider rate-limiting
const RETRIES = 3;           // attempts within THIS run before calling it a fail today
const RETRY_DELAY = 3000;    // wait 3s between attempts

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
    const deadNow = [];
    const now = new Date().toISOString();

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
                delete state[entry.url];
            } else {
                deadNow.push(entry);
            }
        }

        console.log(`Checked ${Math.min(i + CONCURRENCY, entries.length)} / ${entries.length}`);
    }

    // playlist.m3u is NEVER modified here. Dead links are only reported
    // (dead-channels.txt) so they can be reviewed and removed by hand.
    // one line (and one fail count) per URL, even if several entries share it
    const uniqueDead = [...new Map(deadNow.map(e => [e.url, e])).values()];
    for (const { url } of uniqueDead) {
        const prev = state[url] || { fails: 0, firstFailedAt: now };
        state[url] = {
            fails: prev.fails + 1,
            firstFailedAt: prev.firstFailedAt || prev.lastFailedAt || now,
            lastFailedAt: now
        };
    }
    saveState(state);

    let report = `Dead link report - ${now}\n`;
    report += `Checked: ${entries.length} | Not responding today (unique links): ${uniqueDead.length}\n`;
    report += `NOTHING was removed from playlist.m3u. Test each link yourself before deleting.\n\n`;
    uniqueDead
        .sort((a, b) => state[b.url].fails - state[a.url].fails)
        .forEach(entry => {
            const name = entry.inf.split(',').slice(1).join(',').trim();
            const st = state[entry.url];
            report += `[${st.fails} day(s) in a row, since ${st.firstFailedAt.slice(0, 10)}] ${name}\n${entry.url}\n\n`;
        });
    fs.writeFileSync(REPORT_FILE, report, 'utf8');

    console.log(`Done. Not responding: ${uniqueDead.length} / ${entries.length}. Playlist left untouched. See ${REPORT_FILE}`);
}

processPlaylist();
