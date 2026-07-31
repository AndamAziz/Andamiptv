import pkg from 'iptv-checker';
import fs from 'fs';

async function cleanPlaylist() {
  console.log("Checking channels in playlist.m3u...");
  
  try {
    // دەستنیشانکردنی شێوازی فەنکشنی iptv-checker بە شێوەی ئۆتۆماتیک
    const checkFn = typeof pkg === 'function' 
      ? pkg 
      : (pkg.default || pkg.check || pkg.checkM3u || pkg.checkFile);

    if (typeof checkFn !== 'function') {
      console.log("Package structure:", pkg);
      throw new Error("Could not resolve checker function from iptv-checker module.");
    }

    const config = {
      timeout: 5000,
      parallel: 5
    };

    const results = await checkFn('playlist.m3u', config);

    // فلتەرکردنی تەنها ئەو چەناڵانەی کار دەکەن (Status OK)
    const aliveChannels = (results.items || results || []).filter(item => item.status && item.status.ok);

    let newM3uContent = '#EXTM3U\n';
    aliveChannels.forEach(item => {
      const tvgId = item.tvg && item.tvg.id ? item.tvg.id : '';
      const tvgName = item.tvg && item.tvg.name ? item.tvg.name : '';
      const tvgLogo = item.tvg && item.tvg.logo ? item.tvg.logo : '';
      const groupTitle = item.group && item.group.title ? item.group.title : '';

      newM3uContent += `#EXTINF:-1 tvg-id="${tvgId}" tvg-name="${tvgName}" tvg-logo="${tvgLogo}" group-title="${groupTitle}",${item.name || item.title || ''}\n${item.url}\n`;
    });

    fs.writeFileSync('playlist.m3u', newM3uContent);
    console.log(`Done! Kept ${aliveChannels.length} active channels.`);
  } catch (error) {
    console.error("Error checking playlist:", error);
    process.exit(1);
  }
}

cleanPlaylist();
