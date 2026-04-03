const express = require('express');
const https = require('https');
const app = express();

// Railway için Kritik: Port ve Host ayarı
const PORT = process.env.PORT || 3000;

app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', '*');
  if (req.method === 'OPTIONS') { res.sendStatus(200); return; }
  next();
});

// Yahoo Finance Proxy - Sunucu IP engeline karşı hata yönetimi eklendi
function yahoo(sym, interval, range, res) {
  const urls = [
    `https://query1.finance.yahoo.com/v8/finance/chart/${sym}.IS?interval=${interval}&range=${range}`,
    `https://query2.finance.yahoo.com/v8/finance/chart/${sym}.IS?interval=${interval}&range=${range}`
  ];
  
  const headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json'
  };

  function tryUrl(i) {
    if (i >= urls.length) { 
      return res.status(502).json({error:'Yahoo Finance sunucu IP adresini engelledi. Lütfen sayfayı yenileyin.'}); 
    }
    
    const request = https.get(urls[i], { headers, timeout: 5000 }, (yr) => {
      if (yr.statusCode !== 200) { 
        yr.resume(); // Belleği temizle
        return tryUrl(i + 1); 
      }
      let d = '';
      yr.on('data', c => d += c);
      yr.on('end', () => { 
        res.setHeader('Content-Type','application/json'); 
        res.end(d); 
      });
    });

    request.on('error', () => tryUrl(i + 1));
    request.on('timeout', () => { request.destroy(); tryUrl(i + 1); });
  }
  tryUrl(0);
}

// API Route'ları
app.get('/api/:sym', (req, res) => yahoo(req.params.sym.toUpperCase(), req.query.tf||'1d', req.query.range||'1y', res));
app.get('/api/monthly/:sym', (req, res) => yahoo(req.params.sym.toUpperCase(), '1mo', '3y', res));
app.get('/health', (req, res) => res.status(200).send('OK')); // Railway Health Check için

// Ana Sayfa (HTML buraya gelecek, önceki HTML kısmını aynen koruyabilirsin)
app.get('/', (req, res) => { 
  res.setHeader('Content-Type','text/html;charset=utf-8'); 
  res.send(HTML_CONTENT); 
});

// Railway için kritik: 0.0.0.0 adresini dinlemesi şart
app.listen(PORT, '0.0.0.0', () => {
  console.log(`VORTEX v4.4 Aktif! Port: ${PORT}`);
});

// --- Aşağıdaki HTML_CONTENT kısmına senin gönderdiğin o uzun HTML kodunu yapıştır ---
const HTML_CONTENT = `... (Senin gönderdiğin HTML kodunun tamamı buraya gelecek) ...`;
