<?php
header('Content-Type: text/plain; charset=utf-8');

$REPO = '/var/www/andamiptv-fix2/repo';
$PLAYLIST = $REPO . '/playlist.m3u';
$LOCK = '/var/www/andamiptv-fix2/add-channel.lock';

// Fix group ownership/permissions on .git internals in case a root-run
// git command (manual SSH fix, etc.) left files owned root:root without
// group write access, which would otherwise make www-data's git calls
// fail with "Permission denied".
@exec('chgrp -R iptvedit ' . escapeshellarg($REPO) . ' 2>/dev/null');
@exec('chmod -R g+rwX ' . escapeshellarg($REPO) . ' 2>/dev/null');

function run($cmd) {
    $descriptors = [1 => ['pipe','w'], 2 => ['pipe','w']];
    $env = $_ENV;
    $env['GIT_ASKPASS'] = '/etc/andamiptv-fix2/git-askpass.sh';
    $env['GIT_TERMINAL_PROMPT'] = '0';
    $env['HOME'] = '/tmp';
    $proc = proc_open($cmd, $descriptors, $pipes, null, $env);
    $out = stream_get_contents($pipes[1]);
    $err = stream_get_contents($pipes[2]);
    fclose($pipes[1]); fclose($pipes[2]);
    $code = proc_close($proc);
    return [$code, $out, $err];
}

function parseM3U($text) {
    $lines = preg_split('/\r\n|\r|\n/', $text);
    $entries = [];
    $currentExtinf = null;
    foreach ($lines as $line) {
        $trim = trim($line);
        if (strpos($trim, '#EXTINF') === 0) {
            $currentExtinf = $line;
        } elseif ($trim !== '' && $trim[0] !== '#') {
            if ($currentExtinf !== null) {
                $entries[] = ['extinf' => $currentExtinf, 'url' => $trim];
                $currentExtinf = null;
            }
        }
    }
    return $entries;
}

// Remove characters that would break an #EXTINF line (quotes, line breaks).
function cleanField($s) {
    return trim(str_replace(['"', "\r", "\n"], ['', ' ', ' '], $s));
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo "Method not allowed";
    exit;
}

$fp = fopen($LOCK, 'c');
if (!$fp || !flock($fp, LOCK_EX)) {
    http_response_code(503);
    echo "سیستەم قایمە، تکایە چەند چرکەیەک دواتر هەوڵ بدەوە.";
    exit;
}

[$code, $out, $err] = run("git -c safe.directory='*' -C " . escapeshellarg($REPO) . " pull origin main --no-rebase 2>&1");
if ($code !== 0) {
    flock($fp, LOCK_UN);
    fclose($fp);
    http_response_code(500);
    echo "هەڵە لە pull کردن:\n$out\n$err";
    exit;
}

$mode = $_POST['mode'] ?? 'single';
$existingText = file_get_contents($PLAYLIST);
$existingEntries = parseM3U($existingText);
$seenUrls = [];
foreach ($existingEntries as $e) $seenUrls[$e['url']] = true;

$newEntries = [];
$summary = '';

if ($mode === 'playlist') {
    $playlistUrl = trim($_POST['playlist_url'] ?? '');
    if ($playlistUrl === '' || !filter_var($playlistUrl, FILTER_VALIDATE_URL)) {
        flock($fp, LOCK_UN); fclose($fp);
        http_response_code(400);
        echo "لینکی پلەیلیست دروست نییە.";
        exit;
    }
    $context = stream_context_create(['http' => ['timeout' => 20], 'https' => ['timeout' => 20]]);
    $content = @file_get_contents($playlistUrl, false, $context);
    if ($content === false) {
        flock($fp, LOCK_UN); fclose($fp);
        http_response_code(400);
        echo "نەتوانرا لینکەکە بخوێنرێتەوە.";
        exit;
    }
    $fetched = parseM3U($content);
    foreach ($fetched as $e) {
        if (!isset($seenUrls[$e['url']])) {
            $newEntries[] = $e;
            $seenUrls[$e['url']] = true;
        }
    }
    $summary = count($fetched) . " کەناڵ دۆزرایەوە لە پلەیلیستەکە، " . count($newEntries) . " دانەیان نوێن و زیادکران.";
} else {
    $type = $_POST['type'] ?? 'live';              // live | movie | series
    if (!in_array($type, ['live', 'movie', 'series'], true)) $type = 'live';
    $name = cleanField($_POST['name'] ?? '');
    $group = cleanField($_POST['group'] ?? '');
    $logo = cleanField($_POST['logo'] ?? '');
    $url = trim($_POST['url'] ?? '');

    // Movies and series use the standard name:  English name _ Kurdish name {tmdb-ID}
    // The TMDB id makes the app load the exact movie/series info, poster and backdrop from TMDB.
    $tmdbId = '';
    if ($type !== 'live') {
        $tmdbId = preg_replace('/\D/', '', $_POST['tmdb'] ?? '');
        $nameKu = cleanField($_POST['name_ku'] ?? '');
        $name = trim(preg_replace('/\s*\{tmdb-\d+\}/', '', $name));
        if ($name === '' || $tmdbId === '' || (int)$tmdbId < 1) {
            flock($fp, LOCK_UN); fclose($fp);
            http_response_code(400);
            echo "بۆ فیلم و سریاڵ ناوی ئینگلیزی و ژمارەی TMDB پێویستن.";
            exit;
        }
        $name = $name . ($nameKu !== '' ? ' _ ' . $nameKu : '') . ' {tmdb-' . $tmdbId . '}';
    }

    if ($name === '' || $url === '' || !filter_var($url, FILTER_VALIDATE_URL)) {
        flock($fp, LOCK_UN); fclose($fp);
        http_response_code(400);
        echo "ناو و لینکی کەناڵ پێویستن، لینکەکەش دەبێت دروست بێت.";
        exit;
    }
    if (isset($seenUrls[$url])) {
        flock($fp, LOCK_UN); fclose($fp);
        echo "ئەم لینکە پێشتر لە playlist-ەکەدا هەیە، هیچ شتێک زیاد نەکرا.";
        exit;
    }

    if ($type !== 'live') {
        // The same TMDB id must always use the same name: a movie can exist only once, and every
        // episode of a series must share the exact same series name (the app groups episodes by it).
        foreach ($existingEntries as $e) {
            if (strpos($e['extinf'], 'tvg-type="' . $type . '"') === false) continue;
            $existingName = trim(substr($e['extinf'], (int)strrpos($e['extinf'], ',') + 1));
            $existingBase = trim(preg_replace('/\s*-\s*S\d+E\d+\s*$/i', '', $existingName));
            if (!preg_match('/\{tmdb-' . $tmdbId . '\}/', $existingBase)) continue;
            if ($type === 'movie') {
                flock($fp, LOCK_UN); fclose($fp);
                echo "ئەم فیلمە (TMDB $tmdbId) پێشتر لە playlist-ەکەدا هەیە: \"$existingBase\". هیچ شتێک زیاد نەکرا.";
                exit;
            }
            if (strcasecmp($existingBase, $name) !== 0) {
                flock($fp, LOCK_UN); fclose($fp);
                http_response_code(400);
                echo "ئەم سریاڵە (TMDB $tmdbId) پێشتر بەم ناوە هەیە:\n$existingBase\nهەمان ناو بەکاربهێنە (لە لیستی «سریاڵی هەبوو» هەڵیبژێرە).";
                exit;
            }
            break;
        }
    }

    $tvgType = '';
    if ($type === 'movie') {
        if ($group === '') $group = 'Movies';   // movies may have their own group (KURDI, FARSI, ENGLISH ...)
        $tvgType = 'tvg-type="movie"';
    } elseif ($type === 'series') {
        $season = max(1, (int)($_POST['season'] ?? 1));
        $episode = max(1, (int)($_POST['episode'] ?? 1));
        $name = sprintf('%s - S%02dE%02d', $name, $season, $episode);
        if ($group === '') $group = 'Kurdish Drama';
        $tvgType = 'tvg-type="series"';
    } elseif ($group === 'Movies') {
        // "Movies" is now only for VOD movies; live movie channels are "Movies TV".
        $group = 'Movies TV';
    }

    if ($type !== 'live') {
        // Same movie name / same episode already in the playlist?
        foreach ($existingEntries as $e) {
            $existingName = trim(substr($e['extinf'], (int)strrpos($e['extinf'], ',') + 1));
            if (strcasecmp($existingName, $name) === 0) {
                flock($fp, LOCK_UN); fclose($fp);
                echo "\"$name\" پێشتر لە playlist-ەکەدا هەیە، هیچ شتێک زیاد نەکرا.";
                exit;
            }
        }
    }

    // Same attribute layout as the rest of playlist.m3u (no spaces between attributes).
    $extinf = '#EXTINF:-1 tvg-name="' . $name . '"tvg-id=""tvg-logo="' . $logo . '"tvg-chno=""'
            . $tvgType . 'group-title="' . $group . '":http-referrer="",' . $name;
    $newEntries[] = ['extinf' => $extinf, 'url' => $url];
    $labels = ['live' => 'کەناڵ', 'movie' => 'فیلم', 'series' => 'ئەڵقەی سریاڵ'];
    $summary = $labels[$type] . " \"$name\" زیادکرا.";
}

if (empty($newEntries)) {
    flock($fp, LOCK_UN);
    fclose($fp);
    echo $summary !== '' ? $summary : "هیچ شتێکی نوێ نەدۆزرایەوە.";
    exit;
}

$output = rtrim($existingText) . "\n";
foreach ($newEntries as $e) {
    $output .= $e['extinf'] . "\n" . $e['url'] . "\n";
}
file_put_contents($PLAYLIST, $output);

run("git -c safe.directory='*' -C " . escapeshellarg($REPO) . " add playlist.m3u 2>&1");
$commitMsg = "Add channel(s) via web form: " . count($newEntries) . " new entr" . (count($newEntries) === 1 ? "y" : "ies");
[$ccode, $cout, $cerr] = run("git -c safe.directory='*' -c user.email='bot@andam.uk' -c user.name='Andam Bot' -C " . escapeshellarg($REPO) . " commit -m " . escapeshellarg($commitMsg) . " 2>&1");
if ($ccode !== 0) {
    flock($fp, LOCK_UN);
    fclose($fp);
    http_response_code(500);
    echo "$summary\n\n⚠️ فایلەکە نوێکرا بەڵام commit سەرکەوتوو نەبوو:\n$cout\n$cerr";
    exit;
}

[$code, $out, $err] = run("git -c safe.directory='*' -C " . escapeshellarg($REPO) . " push 2>&1");
if ($code !== 0) {
    run("git -c safe.directory='*' -C " . escapeshellarg($REPO) . " pull origin main --no-rebase 2>&1");
    [$code2, $out2, $err2] = run("git -c safe.directory='*' -C " . escapeshellarg($REPO) . " push 2>&1");
    if ($code2 !== 0) {
        flock($fp, LOCK_UN);
        fclose($fp);
        http_response_code(500);
        echo "$summary\n\n⚠️ کۆمیت کرا بەڵام push سەرکەوتوو نەبوو:\n$out2\n$err2\n\nتکایە دواتر جارێکی تر هەوڵ بدەوە.";
        exit;
    }
}

flock($fp, LOCK_UN);
fclose($fp);
echo "$summary\n\n✅ بە سەرکەوتوویی push کرا بۆ GitHub.";
