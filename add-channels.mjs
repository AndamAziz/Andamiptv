import fs from 'fs'

const PLAYLIST_FILE = 'playlist.m3u'
const rawInput = process.argv[2]

if (!rawInput) {
  console.error('پێویستە لینک بدەیت')
  process.exit(1)
}

const sourceUrls = rawInput
  .split(/[\n,]+/)
  .map(u => u.trim())
  .filter(Boolean)

function parseM3U(text) {
  const lines = text.split(/\r?\n/)
  const channels = []
  let currentExtinf = null
  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('#EXTINF')) {
      currentExtinf = line
    } else if (trimmed && !trimmed.startsWith('#')) {
      if (currentExtinf) {
        channels.push({ extinf: currentExtinf, url: trimmed })
        currentExtinf = null
      }
    }
  }
  return channels
}

const existingText = fs.readFileSync(PLAYLIST_FILE, 'utf8')
const existingChannels = parseM3U(existingText)
const seenUrls = new Set(existingChannels.map(ch => ch.url))

let allNew = []

for (const url of sourceUrls) {
  console.log(`\nوەرگرتن لە: ${url}`)
  try {
    const res = await fetch(url)
    const text = await res.text()
    const channels = parseM3U(text)
    const fresh = channels.filter(ch => !seenUrls.has(ch.url))
    fresh.forEach(ch => seenUrls.add(ch.url))
    allNew.push(...fresh)
    console.log(`${channels.length} چەناڵ هەیە، ${fresh.length}ی نوێن`)
  } catch (err) {
    console.log(`❌ هەڵە لە وەرگرتنی ئەم سەرچاوەیە: ${err.message}`)
  }
}

let output = existingText.trimEnd() + '\n'
for (const ch of allNew) {
  output += ch.extinf + '\n' + ch.url + '\n'
}

fs.writeFileSync(PLAYLIST_FILE, output)
console.log(`\n✅ کۆی گشتی ${allNew.length} چەناڵی نوێ زیادکرا`)
