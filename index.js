const express = require('express');
const https = require('https');
const app = express();
const PORT = process.env.PORT || 3000;

app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', '*');
  if (req.method === 'OPTIONS') { res.sendStatus(200); return; }
  next();
});

// Yahoo Finance proxy - grafik verisi
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
    if (i >= urls.length) { res.status(500).json({error:'Yahoo ulaşılamadı'}); return; }
    https.get(urls[i], {headers}, (yr) => {
      if (yr.statusCode !== 200) { tryUrl(i+1); return; }
      let d = '';
      yr.on('data', c => d += c);
      yr.on('end', () => { res.setHeader('Content-Type','application/json'); res.end(d); });
    }).on('error', () => tryUrl(i+1));
  }
  tryUrl(0);
}

app.get('/api/:sym', (req, res) => yahoo(req.params.sym.toUpperCase(), req.query.tf||'1d', req.query.range||'1y', res));
app.get('/api/monthly/:sym', (req, res) => yahoo(req.params.sym.toUpperCase(), '1mo', '3y', res));
app.get('/health', (req, res) => res.json({ok:true}));
app.get('/', (req, res) => { res.setHeader('Content-Type','text/html;charset=utf-8'); res.send(HTML); });

app.listen(PORT, () => console.log('VORTEX OK:' + PORT));

const HTML = `<!DOCTYPE html>
<html lang="tr"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BIST · Vortex v4.4</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Courier New',monospace;background:#07090f;color:#8892a4;height:100dvh;display:flex;flex-direction:column;overflow:hidden;font-size:13px}
::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:#1a2030;border-radius:2px}
#top{background:#0b0e18;border-bottom:2px solid #131826;padding:0 10px;height:44px;display:flex;align-items:center;gap:8px;flex-shrink:0;overflow-x:auto}
#top::-webkit-scrollbar{height:0}
.logo{color:#e8b84b;font-weight:700;font-size:13px;letter-spacing:3px;flex-shrink:0}
.sep{width:1px;height:18px;background:#1a2030;flex-shrink:0}
#hsym{color:#fff;font-weight:700;font-size:15px;letter-spacing:2px}
#stbar{background:#050709;border-bottom:1px solid #131826;padding:3px 10px;font-size:10px;display:flex;align-items:center;gap:6px;flex-shrink:0}
#tabs{background:#0b0e18;border-bottom:1px solid #131826;display:flex;flex-shrink:0;overflow-x:auto}
#tabs::-webkit-scrollbar{height:0}
.tab{background:transparent;border:none;border-bottom:2px solid transparent;padding:9px 12px;cursor:pointer;font-size:11px;font-weight:700;color:#2a3548;font-family:inherit;white-space:nowrap}
.tab.on{color:#e8b84b;border-bottom-color:#e8b84b}
#body{display:flex;flex:1;overflow:hidden;min-height:0}
#wl{width:155px;background:#08090f;border-right:1px solid #131826;display:flex;flex-direction:column;flex-shrink:0}
#wls{width:100%;background:#0f1118;border:none;border-bottom:1px solid #131826;color:#fff;padding:8px 9px;font-size:11px;font-family:inherit;outline:none}
#wlc{padding:4px 10px;font-size:10px;color:#4b5e78;border-bottom:1px solid #131826;flex-shrink:0}
#wll{overflow-y:auto;flex:1}
#center{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.pnl{flex:1;display:flex;flex-direction:column;overflow:hidden;min-height:0}
.hid{display:none!important}
#vtop{background:#080d14;border-bottom:1px solid #131826;padding:4px 8px;display:flex;align-items:center;gap:5px;flex-shrink:0;overflow-x:auto}
#vtop::-webkit-scrollbar{height:0}
.vfb{font-size:11px;font-weight:700;padding:3px 8px;border:1px solid;white-space:nowrap;flex-shrink:0}
.vfl{font-size:8px;letter-spacing:1px;color:#4b5e78;white-space:nowrap;flex-shrink:0}
.vfv{font-size:11px;font-weight:700;white-space:nowrap;flex-shrink:0}
#inds{background:#050810;border-bottom:1px solid #131826;padding:3px 8px;display:flex;gap:7px;overflow-x:auto;flex-shrink:0;font-size:10px}
#inds::-webkit-scrollbar{height:0}
.ic{white-space:nowrap;flex-shrink:0}.icv{font-weight:700}
#tfbar{display:flex;gap:4px;padding:4px 8px;background:#060810;border-bottom:1px solid #131826;flex-shrink:0;align-items:center}
.tfb{background:#0b0e18;border:1px solid #1a2030;color:#4b5e78;padding:3px 9px;font-size:10px;font-family:inherit;cursor:pointer;font-weight:700}
.tfb.on{background:#1a2a1a;border-color:#22c55e;color:#22c55e}
#couter{flex:1;display:flex;flex-direction:column;position:relative;min-height:0;overflow:hidden}
#cvM{display:block;flex:1;min-height:0}
#cvR{display:block;height:60px;flex-shrink:0;border-top:1px solid #131826}
#cmsg{position:absolute;inset:0;background:rgba(7,9,15,.95);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;z-index:10;font-size:12px;color:#4b5e78}
#vbot{background:#080d14;border-top:1px solid #131826;padding:4px 8px;display:flex;gap:5px;overflow-x:auto;flex-shrink:0}
#vbot::-webkit-scrollbar{height:0}
.ve{background:#0b1020;border:1px solid #1a2030;padding:3px 7px;font-size:9px;white-space:nowrap;flex-shrink:0}
.ve .lv{font-size:11px;font-weight:700;display:block}
.bull{color:#22c55e}.bear{color:#ef4444}.neu{color:#e8b84b}.dim{color:#4b5e78}
</style></head><body>

<div id="top">
  <span class="logo">BIST</span><div class="sep"></div>
  <span id="hsym">—</span>
  <span id="clk" style="font-size:9px;color:#2a3548;margin-left:auto;flex-shrink:0;"></span>
</div>

<div id="stbar">
  <div id="dot" style="width:6px;height:6px;border-radius:50%;background:#e8b84b;flex-shrink:0"></div>
  <span id="smsg" style="color:#e8b84b;">Yükleniyor...</span>
  <button onclick="fetchRecs()" style="margin-left:auto;background:transparent;border:1px solid #1a2030;color:#4b5e78;padding:2px 8px;border-radius:3px;cursor:pointer;font-size:9px;font-family:inherit;">↺ Yenile</button>
</div>

<div id="tabs">
  <button class="tab" onclick="goTab('sinyal',this)">📊 VORTEX CHART</button>
  <button class="tab on" onclick="goTab('fiyat',this)">💹 CANLI FİYATLAR</button>
  <button class="tab" onclick="goTab('portfoy',this)">💼 PORTFÖY</button>
</div>

<div id="body">
<div id="wl">
  <input id="wls" placeholder="🔍 Ara..." oninput="buildWL(this.value)">
  <div id="wlc">—</div>
  <div id="wll"></div>
</div>

<div id="center">

<!-- CHART -->
<div id="tp-sinyal" class="pnl hid">
  <div id="vtop">
    <div class="vfb" id="vfbadge" style="color:#4b5e78;border-color:#1a2030;">VF: —</div>
    <div class="sep"></div>
    <span class="vfl">MOM</span><span class="vfv" id="vmom">—</span>
    <div class="sep"></div>
    <span class="vfl">TREND</span><span class="vfv" id="vtr">—</span>
    <div class="sep"></div>
    <span class="vfl">VOL</span><span class="vfv" id="vvol">—</span>
    <div class="sep"></div>
    <span class="vfl">HACİM</span><span class="vfv" id="vhac">—</span>
  </div>
  <div id="inds">
    <span class="ic dim">RSI:<span class="icv" id="irsi">—</span></span>
    <span class="ic dim">STOCH:<span class="icv" id="istoch">—</span></span>
    <span class="ic dim">MACD:<span class="icv" id="imacd">—</span></span>
    <span class="ic dim">BB:<span class="icv" id="ibb">—</span></span>
    <span class="ic dim">ATR:<span class="icv" id="iatr">—</span></span>
    <span class="ic dim">VWAP:<span class="icv" id="ivwap">—</span></span>
    <span class="ic dim">ST:<span class="icv" id="ist">—</span></span>
  </div>
  <div id="tfbar">
    <button class="tfb on" onclick="setTF('1d','1y',this)">1G</button>
    <button class="tfb" onclick="setTF('1wk','2y',this)">1H</button>
    <button class="tfb" onclick="setTF('1mo','5y',this)">1M</button>
    <span style="margin-left:auto;font-size:9px;color:#4b5e78;" id="vplbl">—</span>
  </div>
  <div id="couter">
    <div id="cmsg">
      <span style="font-size:28px;">📊</span>
      <span id="cmt">Sol listeden hisse seç</span>
      <span id="cms" style="font-size:9px;color:#2a3548;"></span>
    </div>
    <canvas id="cvM"></canvas>
    <canvas id="cvR"></canvas>
  </div>
  <div id="vbot">
    <div class="ve"><span style="color:#4b5e78;font-size:8px;">FİYAT</span><span class="lv" style="color:#00d4ff" id="vee">—</span></div>
    <div class="ve"><span style="color:#4b5e78;font-size:8px;">STOP</span><span class="lv bear" id="ves">—</span></div>
    <div class="ve"><span style="color:#4b5e78;font-size:8px;">H1</span><span class="lv neu" id="veh1">—</span></div>
    <div class="ve"><span style="color:#4b5e78;font-size:8px;">H2</span><span class="lv bull" id="veh2">—</span></div>
    <div class="ve"><span style="color:#4b5e78;font-size:8px;">H3</span><span class="lv bull" id="veh3">—</span></div>
    <div class="ve"><span style="color:#4b5e78;font-size:8px;">R/R</span><span class="lv" id="verr">—</span></div>
  </div>
</div>

<!-- FİYATLAR -->
<div id="tp-fiyat" class="pnl">
  <div style="background:#0b1510;border-bottom:1px solid #1a3a1a;padding:5px 10px;font-size:10px;color:#22c55e;flex-shrink:0;display:flex;align-items:center;">
    <span>💹 <strong style="color:#fff">Canlı Fiyatlar</strong></span>
    <button onclick="SD=!SD;renderF()" style="margin-left:auto;background:#1a2030;border:1px solid #2a3548;color:#e8b84b;padding:2px 8px;border-radius:3px;cursor:pointer;font-size:9px;font-family:inherit;">↕ Sırala</button>
  </div>
  <div style="display:grid;grid-template-columns:66px 1fr 70px;padding:6px 8px;background:#0b0e18;border-bottom:2px solid #1a2540;font-size:10px;color:#5b7a9a;font-weight:700;flex-shrink:0;">
    <span>SEMBOL</span><span style="text-align:center">TEK. DERECE</span><span style="text-align:right">GÜN%</span>
  </div>
  <div id="ftable" style="flex:1;overflow-y:auto;"></div>
  <div id="fst" style="padding:4px 10px;font-size:9px;color:#2a3548;flex-shrink:0;border-top:1px solid #131826;background:#0b0e18;">Bekleniyor...</div>
</div>

<!-- PORTFÖY -->
<div id="tp-portfoy" class="pnl hid">
  <div style="background:#0b1020;border-bottom:1px solid #1e3050;padding:8px 12px;font-size:11px;font-weight:700;color:#e8b84b;flex-shrink:0;">💼 PORTFÖY</div>
  <div style="padding:8px 10px;border-bottom:1px solid #131826;flex-shrink:0;">
    <input id="pfsi" placeholder="🔍 Hisse ara..." oninput="spf(this.value)" style="width:100%;background:#060a10;border:1px solid #1e3050;color:#fff;padding:8px 10px;border-radius:5px;font-size:12px;font-family:inherit;outline:none;margin-bottom:6px;">
    <div id="pfsug" style="background:#0b1424;border:1px solid #1e3050;border-top:none;display:none;max-height:130px;overflow-y:auto;border-radius:0 0 5px 5px;margin-bottom:6px;"></div>
    <div id="pflbl" style="font-size:12px;font-weight:700;color:#e8b84b;margin-bottom:6px;min-height:18px;">— seçilmedi</div>
    <div style="display:flex;gap:8px;">
      <button onclick="pfAdd()" style="flex:1;background:#22c55e;color:#000;border:none;padding:9px;border-radius:5px;cursor:pointer;font-size:12px;font-weight:700;font-family:inherit;">+ EKLE</button>
      <button onclick="pfRem()" style="flex:1;background:#300;color:#f44;border:none;padding:9px;border-radius:5px;cursor:pointer;font-size:12px;font-weight:700;font-family:inherit;">− ÇIKAR</button>
    </div>
  </div>
  <div id="pflist" style="flex:1;overflow-y:auto;"></div>
</div>

</div></div>

<script>
var SL=[
{s:"THYAO",n:"THY"},{s:"AKBNK",n:"Akbank"},{s:"GARAN",n:"Garanti"},{s:"EREGL",n:"Ereğli"},
{s:"ASELS",n:"Aselsan"},{s:"KCHOL",n:"Koç Holding"},{s:"ISCTR",n:"İş Bankası"},{s:"VAKBN",n:"Vakıfbank"},
{s:"HALKB",n:"Halk Bank"},{s:"YKBNK",n:"Yapı Kredi"},{s:"FROTO",n:"Ford Otosan"},{s:"TOASO",n:"Tofaş"},
{s:"BIMAS",n:"BİM"},{s:"MGROS",n:"Migros"},{s:"ARCLK",n:"Arçelik"},{s:"TUPRS",n:"Tüpraş"},
{s:"PETKM",n:"Petkim"},{s:"SASA",n:"Sasa"},{s:"EKGYO",n:"Emlak GYO"},{s:"TTKOM",n:"T.Telekom"},
{s:"TCELL",n:"Turkcell"},{s:"PGSUS",n:"Pegasus"},{s:"TAVHL",n:"TAV"},{s:"ENKAI",n:"Enka"},
{s:"KOZAL",n:"Koza Altın"},{s:"KOZAA",n:"Koza Anadolu"},{s:"AEFES",n:"Anadolu Efes"},
{s:"CCOLA",n:"Coca-Cola"},{s:"ULKER",n:"Ülker"},{s:"LOGO",n:"Logo"},
{s:"MAVI",n:"Mavi"},{s:"OTKAR",n:"Otokar"},{s:"TTRAK",n:"T.Traktör"},
{s:"GUBRF",n:"Gübre Fab."},{s:"AKCNS",n:"Akçansa"},{s:"CIMSA",n:"Çimsa"},
{s:"NUHCM",n:"Nuh Çimento"},{s:"BRISA",n:"Brisa"},{s:"KORDS",n:"Kordsa"},
{s:"AYGAZ",n:"Aygaz"},{s:"DOHOL",n:"Doğan H."},{s:"DOAS",n:"Doğuş Oto"},
{s:"SKBNK",n:"Şekerbank"},{s:"ALBRK",n:"Albaraka"},{s:"QNBFB",n:"QNB Finans"},
{s:"TSKB",n:"TSKB"},{s:"ENJSA",n:"Enerjisa"},{s:"AKSEN",n:"Aksa Enerji"},
{s:"AKENR",n:"Ak Enerji"},{s:"GWIND",n:"Galata Wind"},{s:"ODAS",n:"Odaş"},
{s:"ZOREN",n:"Zorlu Enerji"},{s:"ASTOR",n:"Astor Enerji"},{s:"MPARK",n:"MLP Sağlık"},
{s:"TKFEN",n:"Tekfen"},{s:"ALKIM",n:"Alkim"},{s:"SISE",n:"Şişecam"},
{s:"ANACM",n:"Anadolu Cam"},{s:"A1CAP",n:"A1 Capital"},{s:"AKGRT",n:"Aksigorta"},
{s:"AKSA",n:"Aksa Akrilik"},{s:"ALARK",n:"Alarko"},{s:"ANSGR",n:"Anadolu Sig."},
{s:"ARENA",n:"Arena BT"},{s:"ASUZU",n:"Anadolu Isuzu"},{s:"BANVT",n:"Banvit"},
{s:"BERA",n:"Bera H."},{s:"BFREN",n:"Bosch Fren"},{s:"BIZIM",n:"Bizim Top."},
{s:"BJKAS",n:"Beşiktaş"},{s:"BRSAN",n:"Borusan Çelik"},{s:"BTCIM",n:"Batıçimento"},
{s:"BUCIM",n:"Bursa Çim."},{s:"CRFSA",n:"CarrefourSA"},{s:"DARDL",n:"Dardanel"},
{s:"DEVA",n:"Deva H."},{s:"ECILC",n:"Eczacıbaşı İl."},{s:"ERCB",n:"Erçiyas Çim."},
{s:"EUPWR",n:"Europower"},{s:"FENER",n:"Fenerbahçe"},{s:"GARFA",n:"Garanti Fakt."},
{s:"GESAN",n:"Gersan El."},{s:"GSDHO",n:"GSD Holding"},{s:"GSRAY",n:"Galatasaray"},
{s:"HEKTS",n:"Hektaş"},{s:"HLGYO",n:"Halk GYO"},{s:"HOROZ",n:"Horoz Loj."},
{s:"IHLAS",n:"İhlas H."},{s:"INDES",n:"İndeks BT"},{s:"ISATR",n:"İş Portföy"},
{s:"ISGYO",n:"İş GYO"},{s:"IZMDC",n:"İzmit Demir"},{s:"KARSN",n:"Karsan"},
{s:"KARTN",n:"Kartonsan"},{s:"KONTR",n:"Kontrolmatik"},{s:"KONYA",n:"Konya Çim."},
{s:"KRDMD",n:"Kardemir D"},{s:"MUTLU",n:"Mutlu Akü"},{s:"OYAKC",n:"Oyak Çim."},
{s:"PAPIL",n:"Papilon"},{s:"POLHO",n:"Polisan H."},{s:"PRKAB",n:"T.Prysmian"},
{s:"RAYSG",n:"Ray Sigorta"},{s:"RNSHO",n:"Rönesans H."},{s:"RYSAS",n:"Reysaş"},
{s:"SELEC",n:"Selçuk Ecza"},{s:"SNGYO",n:"Sinpaş GYO"},{s:"TRGYO",n:"Torunlar GYO"},
{s:"TURSG",n:"T.Sigorta"},{s:"VESTL",n:"Vestel"},{s:"VKGYO",n:"Vakıf GYO"},
{s:"YYLGD",n:"Yayla Agro"},{s:"BAGFS",n:"Bagfaş"},{s:"AGHOL",n:"AG Anadolu"},
{s:"AHGAZ",n:"Ahlatcı Gaz"},{s:"DEVA",n:"Deva"},{s:"KMPUR",n:"Kimpur"}
];
// dedupe
var _m={};SL=SL.filter(function(x){if(_m[x.s])return false;_m[x.s]=1;return true;});

var CUR="THYAO",TF="1d",TFR="1y",LTAB="fiyat";
var REC={},CHG={},STM={},PF=[],PFS="",API=[],SD=true,BARS=null,MDIR={};

setInterval(function(){var e=document.getElementById("clk");if(e)e.textContent=new Date().toLocaleTimeString("tr-TR");},1000);
function G(id){return document.getElementById(id);}

function setSt(ok,msg){
  var d=G("dot"),m=G("smsg");
  if(d)d.style.background=ok===true?"#22c55e":ok===false?"#ef4444":"#e8b84b";
  if(m){m.textContent=msg;m.style.color=ok===true?"#22c55e":ok===false?"#ef4444":"#e8b84b";}
}
function RL(v){
  if(v==null)return{t:"—",bg:"#1e293b",c:"#475569"};
  if(v<=-0.5)return{t:"G.SAT",bg:"#450a0a",c:"#ef4444"};
  if(v<-0.1)return{t:"SAT",bg:"#3b1010",c:"#fca5a5"};
  if(v<=0.1)return{t:"NÖTR",bg:"#1e293b",c:"#94a3b8"};
  if(v<0.5)return{t:"AL",bg:"#052e16",c:"#86efac"};
  return{t:"G.AL",bg:"#14532d",c:"#22c55e"};
}
function showP(id){
  ["tp-sinyal","tp-fiyat","tp-portfoy"].forEach(function(p){var e=G(p);if(e){e.classList.remove("pnl");e.classList.add("hid");}});
  var e=G(id);if(e){e.classList.remove("hid");e.classList.add("pnl");}
}
function buildWL(q){
  q=(q||"").toUpperCase().trim();
  var f=SL.filter(function(s){return!q||s.s.includes(q)||s.n.toUpperCase().includes(q);});
  var wlc=G("wlc");if(wlc)wlc.textContent=f.length+" hisse";
  var h="";
  f.forEach(function(s){
    var r=RL(REC[s.s]);var chg=CHG[s.s];
    var cs=chg!=null?(chg>=0?"+":"")+chg.toFixed(1)+"%":"";
    var cc=chg!=null?(chg>0?"#22c55e":chg<0?"#ef4444":"#4b5e78"):"#4b5e78";
    var ic=s.s===CUR;
    h+='<div onclick="pick(\''+s.s+'\')" style="padding:8px 9px;border-bottom:1px solid #0d1018;cursor:pointer;background:'+(ic?"#0f1a2a":"transparent")+';display:flex;align-items:center;gap:4px;">'
     +'<div style="flex:1;min-width:0;"><div style="font-size:14px;font-weight:700;color:'+(ic?"#e8b84b":"#fff")+';">'+s.s+'</div>'
     +'<div style="font-size:11px;color:#7a9ab8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'+s.n+'</div></div>'
     +'<div style="text-align:right;flex-shrink:0;">'
     +'<div style="font-size:9px;font-weight:700;background:'+r.bg+';color:'+r.c+';padding:1px 4px;">'+r.t+'</div>'
     +(cs?'<div style="font-size:9px;color:'+cc+';">'+cs+'</div>':"")
     +'</div></div>';
  });
  var wll=G("wll");if(wll)wll.innerHTML=h;
}
function goTab(id,btn){
  document.querySelectorAll(".tab").forEach(function(b){b.classList.remove("on");});
  if(btn)btn.classList.add("on");
  showP("tp-"+id);LTAB=id;
  if(id==="sinyal")loadChart();
  else if(id==="fiyat")renderF();
  else if(id==="portfoy")renderPF();
}
function pick(s){
  CUR=s;var h=G("hsym");if(h)h.textContent=s;
  buildWL(G("wls").value||"");
  showP("tp-sinyal");
  document.querySelectorAll(".tab").forEach(function(b){b.classList.remove("on");});
  document.querySelector("button[onclick*='sinyal']").classList.add("on");
  LTAB="sinyal";loadChart();
}
function setTF(tf,r,btn){
  TF=tf;TFR=r;
  document.querySelectorAll(".tfb").forEach(function(b){b.classList.remove("on");});
  if(btn)btn.classList.add("on");loadChart();
}

// ─── INDICATORS ──────────────────────────────────────────────────────────────
function ema(d,p){var k=2/(p+1),r=[],s=0,c=0;for(var i=0;i<d.length;i++){if(d[i]==null||isNaN(d[i])){r.push(null);continue;}if(c<p){s+=d[i];c++;r.push(c===p?s/p:null);}else{var pv=r.filter(function(v){return v!=null;}).pop()||d[i];r.push(pv*(1-k)+d[i]*k);}}return r;}
function dema(d,p){var e1=ema(d,p),e2=ema(e1.filter(function(v){return v!=null;}),p),res=new Array(d.length).fill(null),j=0;for(var i=p*2-2;i<d.length;i++){if(e1[i]!=null&&j<e2.length&&e2[j]!=null)res[i]=2*e1[i]-e2[j];j++;}return res;}
function calcRSI(c,p){p=p||14;var r=[],g=0,l=0;for(var i=1;i<c.length;i++){var d=c[i]-c[i-1];if(i<=p){g+=Math.max(d,0);l+=Math.max(-d,0);if(i===p)r.push(l===0?100:100-100/(1+g/l));else r.push(null);}else{g=(g*(p-1)+Math.max(d,0))/p;l=(l*(p-1)+Math.max(-d,0))/p;r.push(l===0?100:100-100/(1+g/l));}}return r;}
function calcMACD(c){var e12=ema(c,12),e26=ema(c,26),ml=c.map(function(_,i){return e12[i]!=null&&e26[i]!=null?e12[i]-e26[i]:null;}),sig=ema(ml.filter(function(v){return v!=null;}),9),h=[],si=0;for(var i=0;i<ml.length;i++){if(ml[i]==null)h.push(null);else{h.push(sig[si]!=null?ml[i]-sig[si]:null);si++;}}return{ml:ml,h:h};}
function calcBB(c,p,m){p=p||20;m=m||2;var u=[],l=[],md=[];for(var i=0;i<c.length;i++){if(i<p-1){u.push(null);l.push(null);md.push(null);continue;}var s=c.slice(i-p+1,i+1),mn=s.reduce(function(a,b){return a+b;})/p,sd=Math.sqrt(s.reduce(function(a,b){return a+(b-mn)*(b-mn);},0)/p);u.push(mn+m*sd);l.push(mn-m*sd);md.push(mn);}return{u:u,l:l,m:md};}
function calcStoch(H,L,C,k){k=k||14;var r=[];for(var i=0;i<C.length;i++){if(i<k-1){r.push(null);continue;}var hh=Math.max.apply(null,H.slice(i-k+1,i+1)),ll=Math.min.apply(null,L.slice(i-k+1,i+1));r.push(hh===ll?50:((C[i]-ll)/(hh-ll))*100);}return r;}
function calcATR(H,L,C,p){p=p||14;var tr=[],at=[];for(var i=0;i<C.length;i++){if(i===0){tr.push(H[i]-L[i]);at.push(null);continue;}tr.push(Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1])));if(i<p)at.push(null);else if(i===p)at.push(tr.slice(0,p+1).reduce(function(a,b){return a+b;})/p);else at.push((at[i-1]*(p-1)+tr[i])/p);}return at;}
function calcST(H,L,C,p,m){p=p||10;m=m||3;var a=calcATR(H,L,C,p),dr=[],ps=null,pd=1;for(var i=0;i<C.length;i++){if(a[i]==null){dr.push(null);continue;}var hl=(H[i]+L[i])/2,up=hl+m*a[i],dn=hl-m*a[i],cs,cd;if(ps==null){cs=up;cd=1;}else if(pd===1){cs=C[i]>ps?Math.max(dn,ps):up;cd=C[i]>cs?1:-1;}else{cs=C[i]<ps?Math.min(up,ps):dn;cd=C[i]>cs?1:-1;}dr.push(cd);ps=cs;pd=cd;}return dr;}
function calcOBV(C,V){var o=[V[0]||0];for(var i=1;i<C.length;i++)o.push(C[i]>C[i-1]?o[i-1]+(V[i]||0):C[i]<C[i-1]?o[i-1]-(V[i]||0):o[i-1]);return o;}
function LV(a){for(var i=a.length-1;i>=0;i--)if(a[i]!=null)return a[i];return null;}

// ─── VORTEX SCORE v4.4 ───────────────────────────────────────────────────────
function vScore(I){
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
  if(I.stdir===1)tr+=15;else tr-=10;
  tr=Math.max(0,Math.min(100,tr));
  var vol=40;
  if(I.price<I.bbl)vol+=30;else if(I.price>I.bbu)vol-=20;
  if(I.squeeze)vol+=20;
  if(I.z<-2)vol+=20;else if(I.z>2)vol-=20;
  vol=Math.max(0,Math.min(100,vol));
  var hac=40;
  if(I.volr>1.5)hac+=30;else if(I.volr>1.2)hac+=15;else if(I.volr<0.7)hac-=15;
  if(I.price>I.vwap)hac+=15;else hac-=10;
  if(I.obvUp)hac+=10;
  if(I.fib==="g")hac+=15;else if(I.fib==="m")hac+=8;
  hac=Math.max(0,Math.min(100,hac));
  var w1=0.30,w2=0.30,w3=0.20,w4=0.20;
  var an=I.atr?I.atr/I.price*100:2;
  if(an>3){w1=0.35;w2=0.25;}else if(an<1.5){w1=0.25;w2=0.35;}
  return{mom:mom,tr:tr,vol:vol,hac:hac,f:Math.max(0,Math.min(100,Math.round(mom*w1+tr*w2+vol*w3+hac*w4)))};
}

// ─── CANVAS CHART ────────────────────────────────────────────────────────────
function drawChart(bars,mdir){
  var co=G("couter"),cm=G("cvM"),cr=G("cvR");
  if(!co||!cm||!cr)return;
  var TW=co.clientWidth||320,TH=co.clientHeight-60||200;
  if(TH<80)TH=80;
  var RH=60,dpr=window.devicePixelRatio||1;
  cm.width=TW*dpr;cm.height=TH*dpr;cm.style.width=TW+"px";cm.style.height=TH+"px";
  cr.width=TW*dpr;cr.height=RH*dpr;cr.style.width=TW+"px";cr.style.height=RH+"px";
  var mc=cm.getContext("2d");mc.scale(dpr,dpr);
  var rc=cr.getContext("2d");rc.scale(dpr,dpr);
  var W=TW,H=TH,n=bars.length;if(n<3)return;
  var C=bars.map(function(d){return d.c;}),HH=bars.map(function(d){return d.h;}),LL=bars.map(function(d){return d.l;}),OO=bars.map(function(d){return d.o;}),VV=bars.map(function(d){return d.v;});
  var rA=calcRSI(C,14),mR=calcMACD(C),bR=calcBB(C,20,2),sA=calcStoch(HH,LL,C,14),aA=calcATR(HH,LL,C,14),sD=calcST(HH,LL,C,10,3);
  var de25=dema(C,25),e8a=ema(C,8),e21a=ema(C,21),e50a=ema(C,50),oA=calcOBV(C,VV);
  var vA=[];for(var i=0;i<n;i++){var sl=bars.slice(Math.max(0,i-19),i+1);var tv=sl.reduce(function(a,d){return a+((d.h+d.l+d.c)/3*d.v);},0);var sv=sl.reduce(function(a,d){return a+d.v;},0);vA.push(sv?tv/sv:C[i]);}
  var lRSI=LV(rA)||50,lM=LV(mR.h)||0,lMp=mR.h.filter(function(v){return v!=null;}).slice(-2)[0]||lM;
  var lBU=LV(bR.u)||0,lBL=LV(bR.l)||0,lBM=LV(bR.m)||0;
  var lSt=LV(sA)||50,lA=LV(aA)||0,lSD=LV(sD)||1;
  var lOBV=oA[n-1],pOBV=oA[Math.max(0,n-6)];
  var lDE=LV(de25)||0,lE8=LV(e8a)||0,lE21=LV(e21a)||0,lE50=LV(e50a)||0,lVW=vA[n-1],price=C[n-1];
  var avgV=VV.slice(-20).reduce(function(a,b){return a+b;})/20,volR=avgV?VV[n-1]/avgV:1;
  var sl20=C.slice(-20),sm=sl20.reduce(function(a,b){return a+b;})/sl20.length;
  var ss=Math.sqrt(sl20.reduce(function(a,b){return a+(b-sm)*(b-sm);},0)/sl20.length)||1;
  var z=(price-sm)/ss;
  var bW=lBM?((lBU-lBL)/lBM*100):0,bWp=bR.m[n-6]?((bR.u[n-6]-bR.l[n-6])/bR.m[n-6]*100):bW;
  var rc2=C.slice(-10),rr2=rA.filter(function(v){return v!=null;}).slice(-10);
  var div="none";if(rc2.length>=5&&rr2.length>=5){var pt=rc2[rc2.length-1]-rc2[0],rt=rr2[rr2.length-1]-rr2[0];if(pt<0&&rt>2)div="bull";else if(pt>0&&rt<-2)div="bear";}
  var swH=Math.max.apply(null,HH.slice(-60)),swL=Math.min.apply(null,LL.slice(-60));
  var retr=(swH-swL)?(swH-price)/(swH-swL):0;
  var fib=retr>=0.6&&retr<=0.79?"g":retr>=0.35&&retr<0.6?"m":"x";
  var I={rsi:lRSI,stoch:lSt,macd:lM,macdP:lMp,div:div,mst:mdir||1,dema:lDE,e8:lE8,e21:lE21,e50:lE50,stdir:lSD,price:price,bbu:lBU,bbl:lBL,bbm:lBM,squeeze:bW<bWp*0.9,z:z,volr:volR,vwap:lVW,obvUp:lOBV>pOBV,fib:fib,atr:lA};
  var SC=vScore(I);
  var bc=SC.f>=75?"#22c55e":SC.f>=60?"#00d4ff":SC.f>=40?"#e8b84b":"#ef4444";
  var bt=SC.f>=75?"GÜÇLÜ AL ▲":SC.f>=60?"İZLE ◆":SC.f>=40?"BEKLE ■":"UZAK DUR ▼";
  var bg=G("vfbadge");if(bg){bg.style.color=bc;bg.style.borderColor=bc;bg.textContent="VF:"+SC.f+" "+bt;}
  function sv(id,v,cls){var e=G(id);if(e){e.textContent=v;e.className="vfv "+(cls||"");}}
  sv("vmom",SC.mom,SC.mom>=60?"bull":SC.mom<40?"bear":"neu");
  sv("vtr",SC.tr,SC.tr>=60?"bull":SC.tr<40?"bear":"neu");
  sv("vvol",SC.vol,SC.vol>=60?"bull":SC.vol<40?"bear":"neu");
  sv("vhac",SC.hac,SC.hac>=60?"bull":SC.hac<40?"bear":"neu");
  function sc(id,v,cls){var e=G(id);if(e){e.textContent=v;e.parentElement.className="ic "+(cls||"dim");}}
  sc("irsi",lRSI.toFixed(1),lRSI<35?"bull":lRSI>70?"bear":"neu");
  sc("istoch",lSt.toFixed(1),lSt<20?"bull":lSt>80?"bear":"neu");
  sc("imacd",(lM>0?"▲":"▼")+Math.abs(lM).toFixed(3),lM>0&&lM>lMp?"bull":lM<0?"bear":"neu");
  sc("ibb",price<lBL?"ALT":price>lBU?"ÜST":bW<bWp*0.9?"SIKIŞ":"ORTA",price<lBL?"bull":price>lBU?"bear":"neu");
  sc("iatr",(lA/price*100).toFixed(1)+"%","neu");
  sc("ivwap",price>lVW?"Üst":"Alt",price>lVW?"bull":"bear");
  sc("ist",lSD===1?"YEŞİL":"KIRMIZI",lSD===1?"bull":"bear");
  var prev=bars[n-2]?bars[n-2].c:price,chg=price-prev,pl=G("vplbl");
  if(pl){pl.textContent="₺"+price.toFixed(2)+" "+(chg>=0?"+":"")+((chg/prev)*100).toFixed(2)+"%";pl.style.color=chg>=0?"#22c55e":"#ef4444";}
  var aa=lA||price*0.02,stop2=price-aa*2,t1=price+aa*1.5,t2=price+aa*3,t3=price+aa*5.18;
  var rr=((t2-price)/(price-stop2)).toFixed(1);
  function se(id,v,c){var e=G(id);if(e){e.textContent=v;if(c)e.style.color=c;}}
  se("vee","₺"+price.toFixed(2),"#00d4ff");se("ves","₺"+stop2.toFixed(2),"#ef4444");
  se("veh1","₺"+t1.toFixed(2),"#e8b84b");se("veh2","₺"+t2.toFixed(2),"#22c55e");
  se("veh3","₺"+t3.toFixed(2),"#22c55e");se("verr","1:"+rr,rr>=2?"#22c55e":"#ef4444");
  // ── CANVAS ──
  var allP=[];bars.forEach(function(d){allP.push(d.h,d.l);});bR.u.forEach(function(v){if(v)allP.push(v);});bR.l.forEach(function(v){if(v)allP.push(v);});
  var pMi=Math.min.apply(null,allP.filter(function(v){return v>0;})),pMa=Math.max.apply(null,allP),pR=pMa-pMi||1;
  pMi-=pR*0.03;pMa+=pR*0.18;
  var VH=20,pd={l:2,r:52,t:6,b:18};
  function px(i){return pd.l+(i/(n-1||1))*(W-pd.l-pd.r);}
  function py(v){return pd.t+(1-(v-pMi)/(pMa-pMi))*(H-pd.t-pd.b-VH);}
  mc.fillStyle="#07090f";mc.fillRect(0,0,W,H);
  mc.strokeStyle="#0d1018";mc.lineWidth=0.5;
  for(var gi=0;gi<5;gi++){var gv=pMi+(pMa-pMi)*gi/4,gy=py(gv);mc.beginPath();mc.moveTo(pd.l,gy);mc.lineTo(W-pd.r,gy);mc.stroke();mc.fillStyle="#2a3548";mc.font="9px monospace";mc.textAlign="right";mc.fillText(gv.toFixed(gv>100?0:gv>10?1:2),W-2,gy+3);}
  // ST tint
  var ss2=0,sd2=null;for(var i=0;i<=n;i++){var dd=sD[i]||null;if(dd!==sd2||i===n){if(sd2!=null&&i>ss2){mc.fillStyle=sd2===1?"rgba(34,197,94,.05)":"rgba(239,68,68,.05)";mc.fillRect(px(ss2),pd.t,px(Math.min(i,n-1))-px(ss2),H-pd.t-pd.b-VH);}sd2=dd;ss2=i;}}
  // BB fill
  mc.fillStyle="rgba(0,212,255,.04)";mc.beginPath();var fs=true;
  for(var i=0;i<n;i++){if(bR.u[i]==null)continue;if(fs){mc.moveTo(px(i),py(bR.u[i]));fs=false;}else mc.lineTo(px(i),py(bR.u[i]));}
  for(var i=n-1;i>=0;i--){if(bR.l[i]==null)continue;mc.lineTo(px(i),py(bR.l[i]));}
  mc.closePath();mc.fill();
  function dl(vals,col,al,dash){mc.save();mc.strokeStyle=col;mc.globalAlpha=al||1;mc.lineWidth=1.5;mc.setLineDash(dash||[]);mc.beginPath();var f2=true;for(var i=0;i<n;i++){if(vals[i]==null)continue;var x=px(i),y=py(vals[i]);f2?mc.moveTo(x,y):mc.lineTo(x,y);f2=false;}mc.stroke();mc.restore();}
  dl(bR.u,"rgba(0,212,255,.5)",1,[3,3]);dl(bR.l,"rgba(0,212,255,.5)",1,[3,3]);
  dl(vA,"rgba(180,127,255,.8)",1,[2,2]);dl(e50a,"rgba(180,127,255,.5)",1,[4,2]);dl(de25,"#e8b84b",.9,[]);
  dl(C.map(function(c,i){return aA[i]!=null?c-aA[i]*2:null;}),"rgba(239,68,68,.6)",1,[3,2]);
  function hl(p2,col,lbl){if(p2<pMi||p2>pMa)return;var y2=py(p2);mc.save();mc.strokeStyle=col;mc.lineWidth=1;mc.setLineDash([4,3]);mc.globalAlpha=.7;mc.beginPath();mc.moveTo(pd.l,y2);mc.lineTo(W-pd.r,y2);mc.stroke();mc.setLineDash([]);mc.fillStyle=col;mc.font="bold 9px monospace";mc.textAlign="right";mc.fillText(lbl,W-2,y2-2);mc.restore();}
  hl(stop2,"#ef4444","STOP");hl(t2,"#22c55e","H2");
  var cw=Math.max(1,(W-pd.l-pd.r)/n*.72);
  for(var i=0;i<n;i++){var x=px(i),up=C[i]>=OO[i],col=up?"#22c55e":"#ef4444";mc.strokeStyle=col;mc.lineWidth=1;mc.beginPath();mc.moveTo(x,py(HH[i]));mc.lineTo(x,py(LL[i]));mc.stroke();mc.fillStyle=col;var bt2=py(Math.max(C[i],OO[i])),bb2=py(Math.min(C[i],OO[i]));mc.fillRect(x-cw/2,bt2,cw,Math.max(1,bb2-bt2));}
  for(var i=1;i<n;i++){if(sD[i]!=null&&sD[i-1]!=null&&sD[i]!==sD[i-1]){var ax=px(i),col2=sD[i]===1?"#22c55e":"#ef4444",ay=sD[i]===1?py(LL[i])+12:py(HH[i])-12;mc.fillStyle=col2;mc.font="10px monospace";mc.textAlign="center";mc.fillText(sD[i]===1?"▲":"▼",ax,ay);}}
  var mxV=Math.max.apply(null,VV.filter(function(v){return v>0;}));
  for(var i=0;i<n;i++){var x=px(i),vh=(VV[i]/(mxV||1))*VH*.9;mc.fillStyle=C[i]>=OO[i]?"rgba(34,197,94,.4)":"rgba(239,68,68,.4)";mc.fillRect(x-cw/2,H-pd.b-vh,cw,vh);}
  mc.fillStyle="#2a3548";mc.font="8px monospace";mc.textAlign="center";
  var step=Math.max(1,Math.floor(n/5));
  for(var i=0;i<n;i+=step){if(bars[i].t){var dt=new Date(bars[i].t*1000);mc.fillText(dt.getDate()+"."+(dt.getMonth()+1),px(i),H-pd.b+10);}}
  rc.fillStyle="#050810";rc.fillRect(0,0,W,RH);
  function ry(v){return(1-(v/100))*(RH-14)+4;}
  rc.strokeStyle="#0d1018";rc.lineWidth=.5;
  [30,50,70].forEach(function(lv){var y2=ry(lv);rc.beginPath();rc.moveTo(0,y2);rc.lineTo(W-40,y2);rc.stroke();rc.fillStyle=lv===30?"#22c55e":lv===70?"#ef4444":"#2a3548";rc.font="8px monospace";rc.textAlign="left";rc.fillText(lv,W-38,y2+3);});
  rc.strokeStyle="#00d4ff";rc.lineWidth=1.5;rc.setLineDash([]);rc.beginPath();var fr=true;
  for(var i=0;i<n;i++){if(rA[i]==null)continue;var x=(i/(n-1||1))*(W-40),y2=ry(rA[i]);fr?rc.moveTo(x,y2):rc.lineTo(x,y2);fr=false;}rc.stroke();
  rc.fillStyle=lRSI<35?"#22c55e":lRSI>70?"#ef4444":"#00d4ff";rc.font="bold 9px monospace";rc.textAlign="right";rc.fillText("RSI "+lRSI.toFixed(1),W-2,12);
}

// ─── CHART VERİSİ — Railway sunucu proxy üzerinden ───────────────────────────
function loadChart(){
  var sym=CUR,msg=G("cmsg"),ct=G("cmt"),cs=G("cms");
  if(msg)msg.style.display="flex";
  if(ct)ct.textContent="⏳ "+sym+" grafik yükleniyor...";
  if(cs)cs.textContent="Yahoo Finance → Railway proxy";
  fetch("/api/monthly/"+sym)
    .then(function(r){return r.json();})
    .then(function(data){
      var ch=data&&data.chart;
      if(ch&&ch.result&&ch.result[0]){
        var res=ch.result[0],q=res.indicators.quote[0],mv=[];
        for(var i=0;i<res.timestamp.length;i++)
          if(q.close[i]!=null&&q.high[i]!=null&&q.low[i]!=null)
            mv.push({h:q.high[i],l:q.low[i],c:q.close[i]});
        if(mv.length>=10){
          var mST=calcST(mv.map(function(d){return d.h;}),mv.map(function(d){return d.l;}),mv.map(function(d){return d.c;}),10,3);
          MDIR[sym]=LV(mST)||1;
        }
      }
    })
    .catch(function(){})
    .finally(function(){
      fetch("/api/"+sym+"?tf="+TF+"&range="+TFR)
        .then(function(r){return r.json();})
        .then(function(data){
          var ch=data&&data.chart;
          if(!ch||!ch.result||!ch.result[0]){
            if(msg){msg.style.display="flex";if(ct)ct.textContent="⚠ Veri alınamadı: "+sym;}return;
          }
          var res=ch.result[0],q=res.indicators.quote[0],v=[];
          for(var i=0;i<res.timestamp.length;i++)
            if(q.close[i]!=null&&q.high[i]!=null&&q.low[i]!=null&&q.open[i]!=null)
              v.push({t:res.timestamp[i],o:q.open[i],h:q.high[i],l:q.low[i],c:q.close[i],v:q.volume[i]||0});
          if(v.length<5){if(msg){msg.style.display="flex";if(ct)ct.textContent="⚠ Yetersiz veri";}return;}
          if(msg)msg.style.display="none";
          BARS=v;drawChart(v,MDIR[sym]||1);
          window.onresize=function(){if(BARS)drawChart(BARS,MDIR[CUR]||1);};
        })
        .catch(function(e){if(msg){msg.style.display="flex";if(ct)ct.textContent="⚠ "+e.message;}});
    });
}

// ─── TV SCANNER — tarayıcıdan text/plain POST (çalışıyor) ────────────────────
var TV_URL="https://scanner.tradingview.com/turkey/scan";
var PROXIES=[
  TV_URL,
  "https://corsproxy.io/?"+encodeURIComponent(TV_URL),
  "https://api.allorigins.win/raw?url="+encodeURIComponent(TV_URL),
  "https://api.codetabs.com/v1/proxy?quest="+encodeURIComponent(TV_URL),
  "https://corsproxy.org/?"+encodeURIComponent(TV_URL)
];

function tvPost(body,ms){
  return new Promise(function(resolve,reject){
    var pi=0;
    function next(){
      if(pi>=PROXIES.length){reject(new Error("tüm proxy başarısız"));return;}
      var url=PROXIES[pi++];
      var done=false;
      var timer=setTimeout(function(){if(!done){done=true;next();}},ms||8000);
      var xhr=new XMLHttpRequest();
      xhr.open("POST",url,true);
      xhr.setRequestHeader("Content-Type","text/plain");
      xhr.onload=function(){
        if(done)return;clearTimeout(timer);done=true;
        if(xhr.status>=200&&xhr.status<300){
          try{
            var d=JSON.parse(xhr.responseText);
            if(d&&d.data&&d.data.length>0){resolve(d);return;}
          }catch(e){}
        }
        next();
      };
      xhr.onerror=function(){if(!done){clearTimeout(timer);done=true;next();}};
      xhr.send(JSON.stringify(body));
    }
    next();
  });
}

async function fetchRecs(){
  setSt(null,"Sinyaller yükleniyor...");
  try{
    var data=await tvPost({filter:[],options:{lang:"tr"},columns:["name","Recommend.All","close","change"],sort:{sortBy:"change",sortOrder:"desc"},range:[0,700],markets:["turkey"]},12000);
    API=[];
    data.data.forEach(function(item){
      var sym=(item.s||"").replace(/^BIST(|_DL):/,"").trim();
      var d=item.d;if(!sym||!d)return;
      if(d[1]!=null)REC[sym]=parseFloat(d[1]);
      if(d[3]!=null)CHG[sym]=parseFloat(d[3].toFixed(2));
      var name=sym;for(var k=0;k<SL.length;k++)if(SL[k].s===sym){name=SL[k].n;break;}
      API.push({sym:sym,name:name});
    });
    var slS={};for(var k=0;k<SL.length;k++)slS[SL[k].s]=1;
    API.forEach(function(item){if(!slS[item.sym]){SL.push({s:item.sym,n:item.name});slS[item.sym]=1;}});
    setSt(true,"✅ "+SL.length+" hisse — "+new Date().toLocaleTimeString("tr-TR"));
    buildWL(G("wls")?G("wls").value:"");
    SD=true;renderF();renderPF();
  }catch(e){
    setSt(false,"❌ TV Scanner: "+e.message);
    // yine de hisseleri göster
    buildWL("");renderF();
  }
}

async function fetchMonthly(){
  try{
    var data=await tvPost({filter:[],options:{lang:"tr"},columns:["name","Recommend.All|1M","RSI|1M","EMA20|1M","EMA50|1M","MACD.hist|1M"],sort:{sortBy:"name",sortOrder:"asc"},range:[0,700],markets:["turkey"]},14000);
    data.data.forEach(function(item){
      var sym=(item.s||"").replace(/^BIST(|_DL):/,"").trim();
      var d=item.d;if(!sym||!d)return;
      var rec=parseFloat(d[1]),r2=parseFloat(d[2]),em20=parseFloat(d[3]),em50=parseFloat(d[4]),hist=parseFloat(d[5]);
      if(isNaN(rec)){STM[sym]=0;return;}
      var f1=rec>=0.2,f2=!isNaN(r2)&&r2>=50,f3=!isNaN(em20)&&!isNaN(em50)&&em20>em50,f4=!isNaN(hist)&&hist>0;
      var sc=(f1?1:0)+(f2?1:0)+(f3?1:0)+(f4?1:0);
      STM[sym]=(sc===4||(f1&&sc>=3))?1:-1;
    });
    buildWL(G("wls")?G("wls").value:"");renderPF();
  }catch(e){}
}

// ─── FİYAT TABLOSU ───────────────────────────────────────────────────────────
function renderF(){
  var tablo=G("ftable");if(!tablo)return;
  var rows=(API.length>0)
    ?API.map(function(r){return{sym:r.sym,rec:REC[r.sym],chg:CHG[r.sym]!=null?CHG[r.sym]:null};})
    :SL.map(function(s){return{sym:s.s,rec:REC[s.s],chg:CHG[s.s]!=null?CHG[s.s]:null};});
  rows.sort(function(a,b){var av=a.chg!=null?a.chg:-9999,bv=b.chg!=null?b.chg:-9999;return SD?(bv-av):(av-bv);});
  var parts=[];
  rows.forEach(function(r){
    var r2=RL(r.rec);
    var cs=r.chg!=null?(r.chg>=0?"+":"")+r.chg.toFixed(2)+"%":"—";
    var cc=r.chg!=null?(r.chg>0?"#22c55e":r.chg<0?"#ef4444":"#94a3b8"):"#2a3548";
    var ic=r.sym===CUR;
    parts.push('<div onclick="pick(\''+r.sym+'\')" style="display:grid;grid-template-columns:66px 1fr 70px;padding:6px 8px;border-bottom:1px solid #0d1018;cursor:pointer;background:'+(ic?"#0f1a2a":"transparent")+'">'
      +'<span style="font-size:14px;font-weight:700;color:'+(ic?"#e8b84b":"#fff")+';">'+r.sym+'</span>'
      +'<span style="text-align:center"><span style="font-size:10px;font-weight:700;padding:1px 6px;background:'+r2.bg+';color:'+r2.c+';">'+r2.t+'</span></span>'
      +'<span style="text-align:right;font-size:11px;font-weight:700;color:'+cc+';">'+cs+'</span></div>');
  });
  tablo.innerHTML=parts.join("");
  var st=G("fst");if(st)st.textContent=rows.length+" hisse — "+new Date().toLocaleTimeString("tr-TR");
}

// ─── PORTFÖY ─────────────────────────────────────────────────────────────────
function spf(q){
  var box=G("pfsug");if(!box)return;
  if(!q){box.style.display="none";return;}
  q=q.toUpperCase();
  var m=SL.filter(function(s){return s.s.includes(q)||s.n.toUpperCase().includes(q);}).slice(0,8);
  if(!m.length){box.style.display="none";return;}
  box.style.display="block";
  box.innerHTML=m.map(function(s){return'<div style="padding:8px 10px;cursor:pointer;font-size:12px;border-bottom:1px solid #0f1520;color:#fff;" onclick="selPF(\''+s.s+'\',\''+s.n+'\')">'+s.s+' <span style="color:#4b5e78;font-size:10px;">'+s.n+'</span></div>';}).join("");
}
function selPF(sym,nm){
  PFS=sym;var lbl=G("pflbl");if(lbl)lbl.textContent="✅ "+sym+" — "+nm;
  var sug=G("pfsug");if(sug)sug.style.display="none";
  var inp=G("pfsi");if(inp)inp.value=sym;
}
function pfAdd(){
  if(!PFS){alert("Önce hisse seç!");return;}
  if(PF.find(function(p){return p.sym===PFS;})){alert("Zaten portföyde!");return;}
  PF.push({id:Date.now(),sym:PFS});savePF();renderPF();
}
function pfRem(){
  if(!PFS){alert("Önce hisse seç!");return;}
  PF=PF.filter(function(p){return p.sym!==PFS;});PFS="";savePF();renderPF();
}
function pfDel(id){PF=PF.filter(function(p){return p.id!==id;});savePF();renderPF();}
function savePF(){try{localStorage.setItem("bist_pf6",JSON.stringify(PF));}catch(e){}}
function loadPF(){try{var j=localStorage.getItem("bist_pf6");if(j)PF=JSON.parse(j);}catch(e){}}
function renderPF(){
  var el=G("pflist");if(!el)return;
  if(!PF.length){el.innerHTML='<div style="padding:16px;font-size:11px;color:#2a3548;text-align:center;">Portföy boş.<br>Yukarıdan hisse ekle.</div>';return;}
  var html="";
  PF.forEach(function(p){
    var r2=RL(REC[p.sym]);var chg=CHG[p.sym];
    var cs=chg!=null?(chg>=0?"+":"")+chg.toFixed(2)+"%":"—";
    var cc=chg!=null?(chg>0?"#22c55e":chg<0?"#ef4444":"#94a3b8"):"#2a3548";
    var nm="";for(var k=0;k<SL.length;k++)if(SL[k].s===p.sym){nm=SL[k].n;break;}
    html+='<div style="padding:10px 12px;border-bottom:1px solid #0f1520;display:flex;align-items:center;justify-content:space-between;">'
      +'<div><div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">'
      +'<span onclick="pick(\''+p.sym+'\')" style="font-size:14px;font-weight:700;color:#e8b84b;cursor:pointer;">'+p.sym+'</span>'
      +'<span style="font-size:9px;font-weight:700;padding:1px 6px;background:'+r2.bg+';color:'+r2.c+';">'+r2.t+'</span>'
      +'<span style="font-size:11px;font-weight:700;color:'+cc+';">'+cs+'</span>'
      +'</div><div style="font-size:10px;color:#3d5878;">'+nm+'</div></div>'
      +'<button onclick="pfDel('+p.id+')" style="background:#300;border:none;color:#f44;cursor:pointer;border-radius:3px;padding:3px 10px;font-size:12px;font-family:inherit;">✕</button></div>';
  });
  el.innerHTML=html;
}

// ─── BAŞLAT ───────────────────────────────────────────────────────────────────
loadPF();buildWL("");renderF();
fetchRecs();
setInterval(fetchRecs,30000);
setTimeout(function(){fetchMonthly();setInterval(fetchMonthly,60000);},4000);
</script>
</body></html>`;
