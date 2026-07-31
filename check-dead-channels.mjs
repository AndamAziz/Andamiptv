const fs = require('fs');
const { execSync } = require('child_process');

async function checkUrl(url) {
  try {
    // بەکارهێنانی ffmpeg بۆ پشکنینی ڕاستەوخۆی ستریمەکە لە زۆربەی فرێمەکاندا
    execSync(`ffmpeg -v error -i "${url}" -t 2 -f null -`, { timeout: 8000, stdio: 'ignore' });
    return true;
  } catch (e) {
    return false;
  }
}

async function cleanPlaylist() {
  console.log("Starting IPTV playlist check...");
  
  if (!fs.existsSync('playlist.m3u')) {
    console.error("playlist.m3u file not found!");
    process.exit(1);
  }

  const content = fs.readFileSync('playlist.m3u', 'utf-8');
  const lines = content.split('\n');
  
  let aliveContent = '#EXTM3U\n';
  let currentExtinf = '';
  let checkedCount = 0;
  let aliveCount = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    
    if (line.startsWith('#EXTINF:')) {
      currentExtinf = line;
    } else if (line.startsWith('http://') || line.startsWith('https://')) {
      checkedCount++;
      console.log(`Checking [${checkedCount}]: ${line}`);
      
      const isAlive = await checkUrl(line);
      if (isAlive) {
        console.log(` -> ACTIVE ✅`);
        aliveContent += `${currentExtinf}\n${line}\n`;
        aliveCount++;
      } else {
        console.log(` -> DEAD ❌`);
      }
      currentExtinf = '';
    }
  }

  fs.writeFileSync('playlist.m3u', aliveContent);
  console.log(`\nFinished! Active channels: ${aliveCount} / Total: ${checkedCount}`);
}

cleanPlaylist();
