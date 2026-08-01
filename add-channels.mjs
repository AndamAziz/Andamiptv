import fs from 'fs'

const PLAYLIST_FILE = 'playlist.m3u'
const sourceUrl = process.argv[2]

if (!sourceUrl) {
  console.error('پێویستە لینکی سەرچاوە بدەیت')
  process.exit(1)
}

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

console.log(`وەرگرتنی playlist لە: ${sourceUrl}`)
const res = await fetch(sourceUrl)
const sourceText = await res.text()
const newChannels = parseM3U(sourceText)

const existingText = fs.readFileSync(PLAYLIST_FILE, 'utf8')
const existingChannels = parseM3U(existingText)
const existingUrls = new Set(existingChannels.map(ch => ch.url))

const toAdd = newChannels.filter(ch => !existingUrls.has(ch.url))

console.log(`${newChannels.length} چەناڵ لە سەرچاوەکەدا هەیە`)
console.log(`${toAdd.length} چەناڵی نوێ زیاد دەکرێت (${newChannels.length - toAdd.length} پێشتر هەبوون)`)

let output = existingText.trimEnd() + '\n'
for (const ch of toAdd) {
  output += ch.extinf + '\n' + ch.url + '\n'
}

fs.writeFileSync(PLAYLIST_FILE, output)
console.log('تەواو بوو ✅')
