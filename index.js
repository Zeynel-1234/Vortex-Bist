const express=require('express');
const https=require('https');
const app=express();
const PORT=process.env.PORT||3000;

app.use((req,res,next)=>{
  res.setHeader('Access-Control-Allow-Origin','*');
  if(req.method==='OPTIONS')return res.sendStatus(200);
  next();
});

function yahoo(sym,interval,range,res){
  const url=`https://query1.finance.yahoo.com/v8/finance/chart/${sym}.IS?interval=${interval}&range=${range}`;
  const url2=url.replace('query1','query2');
  function get(u,fallback){
    https.get(u,{headers:{'User-Agent':'Mozilla/5.0','Accept':'application/json'}},(yr)=>{
      if(yr.statusCode!==200&&fallback)return get(url2,false);
      let d='';yr.on('data',c=>d+=c);yr.on('end',()=>{res.setHeader('Content-Type','application/json');res.end(d);});
    }).on('error',()=>{if(fallback)get(url2,false);else res.status(502).json({error:'fail'});});
  }
  get(url,true);
}

app.get('/api/monthly/:sym',(req,res)=>yahoo(req.params.sym.toUpperCase(),'1mo','3y',res));
app.get('/api/:sym',(req,res)=>yahoo(req.params.sym.toUpperCase(),req.query.tf||'1d',req.query.range||'1y',res));
app.get('/health',(req,res)=>res.json({ok:true}));
app.get('/',(req,res)=>{res.setHeader('Content-Type','text/html;charset=utf-8');res.send(HTML);});
app.listen(PORT,()=>console.log('OK:'+PORT));

const HTML=`<!DOCTYPE html>
<html lang="tr"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BIST Vortex</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Courier New',monospace;background:#07090f;color:#8892a4;height:100dvh;display:flex;flex-direction:column;overflow:hidden}
::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:#1a2030}
#top{background:#0b0e18;border-bottom:2px solid #131826;padding:0 10px;height:44px;display:flex;align-items:center;gap:8px;flex-shrink:0}
.logo{color:#e8b84b;font-weight:700;font-size:13px;letter-spacing:3px}
.sp{width:1px;height:18px;background:#1a2030;flex-shrink:0}
#hs{color:#fff;font-weight:700;font-size:15px}
#sb{background:#050709;border-bottom:1px solid #131826;padding:3px 10px;font-size:10px;display:flex;align-items:center;gap:6px;flex-shrink:0}
#tabs{background:#0b0e18;border-bottom:1px solid #131826;display:flex;flex-shrink:0}
.tab{background:transparent;border:none;border-bottom:2px solid transparent;padding:9px 12px;cursor:pointer;font-size:11px;font-weight:700;color:#2a3548;font-family:inherit;white-space:nowrap}
.tab.on{color:#e8b84b;border-bottom-color:#e8b84b}
#body{display:flex;flex:1;overflow:hidden;min-height:0}
#wl{width:155px;background:#08090f;border-right:1px solid #131826;display:flex;flex-direction:column;flex-shrink:0}
#wli{width:100%;background:#0f1118;border:none;border-bottom:1px solid #131826;color:#fff;padding:8px 9px;font-size:11px;font-family:inherit;outline:none}
#wlc{padding:4px 10px;font-size:10px;color:#4b5e78;border-bottom:1px solid #131826;flex-shrink:0}
#wll{overflow-y:auto;flex:1}
#center{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.pnl{flex:1;display:flex;flex-direction:column;overflow:hidden;min-height:0}
.hid{display:none!important}
#vt{background:#080d14;border-bottom:1px solid #131826;padding:4px 8px;display:flex;align-items:center;gap:5px;flex-shrink:0;overflow-x:auto}
.vb{font-size:11px;font-weight:700;padding:3px 8px;border:1px solid;white-space:nowrap;flex-shrink:0}
.vl{font-size:8px;color:#4b5e78;white-space:nowrap;flex-shrink:0}
.vv{font-size:11px;font-weight:700;white-space:nowrap;flex-shrink:0}
#ids{background:#050810;border-bottom:1px solid #131826;padding:3px 8px;display:flex;gap:7px;overflow-x:auto;flex-shrink:0;font-size:10px}
.ic{white-space:nowrap;flex-shrink:0}.icv{font-weight:700}
#tfb{display:flex;gap:4px;padding:4px 8px;background:#060810;border-bottom:1px solid #131826;flex-shrink:0;align-items:center}
.tb{background:#0b0e18;border:1px solid #1a2030;color:#4b5e78;padding:3px 9px;font-size:10px;font-family:inherit;cursor:pointer;font-weight:700}
.tb.on{background:#1a2a1a;border-color:#22c55e;color:#22c55e}
#co{flex:1;display:flex;flex-direction:column;position:relative;min-height:0;overflow:hidden}
#cm{display:block;flex:1;min-height:0}
#cr{display:block;height:60px;flex-shrink:0;border-top:1px solid #131826}
#msg{position:absolute;inset:0;background:rgba(7,9,15,.96);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;z-index:10;font-size:12px;color:#4b5e78;text-align:center;padding:16px}
#vb2{background:#080d14;border-top:1px solid #131826;padding:4px 8px;display:flex;gap:5px;overflow-x:auto;flex-shrink:0}
.ve{background:#0b1020;border:1px solid #1a2030;padding:3px 7px;font-size:9px;white-space:nowrap;flex-shrink:0}
.ve .lv{font-size:11px;font-weight:700;display:block}
.bull{color:#22c55e}.bear{color:#ef4444}.neu{color:#e8b84b}.dim{color:#4b5e78}
</style></head><body>
<div id="top">
  <span class="logo">BIST</span><div class="sp"></div>
  <span id="hs">—</span>
  <span id="clk" style="font-size:9px;color:#2a3548;margin-left:auto"></span>
</div>
<div id="sb">
  <div id="dot" style="width:6px;height:6px;border-radius:50%;background:#e8b84b;flex-shrink:0"></div>
  <span id="sm" style="color:#e8b84b">Başlatılıyor...</span>
  <button onclick="fetchRecs()" style="margin-left:auto;background:transparent;border:1px solid #1a2030;color:#4b5e78;padding:2px 8px;border-radius:3px;cursor:pointer;font-size:9px;font-family:inherit">↺ Yenile</button>
</div>
<div id="tabs">
  <button class="tab" onclick="goTab('s',this)">📊 VORTEX</button>
  <button class="tab on" onclick="goTab('f',this)">💹 FİYATLAR</button>
  <button class="tab" onclick="goTab('p',this)">💼 PORTFÖY</button>
</div>
<div id="body">
<div id="wl">
  <input id="wli" placeholder="🔍 Ara..." oninput="buildWL(this.value)">
  <div id="wlc">—</div>
  <div id="wll"></div>
</div>
<div id="center">

<div id="tp-s" class="pnl hid">
  <div id="vt">
    <div class="vb" id="vfb" style="color:#4b5e78;border-color:#1a2030">VF: —</div>
    <div class="sp"></div>
    <span class="vl">MOM</span><span class="vv" id="vmo">—</span>
    <div class="sp"></div>
    <span class="vl">TREND</span><span class="vv" id="vtr">—</span>
    <div class="sp"></div>
    <span class="vl">VOL</span><span class="vv" id="vvo">—</span>
    <div class="sp"></div>
    <span class="vl">HACİM</span><span class="vv" id="vha">—</span>
  </div>
  <div id="ids">
    <span class="ic dim">RSI:<span class="icv" id="ir">—</span></span>
    <span class="ic dim">STOCH:<span class="icv" id="is2">—</span></span>
    <span class="ic dim">MACD:<span class="icv" id="im">—</span></span>
    <span class="ic dim">BB:<span class="icv" id="ib">—</span></span>
    <span class="ic dim">ATR:<span class="icv" id="ia">—</span></span>
    <span class="ic dim">VWAP:<span class="icv" id="iv">—</span></span>
    <span class="ic dim">ST:<span class="icv" id="it">—</span></span>
  </div>
  <div id="tfb">
    <button class="tb on" onclick="setTF('1d','1y',this)">1G</button>
    <button class="tb" onclick="setTF('1wk','2y',this)">1H</button>
    <button class="tb" onclick="setTF('1mo','5y',this)">1M</button>
    <span style="margin-left:auto;font-size:9px;color:#4b5e78" id="vpl">—</span>
  </div>
  <div id="co">
    <div id="msg"><span style="font-size:28px">📊</span><span id="mt">Sol listeden hisse seç</span><span id="ms" style="font-size:9px;color:#2a3548"></span></div>
    <canvas id="cm"></canvas><canvas id="cr"></canvas>
  </div>
  <div id="vb2">
    <div class="ve"><span style="color:#4b5e78;font-size:8px">FİYAT</span><span class="lv" style="color:#00d4ff" id="ve1">—</span></div>
    <div class="ve"><span style="color:#4b5e78;font-size:8px">STOP</span><span class="lv bear" id="ve2">—</span></div>
    <div class="ve"><span style="color:#4b5e78;font-size:8px">H1</span><span class="lv neu" id="ve3">—</span></div>
    <div class="ve"><span style="color:#4b5e78;font-size:8px">H2</span><span class="lv bull" id="ve4">—</span></div>
    <div class="ve"><span style="color:#4b5e78;font-size:8px">H3</span><span class="lv bull" id="ve5">—</span></div>
    <div class="ve"><span style="color:#4b5e78;font-size:8px">R/R</span><span class="lv" id="ve6">—</span></div>
  </div>
</div>

<div id="tp-f" class="pnl">
  <div style="background:#0b1510;border-bottom:1px solid #1a3a1a;padding:5px 10px;font-size:10px;color:#22c55e;flex-shrink:0;display:flex;align-items:center">
    <span>💹 <strong style="color:#fff">Canlı Fiyatlar</strong></span>
    <button onclick="SD=!SD;renderF()" style="margin-left:auto;background:#1a2030;border:1px solid #2a3548;color:#e8b84b;padding:2px 8px;border-radius:3px;cursor:pointer;font-size:9px;font-family:inherit">↕</button>
  </div>
  <div style="display:grid;grid-template-columns:66px 1fr 70px;padding:6px 8px;background:#0b0e18;border-bottom:2px solid #1a2540;font-size:10px;color:#5b7a9a;font-weight:700;flex-shrink:0">
    <span>SEMBOL</span><span style="text-align:center">SİNYAL</span><span style="text-align:right">GÜN%</span>
  </div>
  <div id="ft" style="flex:1;overflow-y:auto"></div>
  <div id="fs" style="padding:4px 10px;font-size:9px;color:#2a3548;flex-shrink:0;border-top:1px solid #131826;background:#0b0e18">Bekleniyor...</div>
</div>

<div id="tp-p" class="pnl hid">
  <div style="background:#0b1020;border-bottom:1px solid #1e3050;padding:8px 12px;font-size:11px;font-weight:700;color:#e8b84b;flex-shrink:0">💼 PORTFÖY</div>
  <div style="padding:8px 10px;border-bottom:1px solid #131826;flex-shrink:0">
    <input id="pfi" placeholder="🔍 Hisse ara..." oninput="spf(this.value)" style="width:100%;background:#060a10;border:1px solid #1e3050;color:#fff;padding:8px 10px;border-radius:5px;font-size:12px;font-family:inherit;outline:none;margin-bottom:6px">
    <div id="pfs" style="background:#0b1424;border:1px solid #1e3050;border-top:none;display:none;max-height:120px;overflow-y:auto;border-radius:0 0 5px 5px;margin-bottom:6px"></div>
    <div id="pfl" style="font-size:12px;font-weight:700;color:#e8b84b;margin-bottom:6px;min-height:18px">— seçilmedi</div>
    <div style="display:flex;gap:8px">
      <button onclick="pfA()" style="flex:1;background:#22c55e;color:#000;border:none;padding:9px;border-radius:5px;cursor:pointer;font-size:12px;font-weight:700;font-family:inherit">+ EKLE</button>
      <button onclick="pfR()" style="flex:1;background:#300;color:#f44;border:none;padding:9px;border-radius:5px;cursor:pointer;font-size:12px;font-weight:700;font-family:inherit">− ÇIKAR</button>
    </div>
  </div>
  <div id="pfl2" style="flex:1;overflow-y:auto"></div>
</div>

</div></div>
<script>
var SL=[],NM={},CUR="THYAO",TF="1d",TFR="1y",LT="f";
var RC={},CH={},PF=[],PS="",SD=true,BA=null,MD={};

setInterval(()=>{let e=document.getElementById("clk");if(e)e.textContent=new Date().toLocaleTimeString("tr-TR");},1000);
const G=id=>document.getElementById(id);

function setSt(ok,msg){
  let d=G("dot"),m=G("sm");
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
  ["tp-s","tp-f","tp-p"].forEach(p=>{let e=G(p);if(e){e.classList.remove("pnl");e.classList.add("hid");}});
  let e=G(id);if(e){e.classList.remove("hid");e.classList.add("pnl");}
}
function buildWL(q){
  q=(q||"").toUpperCase().trim();
  let f=SL.filter(s=>!q||s.includes(q)||(NM[s]||"").toUpperCase().includes(q));
  let wc=G("wlc");if(wc)wc.textContent=f.length+" hisse";
  let h="";
  f.forEach(s=>{
    let r=RL(RC[s]),chg=CH[s],cs=chg!=null?(chg>=0?"+":"")+chg.toFixed(1)+"%":"";
    let cc=chg!=null?(chg>0?"#22c55e":chg<0?"#ef4444":"#4b5e78"):"#4b5e78";
    let ic=s===CUR;
    h+=\`<div onclick="pick('\${s}')" style="padding:8px 9px;border-bottom:1px solid #0d1018;cursor:pointer;background:\${ic?"#0f1a2a":"transparent"};display:flex;align-items:center;gap:4px">
<div style="flex:1;min-width:0"><div style="font-size:14px;font-weight:700;color:\${ic?"#e8b84b":"#fff"}">\${s}</div>
<div style="font-size:11px;color:#7a9ab8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">\${NM[s]||""}</div></div>
<div style="text-align:right;flex-shrink:0"><div style="font-size:9px;font-weight:700;background:\${r.bg};color:\${r.c};padding:1px 4px">\${r.t}</div>
\${cs?'<div style="font-size:9px;color:'+cc+'">'+cs+'</div>':""}</div></div>\`;
  });
  let wl=G("wll");if(wl)wl.innerHTML=h;
}
function goTab(id,btn){
  document.querySelectorAll(".tab").forEach(b=>b.classList.remove("on"));
  if(btn)btn.classList.add("on");showP("tp-"+id);LT=id;
  if(id==="s")loadChart();else if(id==="f")renderF();else if(id==="p")renderPF();
}
function pick(s){
  CUR=s;let h=G("hs");if(h)h.textContent=s;
  buildWL(G("wli").value||"");
  showP("tp-s");
  document.querySelectorAll(".tab").forEach(b=>b.classList.remove("on"));
  document.querySelector("button[onclick*=\"'s'\"]").classList.add("on");
  LT="s";loadChart();
}
function setTF(tf,r,btn){
  TF=tf;TFR=r;document.querySelectorAll(".tb").forEach(b=>b.classList.remove("on"));
  if(btn)btn.classList.add("on");loadChart();
}

// TV Scanner
const TVS="https://scanner.tradingview.com/turkey/scan";
const PX=[TVS,"https://corsproxy.io/?"+encodeURIComponent(TVS),"https://api.allorigins.win/raw?url="+encodeURIComponent(TVS),"https://api.codetabs.com/v1/proxy?quest="+encodeURIComponent(TVS)];
function tvPost(body,ms){
  return new Promise((res,rej)=>{
    let pi=0;
    function nxt(){
      if(pi>=PX.length){rej(new Error("fail"));return;}
      let url=PX[pi++],done=false;
      let t=setTimeout(()=>{if(!done){done=true;nxt();}},ms||9000);
      let x=new XMLHttpRequest();x.open("POST",url,true);x.setRequestHeader("Content-Type","text/plain");
      x.onload=()=>{if(done)return;clearTimeout(t);done=true;
        if(x.status>=200&&x.status<300){try{let d=JSON.parse(x.responseText);if(d&&d.data&&d.data.length>0){res(d);return;}}catch(e){}}nxt();};
      x.onerror=()=>{if(!done){clearTimeout(t);done=true;nxt();}};
      x.send(JSON.stringify(body));
    }nxt();
  });
}
async function fetchRecs(){
  setSt(null,"Yükleniyor...");
  if(!SL.length)["THYAO","AKBNK","GARAN","EREGL","ASELS","KCHOL","ISCTR","VAKBN","HALKB","YKBNK","FROTO","TOASO","BIMAS","MGROS","ARCLK","TUPRS","PETKM","SASA","EKGYO","TTKOM","TCELL","PGSUS","TAVHL","ENKAI","KOZAL","KOZAA","AEFES","CCOLA","ULKER","LOGO","MAVI","OTKAR","TTRAK","GUBRF","AKCNS","CIMSA","NUHCM","BRISA","KORDS","AYGAZ","DOHOL","DOAS","SKBNK","ALBRK","QNBFB","TSKB","ENJSA","AKSEN","AKENR","GWIND","ODAS","ZOREN","ASTOR","MPARK","TKFEN","ALKIM","SISE","ANACM"].forEach(s=>SL.push(s));
  try{
    let data=await tvPost({filter:[],options:{lang:"tr"},columns:["name","Recommend.All","close","change"],sort:{sortBy:"change",sortOrder:"desc"},range:[0,700],markets:["turkey"]},12000);
    let ex=new Set(SL);
    data.data.forEach(item=>{
      let s=(item.s||"").replace(/^BIST(|_DL):/,"").trim(),d=item.d;
      if(!s||!d)return;
      if(d[1]!=null)RC[s]=parseFloat(d[1]);
      if(d[3]!=null)CH[s]=parseFloat(d[3].toFixed(2));
      if(!ex.has(s)){SL.push(s);ex.add(s);}
      if(!NM[s]&&d[0])NM[s]=d[0];
    });
    setSt(true,"✅ "+SL.length+" hisse · "+new Date().toLocaleTimeString("tr-TR"));
    buildWL(G("wli")?G("wli").value:"");SD=true;renderF();renderPF();
  }catch(e){
    setSt(false,"❌ Yenile'ye bas");buildWL("");renderF();
  }
}

// Indicators
function ema(d,p){let k=2/(p+1),r=[],s=0,c=0;for(let i=0;i<d.length;i++){if(d[i]==null||isNaN(d[i])){r.push(null);continue;}if(c<p){s+=d[i];c++;r.push(c===p?s/p:null);}else{let pv=r.filter(v=>v!=null).pop()||d[i];r.push(pv*(1-k)+d[i]*k);}}return r;}
function dema(d,p){let e1=ema(d,p),e2=ema(e1.filter(v=>v!=null),p),res=new Array(d.length).fill(null),j=0;for(let i=p*2-2;i<d.length;i++){if(e1[i]!=null&&j<e2.length&&e2[j]!=null)res[i]=2*e1[i]-e2[j];j++;}return res;}
function rsi(c,p=14){let r=[],g=0,l=0;for(let i=1;i<c.length;i++){let d=c[i]-c[i-1];if(i<=p){g+=Math.max(d,0);l+=Math.max(-d,0);if(i===p)r.push(l===0?100:100-100/(1+g/l));else r.push(null);}else{g=(g*(p-1)+Math.max(d,0))/p;l=(l*(p-1)+Math.max(-d,0))/p;r.push(l===0?100:100-100/(1+g/l));}}return r;}
function macd(c){let e12=ema(c,12),e26=ema(c,26),ml=c.map((_,i)=>e12[i]!=null&&e26[i]!=null?e12[i]-e26[i]:null),sig=ema(ml.filter(v=>v!=null),9),h=[],si=0;for(let i=0;i<ml.length;i++){if(ml[i]==null)h.push(null);else{h.push(sig[si]!=null?ml[i]-sig[si]:null);si++;}}return{ml,h};}
function bb(c,p=20,m=2){let u=[],l=[],md=[];for(let i=0;i<c.length;i++){if(i<p-1){u.push(null);l.push(null);md.push(null);continue;}let s=c.slice(i-p+1,i+1),mn=s.reduce((a,b)=>a+b)/p,sd=Math.sqrt(s.reduce((a,b)=>a+(b-mn)*(b-mn),0)/p);u.push(mn+m*sd);l.push(mn-m*sd);md.push(mn);}return{u,l,m:md};}
function stoch(H,L,C,k=14){let r=[];for(let i=0;i<C.length;i++){if(i<k-1){r.push(null);continue;}let hh=Math.max(...H.slice(i-k+1,i+1)),ll=Math.min(...L.slice(i-k+1,i+1));r.push(hh===ll?50:((C[i]-ll)/(hh-ll))*100);}return r;}
function atr(H,L,C,p=14){let tr=[],at=[];for(let i=0;i<C.length;i++){if(i===0){tr.push(H[i]-L[i]);at.push(null);continue;}tr.push(Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1])));if(i<p)at.push(null);else if(i===p)at.push(tr.slice(0,p+1).reduce((a,b)=>a+b)/p);else at.push((at[i-1]*(p-1)+tr[i])/p);}return at;}
function spt(H,L,C,p=10,m=3){let a=atr(H,L,C,p),dr=[],ps=null,pd=1;for(let i=0;i<C.length;i++){if(a[i]==null){dr.push(null);continue;}let hl=(H[i]+L[i])/2,up=hl+m*a[i],dn=hl-m*a[i],cs,cd;if(ps==null){cs=up;cd=1;}else if(pd===1){cs=C[i]>ps?Math.max(dn,ps):up;cd=C[i]>cs?1:-1;}else{cs=C[i]<ps?Math.min(up,ps):dn;cd=C[i]>cs?1:-1;}dr.push(cd);ps=cs;pd=cd;}return dr;}
function obv(C,V){let o=[V[0]||0];for(let i=1;i<C.length;i++)o.push(C[i]>C[i-1]?o[i-1]+(V[i]||0):C[i]<C[i-1]?o[i-1]-(V[i]||0):o[i-1]);return o;}
function LV(a){for(let i=a.length-1;i>=0;i--)if(a[i]!=null)return a[i];return null;}

function vScore(I){
  let mom=40;
  if(I.rsi<25)mom+=35;else if(I.rsi<35)mom+=25;else if(I.rsi<45)mom+=10;else if(I.rsi>78)mom-=25;else if(I.rsi>68)mom-=12;
  if(I.stoch<20)mom+=20;else if(I.stoch<30)mom+=10;else if(I.stoch>80)mom-=15;
  if(I.macd>0&&I.macdP!=null&&I.macd>I.macdP)mom+=15;else if(I.macd<0)mom-=15;
  if(I.div==="bull")mom+=20;else if(I.div==="bear")mom-=20;
  mom=Math.max(0,Math.min(100,mom));
  let tr=40;
  if(I.mst===1)tr+=30;else tr-=20;
  if(I.dema&&I.price>I.dema)tr+=20;else tr-=10;
  if(I.e8>I.e21&&I.e21>I.e50)tr+=20;else if(I.e8<I.e21&&I.e21<I.e50)tr-=20;
  if(I.stdir===1)tr+=15;else tr-=10;
  tr=Math.max(0,Math.min(100,tr));
  let vol=40;
  if(I.price<I.bbl)vol+=30;else if(I.price>I.bbu)vol-=20;
  if(I.squeeze)vol+=20;if(I.z<-2)vol+=20;else if(I.z>2)vol-=20;
  vol=Math.max(0,Math.min(100,vol));
  let hac=40;
  if(I.volr>1.5)hac+=30;else if(I.volr>1.2)hac+=15;else if(I.volr<0.7)hac-=15;
  if(I.price>I.vwap)hac+=15;else hac-=10;if(I.obvUp)hac+=10;
  if(I.fib==="g")hac+=15;else if(I.fib==="m")hac+=8;
  hac=Math.max(0,Math.min(100,hac));
  let w1=0.30,w2=0.30,w3=0.20,w4=0.20;
  let an=I.atr?I.atr/I.price*100:2;
  if(an>3){w1=0.35;w2=0.25;}else if(an<1.5){w1=0.25;w2=0.35;}
  return{mom,tr,vol,hac,f:Math.max(0,Math.min(100,Math.round(mom*w1+tr*w2+vol*w3+hac*w4)))};
}

function drawChart(bars,mdir){
  let co=G("co"),cm2=G("cm"),cr2=G("cr");if(!co||!cm2||!cr2)return;
  let TW=co.clientWidth||320,TH=co.clientHeight-60||200;if(TH<80)TH=80;
  let RH=60,dpr=window.devicePixelRatio||1;
  cm2.width=TW*dpr;cm2.height=TH*dpr;cm2.style.width=TW+"px";cm2.style.height=TH+"px";
  cr2.width=TW*dpr;cr2.height=RH*dpr;cr2.style.width=TW+"px";cr2.style.height=RH+"px";
  let mc=cm2.getContext("2d");mc.scale(dpr,dpr);let rc=cr2.getContext("2d");rc.scale(dpr,dpr);
  let W=TW,H=TH,n=bars.length;if(n<3)return;
  let C=bars.map(d=>d.c),HH=bars.map(d=>d.h),LL=bars.map(d=>d.l),OO=bars.map(d=>d.o),VV=bars.map(d=>d.v);
  let rA=rsi(C),mR=macd(C),bR=bb(C),sA=stoch(HH,LL,C),aA=atr(HH,LL,C),sD=spt(HH,LL,C);
  let de25=dema(C,25),e8a=ema(C,8),e21a=ema(C,21),e50a=ema(C,50),oA=obv(C,VV);
  let vA=[];for(let i=0;i<n;i++){let sl=bars.slice(Math.max(0,i-19),i+1),tv=sl.reduce((a,d)=>a+((d.h+d.l+d.c)/3*d.v),0),sv=sl.reduce((a,d)=>a+d.v,0);vA.push(sv?tv/sv:C[i]);}
  let lR=LV(rA)||50,lM=LV(mR.h)||0,lMp=mR.h.filter(v=>v!=null).slice(-2)[0]||lM;
  let lBU=LV(bR.u)||0,lBL=LV(bR.l)||0,lBM=LV(bR.m)||0;
  let lSt=LV(sA)||50,lA=LV(aA)||0,lSD=LV(sD)||1;
  let lOBV=oA[n-1],pOBV=oA[Math.max(0,n-6)];
  let lDE=LV(de25)||0,lE8=LV(e8a)||0,lE21=LV(e21a)||0,lE50=LV(e50a)||0,lVW=vA[n-1],price=C[n-1];
  let avgV=VV.slice(-20).reduce((a,b)=>a+b)/20,volR=avgV?VV[n-1]/avgV:1;
  let sl20=C.slice(-20),sm=sl20.reduce((a,b)=>a+b)/sl20.length;
  let ss=Math.sqrt(sl20.reduce((a,b)=>a+(b-sm)*(b-sm),0)/sl20.length)||1;
  let z=(price-sm)/ss;
  let bW=lBM?((lBU-lBL)/lBM*100):0,bWp=bR.m[n-6]?((bR.u[n-6]-bR.l[n-6])/bR.m[n-6]*100):bW;
  let c2=C.slice(-10),rr2=rA.filter(v=>v!=null).slice(-10);
  let div="none";if(c2.length>=5&&rr2.length>=5){let pt=c2[c2.length-1]-c2[0],rt=rr2[rr2.length-1]-rr2[0];if(pt<0&&rt>2)div="bull";else if(pt>0&&rt<-2)div="bear";}
  let swH=Math.max(...HH.slice(-60)),swL=Math.min(...LL.slice(-60));
  let retr=(swH-swL)?(swH-price)/(swH-swL):0;
  let fib=retr>=0.6&&retr<=0.79?"g":retr>=0.35&&retr<0.6?"m":"x";
  let I={rsi:lR,stoch:lSt,macd:lM,macdP:lMp,div,mst:mdir||1,dema:lDE,e8:lE8,e21:lE21,e50:lE50,stdir:lSD,price,bbu:lBU,bbl:lBL,bbm:lBM,squeeze:bW<bWp*0.9,z,volr:volR,vwap:lVW,obvUp:lOBV>pOBV,fib,atr:lA};
  let SC=vScore(I);
  let bc=SC.f>=75?"#22c55e":SC.f>=60?"#00d4ff":SC.f>=40?"#e8b84b":"#ef4444";
  let bt=SC.f>=75?"GÜÇLÜ AL ▲":SC.f>=60?"İZLE ◆":SC.f>=40?"BEKLE ■":"UZAK DUR ▼";
  let bg=G("vfb");if(bg){bg.style.color=bc;bg.style.borderColor=bc;bg.textContent="VF:"+SC.f+" "+bt;}
  const sv=(id,v,cls)=>{let e=G(id);if(e){e.textContent=v;e.className="vv "+(cls||"");}};
  sv("vmo",SC.mom,SC.mom>=60?"bull":SC.mom<40?"bear":"neu");sv("vtr",SC.tr,SC.tr>=60?"bull":SC.tr<40?"bear":"neu");sv("vvo",SC.vol,SC.vol>=60?"bull":SC.vol<40?"bear":"neu");sv("vha",SC.hac,SC.hac>=60?"bull":SC.hac<40?"bear":"neu");
  const sc=(id,v,cls)=>{let e=G(id);if(e){e.textContent=v;e.parentElement.className="ic "+(cls||"dim");}};
  sc("ir",lR.toFixed(1),lR<35?"bull":lR>70?"bear":"neu");sc("is2",lSt.toFixed(1),lSt<20?"bull":lSt>80?"bear":"neu");sc("im",(lM>0?"▲":"▼")+Math.abs(lM).toFixed(3),lM>0&&lM>lMp?"bull":lM<0?"bear":"neu");sc("ib",price<lBL?"ALT":price>lBU?"ÜST":bW<bWp*0.9?"SIKIŞ":"ORTA",price<lBL?"bull":price>lBU?"bear":"neu");sc("ia",(lA/price*100).toFixed(1)+"%","neu");sc("iv",price>lVW?"Üst":"Alt",price>lVW?"bull":"bear");sc("it",lSD===1?"YEŞİL":"KIRMIZI",lSD===1?"bull":"bear");
  let prev=bars[n-2]?bars[n-2].c:price,chg=price-prev,pl=G("vpl");
  if(pl){pl.textContent="₺"+price.toFixed(2)+" "+(chg>=0?"+":"")+((chg/prev)*100).toFixed(2)+"%";pl.style.color=chg>=0?"#22c55e":"#ef4444";}
  let aa=lA||price*0.02,s2=price-aa*2,t1=price+aa*1.5,t2=price+aa*3,t3=price+aa*5.18;
  let rr=((t2-price)/(price-s2)).toFixed(1);
  const se=(id,v,c)=>{let e=G(id);if(e){e.textContent=v;if(c)e.style.color=c;}};
  se("ve1","₺"+price.toFixed(2),"#00d4ff");se("ve2","₺"+s2.toFixed(2),"#ef4444");se("ve3","₺"+t1.toFixed(2),"#e8b84b");se("ve4","₺"+t2.toFixed(2),"#22c55e");se("ve5","₺"+t3.toFixed(2),"#22c55e");se("ve6","1:"+rr,rr>=2?"#22c55e":"#ef4444");
  let allP=[];bars.forEach(d=>{allP.push(d.h,d.l);});bR.u.forEach(v=>{if(v)allP.push(v);});bR.l.forEach(v=>{if(v)allP.push(v);});
  let pMi=Math.min(...allP.filter(v=>v>0)),pMa=Math.max(...allP),pR=pMa-pMi||1;pMi-=pR*0.03;pMa+=pR*0.18;
  let VH=20,pd={l:2,r:52,t:6,b:18};
  const px=i=>pd.l+(i/(n-1||1))*(W-pd.l-pd.r);
  const py=v=>pd.t+(1-(v-pMi)/(pMa-pMi))*(H-pd.t-pd.b-VH);
  mc.fillStyle="#07090f";mc.fillRect(0,0,W,H);
  mc.strokeStyle="#0d1018";mc.lineWidth=0.5;
  for(let gi=0;gi<5;gi++){let gv=pMi+(pMa-pMi)*gi/4,gy=py(gv);mc.beginPath();mc.moveTo(pd.l,gy);mc.lineTo(W-pd.r,gy);mc.stroke();mc.fillStyle="#2a3548";mc.font="9px monospace";mc.textAlign="right";mc.fillText(gv.toFixed(gv>100?0:gv>10?1:2),W-2,gy+3);}
  let ss2=0,sd2=null;for(let i=0;i<=n;i++){let dd=sD[i]||null;if(dd!==sd2||i===n){if(sd2!=null&&i>ss2){mc.fillStyle=sd2===1?"rgba(34,197,94,.05)":"rgba(239,68,68,.05)";mc.fillRect(px(ss2),pd.t,px(Math.min(i,n-1))-px(ss2),H-pd.t-pd.b-VH);}sd2=dd;ss2=i;}}
  mc.fillStyle="rgba(0,212,255,.04)";mc.beginPath();let fs=true;
  for(let i=0;i<n;i++){if(bR.u[i]==null)continue;if(fs){mc.moveTo(px(i),py(bR.u[i]));fs=false;}else mc.lineTo(px(i),py(bR.u[i]));}
  for(let i=n-1;i>=0;i--){if(bR.l[i]==null)continue;mc.lineTo(px(i),py(bR.l[i]));}mc.closePath();mc.fill();
  const dl=(vals,col,al,dash)=>{mc.save();mc.strokeStyle=col;mc.globalAlpha=al||1;mc.lineWidth=1.5;mc.setLineDash(dash||[]);mc.beginPath();let f2=true;for(let i=0;i<n;i++){if(vals[i]==null)continue;let x=px(i),y=py(vals[i]);f2?mc.moveTo(x,y):mc.lineTo(x,y);f2=false;}mc.stroke();mc.restore();};
  dl(bR.u,"rgba(0,212,255,.5)",1,[3,3]);dl(bR.l,"rgba(0,212,255,.5)",1,[3,3]);
  dl(vA,"rgba(180,127,255,.8)",1,[2,2]);dl(e50a,"rgba(180,127,255,.5)",1,[4,2]);dl(de25,"#e8b84b",.9,[]);
  dl(C.map((c,i)=>aA[i]!=null?c-aA[i]*2:null),"rgba(239,68,68,.6)",1,[3,2]);
  const hl=(p2,col,lbl)=>{if(p2<pMi||p2>pMa)return;let y2=py(p2);mc.save();mc.strokeStyle=col;mc.lineWidth=1;mc.setLineDash([4,3]);mc.globalAlpha=.7;mc.beginPath();mc.moveTo(pd.l,y2);mc.lineTo(W-pd.r,y2);mc.stroke();mc.setLineDash([]);mc.fillStyle=col;mc.font="bold 9px monospace";mc.textAlign="right";mc.fillText(lbl,W-2,y2-2);mc.restore();};
  hl(s2,"#ef4444","STOP");hl(t2,"#22c55e","H2");
  let cw=Math.max(1,(W-pd.l-pd.r)/n*.72);
  for(let i=0;i<n;i++){let x=px(i),up=C[i]>=OO[i],col=up?"#22c55e":"#ef4444";mc.strokeStyle=col;mc.lineWidth=1;mc.beginPath();mc.moveTo(x,py(HH[i]));mc.lineTo(x,py(LL[i]));mc.stroke();mc.fillStyle=col;let bt2=py(Math.max(C[i],OO[i])),bb2=py(Math.min(C[i],OO[i]));mc.fillRect(x-cw/2,bt2,cw,Math.max(1,bb2-bt2));}
  for(let i=1;i<n;i++){if(sD[i]!=null&&sD[i-1]!=null&&sD[i]!==sD[i-1]){let ax=px(i),col2=sD[i]===1?"#22c55e":"#ef4444",ay=sD[i]===1?py(LL[i])+12:py(HH[i])-12;mc.fillStyle=col2;mc.font="10px monospace";mc.textAlign="center";mc.fillText(sD[i]===1?"▲":"▼",ax,ay);}}
  let mxV=Math.max(...VV.filter(v=>v>0));
  for(let i=0;i<n;i++){let x=px(i),vh=(VV[i]/(mxV||1))*VH*.9;mc.fillStyle=C[i]>=OO[i]?"rgba(34,197,94,.4)":"rgba(239,68,68,.4)";mc.fillRect(x-cw/2,H-pd.b-vh,cw,vh);}
  mc.fillStyle="#2a3548";mc.font="8px monospace";mc.textAlign="center";
  let step=Math.max(1,Math.floor(n/5));
  for(let i=0;i<n;i+=step){if(bars[i].t){let dt=new Date(bars[i].t*1000);mc.fillText(dt.getDate()+"."+(dt.getMonth()+1),px(i),H-pd.b+10);}}
  rc.fillStyle="#050810";rc.fillRect(0,0,W,RH);
  const ry=v=>(1-(v/100))*(RH-14)+4;
  rc.strokeStyle="#0d1018";rc.lineWidth=.5;
  [30,50,70].forEach(lv=>{let y2=ry(lv);rc.beginPath();rc.moveTo(0,y2);rc.lineTo(W-40,y2);rc.stroke();rc.fillStyle=lv===30?"#22c55e":lv===70?"#ef4444":"#2a3548";rc.font="8px monospace";rc.textAlign="left";rc.fillText(lv,W-38,y2+3);});
  rc.strokeStyle="#00d4ff";rc.lineWidth=1.5;rc.setLineDash([]);rc.beginPath();let fr=true;
  for(let i=0;i<n;i++){if(rA[i]==null)continue;let x=(i/(n-1||1))*(W-40),y2=ry(rA[i]);fr?rc.moveTo(x,y2):rc.lineTo(x,y2);fr=false;}rc.stroke();
  rc.fillStyle=lR<35?"#22c55e":lR>70?"#ef4444":"#00d4ff";rc.font="bold 9px monospace";rc.textAlign="right";rc.fillText("RSI "+lR.toFixed(1),W-2,12);
}

function loadChart(){
  let sym=CUR,mg=G("msg"),mt=G("mt"),ms2=G("ms");
  if(mg)mg.style.display="flex";if(mt)mt.textContent="⏳ "+sym;if(ms2)ms2.textContent="Yahoo Finance · Railway";
  fetch("/api/monthly/"+sym).then(r=>r.json()).then(data=>{
    let ch=data&&data.chart;
    if(ch&&ch.result&&ch.result[0]){
      let res=ch.result[0],q=res.indicators.quote[0],mv=[];
      for(let i=0;i<res.timestamp.length;i++)if(q.close[i]!=null&&q.high[i]!=null&&q.low[i]!=null)mv.push({h:q.high[i],l:q.low[i],c:q.close[i]});
      if(mv.length>=10){let mST=spt(mv.map(d=>d.h),mv.map(d=>d.l),mv.map(d=>d.c));MD[sym]=LV(mST)||1;}
    }
  }).catch(()=>{}).finally(()=>{
    fetch("/api/"+sym+"?tf="+TF+"&range="+TFR).then(r=>r.json()).then(data=>{
      let ch=data&&data.chart;
      if(!ch||!ch.result||!ch.result[0]){if(mg){mg.style.display="flex";if(mt)mt.textContent="⚠ Veri yok: "+sym;}return;}
      let res=ch.result[0],q=res.indicators.quote[0],v=[];
      for(let i=0;i<res.timestamp.length;i++)if(q.close[i]!=null&&q.high[i]!=null&&q.low[i]!=null&&q.open[i]!=null)v.push({t:res.timestamp[i],o:q.open[i],h:q.high[i],l:q.low[i],c:q.close[i],v:q.volume[i]||0});
      if(v.length<5){if(mg){mg.style.display="flex";if(mt)mt.textContent="⚠ Yetersiz veri";}return;}
      if(mg)mg.style.display="none";BA=v;drawChart(v,MD[sym]||1);
      window.onresize=()=>{if(BA)drawChart(BA,MD[CUR]||1);};
    }).catch(e=>{if(mg){mg.style.display="flex";if(mt)mt.textContent="⚠ "+e.message;}});
  });
}

function renderF(){
  let t=G("ft");if(!t)return;
  let rows=SL.map(s=>({sym:s,rec:RC[s],chg:CH[s]!=null?CH[s]:null}));
  rows.sort((a,b)=>{let av=a.chg!=null?a.chg:-9999,bv=b.chg!=null?b.chg:-9999;return SD?(bv-av):(av-bv);});
  let parts=[];
  rows.forEach(r=>{
    let r2=RL(r.rec),cs=r.chg!=null?(r.chg>=0?"+":"")+r.chg.toFixed(2)+"%":"—";
    let cc=r.chg!=null?(r.chg>0?"#22c55e":r.chg<0?"#ef4444":"#94a3b8"):"#2a3548";let ic=r.sym===CUR;
    parts.push(\`<div onclick="pick('\${r.sym}')" style="display:grid;grid-template-columns:66px 1fr 70px;padding:6px 8px;border-bottom:1px solid #0d1018;cursor:pointer;background:\${ic?"#0f1a2a":"transparent"}">
<span style="font-size:14px;font-weight:700;color:\${ic?"#e8b84b":"#fff"}">\${r.sym}</span>
<span style="text-align:center"><span style="font-size:10px;font-weight:700;padding:1px 6px;background:\${r2.bg};color:\${r2.c}">\${r2.t}</span></span>
<span style="text-align:right;font-size:11px;font-weight:700;color:\${cc}">\${cs}</span></div>\`);
  });
  t.innerHTML=parts.join("");
  let fs2=G("fs");if(fs2)fs2.textContent=rows.length+" hisse · "+new Date().toLocaleTimeString("tr-TR");
}

function spf(q){let box=G("pfs");if(!box)return;if(!q){box.style.display="none";return;}q=q.toUpperCase();let m=SL.filter(s=>s.includes(q)||(NM[s]||"").toUpperCase().includes(q)).slice(0,8);if(!m.length){box.style.display="none";return;}box.style.display="block";box.innerHTML=m.map(s=>\`<div style="padding:8px 10px;cursor:pointer;font-size:12px;border-bottom:1px solid #0f1520;color:#fff" onclick="selPF('\${s}')">\${s} <span style="color:#4b5e78;font-size:10px">\${NM[s]||""}</span></div>\`).join("");}
function selPF(sym){PS=sym;let l=G("pfl");if(l)l.textContent="✅ "+sym;let s=G("pfs");if(s)s.style.display="none";let i=G("pfi");if(i)i.value=sym;}
function pfA(){if(!PS){alert("Önce hisse seç!");return;}if(PF.find(p=>p.sym===PS)){alert("Zaten portföyde!");return;}PF.push({id:Date.now(),sym:PS});savePF();renderPF();}
function pfR(){if(!PS){alert("Önce hisse seç!");return;}PF=PF.filter(p=>p.sym!==PS);PS="";savePF();renderPF();}
function pfD(id){PF=PF.filter(p=>p.id!==id);savePF();renderPF();}
function savePF(){try{localStorage.setItem("bist_pf9",JSON.stringify(PF));}catch(e){}}
function loadPF(){try{let j=localStorage.getItem("bist_pf9");if(j)PF=JSON.parse(j);}catch(e){}}
function renderPF(){
  let el=G("pfl2");if(!el)return;
  if(!PF.length){el.innerHTML='<div style="padding:16px;font-size:11px;color:#2a3548;text-align:center">Portföy boş.</div>';return;}
  el.innerHTML=PF.map(p=>{
    let r2=RL(RC[p.sym]),chg=CH[p.sym],cs=chg!=null?(chg>=0?"+":"")+chg.toFixed(2)+"%":"—",cc=chg!=null?(chg>0?"#22c55e":chg<0?"#ef4444":"#94a3b8"):"#2a3548";
    return \`<div style="padding:10px 12px;border-bottom:1px solid #0f1520;display:flex;align-items:center;justify-content:space-between">
<div><div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
<span onclick="pick('\${p.sym}')" style="font-size:14px;font-weight:700;color:#e8b84b;cursor:pointer">\${p.sym}</span>
<span style="font-size:9px;font-weight:700;padding:1px 6px;background:\${r2.bg};color:\${r2.c}">\${r2.t}</span>
<span style="font-size:11px;font-weight:700;color:\${cc}">\${cs}</span></div>
<div style="font-size:10px;color:#3d5878">\${NM[p.sym]||p.sym}</div></div>
<button onclick="pfD(\${p.id})" style="background:#300;border:none;color:#f44;cursor:pointer;border-radius:3px;padding:3px 10px;font-size:12px;font-family:inherit">✕</button></div>\`;
  }).join("");
}

loadPF();buildWL("");renderF();fetchRecs();
setInterval(fetchRecs,30000);
</script>
</body></html>`;
