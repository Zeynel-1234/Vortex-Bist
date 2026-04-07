import express, { Request, Response } from 'express';
import cors from 'cors';
import path from 'path';
import { analyzRace } from './scorer';
import { scrapeTodayProgram } from './scraper';
import { Race, TrinityResult } from './types';

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.static(path.join(__dirname, '../public')));

// Cache
let cachedRaces: Race[] = [];
let cacheTime = 0;
const CACHE_TTL = 10 * 60 * 1000; // 10 dakika

// ============================================================
// ROUTES
// ============================================================

// Health check
app.get('/health', (_req: Request, res: Response) => {
  res.json({ status: 'ok', time: new Date().toISOString() });
});

// ---- ROUTE 1: Bookmarklet'ten gelen veri ----
// Via Browser'daki bookmarklet veriyi buraya POST eder
app.post('/api/bookmarklet', async (req: Request, res: Response) => {
  try {
    const { races, track, date } = req.body;

    if (!races || !Array.isArray(races)) {
      return res.status(400).json({ error: 'races array gerekli' });
    }

    console.log(`[API] Bookmarklet'ten ${races.length} koşu alındı`);

    const results: TrinityResult[] = [];

    for (const raceData of races) {
      if (!raceData.horses || raceData.horses.length === 0) continue;

      const race: Race = {
        id: `bkm_${raceData.no}_${Date.now()}`,
        no: raceData.no || results.length + 1,
        track: track || raceData.track || 'Bilinmiyor',
        date: date || new Date().toISOString().split('T')[0],
        time: raceData.time,
        distance: raceData.distance,
        surface: raceData.surface,
        horses: raceData.horses,
        source: 'bookmarklet',
      };

      const result = analyzRace(race);
      results.push(result);

      // Cache'e ekle
      cachedRaces.push(race);
    }

    cacheTime = Date.now();

    res.json({
      success: true,
      analyzed: results.length,
      results,
    });
  } catch (error: any) {
    console.error('[API] Bookmarklet hatası:', error);
    res.status(500).json({ error: error.message });
  }
});

// ---- ROUTE 2: Tek koşu analizi ----
app.post('/api/analyze', async (req: Request, res: Response) => {
  try {
    const { race } = req.body;

    if (!race || !race.horses) {
      return res.status(400).json({ error: 'race.horses gerekli' });
    }

    const raceObj: Race = {
      id: race.id || `race_${Date.now()}`,
      no: race.no || 1,
      track: race.track || 'Bilinmiyor',
      date: race.date || new Date().toISOString().split('T')[0],
      horses: race.horses,
      source: 'bookmarklet',
    };

    const result = analyzRace(raceObj);

    res.json({ success: true, result });
  } catch (error: any) {
    console.error('[API] Analiz hatası:', error);
    res.status(500).json({ error: error.message });
  }
});

// ---- ROUTE 3: Otomatik scraping ----
app.get('/api/scrape', async (_req: Request, res: Response) => {
  try {
    console.log('[API] TJK scraping başladı...');

    // Cache kontrolü
    if (Date.now() - cacheTime < CACHE_TTL && cachedRaces.length > 0) {
      console.log('[API] Cache kullanılıyor');
      const results = cachedRaces.map(r => analyzRace(r));
      return res.json({ success: true, source: 'cache', results });
    }

    const races = await scrapeTodayProgram();

    if (races.length === 0) {
      return res.json({
        success: false,
        message: 'TJK\'dan veri çekilemedi. Bookmarklet kullanın.',
        bookmarkletUrl: '/bookmarklet',
      });
    }

    cachedRaces = races;
    cacheTime = Date.now();

    const results = races.map(r => analyzRace(r));

    res.json({ success: true, source: 'scraper', count: races.length, results });
  } catch (error: any) {
    console.error('[API] Scraping hatası:', error);
    res.status(500).json({
      error: error.message,
      hint: 'TJK erişimi engellenmiş olabilir. Bookmarklet kullanın.',
    });
  }
});

// ---- ROUTE 4: Kayıtlı sonuçlar ----
app.get('/api/results', (_req: Request, res: Response) => {
  if (cachedRaces.length === 0) {
    return res.json({ results: [], message: 'Henüz veri yok' });
  }

  const results = cachedRaces.map(r => analyzRace(r));
  res.json({ results, count: results.length, cacheAge: Date.now() - cacheTime });
});

// ---- ROUTE 5: Bookmarklet script ----
app.get('/bookmarklet', (_req: Request, res: Response) => {
  const serverUrl = process.env.RAILWAY_PUBLIC_DOMAIN
    ? `https://${process.env.RAILWAY_PUBLIC_DOMAIN}`
    : `http://localhost:${PORT}`;

  const bookmarklet = `
javascript:(function(){
  var SERVER='${serverUrl}';
  
  // Tüm at satırlarını topla
  var rows=document.querySelectorAll('tr, .at-row, .horse-row');
  var horses=[];
  
  rows.forEach(function(row,idx){
    var cells=row.querySelectorAll('td');
    if(cells.length<4)return;
    
    var h={};
    h.no=parseInt(cells[0]?.textContent?.trim())||idx+1;
    h.name=cells[1]?.textContent?.trim()||'';
    if(!h.name||h.name.length<2)return;
    
    h.jockeyName=cells[3]?.textContent?.trim()||'';
    
    var kiloText=cells[4]?.textContent?.trim()||'';
    var kiloM=kiloText.match(/(\\d+\\.?\\d*)/);
    if(kiloM)h.weight=parseFloat(kiloM[1]);
    
    // Son 6Y - arama yap
    var son6YEl=row.querySelector('[class*="form"],[class*="son"],[class*="derece"]');
    h.son6Y=son6YEl?.textContent?.trim()||cells[5]?.textContent?.trim()||'';
    h.son6Y=h.son6Y.replace(/\\s+/g,'-').replace(/[^0-9\\-]/g,'');
    
    // AGF
    var agfEl=row.querySelector('[class*="agf"]');
    if(!agfEl){
      // Sayısal hücre ara
      for(var i=6;i<cells.length;i++){
        var t=cells[i]?.textContent?.trim();
        if(t&&parseFloat(t)>0&&parseFloat(t)<100){
          h.agf=parseFloat(t);break;
        }
      }
    }else{
      var agfM=agfEl.textContent?.match(/(\\d+\\.?\\d*)/);
      if(agfM)h.agf=parseFloat(agfM[1]);
    }
    
    h.ds=row.innerHTML.toLowerCase().indexOf(' ds')>-1;
    horses.push(h);
  });
  
  if(horses.length===0){
    alert('At bulunamadı! Yarış programı sayfasında mısınız?');
    return;
  }
  
  var raceNo=prompt('Koşu No?','1');
  var track=document.querySelector('[class*="track"],[class*="hipodrom"],h1')?.textContent?.trim()||'TJK';
  
  var payload={
    races:[{
      no:parseInt(raceNo)||1,
      track:track,
      horses:horses
    }],
    track:track,
    date:new Date().toISOString().split('T')[0]
  };
  
  fetch(SERVER+'/api/bookmarklet',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  })
  .then(r=>r.json())
  .then(function(data){
    if(data.success&&data.results&&data.results[0]){
      var r=data.results[0];
      var msg='✅ ANALİZ TAMAM\\n\\n';
      msg+='👑 SOVEREIGN: '+r.sovereign.horse.name+' ('+r.sovereign.total+'p / %'+r.sovereign.probability+')\\n';
      msg+='⚔️ BREAKER: '+r.breaker.horse.name+' ('+r.breaker.total+'p / %'+r.breaker.probability+')\\n';
      msg+='👻 GHOST: '+r.ghost.horse.name+' ('+r.ghost.total+'p / %'+r.ghost.probability+')\\n\\n';
      msg+='Tam sonuç: '+SERVER;
      alert(msg);
    }else{
      alert('Hata: '+JSON.stringify(data));
    }
  })
  .catch(function(e){alert('Sunucu hatası: '+e.message);});
})();
  `.trim();

  res.send(`
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TJK Bookmarklet</title>
  <style>
    body{background:#111;color:#fff;font-family:monospace;padding:20px;max-width:600px;margin:0 auto}
    h1{color:#f5a623}
    .bm{background:#222;border:2px solid #f5a623;padding:15px;border-radius:8px;margin:20px 0;word-break:break-all;font-size:12px;color:#aaa}
    .step{background:#1a1a1a;padding:12px;border-left:3px solid #f5a623;margin:10px 0}
    code{background:#333;padding:2px 6px;border-radius:4px;color:#f5a623}
  </style>
</head>
<body>
  <h1>🏇 TJK Bookmarklet Kurulumu</h1>
  
  <div class="step">
    <strong>1. Adım:</strong> Aşağıdaki kodu kopyala
  </div>
  
  <div class="bm">${bookmarklet.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div>
  
  <div class="step">
    <strong>2. Adım:</strong> Via Browser'da yeni bookmark oluştur<br>
    URL alanına bu kodu yapıştır
  </div>
  
  <div class="step">
    <strong>3. Adım:</strong> mobil.tjk.org'da yarış programını aç<br>
    Bookmark'a tıkla → Analiz otomatik başlar
  </div>
  
  <div class="step">
    <strong>4. Adım:</strong> Sonuçları görmek için:<br>
    <code>${serverUrl}</code>
  </div>
</body>
</html>
  `);
});

// Ana sayfa
app.get('/', (_req: Request, res: Response) => {
  res.sendFile(path.join(__dirname, '../public/index.html'));
});

app.listen(PORT, () => {
  console.log(`[Server] Port ${PORT} dinleniyor`);
  console.log(`[Server] Railway URL: ${process.env.RAILWAY_PUBLIC_DOMAIN || 'localhost'}`);
});

export default app;
