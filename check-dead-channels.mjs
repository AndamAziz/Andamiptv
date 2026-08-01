import fs from 'fs'

const PLAYLIST_FILE = 'playlist.m3u'
const TIMEOUT_MS = 15000
const CONCURRENCY = 10

const content = fs.readFileSync(PLAYLIST_FILE, 'utf8')
const lines = content.split(/\r?\n/)

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

async function checkUrl(url) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: { 'User-Agent': 'VLC/3.0.20 LibVLC/3.0.20' }
    })
    res.body?.cancel?.()
    return res.status < 400
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

console.log(`پشکنینی ${channels.length} چەناڵ دەستپێدەکات...`)

const results = new Array(channels.length)
let index = 0

async function worker() {
  while (index < channels.length) {
    const i = index++
    results[i] = await checkUrl(channels[i].url)
    console.log(`${results[i] ? '✅' : '❌'} ${channels[i].extinf.split(',').pop()}`)
  }
}

await Promise.all(Array.from({ length: CONCURRENCY }, worker))

let output = '#EXTM3U\n'
let deadCount = 0
for (let i = 0; i < channels.length; i++) {
  if (results[i]) {
    output += channels[i].extinf + '\n' + channels[i].url + '\n'
  } else {
    deadCount++
  }
}

fs.writeFileSync(PLAYLIST_FILE, output)
console.log(`\n✅ ${channels.length - deadCount} چەناڵی کارا هێشتەوە`)
console.log(`❌ ${deadCount} چەناڵی مردوو سڕدرانەوە`)
