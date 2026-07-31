import checkM3u from 'iptv-checker';
import fs from 'fs';

async function cleanPlaylist() {
  console.log("Checking channels in playlist.m3u...");
  
  try {
    const config = {
      timeout: 5000,
      parallel: 5
    };

    // ڕاستەوخۆ بانگهێشتکردنی فەنکشنەکە
    const results = await checkM3u('playlist.m3u', config);

    // فلتەرکردنی تەنها ئەو چەناڵانەی کار دەکەن (Status OK)
    const aliveChannels = results.items.filter(item => item.status && item.status.ok);

    let newM3uContent = '#EXTM3U\n';
    aliveChannels.forEach(item => {
      const tvgId = item.tvg && item.tvg.id ? item.tvg.id : '';
      const tvgName = item.tvg && item.tvg.name ? item.tvg.name : '';
      const tvgLogo = item.tvg && item.tvg.logo ? item.tvg.logo : '';
      const groupTitle = item.group && item.group.title ? item.group.title : '';

      newM3uContent += `#EXTINF:-1 tvg-id="${tvgId}" tvg-name="${tvgName}" tvg-logo="${tvgLogo}" group-title="${groupTitle}",${item.name}\n${item.url}\n`;
    });

    fs.writeFileSync('playlist.m3u', newM3uContent);
    console.log(`Done! Kept ${aliveChannels.length} active channels out of ${results.items.length}.`);
  } catch (error) {
    console.error("Error checking playlist:", error);
    process.exit(1);
  }
}

cleanPlaylist();
