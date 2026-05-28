"""
═══════════════════════════════════════════════════════════════
alpha_tab_integration.py — BİRLEŞİK Frontend Entegrasyonu v2.0
───────────────────────────────────────────────────────────────
tab_integration.py ile AYNI middleware deseni. HTML elle düzenleme YOK.

İki iş:
  1) ⚛ sabit buton (sağ üst) → sağ drawer panel: 630 hisse BİRLEŞİK
     sıralama (NVS+ALPHA), rejim göstergesi
  2) Hisse detayı açıldığında, NİHAİ KARAR'ın ÜSTÜNE "BİRLEŞİK KARAR ·
     2 KAPI" kartı enjekte eder. Eski 4 kapı altta referans kalır.

Backend: /unified/scan, /unified/info/{symbol}

KURULUM (main.py'a 2 satır):
    from alpha_tab_integration import install_alpha_tab
    install_alpha_tab(app)
═══════════════════════════════════════════════════════════════
"""
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import PlainTextResponse


INJECT_JS = r"""
/*! Fraktal Kahin · BİRLEŞİK Inject v2.0 */
(function(){
  'use strict';
  var FLAG = '__unified_inject_v2__';
  if (window[FLAG]) return;
  window[FLAG] = true;

  function xhrGet(url, cb, errCb){
    var x = new XMLHttpRequest();
    x.open('GET', url, true);
    x.timeout = 90000;  // soğuk başlangıç + 2 TV çağrısı için uzun
    x.onload = function(){
      if (x.status >= 200 && x.status < 300){
        try { cb(JSON.parse(x.responseText)); }
        catch(e){ if (errCb) errCb(e); }
      } else if (errCb) errCb(new Error('HTTP ' + x.status));
    };
    x.onerror = function(){ if (errCb) errCb(new Error('network')); };
    x.ontimeout = function(){ if (errCb) errCb(new Error('timeout')); };
    x.send();
  }

  // Birleşik skor haritası (sembol → birlesik) — satır rozetleri için
  var uniMap = null;
  var uniMapLoading = false;
  function loadUniMap(){
    if (uniMapLoading) return;
    uniMapLoading = true;
    xhrGet('/unified/scan?top_n=900', function(d){
      uniMapLoading = false;
      if (d && d.sonuclar){
        lastData = d;
        var m = {};
        var i;
        for (i = 0; i < d.sonuclar.length; i++){
          var r = d.sonuclar[i];
          m[r.sembol] = {birlesik: r.birlesik, karar: r.karar, trap: r.trap};
        }
        uniMap = m;
        injectRowScores();
      }
    }, function(){ uniMapLoading = false; });
  }

  function kararCol(k){
    if (k === 'GÜÇLÜ AL') return '#22c55e';
    if (k === 'AL') return '#22c55e';
    if (k === 'AL (zayıf)') return '#9acd32';
    if (k === 'BEKLE') return '#e8b84b';
    return '#6b7280';
  }
  function regCol(r){
    if (r === 'RISK_ON') return '#22c55e';
    if (r === 'RISK_OFF') return '#ef4444';
    return '#e8b84b';
  }
  function fnum(v, d){
    if (v === null || v === undefined || isNaN(v)) return '-';
    return Number(v).toFixed(d == null ? 1 : d);
  }

  // ============================================================
  // BÖLÜM A — ⚛ BİRLEŞİK buton + sağ drawer panel
  // ============================================================
  var panelEl=null, listEl=null, regimeEl=null, metaEl=null, backdropEl=null;
  var curSort='birlesik', lastData=null;

  function addStyle(){
    if (document.getElementById('uni-style-v2')) return;
    var s = document.createElement('style');
    s.id = 'uni-style-v2';
    s.textContent =
      '#uni-fab{position:fixed;right:12px;top:120px;z-index:99998;' +
      'width:50px;height:50px;border-radius:50%;background:rgba(96,165,250,.20);' +
      'border:1.5px solid #60a5fa;color:#9fd;font-size:22px;cursor:pointer;' +
      'display:flex;align-items:center;justify-content:center;' +
      'box-shadow:0 2px 12px rgba(0,0,0,.5)}' +
      '#uni-fab:active{background:rgba(96,165,250,.35)}' +
      '#uni-backdrop{position:fixed;inset:0;z-index:99998;background:rgba(0,0,0,.45);display:none}' +
      '#uni-backdrop.open{display:block}' +
      '#uni-panel{position:fixed;top:0;right:0;bottom:0;z-index:99999;' +
      'width:84vw;max-width:440px;background:#070c11;border-left:2px solid #60a5fa;' +
      'display:none;flex-direction:column;box-shadow:-4px 0 24px rgba(0,0,0,.6);' +
      'transform:translateX(100%);transition:transform .22s ease}' +
      '#uni-panel.open{display:flex;transform:translateX(0)}' +
      '.uni-head{display:flex;align-items:center;gap:8px;padding:12px;border-bottom:1px solid #16202c}' +
      '.uni-ttl{font-size:15px;font-weight:700;color:#9fd}' +
      '.uni-reg{font-size:10px;flex:1 1 auto;text-align:center}' +
      '.uni-close{width:32px;height:32px;border-radius:6px;background:#1a0606;' +
      'border:1px solid #ef4444;color:#ef4444;font-size:16px;cursor:pointer}' +
      '.uni-sorts{display:flex;gap:4px;flex-wrap:wrap;padding:8px;border-bottom:1px solid #16202c}' +
      '.uni-sb{font-size:11px;padding:5px 9px;border-radius:5px;cursor:pointer;' +
      'background:#0d1620;border:1px solid #1c2836;color:#9ab}' +
      '.uni-sb.on{background:#13283c;border-color:#60a5fa;color:#cfe}' +
      '.uni-meta{font-size:10px;color:#5a6a80;padding:5px 12px}' +
      '.uni-list{overflow-y:auto;flex:1 1 auto;padding:0 6px 16px;-webkit-overflow-scrolling:touch}' +
      '.uni-row{display:flex;align-items:center;gap:6px;padding:9px 6px;' +
      'border-bottom:1px solid #11181f;cursor:pointer}' +
      '.uni-row:active{background:#0d1620}' +
      '.uni-rk{flex:0 0 28px;font-size:10px;color:#5a6a80;text-align:right}' +
      '.uni-sym{flex:0 0 58px;font-size:13px;font-weight:700;color:#dce8f5}' +
      '.uni-sc{flex:0 0 32px;font-size:15px;font-weight:700;text-align:right}' +
      '.uni-na{flex:0 0 70px;font-size:9px;color:#5a6a80;text-align:right;line-height:1.2}' +
      '.uni-dec{flex:1 1 auto;font-size:10px;text-align:right}';
    document.head.appendChild(s);
  }

  function buildPanel(){
    if (panelEl) return;
    addStyle();

    var fab=document.createElement('button');
    fab.id='uni-fab'; fab.textContent='⚛'; fab.title='BİRLEŞİK';
    fab.onclick=openPanel; document.body.appendChild(fab);

    backdropEl=document.createElement('div');
    backdropEl.id='uni-backdrop'; backdropEl.onclick=closePanel;
    document.body.appendChild(backdropEl);

    var p=document.createElement('div'); p.id='uni-panel';
    var head=document.createElement('div'); head.className='uni-head';
    var ttl=document.createElement('span'); ttl.className='uni-ttl'; ttl.textContent='⚛ BİRLEŞİK';
    regimeEl=document.createElement('span'); regimeEl.className='uni-reg'; regimeEl.textContent='...';
    var cls=document.createElement('button'); cls.className='uni-close'; cls.textContent='✕';
    cls.onclick=closePanel;
    head.appendChild(ttl); head.appendChild(regimeEl); head.appendChild(cls);

    var sorts=document.createElement('div'); sorts.className='uni-sorts';
    var defs=[['birlesik','Birleşik'],['nvs','NVS'],['alpha','ALPHA'],['change','Gün%']];
    var i;
    for (i=0;i<defs.length;i++){
      (function(key,label){
        var b=document.createElement('button');
        b.className='uni-sb'+(key===curSort?' on':'');
        b.textContent=label; b.setAttribute('data-s',key);
        b.onclick=function(){ setSort(key); };
        sorts.appendChild(b);
      })(defs[i][0],defs[i][1]);
    }

    metaEl=document.createElement('div'); metaEl.className='uni-meta';
    listEl=document.createElement('div'); listEl.className='uni-list';
    listEl.innerHTML='<div style="padding:20px;text-align:center;color:#5a6a80">Yükleniyor...</div>';

    p.appendChild(head); p.appendChild(sorts); p.appendChild(metaEl); p.appendChild(listEl);
    document.body.appendChild(p); panelEl=p;
  }

  function setSort(key){
    curSort=key;
    var btns=panelEl.querySelectorAll('.uni-sb'); var i;
    for (i=0;i<btns.length;i++){
      btns[i].className='uni-sb'+(btns[i].getAttribute('data-s')===key?' on':'');
    }
    if (lastData) renderList(lastData);
  }

  function openPanel(){
    buildPanel();
    if (backdropEl) backdropEl.classList.add('open');
    panelEl.classList.add('open');
    loadScan(false);
  }
  function closePanel(){
    if (panelEl) panelEl.classList.remove('open');
    if (backdropEl) backdropEl.classList.remove('open');
  }

  function renderRegime(reg){
    if (!regimeEl || !reg) return;
    var c=regCol(reg.regime);
    regimeEl.innerHTML='<span style="color:'+c+';font-weight:700">● '+(reg.regime||'?')+'</span>';
  }

  function renderList(data){
    lastData=data; renderRegime(data.regime);
    var rows=(data.sonuclar||[]).slice();
    if (curSort==='rank'){ rows.sort(function(a,b){return a.rank-b.rank;}); }
    else { rows.sort(function(a,b){
      var av=a[curSort],bv=b[curSort]; if(av==null)av=-999; if(bv==null)bv=-999; return bv-av;
    }); }
    if (metaEl) metaEl.textContent=data.n_total+' hisse · '+data.sure_ms+'ms · NVS×.55 + ALPHA×.45';
    var html='', i, r;
    for (i=0;i<rows.length;i++){
      r=rows[i];
      var col=kararCol(r.karar);
      var trap = r.trap ? ' ⚠' : '';
      html+='<div class="uni-row" data-sym="'+r.sembol+'">';
      html+='<span class="uni-rk">'+r.rank+'</span>';
      html+='<span class="uni-sym">'+r.sembol+'</span>';
      html+='<span class="uni-sc" style="color:'+col+'">'+Math.round(r.birlesik)+'</span>';
      html+='<span class="uni-na">N'+(r.nvs!=null?Math.round(r.nvs):'-')+' · A'+(r.alpha!=null?Math.round(r.alpha):'-')+'</span>';
      html+='<span class="uni-dec" style="color:'+col+'">'+r.karar+trap+'</span>';
      html+='</div>';
    }
    listEl.innerHTML=html;
    var nodes=listEl.querySelectorAll('.uni-row');
    for (i=0;i<nodes.length;i++){
      nodes[i].onclick=function(){
        var sym=this.getAttribute('data-sym');
        if (sym && typeof window.openDetail==='function'){ closePanel(); window.openDetail(sym); }
      };
    }
  }

  function loadScan(force){
    if (!listEl) return;
    if (lastData && !force){ renderList(lastData); }
    else { listEl.innerHTML='<div style="padding:20px;text-align:center;color:#5a6a80">⏳ Taranıyor (~3sn)...</div>'; }
    xhrGet('/unified/scan?top_n=700&force='+(force?'true':'false'),
      function(d){ renderList(d); },
      function(err){ listEl.innerHTML='<div style="padding:20px;text-align:center;color:#ef4444">✗ '+
        (err&&err.message?err.message:'hata')+'</div>'; });
  }

  // ============================================================
  // BÖLÜM C — Ana liste satırlarına "B75" birleşik rozeti enjekte
  // ============================================================
  function injectRowScores(){
    if (!uniMap) return;
    var rows = document.querySelectorAll('[onclick*="openDetail"]');
    var i, j;
    for (i = 0; i < rows.length; i++){
      var el = rows[i];
      var txt = el.textContent || '';
      if (txt.indexOf('NVS ') === -1) continue;       // sadece ana kart satırları
      if (el.querySelector('.uni-badge')) continue;    // zaten var
      var oc = el.getAttribute('onclick') || '';
      var m = oc.match(/openDetail\(['"]([A-ZÇĞİÖŞÜ]{2,7})['"]\)/);
      if (!m) continue;
      var info = uniMap[m[1]];
      if (!info || info.birlesik == null) continue;
      var spans = el.querySelectorAll('span');
      var nvsSpan = null;
      for (j = 0; j < spans.length; j++){
        if ((spans[j].textContent || '').indexOf('NVS') === 0){ nvsSpan = spans[j]; break; }
      }
      var col = kararCol(info.karar);
      var badge = document.createElement('span');
      badge.className = 'uni-badge';
      badge.textContent = 'B' + Math.round(info.birlesik) + (info.trap ? '⚠' : '');
      badge.style.cssText = 'display:inline-block;font-size:9px;font-weight:700;' +
        'padding:1px 5px;margin-left:4px;border-radius:3px;' +
        'background:' + col + '22;color:' + col + ';border:1px solid ' + col + '55';
      if (nvsSpan && nvsSpan.parentNode){
        nvsSpan.parentNode.insertBefore(badge, nvsSpan.nextSibling);
      }
    }
  }

  // ============================================================
  // BÖLÜM B — NİHAİ KARAR'ın ÜSTÜNE "BİRLEŞİK KARAR · 2 KAPI" kartı
  // ============================================================
  var injecting=false, lastSym=null, lastInfo=null;

  function getCurrentSymbol(){
    var rs=document.getElementById('rsym');
    if (rs && rs.textContent){
      var t=rs.textContent.trim().toUpperCase();
      if (/^[A-ZÇĞİÖŞÜ]{2,7}$/.test(t)) return t;
    }
    try { if (typeof CURRENT_SYM==='string' && CURRENT_SYM) return CURRENT_SYM.toUpperCase(); } catch(e){}
    return null;
  }

  function buildCard(info){
    if (!info || !info.available){
      return '<div style="font-size:11px;color:#e8b84b">BİRLEŞİK: veri yok</div>';
    }
    var col=kararCol(info.karar);
    var reg=info.regime||{}; var rc=regCol(reg.regime);
    var H='';
    H+='<div style="font-size:9px;color:#60a5fa;letter-spacing:2px;margin-bottom:6px">⚛ BİRLEŞİK KARAR · 2 KAPI</div>';
    H+='<div style="font-size:26px;font-weight:700;color:'+col+';text-align:center;line-height:1">'+info.karar+'</div>';
    H+='<div style="text-align:center;font-size:13px;color:#cfe;margin:4px 0">Birleşik Skor: <b style="color:'+col+'">'+Math.round(info.birlesik)+'</b> · #'+info.rank+'/'+info.universe_size+'</div>';
    H+='<div style="font-size:10px;color:#a8b6c8;text-align:center;line-height:1.5;margin-bottom:8px">'+info.aciklama+'</div>';
    // bileşenler
    H+='<div style="display:flex;gap:6px;margin-bottom:8px">';
    H+='<div style="flex:1;background:#080c12;border-radius:4px;padding:6px;text-align:center">'+
       '<div style="font-size:8px;color:#5a6a80">NVS ×.55</div>'+
       '<div style="font-size:16px;font-weight:700;color:#cfe">'+(info.nvs!=null?Math.round(info.nvs):'-')+'</div></div>';
    H+='<div style="flex:1;background:#080c12;border-radius:4px;padding:6px;text-align:center">'+
       '<div style="font-size:8px;color:#5a6a80">ALPHA ×.45</div>'+
       '<div style="font-size:16px;font-weight:700;color:#9fd">'+(info.alpha!=null?Math.round(info.alpha):'-')+'</div></div>';
    H+='</div>';
    // 2 kapı
    var g1c=info.gate1?'#22c55e':'#ef4444', g1i=info.gate1?'✓':'✗';
    var g2c=info.gate2?'#22c55e':'#ef4444', g2i=info.gate2?'✓':'✗';
    H+='<div style="display:flex;align-items:center;justify-content:space-between;padding:5px 8px;background:#080c12;border-radius:4px;margin-bottom:4px;border-left:3px solid '+g1c+';font-size:10px">'+
       '<span style="color:#fff"><span style="color:'+g1c+'">'+g1i+'</span> Kapı 1: Birleşik ≥ 60</span>'+
       '<span style="color:'+g1c+';font-weight:700">'+Math.round(info.birlesik)+'</span></div>';
    H+='<div style="display:flex;align-items:center;justify-content:space-between;padding:5px 8px;background:#080c12;border-radius:4px;border-left:3px solid '+g2c+';font-size:10px">'+
       '<span style="color:#fff"><span style="color:'+g2c+'">'+g2i+'</span> Kapı 2: Giriş sağlığı (Trend↑, RSI<72)</span>'+
       '<span style="color:'+g2c+';font-weight:700">RSI '+(info.rsi!=null?Math.round(info.rsi):'-')+'</span></div>';
    if (info.trap){
      H+='<div style="margin-top:6px;padding:5px 8px;background:#2a1505;border-radius:4px;font-size:10px;color:#e8b84b">⚠ Tuzak: NVS yüksek ama ALPHA zayıf — akranlarına göre geride</div>';
    }
    H+='<div style="margin-top:6px;font-size:10px;color:#9ab;text-align:center">REJİM: <b style="color:'+rc+'">'+(reg.regime||'?')+'</b></div>';
    return H;
  }

  function injectCard(info){
    var card=document.getElementById('karar-card');
    if (!card || !card.parentNode) return;
    var old=document.getElementById('uni-karar-card');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var box=document.createElement('div');
    box.id='uni-karar-card';
    box.style.cssText='background:linear-gradient(180deg,#0a1620 0%,#050a10 100%);'+
      'border:2px solid #60a5fa;border-radius:8px;padding:12px;margin-bottom:10px;'+
      'box-shadow:0 0 18px rgba(96,165,250,.18)';
    box.innerHTML=buildCard(info);
    injecting=true;
    card.parentNode.insertBefore(box, card);  // NİHAİ KARAR'ın ÜSTÜNE
    setTimeout(function(){ injecting=false; }, 80);
  }

  function checkPanel(){
    if (injecting) return;
    var card=document.getElementById('karar-card');
    if (!card) return;
    var sym=getCurrentSymbol();
    if (!sym) return;
    if (sym===lastSym && lastInfo){
      if (!document.getElementById('uni-karar-card')) injectCard(lastInfo);
      return;
    }
    xhrGet('/unified/info/'+encodeURIComponent(sym), function(info){
      lastSym=sym; lastInfo=info; injectCard(info);
    }, function(){});
  }

  var deb=null;
  function onMut(){ if(deb)clearTimeout(deb); deb=setTimeout(function(){
    checkPanel();
    injectRowScores();
  },250); }

  function start(){
    buildPanel();
    var mo=new MutationObserver(onMut);
    mo.observe(document.body,{childList:true,subtree:true});
    // Birleşik haritayı arka planda yükle (satır rozetleri + rejim için)
    loadUniMap();
    setTimeout(checkPanel,800);
    setTimeout(injectRowScores,1500);
    console.log('[unified-inject] aktif');
  }

  if (document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded', start);
  } else { start(); }
})();
"""


_router = APIRouter(tags=["unified-tab-integration"])


@_router.get("/alpha-inject.js")
async def serve_inject_js():
    return PlainTextResponse(
        content=INJECT_JS,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=120"},
    )


INJECT_TAG = '<script src="/alpha-inject.js" defer></script>'


def install_alpha_tab(app: FastAPI) -> None:
    app.include_router(_router)

    @app.middleware("http")
    async def _unified_tab_middleware(request: Request, call_next):
        if request.url.path not in ("/", "", "/app"):
            return await call_next(request)
        if request.method.upper() != "GET":
            return await call_next(request)

        response = await call_next(request)
        ct = (response.headers.get("content-type", "") or "").lower()
        if "text/html" not in ct:
            return response
        ce = (response.headers.get("content-encoding", "") or "").lower().strip()
        if ce and ce not in ("identity", ""):
            return response

        try:
            chunks = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                chunks.append(chunk)
            body = b"".join(chunks)
        except Exception:
            return response

        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return Response(
                content=body, status_code=response.status_code,
                headers={k: v for k, v in response.headers.items()
                         if k.lower() not in ("content-length", "content-encoding")},
                media_type=response.media_type)

        if "alpha-inject.js" in text:
            new_text = text
        else:
            idx = text.rfind("</body>")
            new_text = (text + "\n" + INJECT_TAG + "\n") if idx == -1 \
                else text[:idx] + INJECT_TAG + "\n" + text[idx:]

        new_body = new_text.encode("utf-8")
        new_headers = {}
        for k, v in response.headers.items():
            if k.lower() in ("content-length", "content-encoding"):
                continue
            new_headers[k] = v
        new_headers["content-length"] = str(len(new_body))
        return Response(content=new_body, status_code=response.status_code,
                        headers=new_headers, media_type="text/html; charset=utf-8")
