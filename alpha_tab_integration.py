"""
═══════════════════════════════════════════════════════════════
alpha_tab_integration.py — ALPHA Frontend Entegrasyonu
───────────────────────────────────────────────────────────────
tab_integration.py ile AYNI desen: middleware ile HTML'e
<script src="/alpha-inject.js"> enjekte eder. HTML'i elle
düzenlemen GEREKMEZ. Mevcut crossover entegrasyonuna dokunmaz.

İki iş yapar:
  1) "⚛ ALPHA" yüzen buton + panel: 630 hisse cross-sectional
     sıralama + rejim göstergesi
  2) Hisse detayı (NİHAİ KARAR) açıldığında Kapı 4'ün altına
     2 bilgi satırı enjekte eder: ALPHA + REJİM

KURULUM (main.py'a 2 satır):
    from alpha_tab_integration import install_alpha_tab
    install_alpha_tab(app)
═══════════════════════════════════════════════════════════════
"""
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import PlainTextResponse


INJECT_JS = r"""
/*! Fraktal Kahin · ALPHA Inject v1.0 */
(function(){
  'use strict';
  var FLAG = '__alpha_inject_v1__';
  if (window[FLAG]) return;
  window[FLAG] = true;

  // ============================================================
  // XHR
  // ============================================================
  function xhrGet(url, cb, errCb){
    var x = new XMLHttpRequest();
    x.open('GET', url, true);
    x.timeout = 30000;
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

  function decCol(d){
    if (d === 'GÜÇLÜ AL') return '#22c55e';
    if (d === 'AL') return '#9acd32';
    if (d === 'BEKLE') return '#e8b84b';
    if (d === 'KAÇIN') return '#f08080';
    if (d === 'GÜÇLÜ KAÇIN') return '#ef4444';
    return '#7a8aa0';
  }
  function regCol(r){
    if (r === 'RISK_ON') return '#22c55e';
    if (r === 'RISK_OFF') return '#ef4444';
    return '#e8b84b';
  }
  function fnum(v, d){
    if (v === null || v === undefined || isNaN(v)) return '-';
    return Number(v).toFixed(d == null ? 2 : d);
  }

  // ============================================================
  // BÖLÜM A — ⚛ ALPHA buton + panel
  // ============================================================
  var panelEl = null, listEl = null, regimeEl = null, metaEl = null;
  var curSort = 'composite_z';
  var lastData = null;

  function addStyle(){
    if (document.getElementById('alpha-style-v1')) return;
    var s = document.createElement('style');
    s.id = 'alpha-style-v1';
    s.textContent =
      '#alpha-fab{position:fixed;left:12px;bottom:70px;z-index:99998;' +
      'width:46px;height:46px;border-radius:50%;background:rgba(96,165,250,.18);' +
      'border:1.5px solid #60a5fa;color:#9fd;font-size:20px;cursor:pointer;' +
      'display:flex;align-items:center;justify-content:center;' +
      'box-shadow:0 2px 10px rgba(0,0,0,.4)}' +
      '#alpha-fab:active{background:rgba(96,165,250,.32)}' +
      '#alpha-panel{position:fixed;left:0;right:0;bottom:0;top:auto;z-index:99999;' +
      'max-height:82vh;background:#070c11;border-top:2px solid #60a5fa;' +
      'border-radius:14px 14px 0 0;display:none;flex-direction:column;' +
      'box-shadow:0 -4px 24px rgba(0,0,0,.6)}' +
      '#alpha-panel.open{display:flex}' +
      '.alpha-head{display:flex;align-items:center;gap:8px;padding:10px 12px;' +
      'border-bottom:1px solid #16202c}' +
      '.alpha-ttl{font-size:14px;font-weight:700;color:#9fd;flex:0 0 auto}' +
      '.alpha-reg{font-size:11px;flex:1 1 auto;text-align:center}' +
      '.alpha-close{flex:0 0 auto;width:30px;height:30px;border-radius:6px;' +
      'background:#1a0606;border:1px solid #ef4444;color:#ef4444;font-size:16px;cursor:pointer}' +
      '.alpha-sorts{display:flex;gap:4px;flex-wrap:wrap;padding:6px 10px;' +
      'border-bottom:1px solid #16202c}' +
      '.alpha-sb{font-size:11px;padding:4px 8px;border-radius:5px;cursor:pointer;' +
      'background:#0d1620;border:1px solid #1c2836;color:#9ab}' +
      '.alpha-sb.on{background:#13283c;border-color:#60a5fa;color:#cfe}' +
      '.alpha-meta{font-size:10px;color:#5a6a80;padding:4px 12px}' +
      '.alpha-list{overflow-y:auto;flex:1 1 auto;padding:0 6px 12px}' +
      '.alpha-row{display:flex;align-items:center;gap:6px;padding:7px 6px;' +
      'border-bottom:1px solid #11181f;cursor:pointer}' +
      '.alpha-row:active{background:#0d1620}' +
      '.alpha-rk{flex:0 0 32px;font-size:10px;color:#5a6a80;text-align:right}' +
      '.alpha-sym{flex:0 0 64px;font-size:13px;font-weight:700;color:#dce8f5}' +
      '.alpha-sc{flex:0 0 38px;font-size:14px;font-weight:700;text-align:right}' +
      '.alpha-dec{flex:1 1 auto;font-size:11px;text-align:right}' +
      '.alpha-z{flex:0 0 44px;font-size:10px;color:#7a8aa0;text-align:right}';
    document.head.appendChild(s);
  }

  function buildPanel(){
    if (panelEl) return;
    addStyle();

    var fab = document.createElement('button');
    fab.id = 'alpha-fab';
    fab.textContent = '⚛';
    fab.title = 'ALPHA · Çok Faktör';
    fab.onclick = openPanel;
    document.body.appendChild(fab);

    var p = document.createElement('div');
    p.id = 'alpha-panel';

    var head = document.createElement('div');
    head.className = 'alpha-head';
    var ttl = document.createElement('span');
    ttl.className = 'alpha-ttl'; ttl.textContent = '⚛ ALPHA';
    regimeEl = document.createElement('span');
    regimeEl.className = 'alpha-reg'; regimeEl.textContent = '...';
    var cls = document.createElement('button');
    cls.className = 'alpha-close'; cls.textContent = '✕';
    cls.onclick = closePanel;
    head.appendChild(ttl); head.appendChild(regimeEl); head.appendChild(cls);

    var sorts = document.createElement('div');
    sorts.className = 'alpha-sorts';
    var defs = [['composite_z','Z'],['z_mom','Mom'],['z_mr','M-Rev'],
                ['z_lv','LowVol'],['z_tr','Trend']];
    var i;
    for (i = 0; i < defs.length; i++){
      (function(key, label){
        var b = document.createElement('button');
        b.className = 'alpha-sb' + (key === curSort ? ' on' : '');
        b.textContent = label;
        b.setAttribute('data-s', key);
        b.onclick = function(){ setSort(key); };
        sorts.appendChild(b);
      })(defs[i][0], defs[i][1]);
    }

    metaEl = document.createElement('div');
    metaEl.className = 'alpha-meta'; metaEl.textContent = '';

    listEl = document.createElement('div');
    listEl.className = 'alpha-list';
    listEl.innerHTML = '<div style="padding:20px;text-align:center;color:#5a6a80">Yükleniyor...</div>';

    p.appendChild(head); p.appendChild(sorts);
    p.appendChild(metaEl); p.appendChild(listEl);
    document.body.appendChild(p);
    panelEl = p;
  }

  function setSort(key){
    curSort = key;
    var btns = panelEl.querySelectorAll('.alpha-sb');
    var i;
    for (i = 0; i < btns.length; i++){
      if (btns[i].getAttribute('data-s') === key) btns[i].className = 'alpha-sb on';
      else btns[i].className = 'alpha-sb';
    }
    if (lastData) renderList(lastData);
  }

  function openPanel(){
    buildPanel();
    panelEl.classList.add('open');
    loadScan(false);
  }
  function closePanel(){ if (panelEl) panelEl.classList.remove('open'); }

  function renderRegime(reg){
    if (!regimeEl || !reg) return;
    var c = regCol(reg.regime);
    regimeEl.innerHTML = '<span style="color:' + c + ';font-weight:700">● ' +
      (reg.regime || '?') + '</span>' +
      (reg.ema_aligned ? ' · EMA✓' : ' · EMA✗');
  }

  function renderList(data){
    lastData = data;
    renderRegime(data.regime);
    var rows = (data.sonuclar || []).slice();
    if (curSort === 'rank'){
      rows.sort(function(a,b){ return a.rank - b.rank; });
    } else {
      rows.sort(function(a,b){
        var av = a[curSort], bv = b[curSort];
        if (av == null) av = -99; if (bv == null) bv = -99;
        return bv - av;
      });
    }
    if (metaEl){
      metaEl.textContent = data.n_total + ' hisse · ' + data.sure_ms + 'ms · ' +
        (data.has_fundamentals ? 'temel✓' : 'temel✗') + ' · ' + data.tier;
    }
    var html = '';
    var i, r;
    for (i = 0; i < rows.length; i++){
      r = rows[i];
      var col = decCol(r.decision);
      html += '<div class="alpha-row" data-sym="' + r.sembol + '">';
      html += '<span class="alpha-rk">' + r.rank + '</span>';
      html += '<span class="alpha-sym">' + r.sembol + '</span>';
      html += '<span class="alpha-sc" style="color:' + col + '">' + r.score + '</span>';
      html += '<span class="alpha-dec" style="color:' + col + '">' + r.decision + '</span>';
      html += '<span class="alpha-z">' + fnum(r.composite_z, 2) + '</span>';
      html += '</div>';
    }
    listEl.innerHTML = html;
    // tıklama → hisse detayı aç
    var nodes = listEl.querySelectorAll('.alpha-row');
    for (i = 0; i < nodes.length; i++){
      nodes[i].onclick = function(){
        var sym = this.getAttribute('data-sym');
        if (sym && typeof window.openDetail === 'function'){
          closePanel();
          window.openDetail(sym);
        }
      };
    }
  }

  function loadScan(force){
    if (!listEl) return;
    if (lastData && !force){ renderList(lastData); }
    else { listEl.innerHTML = '<div style="padding:20px;text-align:center;color:#5a6a80">⏳ TradingView taranıyor (~2sn)...</div>'; }
    xhrGet('/alpha/scan?top_n=700&force=' + (force ? 'true':'false'),
      function(data){ renderList(data); },
      function(err){
        listEl.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">✗ ' +
          (err && err.message ? err.message : 'hata') + '</div>';
      });
  }

  // ============================================================
  // BÖLÜM B — NİHAİ KARAR paneline ALPHA + REJİM satırı enjekte
  // ============================================================
  var injecting = false;
  var lastInjectedSym = null;
  var lastInfo = null;

  function getCurrentSymbol(){
    // 1) #rsym elementi (fkahin-index'te CURRENT_SYM buraya yazılır)
    var rs = document.getElementById('rsym');
    if (rs && rs.textContent){
      var t = rs.textContent.trim().toUpperCase();
      if (/^[A-ZÇĞİÖŞÜ]{2,7}$/.test(t)) return t;
    }
    // 2) bare CURRENT_SYM global (let — bazen erişilebilir)
    try { if (typeof CURRENT_SYM === 'string' && CURRENT_SYM) return CURRENT_SYM.toUpperCase(); } catch(e){}
    return null;
  }

  function buildInjectHtml(sym, info){
    var html = '';
    if (info && info.available){
      var col = decCol(info.decision);
      html += '<div style="display:flex;align-items:center;justify-content:space-between;' +
        'padding:6px 8px;background:#080c12;border-radius:4px;margin-bottom:4px;' +
        'border-left:3px solid #60a5fa;font-size:10px">';
      html += '<span style="color:#9ab">ⓘ ALPHA · #' + info.rank + '/' + info.universe_size +
        ' · güven %' + Math.round((info.confidence||0)*100) + '</span>';
      html += '<span style="font-weight:700;color:' + col + '">Skor ' + info.score +
        ' · ' + info.decision + '</span>';
      html += '</div>';
      var f = info.factors || {};
      html += '<div style="padding:2px 10px;font-size:9px;color:#5a6a80;margin-bottom:4px">' +
        'Mom ' + fnum(f.momentum,1) + ' · MR ' + fnum(f.mean_rev,1) +
        ' · LowVol ' + fnum(f.low_vol,1) + ' · Trend ' + fnum(f.trend,1) +
        (f.quality != null ? ' · Qual ' + fnum(f.quality,1) : '') + '</div>';
    } else {
      var msg = 'ALPHA verisi yok';
      if (info && info.reason === 'not_in_universe') msg = info.sembol + ' likidite filtresinde elendi';
      html += '<div style="padding:6px 8px;background:#080c12;border-radius:4px;margin-bottom:4px;' +
        'border-left:3px solid #e8b84b;font-size:10px;color:#e8b84b">ⓘ ' + msg + '</div>';
    }
    // REJİM
    var reg = (info && info.regime) || {};
    var rc = regCol(reg.regime);
    html += '<div style="display:flex;align-items:center;justify-content:space-between;' +
      'padding:6px 8px;background:#080c12;border-radius:4px;' +
      'border-left:3px solid ' + rc + ';font-size:10px">';
    html += '<span style="color:#9ab">ⓘ REJİM</span>';
    html += '<span style="font-weight:700;color:' + rc + '">' + (reg.regime || '?') +
      (reg.ema_aligned ? ' · EMA20>50>200 ✓' : ' · EMA hizasız') + '</span>';
    html += '</div>';
    return html;
  }

  function injectInto(card, sym, info){
    var old = card.querySelector('.alpha-inject-box');
    if (old) old.parentNode.removeChild(old);
    var box = document.createElement('div');
    box.className = 'alpha-inject-box';
    box.style.cssText = 'margin-top:8px;padding-top:6px;border-top:1px dashed #1c2836';
    box.innerHTML = buildInjectHtml(sym, info);
    injecting = true;
    card.appendChild(box);
    setTimeout(function(){ injecting = false; }, 60);
  }

  function checkKararPanel(){
    if (injecting) return;
    var card = document.getElementById('karar-card');
    if (!card) return;
    var sym = getCurrentSymbol();
    if (!sym) return;

    // Aynı sembol + zaten enjekte var → tekrar fetch etme, sadece varlığını koru
    if (sym === lastInjectedSym && lastInfo){
      if (!card.querySelector('.alpha-inject-box')){
        injectInto(card, sym, lastInfo);
      }
      return;
    }
    // Yeni sembol → fetch
    xhrGet('/alpha/info/' + encodeURIComponent(sym), function(info){
      lastInjectedSym = sym;
      lastInfo = info;
      var c2 = document.getElementById('karar-card');
      if (c2) injectInto(c2, sym, info);
    }, function(){ /* sessiz */ });
  }

  // ============================================================
  // BAŞLAT
  // ============================================================
  var debTimer = null;
  function onMut(){
    if (debTimer) clearTimeout(debTimer);
    debTimer = setTimeout(checkKararPanel, 200);
  }

  function start(){
    buildPanel();
    var mo = new MutationObserver(onMut);
    mo.observe(document.body, {childList:true, subtree:true});
    // rejim göstergesini önceden doldur
    xhrGet('/alpha/regime', function(reg){ renderRegime(reg); });
    setTimeout(checkKararPanel, 800);
    console.log('[alpha-inject] aktif');
  }

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
"""


_router = APIRouter(tags=["alpha-tab-integration"])


@_router.get("/alpha-inject.js")
async def serve_alpha_inject_js():
    return PlainTextResponse(
        content=INJECT_JS,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=120"},
    )


INJECT_TAG = '<script src="/alpha-inject.js" defer></script>'


def install_alpha_tab(app: FastAPI) -> None:
    """
    ALPHA frontend entegrasyonunu kurar.
    main.py'a 2 satır:
        from alpha_tab_integration import install_alpha_tab
        install_alpha_tab(app)
    """
    app.include_router(_router)

    @app.middleware("http")
    async def _alpha_tab_middleware(request: Request, call_next):
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
                content=body,
                status_code=response.status_code,
                headers={k: v for k, v in response.headers.items()
                         if k.lower() not in ("content-length", "content-encoding")},
                media_type=response.media_type,
            )

        if "alpha-inject.js" in text:
            new_text = text
        else:
            idx = text.rfind("</body>")
            if idx == -1:
                new_text = text + "\n" + INJECT_TAG + "\n"
            else:
                new_text = text[:idx] + INJECT_TAG + "\n" + text[idx:]

        new_body = new_text.encode("utf-8")
        new_headers = {}
        for k, v in response.headers.items():
            lk = k.lower()
            if lk in ("content-length", "content-encoding"):
                continue
            new_headers[k] = v
        new_headers["content-length"] = str(len(new_body))

        return Response(
            content=new_body,
            status_code=response.status_code,
            headers=new_headers,
            media_type="text/html; charset=utf-8",
        )
