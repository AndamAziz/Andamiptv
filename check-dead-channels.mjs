import pkg from 'iptv-checker';
const IPTVChecker = pkg.default || pkg;
import fs from 'fs';

async function cleanPlaylist() {
  console.log("Checking channels in playlist.m3u...");
  
  try {
    const config = {
      timeout: 5000,
      parallel: 5
    };
    
    const checker = new IPTVChecker(config);
    const results = await checker.checkFile('playlist.m3u');
    
    // فلتەرکردنی تەنها ئەو چەناڵانەی کە کار دەکەن (Status OK)
    const aliveChannels = results.items.filter(item => item.status && item.status.ok);
    
    let newM3uContent = '#EXTM3U\n';
    aliveChannels.forEach(item => {
      newM3uContent += `#EXTINF:-1 tvg-id="${item.tvg.id || ''}" tvg-name="${item.tvg.name || ''}" tvg-logo="${item.tvg.logo || ''}" group-title="${item.group.title || ''}",${item.name}\n${item.url}\n`;
    });
    
    fs.writeFileSync('playlist.m3u', newM3uContent);
    console.log(`Done! Kept ${aliveChannels.length} active channels out of ${results.items.length}.`);
  } catch (error) {
    console.error("Error checking playlist:", error);
    process.exit(1);
  }
}

cleanPlaylist();
