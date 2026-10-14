<?php
$repo = '/var/www/andamiptv-fix2/repo';

// Live-channel groups: keys of categories.json
$liveGroups = [];
$categoriesFile = $repo . '/categories.json';
if (file_exists($categoriesFile)) {
    $data = json_decode(file_get_contents($categoriesFile), true);
    if (is_array($data)) $liveGroups = array_keys($data);
}

// Series groups and series names already in playlist.m3u (so new episodes reuse the exact same names)
$seriesGroups = ['Kurdish Drama'];
$movieGroups = ['Movies'];
$seriesList = [];
$playlistFile = $repo . '/playlist.m3u';
if (file_exists($playlistFile)) {
    foreach (file($playlistFile, FILE_IGNORE_NEW_LINES) as $line) {
        if (strpos($line, '#EXTINF') !== 0) continue;
        $isSeries = strpos($line, 'tvg-type="series"') !== false;
        $isMovie = strpos($line, 'tvg-type="movie"') !== false;
        if (!$isSeries && !$isMovie) continue;
        if (preg_match('/group-title="([^"]*)"/', $line, $m) && $m[1] !== '') {
            if ($isMovie) $movieGroups[] = $m[1]; else $seriesGroups[] = $m[1];
        }
        if ($isSeries) {
            $display = trim(substr($line, (int)strrpos($line, ',') + 1));
            if (preg_match('/^(.*?)\s*-\s*S\d+E\d+/i', $display, $m)) {
                $base = trim($m[1]);
                $tmdb = preg_match('/\{tmdb-(\d+)\}/', $base, $t) ? $t[1] : '';
                $plain = trim(preg_replace('/\s*\{tmdb-\d+\}/', '', $base));
                $parts = explode(' _ ', $plain, 2);
                $seriesList[$base] = ['full' => $base, 'en' => trim($parts[0]), 'ku' => trim($parts[1] ?? ''), 'tmdb' => $tmdb];
            }
        }
    }
}
$seriesGroups = array_values(array_unique($seriesGroups));
$movieGroups = array_values(array_unique($movieGroups));
$seriesList = array_values($seriesList);
?>
<!DOCTYPE html>
<html lang="ckb" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>زیادکردنی کەناڵ</title>
<style>
body { font-family: sans-serif; max-width: 480px; margin: 20px auto; padding: 0 15px; }
label { display: block; margin-top: 14px; font-weight: bold; }
input, select { width: 100%; padding: 10px; margin-top: 4px; box-sizing: border-box; font-size: 16px; }
button { width: 100%; padding: 14px; margin-top: 20px; background: #2563eb; color: white; border: none; border-radius: 6px; font-size: 16px; }
#result { margin-top: 16px; padding: 12px; border-radius: 6px; white-space: pre-wrap; display: none; }
.ok { background: #dcfce7; color: #166534; }
.err { background: #fee2e2; color: #991b1b; }
.row { display: flex; gap: 10px; }
.row > div { flex: 1; }
.hint { font-size: 13px; color: #555; margin-top: 4px; font-weight: normal; }
</style>
</head>
<body>
<h2>زیادکردنی کەناڵ / فیلم / سریاڵ</h2>
<form id="chForm">
  <label>جۆر</label>
  <select name="mode" id="mode">
    <option value="single">یەک کەناڵ / فیلم / ئەڵقە</option>
    <option value="playlist">لینکی پلەیلیست (چەندین کەناڵی تێدایە)</option>
  </select>

  <div id="single-fields">
    <label>جۆری ناوەڕۆک</label>
    <select name="type" id="type">
      <option value="live">کەناڵی زیندوو</option>
      <option value="movie">فیلم</option>
      <option value="series">سریاڵ (ئەڵقە)</option>
    </select>

    <div id="existing-series-wrap" style="display:none">
      <label>سریاڵی هەبوو (هەڵیبژێرە بۆ ئەڵقەی نوێ)</label>
      <select id="existingSeries">
        <option value="">— سریاڵی نوێ —</option>
        <?php foreach ($seriesList as $i => $sr): ?>
        <option value="<?= $i ?>"><?= htmlspecialchars($sr['en'] . ($sr['ku'] !== '' ? ' _ ' . $sr['ku'] : '')) ?><?= $sr['tmdb'] !== '' ? ' (TMDB ' . htmlspecialchars($sr['tmdb']) . ')' : '' ?></option>
        <?php endforeach; ?>
      </select>
    </div>

    <label id="name-label">ناوی کەناڵ</label>
    <input type="text" name="name" id="name" autocomplete="off">

    <div id="vod-fields" style="display:none">
      <label>ناوی کوردی</label>
      <input type="text" name="name_ku" id="name_ku" autocomplete="off" placeholder="ناوی کوردی (ئارەزوومەندانە)">
      <label>ژمارەی TMDB</label>
      <input type="text" name="tmdb" id="tmdb" inputmode="numeric" pattern="[0-9]*" placeholder="نموونە: 75404" autocomplete="off">
      <div class="hint">
        ژمارەکە لە ناونیشانی themoviedb.org وەربگرە: /movie/<b>75404</b> یان /tv/<b>94146</b>.
        ئەپەکە بەم ژمارەیە زانیاری و پۆستەر و باکگراوندی ڕاستی فیلم/سریاڵەکە دەهێنێت.<br>
        <a href="#" id="tmdbSearch" target="_blank" rel="noopener">١) گەڕان لە TMDB بەپێی ناوی ئینگلیزی</a> &nbsp;|&nbsp;
        <a href="#" id="tmdbCheck" target="_blank" rel="noopener" style="display:none">٢) پشکنینی ژمارەکە لە TMDB</a>
      </div>
      <div class="hint" id="namePreview" style="direction:ltr;text-align:left;font-weight:bold"></div>
    </div>

    <div id="series-fields" style="display:none">
      <div class="row">
        <div><label>وەرز</label><input type="number" name="season" min="1" value="1"></div>
        <div><label>ئەڵقە</label><input type="number" name="episode" min="1" value="1"></div>
      </div>
      <div class="hint">بۆ ئەڵقەی نوێی سریاڵێکی هەبوو، سریاڵەکە لە لیستی سەرەوە هەڵبژێرە، ئەو کات ناو و ژمارەی TMDB خۆکار پڕ دەبنەوە.</div>
    </div>

    <div id="group-wrap">
      <label>گروپ</label>
      <input type="text" name="group" id="group" list="groupList" autocomplete="off">
      <datalist id="groupList"></datalist>
    </div>
    <div class="hint" id="movie-hint" style="display:none">گروپی فیلم بنووسە (وەک KURDI یان FARSI یان ENGLISH). ئەگەر بەتاڵ بێت دەچێتە Movies.</div>

    <label>لینکی وێنە (لۆگۆ)</label>
    <input type="url" name="logo" placeholder="https://...">
    <label>لینک</label>
    <input type="url" name="url" placeholder="https://.../stream.m3u8">
  </div>

  <div id="playlist-fields" style="display:none">
    <label>لینکی پلەیلیستی m3u</label>
    <input type="url" name="playlist_url" placeholder="https://.../playlist.m3u">
  </div>

  <button type="submit">زیادکردن</button>
</form>
<div id="result"></div>

<script>
const LIVE_GROUPS = <?= json_encode($liveGroups, JSON_UNESCAPED_UNICODE) ?>;
const SERIES_LIST = <?= json_encode($seriesList, JSON_UNESCAPED_UNICODE) ?>;
const SERIES_GROUPS = <?= json_encode($seriesGroups, JSON_UNESCAPED_UNICODE) ?>;
const MOVIE_GROUPS = <?= json_encode($movieGroups, JSON_UNESCAPED_UNICODE) ?>;
const $ = id => document.getElementById(id);
const esc = s => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

function updatePreview() {
  const en = $('name').value.trim(), ku = $('name_ku').value.trim(), id = $('tmdb').value.replace(/\D/g, '');
  const t = $('type').value;
  $('namePreview').textContent = en && id ? en + (ku ? ' _ ' + ku : '') + ' {tmdb-' + id + '}' + (t === 'series' ? ' - S..E..' : '') : '';
  const kind = t === 'series' ? 'tv' : 'movie';
  $('tmdbSearch').href = 'https://www.themoviedb.org/search/' + kind + '?query=' + encodeURIComponent(en);
  const chk = $('tmdbCheck');
  chk.style.display = id ? 'inline' : 'none';
  chk.href = 'https://www.themoviedb.org/' + kind + '/' + id;
}

function updateType() {
  const t = $('type').value;
  const vod = t !== 'live';
  $('series-fields').style.display = t === 'series' ? 'block' : 'none';
  $('existing-series-wrap').style.display = t === 'series' && SERIES_LIST.length ? 'block' : 'none';
  $('vod-fields').style.display = vod ? 'block' : 'none';
  $('tmdb').required = vod;
  $('group-wrap').style.display = 'block';
  $('movie-hint').style.display = t === 'movie' ? 'block' : 'none';
  $('name-label').textContent = t === 'series' ? 'ناوی سریاڵ بە ئینگلیزی (بێ S01E01)' : t === 'movie' ? 'ناوی فیلم بە ئینگلیزی' : 'ناوی کەناڵ';
  $('existingSeries').value = '';
  $('group').value = '';
  $('group').placeholder = t === 'series' ? 'Kurdish Drama' : t === 'movie' ? 'KURDI / FARSI / ENGLISH ... (بەتاڵ = Movies)' : 'Kurdish Channels';
  const groups = t === 'series' ? SERIES_GROUPS : t === 'movie' ? MOVIE_GROUPS : LIVE_GROUPS;
  $('groupList').innerHTML = groups.map(g => '<option value="' + esc(g) + '">').join('');
  updatePreview();
}
$('type').addEventListener('change', updateType);
['name', 'name_ku', 'tmdb'].forEach(id => $(id).addEventListener('input', updatePreview));
$('existingSeries').addEventListener('change', () => {
  const sr = SERIES_LIST[$('existingSeries').value];
  if (!sr) return;
  $('name').value = sr.en; $('name_ku').value = sr.ku; $('tmdb').value = sr.tmdb;
  updatePreview();
});
updateType();

$('mode').addEventListener('change', () => {
  $('single-fields').style.display = $('mode').value === 'single' ? 'block' : 'none';
  $('playlist-fields').style.display = $('mode').value === 'playlist' ? 'block' : 'none';
});

$('chForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector('button');
  const result = $('result');
  btn.disabled = true;
  btn.textContent = 'چاوەڕوان بە...';
  result.style.display = 'none';
  try {
    const res = await fetch('add.php', { method: 'POST', body: new FormData(e.target) });
    const text = await res.text();
    result.textContent = text;
    result.className = res.ok ? 'ok' : 'err';
    result.style.display = 'block';
    if (res.ok) {
      // keep the content type, series name/group and season; bump the episode number for the next one
      const t = $('type').value, name = $('name').value, nameKu = $('name_ku').value, tmdb = $('tmdb').value, group = $('group').value;
      const season = e.target.season.value, ep = parseInt(e.target.episode.value || '0', 10);
      e.target.reset();
      $('type').value = t;
      updateType();
      if (t === 'series') { $('name').value = name; $('name_ku').value = nameKu; $('tmdb').value = tmdb; $('group').value = group; e.target.season.value = season; e.target.episode.value = ep + 1; updatePreview(); }
    }
  } catch (err) {
    result.textContent = 'هەڵەیەک ڕوویدا: ' + err.message;
    result.className = 'err';
    result.style.display = 'block';
  }
  btn.disabled = false;
  btn.textContent = 'زیادکردن';
});
</script>
</body>
</html>
