const express = require('express');
const https = require('https');
const app = express();
const PORT = process.env.PORT || 3000;

// ---------- HTML TANIMI EN ÜSTE TAŞINDI ----------
const HTML = `<!DOCTYPE html> ... (HTML içeriğinizin tamamı aynen burada olacak) ... `;

// CORS middleware
app.use((req, res, next) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', '*');
    if (req.method === 'OPTIONS') {
        res.sendStatus(200);
        return;
    }
    next();
});

// Yahoo Finance proxy
function yahoo(sym, interval, range, res) {
    const urls = [
        `https://query1.finance.yahoo.com/v8/finance/chart/${sym}.IS?interval=${interval}&range=${range}`,
        `https://query2.finance.yahoo.com/v8/finance/chart/${sym}.IS?interval=${interval}&range=${range}`
    ];
    const headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120',
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9'
    };
    function tryUrl(i) {
        if (i >= urls.length) {
            res.status(500).json({ error: 'Yahoo ulaşılamadı' });
            return;
        }
        https.get(urls[i], { headers }, (yr) => {
            if (yr.statusCode !== 200) {
                tryUrl(i + 1);
                return;
            }
            let d = '';
            yr.on('data', c => d += c);
            yr.on('end', () => {
                res.setHeader('Content-Type', 'application/json');
                res.end(d);
            });
        }).on('error', () => tryUrl(i + 1));
    }
    tryUrl(0);
}

// API route'lar
app.get('/api/:sym', (req, res) => yahoo(req.params.sym.toUpperCase(), req.query.tf || '1d', req.query.range || '1y', res));
app.get('/api/monthly/:sym', (req, res) => yahoo(req.params.sym.toUpperCase(), '1mo', '3y', res));
app.get('/health', (req, res) => res.json({ ok: true }));
app.get('/', (req, res) => {
    res.setHeader('Content-Type', 'text/html;charset=utf-8');
    res.send(HTML);
});

app.listen(PORT, () => console.log('VORTEX OK:' + PORT));
