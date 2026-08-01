import { IPTVChecker } from 'iptv-checker'
import fs from 'fs'

const PLAYLIST_FILE = 'playlist.m3u'

const checker = new IPTVChecker({
  timeout: 15000,
  parallel: 8,
  retry: 1
})

console.log('پشکنینی چەنالەکان دەستپێدەکات...')

const results = await checker.checkPlaylist(PLAYLIST_FILE)
const working = results.items.filter(item => item.status.ok)
const dead = results.items.filter(item => !item.status.ok)

let output = (results.header.raw || '#EXTM3U') + '\n'
for (const item of working) {
  output += item.raw.trim() + '\n'
}

fs.writeFileSync(PLAYLIST_FILE, output)

console.log(`✅ ${working.length} چەناڵی کارا هێشتەوە`)
console.log(`❌ ${dead.length} چەناڵی مردوو سڕایەوە:`)
dead.forEach(item => console.log(`   - ${item.name}`))
