"""
================================================================
Vortex-BIST · Kesişim Tab Entegrasyonu  (v2)
================================================================
Ana sayfaya "🎯 KSŞ" butonu ekler (Sırala satırının sonuna).
HTML/CSS dosyalarına DOKUNMAZ — sadece middleware ile script enjekte eder.

YENİLİKLER (v2):
  • Buton "Sırala:" satırının sonuna gelir (öncesinde yüzen buton)
  • Tıklayınca tarama in-place başlar, sayfa değişmez
  • Sonuçlar sağ sütunu kaplayan overlay kartlar olarak gelir
  • Her karta tıklayınca sol listedeki sembole click simülasyonu yapılır
    → Mevcut NİHAİ KARAR (LAB/FRAK/TV) paneli otomatik açılır

KURULUM (main.py'a 2 satır):
    from tab_integration import install_crossover_tab
    install_crossover_tab(app)

GERİ ALMA: o 2 satırı sil — sistem bit-aynı eski haline döner.
================================================================
"""

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import PlainTextResponse


# ================================================================
# INJECT JS — ana sayfada çalışan client kodu
# ================================================================

INJECT_JS = r"""
/*! Vortex-BIST · Crossover Tab Injector v2.0 */
(function(){
  'use strict';

  var FLAG = '__xover_tab_v2__';
  if (window[FLAG]) return;
  window[FLAG] = true;

  var MAX_TRIES = 80;
  var POLL_MS   = 200;
  var tries     = 0;

  var SCAN_URL   = '/crossover/api/scan';
  var STATUS_URL = '/crossover/api/status';

  // ============================================================
  // XHR yardımcısı
  // ============================================================
  function xhrGet(url, cb, errCb) {
    var x = new XMLHttpRequest();
    x.open('GET', url, true);
    x.timeout = 600000;
    x.onload = function(){
      if (x.status >= 200 && x.status < 300) {
        try { cb(JSON.parse(x.responseText)); }
        catch(e) { if (errCb) errCb(e); }
      } else if (errCb) errCb(new Error('HTTP ' + x.status));
    };
    x.onerror = function(){ if (errCb) errCb(new Error('network')); };
    x.ontimeout = function(){ if (errCb) errCb(new Error('timeout')); };
    x.send();
  }

  // ============================================================
  // Sırala satırını bul
  // ============================================================
  function findSiralaRow() {
    var els = document.querySelectorAll('*');
    var anchor = null;
    for (var i = 0; i < els.length; i++) {
      var t = (els[i].textContent || '').trim();
      if (t.length === 0 || t.length > 200) continue;
      if (t.toLowerCase().indexOf('sırala') === -1) continue;
      if (t.indexOf('NVS') === -1 || t.indexOf('A-Z') === -1) continue;
      anchor = els[i];
      break;
    }
    if (!anchor) return null;

    var azBtn = null;
    var candidates = anchor.querySelectorAll('button, span, div, a');
    for (var j = 0; j < candidates.length; j++) {
      var ct = (candidates[j].textContent || '').trim();
      if (ct === 'A-Z' || (ct.indexOf('A-Z') !== -1 && ct.length < 8)) {
        azBtn = candidates[j];
      }
    }
    if (!azBtn) return null;
    return { row: azBtn.parentNode, sampleBtn: azBtn };
  }

  // ============================================================
  // Sol sembol listesini bul
  // ============================================================
  function findSymbolList() {
    var all = document.querySelectorAll('div, li, a, span, tr');
    var hits = ['DUNYH','ALVES','ANGEN','KOPOL','INTEM','KZGYO','ULUSE','TNZTP','BVSAN','BIZIM'];
    var best = null;
    var bestCount = 0;
    var visited = {};

    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      var parent = el.parentNode;
      if (!parent) continue;
      var key = parent.tagName + '_' + ((parent.className||'')+'').slice(0,30);
      if (visited[key]) continue;
      visited[key] = true;

      var kids = parent.children;
      var count = 0;
      for (var k = 0; k < kids.length && k < 60; k++) {
        var kt = (kids[k].textContent || '').trim();
        var firstWord = kt.split(/\s+/)[0].replace(/[^A-ZÇĞİÖŞÜ]/g,'');
        if (firstWord.length >= 3 && firstWord.length <= 7 &&
            firstWord === firstWord.toUpperCase() && firstWord.length > 0) {
          count++;
        }
        for (var h = 0; h < hits.length; h++) {
          if (kt.indexOf(hits[h]) !== -1) { count += 3; break; }
        }
      }
      if (count > bestCount) {
        bestCount = count;
        best = parent;
      }
    }
    if (bestCount < 5) return null;
    return best;
  }

  // ============================================================
  // Sembole sol listede tıkla (NİHAİ KARAR'ı tetikler)
  // ============================================================
  function clickSymbolInList(symbol) {
    var list = findSymbolList();
    if (!list) return false;

    var kids = list.querySelectorAll('*');
    for (var i = 0; i < kids.length; i++) {
      var t = (kids[i].textContent || '').trim();
      if (!t) continue;
      var firstWord = t.split(/\s+/)[0].replace(/[^A-ZÇĞİÖŞÜ]/g,'');
      if (firstWord === symbol) {
        var target = kids[i];
        // En tıklanabilir atayı bul
        var p = target;
        for (var d = 0; d < 4 && p && p !== list; d++) {
          if (p.onclick || p.tagName === 'BUTTON' || p.tagName === 'A' ||
              p.getAttribute('role') === 'button' ||
              (p.style && p.style.cursor === 'pointer')) {
            target = p;
            break;
          }
          p = p.parentNode;
        }
        try { target.scrollIntoView({block:'center', behavior:'auto'}); } catch(e){}
        try { target.click(); } catch(e1){}
        try {
          var ev = document.createEvent('MouseEvents');
          ev.initEvent('click', true, true);
          target.dispatchEvent(ev);
        } catch(e2){}
        return true;
      }
    }
    return false;
  }

  // ============================================================
  // Stil dosyası
  // ============================================================
  function injectStyles() {
    if (document.getElementById('xover-style-v2')) return;
    var s = document.createElement('style');
    s.id = 'xover-style-v2';
    s.textContent = (
      '#xover-btn-main{display:inline-flex;align-items:center;gap:5px;' +
      'padding:6px 14px;margin-left:6px;background:rgba(126,211,33,.08);' +
      'border:1px solid #7ed321;color:#7ed321;font:600 13px inherit;' +
      'cursor:pointer;border-radius:8px;letter-spacing:.4px;' +
      'transition:background .15s,box-shadow .15s;white-space:nowrap;}' +
      '#xover-btn-main:hover{background:rgba(126,211,33,.18);' +
      'box-shadow:0 0 0 2px rgba(126,211,33,.18);}' +
      '#xover-btn-main:active{background:rgba(126,211,33,.28);}' +
      '#xover-btn-main.scanning{background:rgba(245,197,66,.15);' +
      'border-color:#f5c542;color:#f5c542;}' +
      '#xover-btn-main .dot{width:8px;height:8px;border-radius:50%;' +
      'background:currentColor;display:inline-block;}' +
      '#xover-panel{position:fixed;inset:0;background:rgba(0,0,0,.92);' +
      'z-index:99999;display:none;flex-direction:column;}' +
      '#xover-panel.open{display:flex;}' +
      '#xover-head{display:flex;align-items:center;gap:10px;' +
      'padding:12px 14px;background:#0a0a0a;border-bottom:1px solid #1f1f1f;' +
      'color:#7ed321;font:600 15px system-ui,sans-serif;letter-spacing:.5px;}' +
      '#xover-head .ttl{flex:1;}' +
      '#xover-head .ts{font-size:11px;color:#888;font-weight:400;}' +
      '#xover-close-btn{background:#1a1a1a;color:#fff;border:1px solid #2a2a2a;' +
      'padding:8px 14px;border-radius:8px;font:500 14px inherit;cursor:pointer;}' +
      '#xover-close-btn:active{background:#333;}' +
      '#xover-filters{display:flex;gap:6px;flex-wrap:wrap;padding:10px 14px;' +
      'background:#0a0a0a;border-bottom:1px solid #1f1f1f;}' +
      '#xover-filters .f{padding:6px 12px;border-radius:18px;cursor:pointer;' +
      'font:500 12px system-ui,sans-serif;border:1px solid #2a2a2a;' +
      'background:#0f0f0f;color:#bbb;letter-spacing:.4px;}' +
      '#xover-filters .f.act{background:#1a2a1a;color:#7ed321;border-color:#7ed321;}' +
      '#xover-filters .f .n{margin-left:5px;opacity:.7;font-weight:400;}' +
      '#xover-list{flex:1;overflow-y:auto;background:#050505;padding:8px 0;' +
      '-webkit-overflow-scrolling:touch;}' +
      '.xc-row{display:flex;align-items:center;gap:12px;padding:12px 14px;' +
      'border-bottom:1px solid #111;cursor:pointer;transition:background .12s;}' +
      '.xc-row:active{background:#0f1a0f;}' +
      '.xc-row:hover{background:#0a1208;}' +
      '.xc-left{flex:0 0 auto;min-width:78px;}' +
      '.xc-sym{font:700 17px system-ui,sans-serif;color:#fff;letter-spacing:.5px;}' +
      '.xc-price{font:500 12px system-ui,sans-serif;color:#888;margin-top:2px;}' +
      '.xc-mid{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px;}' +
      '.xc-badges{display:flex;gap:5px;flex-wrap:wrap;align-items:center;}' +
      '.xc-cat{padding:3px 9px;border-radius:11px;' +
      'font:600 11px system-ui,sans-serif;letter-spacing:.6px;}' +
      '.xc-cat.YENI{background:rgba(126,211,33,.16);color:#7ed321;' +
      'border:1px solid rgba(126,211,33,.4);}' +
      '.xc-cat.ORTA{background:rgba(245,197,66,.16);color:#f5c542;' +
      'border:1px solid rgba(245,197,66,.4);}' +
      '.xc-cat.YUKSEK{background:rgba(255,90,90,.14);color:#ff5a5a;' +
      'border:1px solid rgba(255,90,90,.35);}' +
      '.xc-info{font:500 11px system-ui,sans-serif;color:#888;}' +
      '.xc-pct{font:700 14px system-ui,sans-serif;color:#7ed321;' +
      'min-width:62px;text-align:right;}' +
      '.xc-arrow{color:#444;font-size:18px;margin-left:6px;}' +
      '#xover-state{padding:30px 14px;text-align:center;color:#aaa;' +
      'font:500 14px system-ui,sans-serif;}' +
      '#xover-state .big{font:700 28px system-ui,sans-serif;color:#7ed321;' +
      'margin:8px 0;}' +
      '#xover-state .bar{width:80%;max-width:300px;height:6px;background:#1a1a1a;' +
      'border-radius:3px;margin:14px auto;overflow:hidden;}' +
      '#xover-state .fill{height:100%;background:#7ed321;width:0%;' +
      'transition:width .3s;}' +
      '#xover-state .err{color:#ff5a5a;}' +
      '#xover-state .hint{margin-top:14px;font-size:12px;color:#666;}' +
      '#xover-fab{position:fixed;bottom:90px;right:14px;z-index:9998;' +
      'padding:13px 18px;border-radius:28px;background:#0a0a0a;' +
      'border:1px solid #7ed321;color:#7ed321;font:600 14px system-ui,sans-serif;' +
      'box-shadow:0 4px 16px rgba(0,0,0,.8);cursor:pointer;}'
    );
    document.head.appendChild(s);
  }

  // ============================================================
  // Overlay panel
  // ============================================================
  var panelEl = null;
  var stateEl = null;
  var filtersEl = null;
  var listEl = null;
  var DATA = [];
  var FILTER = 'ALL';
  var pollTimer = null;
  var lastScanTs = null;

  function buildPanel() {
    if (panelEl) return panelEl;
    var p = document.createElement('div');
    p.id = 'xover-panel';

    var head = document.createElement('div');
    head.id = 'xover-head';

    var ttl = document.createElement('span');
    ttl.className = 'ttl';
    ttl.textContent = '🎯 KESİŞİM TARAYICI · ST × LSMA';

    var ts = document.createElement('span');
    ts.className = 'ts';
    ts.id = 'xover-ts';

    var close = document.createElement('button');
    close.id = 'xover-close-btn';
    close.type = 'button';
    close.textContent = '✕ Kapat';
    close.addEventListener('click', closePanel);

    head.appendChild(ttl);
    head.appendChild(ts);
    head.appendChild(close);

    filtersEl = document.createElement('div');
    filtersEl.id = 'xover-filters';
    filtersEl.style.display = 'none';

    stateEl = document.createElement('div');
    stateEl.id = 'xover-state';

    listEl = document.createElement('div');
    listEl.id = 'xover-list';
    listEl.style.display = 'none';

    p.appendChild(head);
    p.appendChild(filtersEl);
    p.appendChild(stateEl);
    p.appendChild(listEl);
    document.body.appendChild(p);
    panelEl = p;
    return p;
  }

  function openPanel() {
    buildPanel();
    panelEl.classList.add('open');
  }

  function closePanel() {
    if (panelEl) panelEl.classList.remove('open');
    var b = document.getElementById('xover-btn-main');
    if (b) {
      b.classList.remove('scanning');
      b.innerHTML = '🎯 KSŞ';
    }
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  // ============================================================
  // Tarama akışı
  // ============================================================
  function setState(html) {
    if (!stateEl) return;
    stateEl.style.display = 'block';
    if (listEl) listEl.style.display = 'none';
    if (filtersEl) filtersEl.style.display = 'none';
    stateEl.innerHTML = html;
  }

  function setScanningButton(on) {
    var b = document.getElementById('xover-btn-main');
    if (!b) return;
    if (on) {
      b.classList.add('scanning');
      b.innerHTML = '<span class="dot"></span> TARANIYOR…';
    } else {
      b.classList.remove('scanning');
      b.innerHTML = '🎯 KSŞ';
    }
  }

  function startScan(force) {
    openPanel();
    setScanningButton(true);
    setState(
      '<div>Hisseler taranıyor…</div>' +
      '<div class="big" id="xover-prog">0%</div>' +
      '<div class="bar"><div class="fill" id="xover-fill"></div></div>' +
      '<div class="hint">Yaklaşık 2-4 dakika · arka planda çalışır</div>'
    );

    xhrGet(STATUS_URL, function(st){
      if (st && st.scanning) {
        beginPolling();
      } else {
        var url = SCAN_URL + (force ? '?refresh=true' : '');
        xhrGet(url, function(d){
          if (d && d.scanning) {
            beginPolling();
          } else if (d && d.results) {
            renderResults(d);
            setScanningButton(false);
          } else {
            beginPolling();
          }
        }, function(err){
          setScanningButton(false);
          setState('<div class="err">❌ Hata: ' + (err.message||err) + '</div>' +
                   '<div class="hint">Sayfayı yenile veya tekrar dene</div>');
        });
      }
    }, function(err){
      setScanningButton(false);
      setState('<div class="err">❌ Durum alınamadı</div>' +
               '<div class="hint">' + (err.message||err) + '</div>');
    });
  }

  function beginPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(function(){
      xhrGet(STATUS_URL, function(st){
        if (!st) return;
        var pg = document.getElementById('xover-prog');
        var fl = document.getElementById('xover-fill');
        if (pg && fl && typeof st.progress === 'number') {
          var pct = Math.max(0, Math.min(100, Math.round(st.progress * 100)));
          pg.textContent = pct + '%';
          fl.style.width = pct + '%';
        }
        if (!st.scanning && st.has_cache) {
          clearInterval(pollTimer); pollTimer = null;
          xhrGet(SCAN_URL, function(d){
            renderResults(d);
            setScanningButton(false);
          }, function(){
            setScanningButton(false);
            setState('<div class="err">❌ Sonuçlar yüklenemedi</div>');
          });
        }
      }, function(){});
    }, 1500);
  }

  function catKey(c){
    if (c === 'YENİ' || c === 'YENI') return 'YENI';
    if (c === 'YÜKSEK' || c === 'YUKSEK') return 'YUKSEK';
    return 'ORTA';
  }
  function catLabel(c){
    if (c === 'YENI') return 'YENİ';
    if (c === 'YUKSEK') return 'YÜKSEK';
    return 'ORTA';
  }

  function renderResults(d) {
    DATA = (d && d.results) ? d.results : [];
    lastScanTs = d && d.timestamp ? d.timestamp : null;

    var tsEl = document.getElementById('xover-ts');
    if (tsEl && lastScanTs) {
      tsEl.textContent = '· ' + (lastScanTs+'').replace('T',' ').slice(0,16);
    }

    var cy=0, co=0, cu=0;
    for (var i=0; i<DATA.length; i++){
      var k = catKey(DATA[i].category);
      if (k==='YENI') cy++;
      else if (k==='ORTA') co++;
      else cu++;
    }

    filtersEl.innerHTML = '';
    var defs = [
      {k:'ALL',  lbl:'TÜMÜ',   n:DATA.length},
      {k:'YENI', lbl:'🆕 YENİ', n:cy},
      {k:'ORTA', lbl:'⚡ ORTA', n:co},
      {k:'YUKSEK', lbl:'🔥 YÜKSEK', n:cu}
    ];
    for (var j=0; j<defs.length; j++){
      var btn = document.createElement('div');
      btn.className = 'f' + (FILTER===defs[j].k ? ' act' : '');
      btn.setAttribute('data-k', defs[j].k);
      btn.innerHTML = defs[j].lbl + '<span class="n">' + defs[j].n + '</span>';
      btn.addEventListener('click', (function(k){
        return function(){
          FILTER = k;
          var fs = filtersEl.querySelectorAll('.f');
          for (var x=0; x<fs.length; x++){
            if (fs[x].getAttribute('data-k')===k) fs[x].classList.add('act');
            else fs[x].classList.remove('act');
          }
          renderList();
        };
      })(defs[j].k));
      filtersEl.appendChild(btn);
    }
    filtersEl.style.display = 'flex';

    renderList();
  }

  function renderList() {
    if (!listEl) return;
    stateEl.style.display = 'none';
    listEl.style.display = 'block';
    listEl.innerHTML = '';

    var rows = [];
    for (var i=0; i<DATA.length; i++){
      var r = DATA[i];
      var k = catKey(r.category);
      if (FILTER !== 'ALL' && k !== FILTER) continue;
      rows.push({row:r, k:k});
    }

    if (rows.length === 0) {
      listEl.innerHTML = '<div style="padding:40px 14px;text-align:center;color:#666;">' +
                        'Bu filtrede hisse yok</div>';
      return;
    }

    for (var i=0; i<rows.length; i++){
      var r = rows[i].row;
      var k = rows[i].k;
      var d = document.createElement('div');
      d.className = 'xc-row';
      d.setAttribute('data-symbol', r.symbol);

      var cross = r.cross_date ? (r.cross_date+'').slice(5) : '';
      var days = r.days_since_cross != null ? r.days_since_cross + 'g' : '';
      var lb = r.last_bar ? ' · son:' + (r.last_bar+'').slice(5) : '';
      var pctNum = typeof r.pct_change === 'number' ? r.pct_change : 0;
      var pct = (pctNum >= 0 ? '+' : '') + pctNum.toFixed(2) + '%';
      var price = typeof r.current_price === 'number' ? r.current_price : 0;

      d.innerHTML =
        '<div class="xc-left">' +
          '<div class="xc-sym">' + r.symbol + '</div>' +
          '<div class="xc-price">₺' + price.toFixed(2) + '</div>' +
        '</div>' +
        '<div class="xc-mid">' +
          '<div class="xc-badges">' +
            '<span class="xc-cat ' + k + '">' + catLabel(k) + '</span>' +
            '<span class="xc-info">KS: ' + cross + ' · ' + days + lb + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="xc-pct">' + pct + '</div>' +
        '<div class="xc-arrow">›</div>';

      d.addEventListener('click', (function(sym){
        return function(){
          closePanel();
          setTimeout(function(){
            var ok = clickSymbolInList(sym);
            if (!ok) {
              window.location.href = '/crossover/';
            }
          }, 120);
        };
      })(r.symbol));

      listEl.appendChild(d);
    }
  }

  // ============================================================
  // KSŞ butonu Sırala satırına ekle
  // ============================================================
  function injectButton() {
    if (document.getElementById('xover-btn-main')) return;

    var found = findSiralaRow();
    if (!found) {
      tries++;
      if (tries < MAX_TRIES) {
        setTimeout(injectButton, POLL_MS);
      } else {
        injectStyles();
        addFloatingFallback();
      }
      return;
    }

    injectStyles();

    var btn = document.createElement('button');
    btn.id = 'xover-btn-main';
    btn.type = 'button';
    btn.innerHTML = '🎯 KSŞ';
    btn.title = 'Kesişim Tarayıcı · Supertrend × LSMA';
    btn.addEventListener('click', function(e){
      e.preventDefault();
      e.stopPropagation();
      startScan(false);
    });

    try {
      var az = found.sampleBtn;
      if (az && az.nextSibling) {
        az.parentNode.insertBefore(btn, az.nextSibling);
      } else {
        found.row.appendChild(btn);
      }
    } catch(err) {
      try { found.row.appendChild(btn); } catch(e2) { addFloatingFallback(); }
    }
  }

  function addFloatingFallback() {
    if (document.getElementById('xover-fab')) return;
    var fb = document.createElement('button');
    fb.id = 'xover-fab';
    fb.type = 'button';
    fb.textContent = '🎯 KSŞ';
    fb.addEventListener('click', function(){ startScan(false); });
    document.body.appendChild(fb);
  }

  function start() {
    setTimeout(injectButton, 200);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
"""


# ================================================================
# ROUTER
# ================================================================

_router = APIRouter(tags=["crossover-tab-integration-v2"])


@_router.get("/crossover-inject.js")
async def serve_inject_js():
    return PlainTextResponse(
        content=INJECT_JS,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=120"},
    )


# ================================================================
# MIDDLEWARE
# ================================================================

INJECT_TAG = '<script src="/crossover-inject.js" defer></script>'


def install_crossover_tab(app: FastAPI) -> None:
    """
    Ana FastAPI uygulamasına Kesişim Tab entegrasyonunu kurar (v2).

    Kullanım (main.py'a 2 satır):
        from tab_integration import install_crossover_tab
        install_crossover_tab(app)

    v2 yenilikleri:
      • Buton "Sırala:" satırının sonuna yerleşir
      • In-place tarama: ana sayfa korunur
      • Sonuçlar overlay'de ana sayfa stilinde kartlar
      • Karta tıklayınca sol listede sembol click simülasyonu
        → mevcut NİHAİ KARAR paneli açılır
    """
    app.include_router(_router)

    @app.middleware("http")
    async def _xover_tab_middleware(request: Request, call_next):
        if request.url.path not in ("/", ""):
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

        if "crossover-inject.js" in text:
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
