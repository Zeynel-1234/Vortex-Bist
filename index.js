const express = require('express');
const https = require('https');
const app = express();
const PORT = process.env.PORT || 3000;

app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  next();
});

// Yahoo Finance proxy
app.get('/api/:sym', (req, res) => {
  const sym = req.params.sym.toUpperCase() + '.IS';
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${sym}?interval=1d&range=1y`;
  https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (yr) => {
    let d = '';
    yr.on('data', c => d += c);
    yr.on('end', () => { res.setHeader('Content-Type','application/json'); res.end(d); });
  }).on('error', e => res.status(500).json({ error: e.message }));
});

app.get('/api/monthly/:sym', (req, res) => {
  const sym = req.params.sym.toUpperCase() + '.IS';
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${sym}?interval=1mo&range=3y`;
  https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (yr) => {
    let d = '';
    yr.on('data', c => d += c);
    yr.on('end', () => { res.setHeader('Content-Type','application/json'); res.end(d); });
  }).on('error', e => res.status(500).json({ error: e.message }));
});

// Ana sayfa — b-161 uygulaması
app.get('/', (req, res) => {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.send(HTML);
});

app.listen(PORT, () => console.log('VORTEX çalışıyor: ' + PORT));

const HTML = `<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BIST Terminal · Vortex v4.4</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Courier New',monospace;background:#07090f;color:#8892a4;height:100dvh;display:flex;flex-direction:column;overflow:hidden;font-size:13px}
::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:#1a2030;border-radius:2px}
#top{background:#0b0e18;border-bottom:2px solid #131826;padding:0 10px;height:44px;display:flex;align-items:center;gap:8px;flex-shrink:0;overflow-x:auto}
#top::-webkit-scrollbar{height:0}
.logo{color:#e8b84b;font-weight:700;font-size:13px;letter-spacing:3px;flex-shrink:0}
.sep{width:1px;height:18px;background:#131826;flex-shrink:0}
#hdr-sym{color:#fff;font-weight:700;font-size:15px;letter-spacing:2px;flex-shrink:0}
#stbar{background:#050709;border-bottom:1px solid #131826;padding:3px 10px;font-size:10px;display:flex;align-items:center;gap:6px;flex-shrink:0}
#tabs{background:#0b0e18;border-bottom:1px solid #131826;display:flex;flex-shrink:0;overflow-x:auto}
#tabs::-webkit-scrollbar{height:0}
.tab{background:transparent;border:none;border-bottom:2px solid transparent;padding:9px 12px;cursor:pointer;font-size:11px;font-weight:700;color:#2a3548;font-family:inherit;white-space:nowrap}
.tab.on{color:#e8b84b;border-bottom-color:#e8b84b}
#body{display:flex;flex:1;overflow:hidden;min-height:0}
#wl{width:155px;background:#08090f;border-right:1px solid #131826;display:flex;flex-direction:column;flex-shrink:0}
#wl-s{width:100%;background:#0f1118;border:none;color:#fff;padding:8px 9px;font-size:11px;font-family:inherit;outline:none;border-bottom:1px solid #131826;display:block}
#wl-count{padding:4px 10px;font-size:10px;color:#4b5e78;border-bottom:1px solid #131826;flex-shrink:0}
#wl-list{overflow-y:auto;flex:1}
#pf-panel{display:none;flex-direction:column;flex:1;overflow:hidden}
#center{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.panel{flex:1;display:flex;flex-direction:column;overflow:hidden;min-height:0}
.hidden{display:none!important}
#bell-wrap{position:relative;flex-shrink:0;cursor:pointer;margin-left:auto}
#bell-count{position:absolute;top:-4px;right:-4px;background:#ef4444;color:#fff;font-size:8px;font-weight:700;border-radius:50%;width:14px;height:14px;display:none;align-items:center;justify-content:center;line-height:14px;text-align:center}
#bell-panel{display:none;position:fixed;top:44px;right:0;width:280px;background:#0b1020;border:1px solid #1e3050;border-radius:0 0 8px 8px;z-index:100;max-height:400px;overflow-y:auto;box-shadow:0 4px 20px #000a}
#vf-top{background:#080d14;border-bottom:1px solid #131826;padding:4px 8px;display:flex;align-items:center;gap:5px;flex-shrink:0;overflow-x:auto}
#vf-top::-webkit-scrollbar{height:0}
.vfb{font-size:11px;font-weight:700;padding:3px 8px;border:1px solid;white-space:nowrap;flex-shrink:0}
.vfl{font-size:8px;letter-spacing:1px;color:#4b5e78;white-space:nowrap;flex-shrink:0}
.vfv{font-size:11px;font-weight:700;white-space:nowrap;flex-shrink:0}
#ind-s{background:#050810;border-bottom:1px solid #131826;padding:3px 8px;display:flex;gap:7px;overflow-x:auto;flex-shrink:0;font-size:10px}
#ind-s::-webkit-scrollbar{height:0}
.ic{white-space:nowrap;flex-shrink:0}.icv{font-weight:700}
#chart-outer{flex:1;display:flex;flex-direction:column;position:relative;min-height:0;overflow:hidden}
#cv-main{display:block;flex:1;min-height:0}
#cv-rsi{display:block;height:60px;flex-shrink:0;border-top:1px solid #131826}
#chart-msg{position:absolute;inset:0;background:rgba(7,9,15,0.95);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;z-index:10;font-size:11px;color:#4b5e78}
#vf-bot{background:#080d14;border-top:1px solid #131826;padding:4px 8px;display:flex;gap:5px;overflow-x:auto;flex-shrink:0}
#vf-bot::-webkit-scrollbar{height:0}
.ve{background:#0b1020;border:1px solid #1a2030;padding:3px 7px;font-size:9px;white-space:nowrap;flex-shrink:0}
.ve .lv{font-size:11px;font-weight:700;display:block}
.bull{color:#22c55e}.bear{color:#ef4444}.neu{color:#e8b84b}.dim{color:#4b5e78}
</style>
</head>
<body>
<div id="top">
  <span class="logo">BIST</span><div class="sep"></div>
  <span id="hdr-sym">—</span>
  <div id="bell-wrap" onclick="toggleBell()"><span style="font-size:18px;">🔔</span><span id="bell-count">0</span></div>
  <div id="bell-panel">
    <div style="padding:8px 12px;border-bottom:1px solid #1e3050;display:flex;justify-content:space-between;align-items:center;">
      <span style="font-size:11px;font-weight:700;color:#e8b84b;letter-spacing:2px;">SİNYAL UYARILARI</span>
      <button onclick="BELLS=[];renderBell()" style="background:transparent;border:none;color:#4b5e78;cursor:pointer;font-size:10px;">Temizle</button>
    </div>
    <div id="bell-list" style="padding:10px;font-size:10px;color:#2a3548;text-align:center;">Henüz sinyal yok.</div>
  </div>
  <span id="clk" style="font-size:9px;color:#1a2030;flex-shrink:0;margin-left:6px;"></span>
</div>
<div id="stbar">
  <div id="st-dot" style="width:6px;height:6px;border-radius:50%;background:#e8b84b;flex-shrink:0"></div>
  <span id="st-msg" style="color:#e8b84b;">Yükleniyor...</span>
  <button onclick="fetchRecs()" style="margin-left:auto;background:transparent;border:1px solid #1a2030;color:#4b5e78;padding:2px 8px;border-radius:3px;cursor:pointer;font-size:9px;font-family:inherit;">↺ Yenile</button>
</div>
<div id="tabs">
  <button class="tab" onclick="goTab('sinyal',this)">📊 VORTEX CHART</button>
  <button class="tab on" onclick="goTab('fiyatlar',this)">💹 CANLI FİYATLAR</button>
  <button class="tab" onclick="goTab('portfoy',this)">💼 PORTFÖY</button>
</div>
<div id="body">
<div id="wl">
  <input id="wl-s" placeholder="🔍 Ara..." oninput="buildWL(this.value)">
  <div id="wl-count"></div>
  <div id="wl-list"></div>
  <div id="pf-panel">
    <div style="padding:9px;border-bottom:1px solid #131826;flex-shrink:0;">
      <div style="font-size:10px;font-weight:700;color:#e8b84b;margin-bottom:7px;">+ HİSSE EKLE</div>
      <input id="pf-si" placeholder="🔍 Ara..." oninput="searchPF(this.value)" style="width:100%;background:#060a10;border:1px solid #1e3050;color:#fff;padding:6px 8px;font-size:11px;font-family:inherit;outline:none;margin-bottom:5px;">
      <div id="pf-sug" style="background:#0b1424;border:1px solid #1e3050;border-top:none;display:none;max-height:100px;overflow-y:auto;margin-bottom:5px;"></div>
      <div id="pf-lbl" style="font-size:11px;font-weight:700;color:#e8b84b;margin-bottom:5px;min-height:16px;">— seçilmedi</div>
      <div style="display:flex;gap:4px;margin-bottom:5px;">
        <input id="pf-q" type="number" placeholder="Adet" style="flex:1;background:#060a10;border:1px solid #1e3050;color:#fff;padding:5px;font-size:11px;font-family:inherit;outline:none;">
        <input id="pf-p" type="number" placeholder="₺" step="0.01" style="flex:1;background:#060a10;border:1px solid #1e3050;color:#fff;padding:5px;font-size:11px;font-family:inherit;outline:none;">
      </div>
      <button onclick="addToPF()" style="width:100%;background:#22c55e;color:#000;border:none;padding:7px;cursor:pointer;font-size:11px;font-weight:700;font-family:inherit;">+ PORTFÖYE EKLE</button>
    </div>
    <div style="padding:4px 9px;font-size:9px;color:#4b5e78;border-bottom:1px solid #131826;font-weight:700;flex-shrink:0;">PORTFÖY:</div>
    <div id="pf-items" style="overflow-y:auto;flex:1;"></div>
  </div>
</div>
<div id="center">
  <div id="tp-sinyal" class="panel hidden">
    <div id="vf-top">
      <div class="vfb" id="vf-badge" style="color:#4b5e78;border-color:#1a2030;">VF: —</div>
      <div class="sep"></div>
      <span class="vfl">MOM</span><span class="vfv" id="vf-mom">—</span>
      <div class="sep"></div>
      <span class="vfl">TREND</span><span class="vfv" id="vf-trend">—</span>
      <div class="sep"></div>
      <span class="vfl">VOL</span><span class="vfv" id="vf-vol">—</span>
      <div class="sep"></div>
      <span class="vfl">HACİM</span><span class="vfv" id="vf-hacim">—</span>
    </div>
    <div id="ind-s">
      <span class="ic dim">RSI:<span class="icv" id="ic-rsi">—</span></span>
      <span class="ic dim">STOCH:<span class="icv" id="ic-stoch">—</span></span>
      <span class="ic dim">MACD:<span class="icv" id="ic-macd">—</span></span>
      <span class="ic dim">BB:<span class="icv" id="ic-bb">—</span></span>
      <span class="ic dim">ATR:<span class="icv" id="ic-atr">—</span></span>
      <span class="ic dim">VWAP:<span class="icv" id="ic-vwap">—</span></span>
      <span class="ic dim">ST:<span class="icv" id="ic-st">—</span></span>
    </div>
    <div style="display:flex;gap:4px;padding:4px 8px;background:#060810;border-bottom:1px solid #131826;flex-shrink:0;align-items:center;">
      <button class="on" onclick="setTF('1d','1y',this)" style="background:#1a2a1a;border:1px solid #22c55e;color:#22c55e;padding:3px 9px;font-size:10px;font-family:inherit;cursor:pointer;font-weight:700;">1G</button>
      <button onclick="setTF('1wk','2y',this)" style="background:#0b0e18;border:1px solid #1a2030;color:#4b5e78;padding:3px 9px;font-size:10px;font-family:inherit;cursor:pointer;font-weight:700;">1H</button>
      <button onclick="setTF('1mo','5y',this)" style="background:#0b0e18;border:1px solid #1a2030;color:#4b5e78;padding:3px 9px;font-size:10px;font-family:inherit;cursor:pointer;font-weight:700;">1M</button>
      <span style="margin-left:auto;font-size:9px;color:#4b5e78;" id="vf-plbl">—</span>
    </div>
    <div id="chart-outer">
      <div id="chart-msg"><span style="font-size:24px;">📊</span><span id="cm-t">Sol listeden hisse seç</span><span id="cm-s" style="font-size:9px;color:#2a3548;"></span></div>
      <canvas id="cv-main"></canvas>
      <canvas id="cv-rsi"></canvas>
    </div>
    <div id="vf-bot">
      <div class="ve"><span style="color:#4b5e78;font-size:8px;">FİYAT</span><span class="lv" style="color:#00d4ff" id="ve-e">—</span></div>
      <div class="ve"><span style="color:#4b5e78;font-size:8px;">STOP</span><span class="lv bear" id="ve-s">—</span></div>
      <div class="ve"><span style="color:#4b5e78;font-size:8px;">H1</span><span class="lv neu" id="ve-h1">—</span></div>
      <div class="ve"><span style="color:#4b5e78;font-size:8px;">H2</span><span class="lv bull" id="ve-h2">—</span></div>
      <div class="ve"><span style="color:#4b5e78;font-size:8px;">H3</span><span class="lv bull" id="ve-h3">—</span></div>
      <div class="ve"><span style="color:#4b5e78;font-size:8px;">R/R</span><span class="lv" id="ve-rr">—</span></div>
    </div>
  </div>
  <div id="tp-fiyatlar" class="panel">
    <div style="background:#0b1510;border-bottom:1px solid #1a3a1a;padding:5px 10px;font-size:10px;color:#22c55e;flex-shrink:0;display:flex;align-items:center;gap:8px;">
      <span>💹 <strong style="color:#fff">Canlı Fiyatlar</strong></span>
      <button onclick="SORT_D=!SORT_D;renderFiyat()" style="margin-left:auto;background:#1a2030;border:1px solid #2a3548;color:#e8b84b;padding:2px 8px;border-radius:3px;cursor:pointer;font-size:9px;font-family:inherit;">↕ Sırala</button>
    </div>
    <div style="display:grid;grid-template-columns:62px 1fr 68px;padding:7px 8px;background:#0b0e18;border-bottom:2px solid #1a2540;font-size:10px;color:#5b7a9a;letter-spacing:1px;flex-shrink:0;font-weight:700;">
      <span>SEMBOL</span><span style="text-align:center;">TEK. DERECE</span><span style="text-align:right;">GÜN%</span>
    </div>
    <div id="fiyat-tablo" style="flex:1;overflow-y:auto;"></div>
    <div id="fiyat-st" style="padding:4px 10px;font-size:9px;color:#2a3548;flex-shrink:0;border-top:1px solid #131826;background:#0b0e18;">Bekleniyor...</div>
  </div>
  <div id="tp-portfoy" class="panel hidden">
    <div style="background:#0b1020;border-bottom:1px solid #1e3050;padding:8px 12px;font-size:11px;font-weight:700;color:#e8b84b;letter-spacing:1px;flex-shrink:0;">💼 PORTFÖY</div>
    <div style="padding:8px 10px;border-bottom:1px solid #131826;flex-shrink:0;">
      <input id="pf-s2" placeholder="🔍 Hisse ara..." oninput="searchPF2(this.value)" style="width:100%;background:#060a10;border:1px solid #1e3050;color:#fff;padding:8px 10px;border-radius:5px;font-size:12px;font-family:inherit;outline:none;">
      <div id="pf-sug2" style="background:#0b1424;border:1px solid #1e3050;border-top:none;display:none;max-height:120px;overflow-y:auto;border-radius:0 0 5px 5px;"></div>
      <div id="pf-lbl2" style="font-size:12px;font-weight:700;color:#e8b84b;margin-top:6px;min-height:16px;">— seçilmedi</div>
      <div style="display:flex;gap:8px;margin-top:8px;">
        <button onclick="addToPF2()" style="flex:1;background:#22c55e;color:#000;border:none;padding:9px;border-radius:5px;cursor:pointer;font-size:12px;font-weight:700;font-family:inherit;">+ PORTFÖYE EKLE</button>
        <button onclick="removePF2()" style="flex:1;background:#300;color:#f44;border:none;padding:9px;border-radius:5px;cursor:pointer;font-size:12px;font-weight:700;font-family:inherit;">− ÇIKAR</button>
      </div>
    </div>
    <div id="pf-right" style="flex:1;overflow-y:auto;"></div>
  </div>
</div></div>
<script>
var SL=[
{s:"THYAO",n:"THY"},{s:"AKBNK",n:"Akbank"},{s:"GARAN",n:"Garanti"},{s:"EREGL",n:"Ereğli"},
{s:"ASELS",n:"Aselsan"},{s:"KCHOL",n:"Koç Holding"},{s:"ISCTR",n:"İş Bankası"},{s:"VAKBN",n:"Vakıfbank"},
{s:"HALKB",n:"Halk Bank"},{s:"YKBNK",n:"Yapı Kredi"},{s:"FROTO",n:"Ford Otosan"},{s:"TOASO",n:"Tofaş"},
{s:"BIMAS",n:"BİM"},{s:"MGROS",n:"Migros"},{s:"ARCLK",n:"Arçelik"},{s:"TUPRS",n:"Tüpraş"},
{s:"PETKM",n:"Petkim"},{s:"SASA",n:"Sasa"},{s:"EKGYO",n:"Emlak GYO"},{s:"TTKOM",n:"Türk Telekom"},
{s:"TCELL",n:"Turkcell"},{s:"PGSUS",n:"Pegasus"},{s:"TAVHL",n:"TAV"},{s:"ENKAI",n:"Enka"},
{s:"KOZAL",n:"Koza Altın"},{s:"KOZAA",n:"Koza Anadolu"},{s:"AEFES",n:"Anadolu Efes"},
{s:"CCOLA",n:"Coca-Cola"},{s:"ULKER",n:"Ülker"},{s:"LOGO",n:"Logo Yazılım"},
{s:"MAVI",n:"Mavi"},{s:"OTKAR",n:"Otokar"},{s:"TTRAK",n:"Türk Traktör"},
{s:"GUBRF",n:"Gübre Fab."},{s:"BAGFS",n:"Bagfaş"},{s:"AKCNS",n:"Akçansa"},
{s:"CIMSA",n:"Çimsa"},{s:"NUHCM",n:"Nuh Çimento"},{s:"BRISA",n:"Brisa"},
{s:"KORDS",n:"Kordsa"},{s:"AYGAZ",n:"Aygaz"},{s:"DOHOL",n:"Doğan Holding"},
{s:"DOAS",n:"Doğuş Oto"},{s:"SKBNK",n:"Şekerbank"},{s:"ALBRK",n:"Albaraka"},
{s:"QNBFB",n:"QNB Finansbank"},{s:"TSKB",n:"TSKB"},{s:"ENJSA",n:"Enerjisa"},
{s:"AKSEN",n:"Aksa Enerji"},{s:"AKENR",n:"Ak Enerji"},{s:"GWIND",n:"Galata Wind"},
{s:"ODAS",n:"Odaş Elektrik"},{s:"ZOREN",n:"Zorlu Enerji"},{s:"ASTOR",n:"Astor Enerji"},
{s:"MPARK",n:"MLP Sağlık"},{s:"TKFEN",n:"Tekfen"},{s:"ALKIM",n:"Alkim Kimya"},
{s:"SISE",n:"Şişecam"},{s:"ANACM",n:"Anadolu Cam"},{s:"A1CAP",n:"A1 Capital"},
{s:"AGHOL",n:"AG Anadolu"},{s:"AKGRT",n:"Aksigorta"},{s:"AKSA",n:"Aksa Akrilik"},
{s:"ALARK",n:"Alarko"},{s:"ANSGR",n:"Anadolu Sig."},{s:"ARENA",n:"Arena BT"},
{s:"ASUZU",n:"Anadolu Isuzu"},{s:"AYEN",n:"Aydem Enerji"},{s:"BANVT",n:"Banvit"},
{s:"BERA",n:"Bera Holding"},{s:"BFREN",n:"Bosch Fren"},{s:"BIZIM",n:"Bizim Toptan"},
{s:"BJKAS",n:"Beşiktaş"},{s:"BRSAN",n:"Borusan Çelik"},{s:"BTCIM",n:"Batıçimento"},
{s:"BUCIM",n:"Bursa Çimento"},{s:"CRFSA",n:"CarrefourSA"},{s:"DARDL",n:"Dardanel"},
{s:"DEVA",n:"Deva Holding"},{s:"ECILC",n:"Eczacıbaşı İlaç"},{s:"ERZYT",n:"Eczacıbaşı Yat."},
{s:"ERCB",n:"Erçiyas Çimento"},{s:"EUPWR",n:"Europower"},{s:"FENER",n:"Fenerbahçe"},
{s:"GARFA",n:"Garanti Faktoring"},{s:"GESAN",n:"Gersan Elektrik"},{s:"GSDHO",n:"GSD Holding"},
{s:"GSRAY",n:"Galatasaray"},{s:"HEKTS",n:"Hektaş"},{s:"HLGYO",n:"Halk GYO"},
{s:"HOROZ",n:"Horoz Lojistik"},{s:"IHLAS",n:"İhlas Holding"},{s:"INDES",n:"İndeks BT"},
{s:"ISATR",n:"İş Portföy"},{s:"ISGYO",n:"İş GYO"},{s:"IZMDC",n:"İzmit Demir"},
{s:"KARSN",n:"Karsan"},{s:"KARTN",n:"Kartonsan"},{s:"KIMMR",n:"Kimmr"},
{s:"KMPUR",n:"Kimpur"},{s:"KONTR",n:"Kontrolmatik"},{s:"KONYA",n:"Konya Çimento"},
{s:"KRDMD",n:"Kardemir D"},{s:"MUTLU",n:"Mutlu Akü"},{s:"OTKAR",n:"Otokar"},
{s:"OYAKC",n:"Oyak Çimento"},{s:"PAPIL",n:"Papilon Savunma"},{s:"POLHO",n:"Polisan Holding"},
{s:"PRKAB",n:"Türk Prysmian"},{s:"RAYSG",n:"Ray Sigorta"},{s:"RNSHO",n:"Rönesans Holding"},
{s:"RYSAS",n:"Reysaş"},{s:"SELEC",n:"Selçuk Ecza"},{s:"SNGYO",n:"Sinpaş GYO"},
{s:"TRGYO",n:"Torunlar GYO"},{s:"TURSG",n:"Turk. Sigorta"},{s:"VESTL",n:"Vestel"},
{s:"VKGYO",n:"Vakıf GYO"},{s:"YYLGD",n:"Yayla Agro"}
];
var CUR="THYAO",TF="1d",TFR="1y",LAST_TAB="fiyatlar";
var REC={},CHG={},ST_M={},PF=[],PF_SEL="",PF_SEL2="",API_ALL=[],BELLS=[],PREV_ST={},SORT_D=true;
var BARS=null;
setInterval(function(){var e=document.getElementById("clk");if(e)e.textContent=new Date().toLocaleTimeString("tr-TR");},1000);
function setSt(ok,msg){var d=document.getElementById("st-dot"),m=document.getElementById("st-msg");if(d)d.style.background=ok===true?"#22c55e":ok===false?"#ef4444":"#e8b84b";if(m){m.textContent=msg;m.style.color=ok===true?"#22c55e":ok===false?"#ef4444":"#e8b84b";}}
function recLbl(v){if(v==null)return{t:"—",bg:"#1e293b",c:"#475569"};if(v<=-0.5)return{t:"G.SAT",bg:"#450a0a",c:"#ef4444"};if(v<-0.1)return{t:"SAT",bg:"#3b1010",c:"#fca5a5"};if(v<=0.1)return{t:"NÖTR",bg:"#1e293b",c:"#94a3b8"};if(v<0.5)return{t:"AL",bg:"#052e16",c:"#86efac"};return{t:"G.AL",bg:"#14532d",c:"#22c55e"};}
function showP(id){["tp-sinyal","tp-fiyatlar","tp-portfoy"].forEach(function(p){var e=document.getElementById(p);if(e){e.classList.remove("panel");e.classList.add("hidden");}});var e=document.getElementById("tp-"+id);if(e){e.classList.remove("hidden");e.classList.add("panel");}}
function buildWL(q){q=(q||"").toUpperCase().trim();var list=document.getElementById("wl-list"),cnt=document.getElementById("wl-count");var f=SL.filter(function(s){return!q||s.s.includes(q)||s.n.toUpperCase().includes(q);});if(cnt)cnt.textContent=f.length+" hisse";var h="";f.forEach(function(s){var rl=recLbl(REC[s.s]);var chg=CHG[s.s];var cs=chg!=null?(chg>=0?"+":"")+chg.toFixed(1)+"%":"";var cc=chg!=null?(chg>0?"#22c55e":chg<0?"#ef4444":"#4b5e78"):"#4b5e78";var ic=s.s===CUR;h+='<div onclick="pickSym(\''+s.s+'\')" style="padding:8px 9px;border-bottom:1px solid #0d1018;cursor:pointer;background:'+(ic?"#0f1a2a":"transparent")+';display:flex;align-items:center;gap:4px;"><div style="flex:1;min-width:0;"><div><span style="font-size:14px;font-weight:700;color:'+(ic?"#e8b84b":"#ffffff")+';">'+s.s+'</span></div><div style="font-size:11px;color:#7a9ab8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'+s.n+'</div></div><div style="text-align:right;flex-shrink:0;"><div style="font-size:9px;font-weight:700;background:'+rl.bg+';color:'+rl.c+';padding:1px 4px;">'+rl.t+'</div>'+(cs?'<div style="font-size:9px;color:'+cc+';">'+cs+'</div>':"")+' </div></div>';});if(list)list.innerHTML=h;}
function goTab(id,btn){document.querySelectorAll(".tab").forEach(function(b){b.classList.remove("on");});if(btn)btn.classList.add("on");var pfp=document.getElementById("pf-panel"),wls=document.getElementById("wl-s"),wll=document.getElementById("wl-list"),wlc=document.getElementById("wl-count");if(id==="portfoy"){if(pfp)pfp.style.display="flex";if(wls)wls.style.display="none";if(wll)wll.style.display="none";if(wlc)wlc.style.display="none";}else{if(pfp)pfp.style.display="none";if(wls)wls.style.display="block";if(wll)wll.style.display="block";if(wlc)wlc.style.display="block";}showP(id);LAST_TAB=id;if(id==="sinyal")loadChart();else if(id==="fiyatlar")renderFiyat();else if(id==="portfoy")renderPF2();}
function pickSym(s){CUR=s;document.getElementById("hdr-sym").textContent=s;buildWL(document.getElementById("wl-s").value||"");showP("sinyal");document.querySelectorAll(".tab").forEach(function(b){b.classList.remove("on");});document.querySelector("button[onclick*='sinyal']").classList.add("on");LAST_TAB="sinyal";loadChart();}
function setTF(tf,r,btn){TF=tf;TFR=r;document.querySelectorAll("#tp-sinyal button").forEach(function(b){b.style.background="#0b0e18";b.style.borderColor="#1a2030";b.style.color="#4b5e78";});if(btn){btn.style.background="#1a2a1a";btn.style.borderColor="#22c55e";btn.style.color="#22c55e";}loadChart();}
// INDICATORS
function ema(d,p){var k=2/(p+1),r=[],s=0,c=0;for(var i=0;i<d.length;i++){if(d[i]==null||isNaN(d[i])){r.push(null);continue;}if(c<p){s+=d[i];c++;r.push(c===p?s/p:null);}else{var pv=r.filter(function(v){return v!=null;}).pop()||d[i];r.push(pv*(1-k)+d[i]*k);}}return r;}
function dema(d,p){var e1=ema(d,p);var e2=ema(e1.filter(function(v){return v!=null;}),p);var r=new Array(d.length).fill(null);var j=0;for(var i=p*2-2;i<d.length;i++){if(e1[i]!=null&&j<e2.length&&e2[j]!=null)r[i]=2*e1[i]-e2[j];j++;}return r;}
function calcRSI(c,p){p=p||14;var r=[],g=0,l=0;for(var i=1;i<c.length;i++){var d=c[i]-c[i-1];if(i<=p){g+=Math.max(d,0);l+=Math.max(-d,0);if(i===p)r.push(l===0?100:100-100/(1+g/l));else r.push(null);}else{g=(g*(p-1)+Math.max(d,0))/p;l=(l*(p-1)+Math.max(-d,0))/p;r.push(l===0?100:100-100/(1+g/l));}}return r;}
function calcMACD(c){var e12=ema(c,12),e26=ema(c,26);var ml=c.map(function(_,i){return e12[i]!=null&&e26[i]!=null?e12[i]-e26[i]:null;});var vm=ml.filter(function(v){return v!=null;});var sig=ema(vm,9);var h=[],si=0;for(var i=0;i<ml.length;i++){if(ml[i]==null)h.push(null);else{h.push(sig[si]!=null?ml[i]-sig[si]:null);si++;}}return{ml:ml,h:h};}
function calcBB(c,p,m){p=p||20;m=m||2;var u=[],l=[],md=[];for(var i=0;i<c.length;i++){if(i<p-1){u.push(null);l.push(null);md.push(null);continue;}var s=c.slice(i-p+1,i+1);var mn=s.reduce(function(a,b){return a+b;})/p;var sd=Math.sqrt(s.reduce(function(a,b){return a+(b-mn)*(b-mn);},0)/p);u.push(mn+m*sd);l.push(mn-m*sd);md.push(mn);}return{u:u,l:l,m:md};}
function calcStoch(H,L,C,k){k=k||14;var r=[];for(var i=0;i<C.length;i++){if(i<k-1){r.push(null);continue;}var hh=Math.max.apply(null,H.slice(i-k+1,i+1));var ll=Math.min.apply(null,L.slice(i-k+1,i+1));r.push(hh===ll?50:((C[i]-ll)/(hh-ll))*100);}return r;}
function calcATR(H,L,C,p){p=p||14;var tr=[],at=[];for(var i=0;i<C.length;i++){if(i===0){tr.push(H[i]-L[i]);at.push(null);continue;}tr.push(Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1])));if(i<p)at.push(null);else if(i===p)at.push(tr.slice(0,p+1).reduce(function(a,b){return a+b;})/p);else at.push((at[i-1]*(p-1)+tr[i])/p);}return at;}
function calcST(H,L,C,p,m){p=p||10;m=m||3;var a=calcATR(H,L,C,p),dr=[],ps=null,pd=1;for(var i=0;i<C.length;i++){if(a[i]==null){dr.push(null);continue;}var hl2=(H[i]+L[i])/2,up=hl2+m*a[i],dn=hl2-m*a[i];var cs,cd;if(ps==null){cs=up;cd=1;}else if(pd===1){cs=C[i]>ps?Math.max(dn,ps):up;cd=C[i]>cs?1:-1;}else{cs=C[i]<ps?Math.min(up,ps):dn;cd=C[i]>cs?1:-1;}dr.push(cd);ps=cs;pd=cd;}return dr;}
function calcOBV(C,V){var o=[V[0]||0];for(var i=1;i<C.length;i++)o.push(C[i]>C[i-1]?o[i-1]+(V[i]||0):C[i]<C[i-1]?o[i-1]-(V[i]||0):o[i-1]);return o;}
function lv(a){for(var i=a.length-1;i>=0;i--)if(a[i]!=null)return a[i];return null;}
// VORTEX SCORE
function vortexScore(I){
  var mom=40;
  if(I.rsi<25)mom+=35;else if(I.rsi<35)mom+=25;else if(I.rsi<45)mom+=10;else if(I.rsi>78)mom-=25;else if(I.rsi>68)mom-=12;
  if(I.stoch<20)mom+=20;else if(I.stoch<30)mom+=10;else if(I.stoch>80)mom-=15;
  if(I.macd>0&&I.macdP!=null&&I.macd>I.macdP)mom+=15;else if(I.macd<0)mom-=15;
  if(I.div==="bull")mom+=20;else if(I.div==="bear")mom-=20;
  mom=Math.max(0,Math.min(100,mom));
  var tr=40;
  if(I.mst===1)tr+=30;else tr-=20;
  if(I.dema&&I.price>I.dema)tr+=20;else tr-=10;
  if(I.e8>I.e21&&I.e21>I.e50)tr+=20;else if(I.e8<I.e21&&I.e21<I.e50)tr-=20;
  if(I.st===1)tr+=15;else tr-=10;
  tr=Math.max(0,Math.min(100,tr));
  var vol=40;
  if(I.price<I.bbl)vol+=30;else if(I.price>I.bbu)vol-=20;
  if(I.squeeze)vol+=20;
  if(I.zscore<-2)vol+=20;else if(I.zscore>2)vol-=20;
  vol=Math.max(0,Math.min(100,vol));
  var hac=40;
  if(I.volr>1.5)hac+=30;else if(I.volr>1.2)hac+=15;else if(I.volr<0.7)hac-=15;
  if(I.price>I.vwap)hac+=15;else hac-=10;
  if(I.obvUp)hac+=10;
  if(I.fib==="g")hac+=15;else if(I.fib==="m")hac+=8;
  hac=Math.max(0,Math.min(100,hac));
  var w1=0.30,w2=0.30,w3=0.20,w4=0.20;
  var atrN=I.atr?I.atr/I.price*100:2;
  if(atrN>3){w1=0.35;w2=0.25;}else if(atrN<1.5){w1=0.25;w2=0.35;}
  return{mom:mom,tr:tr,vol:vol,hac:hac,final:Math.max(0,Math.min(100,Math.round(mom*w1+tr*w2+vol*w3+hac*w4)))};
}
// CANVAS CHART
function drawChart(bars,mdir){
  var co=document.getElementById("chart-outer"),cm=document.getElementById("cv-main"),cr=document.getElementById("cv-rsi");
  if(!co||!cm||!cr)return;
  var TW=co.clientWidth||320,TH=co.clientHeight-60||200;
  if(TH<80)TH=80;
  var RH=60,dpr=window.devicePixelRatio||1;
  cm.width=TW*dpr;cm.height=TH*dpr;cm.style.width=TW+"px";cm.style.height=TH+"px";
  cr.width=TW*dpr;cr.height=RH*dpr;cr.style.width=TW+"px";cr.style.height=RH+"px";
  var mc=cm.getContext("2d");mc.scale(dpr,dpr);
  var rc=cr.getContext("2d");rc.scale(dpr,dpr);
  var W=TW,H=TH,n=bars.length;
  if(n<3)return;
  var C=bars.map(function(d){return d.c;}),HH=bars.map(function(d){return d.h;}),LL=bars.map(function(d){return d.l;}),OO=bars.map(function(d){return d.o;}),VV=bars.map(function(d){return d.v;});
  var rsiA=calcRSI(C,14),macdR=calcMACD(C),bbR=calcBB(C,20,2);
  var stochA=calcStoch(HH,LL,C,14),atrA=calcATR(HH,LL,C,14),stDir=calcST(HH,LL,C,10,3);
  var dema25=dema(C,25),e8a=ema(C,8),e21a=ema(C,21),e50a=ema(C,50);
  var obvA=calcOBV(C,VV);
  var vwapA=[];for(var i=0;i<n;i++){var sl2=bars.slice(Math.max(0,i-19),i+1);var tv=sl2.reduce(function(a,d){return a+((d.h+d.l+d.c)/3*d.v);},0);var sv=sl2.reduce(function(a,d){return a+d.v;},0);vwapA.push(sv?tv/sv:C[i]);}
  var lRSI=lv(rsiA)||50,lMACD=lv(macdR.h)||0,lMACDp=macdR.h.filter(function(v){return v!=null;}).slice(-2)[0]||lMACD;
  var lBBU=lv(bbR.u)||0,lBBL=lv(bbR.l)||0,lBBM=lv(bbR.m)||0;
  var lStoch=lv(stochA)||50,lATR=lv(atrA)||0,lST=lv(stDir)||1;
  var lOBV=obvA[n-1],pOBV=obvA[Math.max(0,n-6)];
  var lDE=lv(dema25)||0,lE8=lv(e8a)||0,lE21=lv(e21a)||0,lE50=lv(e50a)||0;
  var lVWAP=vwapA[n-1],price=C[n-1];
  var avgV=VV.slice(-20).reduce(function(a,b){return a+b;})/20,volR=avgV?VV[n-1]/avgV:1;
  var sl20=C.slice(-20),sl20m=sl20.reduce(function(a,b){return a+b;})/sl20.length;
  var sl20s=Math.sqrt(sl20.reduce(function(a,b){return a+(b-sl20m)*(b-sl20m);},0)/sl20.length)||1;
  var zscore=(price-sl20m)/sl20s;
  var bbW=lBBM?((lBBU-lBBL)/lBBM*100):0;
  var bbWp=bbR.m[n-6]?((bbR.u[n-6]-bbR.l[n-6])/bbR.m[n-6]*100):bbW;
  var rc2=C.slice(-10),rr2=rsiA.filter(function(v){return v!=null;}).slice(-10);
  var div="none";if(rc2.length>=5&&rr2.length>=5){var pt=rc2[rc2.length-1]-rc2[0],rt=rr2[rr2.length-1]-rr2[0];if(pt<0&&rt>2)div="bull";else if(pt>0&&rt<-2)div="bear";}
  var swH=Math.max.apply(null,HH.slice(-60)),swL=Math.min.apply(null,LL.slice(-60));
  var retr=(swH-swL)?(swH-price)/(swH-swL):0;
  var fib=retr>=0.6&&retr<=0.79?"g":retr>=0.35&&retr<0.6?"m":"x";
  var I={rsi:lRSI,stoch:lStoch,macd:lMACD,macdP:lMACDp,div:div,mst:mdir||1,dema:lDE,e8:lE8,e21:lE21,e50:lE50,st:lST,price:price,bbu:lBBU,bbl:lBBL,bbm:lBBM,squeeze:bbW<bbWp*0.9,zscore:zscore,volr:volR,vwap:lVWAP,obvUp:lOBV>pOBV,fib:fib,atr:lATR};
  var SC=vortexScore(I);
  var bc=SC.final>=75?"#22c55e":SC.final>=60?"#00d4ff":SC.final>=40?"#e8b84b":"#ef4444";
  var bt=SC.final>=75?"GÜÇLÜ AL ▲":SC.final>=60?"İZLE ◆":SC.final>=40?"BEKLE ■":"UZAK DUR ▼";
  var bg=document.getElementById("vf-badge");if(bg){bg.style.color=bc;bg.style.borderColor=bc;bg.textContent="VF:"+SC.final+" "+bt;}
  function sv(id,v,cls){var e=document.getElementById(id);if(e){e.textContent=v;e.className="vfv "+(cls||"");}}
  sv("vf-mom",SC.mom,SC.mom>=60?"bull":SC.mom<40?"bear":"neu");sv("vf-trend",SC.tr,SC.tr>=60?"bull":SC.tr<40?"bear":"neu");sv("vf-vol",SC.vol,SC.vol>=60?"bull":SC.vol<40?"bear":"neu");sv("vf-hacim",SC.hac,SC.hac>=60?"bull":SC.hac<40?"bear":"neu");
  function sc2(id,v,cls){var e=document.getElementById(id);if(e){e.textContent=v;e.parentElement.className="ic "+(cls||"dim");}}
  sc2("ic-rsi",lRSI.toFixed(1),lRSI<35?"bull":lRSI>70?"bear":"neu");sc2("ic-stoch",lStoch.toFixed(1),lStoch<20?"bull":lStoch>80?"bear":"neu");sc2("ic-macd",(lMACD>0?"▲":"▼")+Math.abs(lMACD).toFixed(3),lMACD>0&&lMACD>lMACDp?"bull":lMACD<0?"bear":"neu");sc2("ic-bb",price<lBBL?"ALT":price>lBBU?"ÜST":bbW<bbWp*0.9?"SIKIŞ":"ORTA",price<lBBL?"bull":price>lBBU?"bear":"neu");sc2("ic-atr",(lATR/price*100).toFixed(1)+"%","neu");sc2("ic-vwap",price>lVWAP?"Üst":"Alt",price>lVWAP?"bull":"bear");sc2("ic-st",lST===1?"YEŞİL":"KIRMIZI",lST===1?"bull":"bear");
  var prev=bars[n-2]?bars[n-2].c:price;var chg=price-prev;var pl=document.getElementById("vf-plbl");if(pl){pl.textContent="₺"+price.toFixed(2)+" "+(chg>=0?"+":"")+((chg/prev)*100).toFixed(2)+"%";pl.style.color=chg>=0?"#22c55e":"#ef4444";}
  var a=lATR||price*0.02,stop2=price-a*2,t1=price+a*1.5,t2=price+a*3,t3=price+a*5.18;var rr2b=((t2-price)/(price-stop2)).toFixed(1);
  function se(id,v,c){var e=document.getElementById(id);if(e){e.textContent=v;if(c)e.style.color=c;}}
  se("ve-e","₺"+price.toFixed(2),"#00d4ff");se("ve-s","₺"+stop2.toFixed(2),"#ef4444");se("ve-h1","₺"+t1.toFixed(2),"#e8b84b");se("ve-h2","₺"+t2.toFixed(2),"#22c55e");se("ve-h3","₺"+t3.toFixed(2),"#22c55e");se("ve-rr","1:"+rr2b,rr2b>=2?"#22c55e":"#ef4444");
  var allP=[];bars.forEach(function(d){allP.push(d.h,d.l);});bbR.u.forEach(function(v){if(v)allP.push(v);});bbR.l.forEach(function(v){if(v)allP.push(v);});
  var pMin=Math.min.apply(null,allP.filter(function(v){return v>0;}));var pMax=Math.max.apply(null,allP);var pRng=pMax-pMin||1;pMin-=pRng*0.03;pMax+=pRng*0.18;
  var VH=20,pad={l:2,r:52,t:6,b:18};
  function px(i){return pad.l+(i/(n-1||1))*(W-pad.l-pad.r);}function py(v){return pad.t+(1-(v-pMin)/(pMax-pMin))*(H-pad.t-pad.b-VH);}
  mc.fillStyle="#07090f";mc.fillRect(0,0,W,H);
  mc.strokeStyle="#0d1018";mc.lineWidth=0.5;for(var gi=0;gi<5;gi++){var gv=pMin+(pMax-pMin)*gi/4;var gy=py(gv);mc.beginPath();mc.moveTo(pad.l,gy);mc.lineTo(W-pad.r,gy);mc.stroke();mc.fillStyle="#2a3548";mc.font="9px monospace";mc.textAlign="right";mc.fillText(gv.toFixed(gv>100?0:gv>10?1:2),W-2,gy+3);}
  var sS2=0,sD2=null;for(var i=0;i<=n;i++){var dd=stDir[i]||null;if(dd!==sD2||i===n){if(sD2!=null&&i>sS2){mc.fillStyle=sD2===1?"rgba(34,197,94,0.05)":"rgba(239,68,68,0.05)";mc.fillRect(px(sS2),pad.t,px(Math.min(i,n-1))-px(sS2),H-pad.t-pad.b-VH);}sD2=dd;sS2=i;}}
  mc.fillStyle="rgba(0,212,255,0.04)";mc.beginPath();var fs=true;for(var i=0;i<n;i++){if(bbR.u[i]==null)continue;if(fs){mc.moveTo(px(i),py(bbR.u[i]));fs=false;}else mc.lineTo(px(i),py(bbR.u[i]));}for(var i=n-1;i>=0;i--){if(bbR.l[i]==null)continue;mc.lineTo(px(i),py(bbR.l[i]));}mc.closePath();mc.fill();
  function dl(vals,col,alpha,dash){mc.save();mc.strokeStyle=col;mc.globalAlpha=alpha||1;mc.lineWidth=1.5;mc.setLineDash(dash||[]);mc.beginPath();var f2=true;for(var i=0;i<n;i++){if(vals[i]==null)continue;var x=px(i),y=py(vals[i]);f2?mc.moveTo(x,y):mc.lineTo(x,y);f2=false;}mc.stroke();mc.restore();}
  dl(bbR.u,"rgba(0,212,255,0.5)",1,[3,3]);dl(bbR.l,"rgba(0,212,255,0.5)",1,[3,3]);dl(vwapA,"rgba(180,127,255,0.8)",1,[2,2]);dl(e50a,"rgba(180,127,255,0.5)",1,[4,2]);dl(dema25,"#e8b84b",0.9,[]);
  var atrStopL=C.map(function(c,i){return atrA[i]!=null?c-atrA[i]*2:null;});dl(atrStopL,"rgba(239,68,68,0.6)",1,[3,2]);
  function hl(p2,col,lbl){if(p2<pMin||p2>pMax)return;var y2=py(p2);mc.save();mc.strokeStyle=col;mc.lineWidth=1;mc.setLineDash([4,3]);mc.globalAlpha=0.7;mc.beginPath();mc.moveTo(pad.l,y2);mc.lineTo(W-pad.r,y2);mc.stroke();mc.setLineDash([]);mc.fillStyle=col;mc.font="bold 9px monospace";mc.textAlign="right";mc.fillText(lbl,W-2,y2-2);mc.restore();}
  hl(stop2,"#ef4444","STOP");hl(t2,"#22c55e","H2");
  var cw2=Math.max(1,(W-pad.l-pad.r)/n*0.72);
  for(var i=0;i<n;i++){var x=px(i);var isUp=C[i]>=OO[i];var col=isUp?"#22c55e":"#ef4444";mc.strokeStyle=col;mc.lineWidth=1;mc.beginPath();mc.moveTo(x,py(HH[i]));mc.lineTo(x,py(LL[i]));mc.stroke();mc.fillStyle=col;var bt2=py(Math.max(C[i],OO[i])),bb2=py(Math.min(C[i],OO[i]));mc.fillRect(x-cw2/2,bt2,cw2,Math.max(1,bb2-bt2));}
  for(var i=1;i<n;i++){if(stDir[i]!=null&&stDir[i-1]!=null&&stDir[i]!==stDir[i-1]){var ax=px(i);var col2=stDir[i]===1?"#22c55e":"#ef4444";var ay=stDir[i]===1?py(LL[i])+12:py(HH[i])-12;mc.fillStyle=col2;mc.font="10px monospace";mc.textAlign="center";mc.fillText(stDir[i]===1?"▲":"▼",ax,ay);}}
  var maxV=Math.max.apply(null,VV.filter(function(v){return v>0;}));
  for(var i=0;i<n;i++){var x=px(i);var vh=(VV[i]/(maxV||1))*VH*0.9;mc.fillStyle=C[i]>=OO[i]?"rgba(34,197,94,0.4)":"rgba(239,68,68,0.4)";mc.fillRect(x-cw2/2,H-pad.b-vh,cw2,vh);}
  mc.fillStyle="#2a3548";mc.font="8px monospace";mc.textAlign="center";var step=Math.max(1,Math.floor(n/5));for(var i=0;i<n;i+=step){if(bars[i].t){var dt=new Date(bars[i].t*1000);mc.fillText(dt.getDate()+"."+(dt.getMonth()+1),px(i),H-pad.b+10);}}
  rc.fillStyle="#050810";rc.fillRect(0,0,W,RH);function ry(v){return(1-(v/100))*(RH-14)+4;}
  rc.strokeStyle="#0d1018";rc.lineWidth=0.5;[30,50,70].forEach(function(lvl){var y2=ry(lvl);rc.beginPath();rc.moveTo(0,y2);rc.lineTo(W-40,y2);rc.stroke();rc.fillStyle=lvl===30?"#22c55e":lvl===70?"#ef4444":"#2a3548";rc.font="8px monospace";rc.textAlign="left";rc.fillText(lvl,W-38,y2+3);});
  rc.strokeStyle="#00d4ff";rc.lineWidth=1.5;rc.setLineDash([]);rc.beginPath();var fr=true;for(var i=0;i<n;i++){if(rsiA[i]==null)continue;var x=(i/(n-1||1))*(W-40);var y2=ry(rsiA[i]);fr?rc.moveTo(x,y2):rc.lineTo(x,y2);fr=false;}rc.stroke();
  rc.fillStyle=lRSI<35?"#22c55e":lRSI>70?"#ef4444":"#00d4ff";rc.font="bold 9px monospace";rc.textAlign="right";rc.fillText("RSI "+lRSI.toFixed(1),W-2,12);
}
// LOAD CHART — sunucudan veri çek
var MDIR={};
function loadChart(){
  var sym=CUR;
  var msg=document.getElementById("chart-msg"),ct=document.getElementById("cm-t"),cs=document.getElementById("cm-s");
  if(msg)msg.style.display="flex";if(ct)ct.textContent="⏳ "+sym+" yükleniyor...";if(cs)cs.textContent="";
  fetch("/api/monthly/"+sym).then(function(r){return r.json();}).then(function(data){
    var chart=data&&data.chart;if(chart&&chart.result&&chart.result[0]){var res=chart.result[0],q=res.indicators.quote[0];var mv=[];for(var i=0;i<res.timestamp.length;i++)if(q.close[i]!=null&&q.high[i]!=null&&q.low[i]!=null)mv.push({h:q.high[i],l:q.low[i],c:q.close[i]});if(mv.length>=10){var mST=calcST(mv.map(function(d){return d.h;}),mv.map(function(d){return d.l;}),mv.map(function(d){return d.c;}),10,3);MDIR[sym]=lv(mST)||1;}}
  }).catch(function(){}).finally(function(){fetchDaily();});
  function fetchDaily(){
    fetch("/api/"+sym+"?tf="+TF+"&range="+TFR).then(function(r){return r.json();}).then(function(data){
      var chart=data&&data.chart;if(!chart||!chart.result||!chart.result[0]){if(msg){msg.style.display="flex";if(ct)ct.textContent="⚠ Veri alınamadı: "+sym;}return;}
      var res=chart.result[0],q=res.indicators.quote[0];
      var valid=[];for(var i=0;i<res.timestamp.length;i++)if(q.close[i]!=null&&q.high[i]!=null&&q.low[i]!=null&&q.open[i]!=null)valid.push({t:res.timestamp[i],o:q.open[i],h:q.high[i],l:q.low[i],c:q.close[i],v:q.volume[i]||0});
      if(valid.length<5){if(msg){msg.style.display="flex";if(ct)ct.textContent="⚠ Yetersiz veri";}return;}
      if(msg)msg.style.display="none";BARS=valid;drawChart(valid,MDIR[sym]||1);
      window.onresize=function(){if(BARS)drawChart(BARS,MDIR[CUR]||1);};
    }).catch(function(e){if(msg){msg.style.display="flex";if(ct)ct.textContent="⚠ Hata: "+e.message;}});
  }
}
// TV SCANNER
var TV_SCAN="https://scanner.tradingview.com/turkey/scan";
var PROXIES=[TV_SCAN,"https://corsproxy.io/?"+encodeURIComponent(TV_SCAN),"https://api.allorigins.win/raw?url="+encodeURIComponent(TV_SCAN),"https://api.codetabs.com/v1/proxy?quest="+encodeURIComponent(TV_SCAN)];
function tvPost(body,ms){return new Promise(function(resolve,reject){var pi=0;function tryNext(){if(pi>=PROXIES.length){reject(new Error("fail"));return;}var url=PROXIES[pi++];var done=false;var t=setTimeout(function(){if(!done){done=true;tryNext();}},ms||8000);var xhr=new XMLHttpRequest();xhr.open("POST",url,true);xhr.setRequestHeader("Content-Type","text/plain");xhr.onload=function(){if(done)return;clearTimeout(t);done=true;if(xhr.status>=200&&xhr.status<300){try{var d=JSON.parse(xhr.responseText);if(d&&d.data&&d.data.length>0){resolve(d);return;}}catch(e){}}tryNext();};xhr.onerror=function(){if(!done){clearTimeout(t);done=true;tryNext();}};xhr.send(JSON.stringify(body));}tryNext();});}
async function fetchRecs(){setSt(null,"Sinyaller yükleniyor...");var body={filter:[],options:{lang:"tr"},columns:["name","Recommend.All","close","change"],sort:{sortBy:"change",sortOrder:"desc"},range:[0,700],markets:["turkey"]};try{var data=await tvPost(body,12000);API_ALL=[];data.data.forEach(function(item){var sym=(item.s||"").replace(/^BIST(|_DL):/,"").trim();var d=item.d;if(!sym||!d)return;if(d[1]!=null)REC[sym]=parseFloat(d[1]);if(d[3]!=null)CHG[sym]=parseFloat(d[3].toFixed(2));var name=sym;for(var k=0;k<SL.length;k++)if(SL[k].s===sym){name=SL[k].n;break;}API_ALL.push({sym:sym,name:name});});var slS={};for(var k=0;k<SL.length;k++)slS[SL[k].s]=1;API_ALL.forEach(function(item){if(!slS[item.sym]){SL.push({s:item.sym,n:item.name});slS[item.sym]=1;}});setSt(true,"✅ "+SL.length+" hisse — "+new Date().toLocaleTimeString("tr-TR"));buildWL(document.getElementById("wl-s")?document.getElementById("wl-s").value:"");SORT_D=true;renderFiyat();checkSTAlerts();renderPF2();}catch(e){setSt(false,"❌ Bağlanamadı");}}
async function fetchRecsMonthly(){var body={filter:[],options:{lang:"tr"},columns:["name","Recommend.All|1M","RSI|1M","EMA20|1M","EMA50|1M","MACD.hist|1M"],sort:{sortBy:"name",sortOrder:"asc"},range:[0,700],markets:["turkey"]};try{var data=await tvPost(body,14000);data.data.forEach(function(item){var sym=(item.s||"").replace(/^BIST(|_DL):/,"").trim();var d=item.d;if(!sym||!d)return;var rec=parseFloat(d[1]),rsi2=parseFloat(d[2]),ema20=parseFloat(d[3]),ema50=parseFloat(d[4]),hist=parseFloat(d[5]);if(isNaN(rec)){ST_M[sym]=0;return;}var f1=!isNaN(rec)&&rec>=0.2,f2=!isNaN(rsi2)&&rsi2>=50,f3=!isNaN(ema20)&&!isNaN(ema50)&&ema20>ema50,f4=!isNaN(hist)&&hist>0;var sc3=(f1?1:0)+(f2?1:0)+(f3?1:0)+(f4?1:0);ST_M[sym]=(sc3===4||(f1&&sc3===3))?1:-1;});buildWL(document.getElementById("wl-s")?document.getElementById("wl-s").value:"");renderPF2();}catch(e){}}
function renderFiyat(){var tablo=document.getElementById("fiyat-tablo");if(!tablo)return;var rows=(API_ALL.length>0)?API_ALL.map(function(r){return{sym:r.sym,rec:REC[r.sym],chg:CHG[r.sym]!=null?CHG[r.sym]:null};}):SL.map(function(s){return{sym:s.s,rec:REC[s.s],chg:CHG[s.s]!=null?CHG[s.s]:null};});rows.sort(function(a,b){var av=a.chg!=null?a.chg:-9999,bv=b.chg!=null?b.chg:-9999;return SORT_D?(bv-av):(av-bv);});var parts=[];for(var j=0;j<rows.length;j++){var r=rows[j];var rl=recLbl(r.rec);var cs=r.chg!=null?(r.chg>=0?"+":"")+r.chg.toFixed(2)+"%":"—";var cc=r.chg!=null?(r.chg>0?"#22c55e":r.chg<0?"#ef4444":"#94a3b8"):"#2a3548";var ic=r.sym===CUR;parts.push('<div onclick="pickSym(\''+r.sym+'\')" style="display:grid;grid-template-columns:62px 1fr 68px;padding:6px 8px;border-bottom:1px solid #0d1018;cursor:pointer;background:'+(ic?"#0f1a2a":"transparent")+'">'+'<span style="font-size:14px;font-weight:700;color:'+(ic?"#e8b84b":"#ffffff")+';">'+r.sym+'</span>'+'<span style="text-align:center;"><span style="font-size:10px;font-weight:700;padding:1px 6px;background:'+rl.bg+';color:'+rl.c+';">'+rl.t+'</span></span>'+'<span style="text-align:right;font-size:11px;font-weight:700;color:'+cc+';">'+cs+'</span></div>');}tablo.innerHTML=parts.join("");var st=document.getElementById("fiyat-st");if(st)st.textContent=rows.length+" hisse — "+new Date().toLocaleTimeString("tr-TR");}
// PORTFOY
function searchPF(q){var box=document.getElementById("pf-sug");if(!box)return;if(!q){box.style.display="none";return;}q=q.toUpperCase();var m=SL.filter(function(s){return s.s.includes(q)||s.n.toUpperCase().includes(q);}).slice(0,8);if(!m.length){box.style.display="none";return;}box.style.display="block";box.innerHTML=m.map(function(s){return'<div style="padding:7px 9px;cursor:pointer;font-size:11px;border-bottom:1px solid #0f1520;color:#fff;" onclick="selPF(\''+s.s+'\',\''+s.n+'\')">'+s.s+' <span style="color:#4b5e78;font-size:10px;">'+s.n+'</span></div>';}).join("");}
function selPF(sym,name){PF_SEL=sym;var lbl=document.getElementById("pf-lbl");if(lbl)lbl.textContent="✅ "+sym;var sug=document.getElementById("pf-sug");if(sug)sug.style.display="none";var inp=document.getElementById("pf-si");if(inp)inp.value=sym;}
function searchPF2(q){var box=document.getElementById("pf-sug2");if(!box)return;if(!q){box.style.display="none";return;}q=q.toUpperCase();var m=SL.filter(function(s){return s.s.includes(q)||s.n.toUpperCase().includes(q);}).slice(0,8);if(!m.length){box.style.display="none";return;}box.style.display="block";box.innerHTML=m.map(function(s){return'<div style="padding:7px 9px;cursor:pointer;font-size:11px;border-bottom:1px solid #0f1520;color:#fff;" onclick="selPF2(\''+s.s+'\',\''+s.n+'\')">'+s.s+' <span style="color:#4b5e78;font-size:10px;">'+s.n+'</span></div>';}).join("");}
function selPF2(sym,name){PF_SEL2=sym;var lbl=document.getElementById("pf-lbl2");if(lbl)lbl.textContent="✅ "+sym+" — "+name;var sug=document.getElementById("pf-sug2");if(sug)sug.style.display="none";var inp=document.getElementById("pf-s2");if(inp)inp.value=sym;}
function addToPF(){var sym=PF_SEL;var qty=parseFloat(document.getElementById("pf-q").value);var price2=parseFloat(document.getElementById("pf-p").value);if(!sym){alert("Önce hisse seç!");return;}if(isNaN(qty)||qty<=0){alert("Adet gir!");return;}if(isNaN(price2)||price2<=0){alert("Fiyat gir!");return;}PF.push({id:Date.now(),sym:sym,qty:qty,bp:price2});document.getElementById("pf-si").value="";document.getElementById("pf-lbl").textContent="— seçilmedi";document.getElementById("pf-q").value="";document.getElementById("pf-p").value="";PF_SEL="";savePF();renderPFItems();}
function addToPF2(){var sym=PF_SEL2;if(!sym){alert("Önce hisse seç!");return;}if(PF.find(function(p){return p.sym===sym;})){alert("Zaten portföyde!");return;}PF.push({id:Date.now(),sym:sym,qty:0,bp:0});savePF();renderPF2();}
function removePF2(){var sym=PF_SEL2;if(!sym){alert("Önce hisseyi seç!");return;}PF=PF.filter(function(p){return p.sym!==sym;});PF_SEL2="";savePF();renderPF2();}
function removePFById(id){PF=PF.filter(function(p){return p.id!==id;});savePF();renderPF2();}
function savePF(){try{localStorage.setItem("bist_pf_v5",JSON.stringify(PF));}catch(e){}}
function loadPF(){try{var j=localStorage.getItem("bist_pf_v5");if(j)PF=JSON.parse(j);}catch(e){}}
function renderPF2(){renderPFItems();var el=document.getElementById("pf-right");if(!el)return;if(!PF.length){el.innerHTML='<div style="padding:16px;font-size:11px;color:#2a3548;text-align:center;line-height:2;">Portföy boş.</div>';return;}var html="";PF.forEach(function(p){var rl=recLbl(REC[p.sym]);var chg=CHG[p.sym];var cs=chg!=null?(chg>=0?"+":"")+chg.toFixed(2)+"%":"—";var cc=chg!=null?(chg>0?"#22c55e":chg<0?"#ef4444":"#94a3b8"):"#2a3548";var nm="";for(var k=0;k<SL.length;k++)if(SL[k].s===p.sym){nm=SL[k].n;break;}html+='<div style="padding:10px;border-bottom:1px solid #0f1520;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;"><div style="display:flex;align-items:center;gap:6px;"><span onclick="pickSym(\''+p.sym+'\')" style="font-size:14px;font-weight:700;color:#e8b84b;cursor:pointer;">'+p.sym+'</span><span style="font-size:9px;font-weight:700;padding:1px 6px;background:'+rl.bg+';color:'+rl.c+';">'+rl.t+'</span><span style="font-size:11px;font-weight:700;color:'+cc+';">'+cs+'</span></div><button onclick="removePFById('+p.id+')" style="background:#300;border:none;color:#f44;cursor:pointer;border-radius:3px;padding:3px 10px;font-size:12px;font-family:inherit;">✕</button></div><div style="font-size:10px;color:#3d5878;">'+nm+(p.qty?'<span style="color:#4b5e78;"> · '+p.qty+' × ₺'+p.bp.toFixed(2)+'</span>':'')+'</div></div>';});el.innerHTML=html;}
function renderPFItems(){var el=document.getElementById("pf-items");if(!el)return;if(!PF.length){el.innerHTML='<div style="padding:10px;font-size:10px;color:#2a3548;text-align:center;">Portföy boş.</div>';return;}var html="";PF.forEach(function(p){var rl=recLbl(REC[p.sym]);html+='<div style="padding:7px 9px;border-bottom:1px solid #0f1520;display:flex;justify-content:space-between;align-items:center;"><div><div style="display:flex;align-items:center;gap:4px;margin-bottom:2px;"><span style="font-size:12px;font-weight:700;color:#e8b84b;">'+p.sym+'</span><span style="font-size:8px;padding:1px 5px;background:'+rl.bg+';color:'+rl.c+';">'+rl.t+'</span></div>'+(p.qty?'<div style="font-size:9px;color:#3d5878;">'+p.qty+' × ₺'+p.bp.toFixed(2)+'</div>':'')+'</div><button onclick="removePFById('+p.id+')" style="background:#300;border:none;color:#f44;cursor:pointer;border-radius:3px;padding:3px 8px;font-size:11px;font-family:inherit;">✕</button></div>';});el.innerHTML=html;}
function toggleBell(){var p=document.getElementById("bell-panel");if(p)p.style.display=(p.style.display==="none"?"block":"none");}
function renderBell(){var cnt=document.getElementById("bell-count"),list=document.getElementById("bell-list");if(cnt){if(BELLS.length){cnt.style.display="flex";cnt.textContent=BELLS.length>9?"9+":BELLS.length;}else cnt.style.display="none";}if(!list)return;if(!BELLS.length){list.innerHTML='<div style="padding:10px;font-size:10px;color:#2a3548;text-align:center;">Henüz sinyal yok.</div>';return;}list.innerHTML=BELLS.slice(0,20).map(function(b){return'<div style="padding:7px 8px;border-bottom:1px solid #0f1520;display:flex;gap:7px;align-items:center;"><span>'+(b.c==="red"?"🔴":"🟢")+'</span><div><div style="font-size:12px;font-weight:700;color:#fff;">'+b.sym+'</div><div style="font-size:9px;color:#94a3b8;">'+b.msg+'</div></div></div>';}).join("");}
function addBell(sym,msg,col){BELLS.unshift({sym:sym,msg:msg,c:col});if(BELLS.length>50)BELLS.pop();renderBell();}
function checkSTAlerts(){if(!PF.length)return;PF.forEach(function(p){var cur=REC[p.sym],prev=PREV_ST[p.sym];if(cur!=null&&prev!=null){if(prev>-0.5&&cur<=-0.5)addBell(p.sym,"G.SAT sinyali!","red");if(prev<0.5&&cur>=0.5)addBell(p.sym,"G.AL sinyali!","green");}PREV_ST[p.sym]=cur;});}
loadPF();buildWL("");renderFiyat();fetchRecs();
setInterval(fetchRecs,30000);setTimeout(function(){fetchRecsMonthly();setInterval(fetchRecsMonthly,60000);},3000);
</script>
</body>
</html>`;
