import { IPTVChecker } from 'iptv-checker'
import fs from 'fs'

const PLAYLIST_FILE = 'playlist.m3u'

async function runChecker() {
  const checker = new IPTVChecker({
    timeout: 15000,
    parallel: 8,
    retry: 1
  })

  console.log('پشکنینی چەنالەکان دەستپێدەکات...')

  try {
    const results = await checker.checkPlaylist(PLAYLIST_FILE)
    const working = results.items.filter(item => item.status.ok)
    const dead = results.items.filter(item => !item.status.ok)

    let output = (results.header?.raw || '#EXTM3U') + '\n\n'
    for (const item of working) {
      output += item.raw.trim() + '\n\n'
    }

    fs.writeFileSync(PLAYLIST_FILE, output)

    console.log(`✅ ${working.length} چەناڵی کارا هێشتەوە`)
    console.log(`❌ ${dead.length} چەناڵی مردوو سڕایەوە:`)
    dead.forEach(item => console.log(`   - ${item.name}`))
  } catch (err) {
    console.error('هەڵەیەک ڕوویدا لە کاتی پشکنیندا:', err)
    process.exit(1)
  }
}

runChecker()
