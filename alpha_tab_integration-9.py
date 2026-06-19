"""
═══════════════════════════════════════════════════════════════
alpha_tab_integration.py — KSŞ PANELİNE NVS ROZETİ v1.0
───────────────────────────────────────────────────────────────
BİRLEŞİK/ALPHA sistemi İPTAL edildi. Bu dosya artık SADECE:
  KSŞ (Kesişim Tarayıcı) panelindeki her hisse satırının yanına
  o hissenin NVS değerini rozet olarak ekler.

Veri kaynağı: mevcut /scan endpoint (NVS, dokunulmadı).
DOM: KSŞ satırları .xc-row + data-symbol="SYM".

KURULUM (main.py'da TEK satır kalır):
    from alpha_tab_integration import install_alpha_tab
    install_alpha_tab(app)

İPTAL için main.py'dan ŞUNLARI SİL (varsa):
    from alpha_engine import alpha_router / app.include_router(alpha_router)
    from unified import unified_router  / app.include_router(unified_router)
═══════════════════════════════════════════════════════════════
"""
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import PlainTextResponse


INJECT_JS = r"""
/*! Fraktal Kahin · KSŞ NVS Rozeti v1.0 */
(function(){
  'use strict';
  var FLAG = '__kss_nvs_badge_v1__';
  if (window[FLAG]) return;
  window[FLAG] = true;

  var NVS = {};        // {SYM: {n:nvs, l:label}}
  var loaded = false;
  var loading = false;

  function xhrGet(url, cb, errCb){
    var x = new XMLHttpRequest();
    x.open('GET', url, true);
    x.timeout = 70000;
    x.onload = function(){
      if (x.status >= 200 && x.status < 300){
        try { cb(JSON.parse(x.responseText)); } catch(e){ if(errCb)errCb(e); }
      } else if (errCb) errCb(new Error('HTTP ' + x.status));
    };
    x.onerror = function(){ if (errCb) errCb(new Error('net')); };
    x.ontimeout = function(){ if (errCb) errCb(new Error('timeout')); };
    x.send();
  }

  function nvsColor(n){
    if (n == null) return '#6b7280';
    if (n >= 80) return '#22c55e';   // GÜÇLÜ AL
    if (n >= 65) return '#9acd32';   // AL
    if (n >= 45) return '#e8b84b';   // NÖTR
    if (n >= 30) return '#f08080';   // SAT
    return '#ef4444';                // GÜÇLÜ SAT
  }
  function nvsShort(n){
    if (n == null) return '—';
    if (n >= 80) return 'G.AL';
    if (n >= 65) return 'AL';
    if (n >= 45) return 'NÖTR';
    if (n >= 30) return 'SAT';
    return 'G.SAT';
  }

  function loadNVS(cb){
    if (loaded){ if(cb)cb(); return; }
    if (loading){ return; }
    loading = true;
    xhrGet('/scan?limit=700', function(d){
      loading = false;
      var arr = (d && d.sonuclar) ? d.sonuclar : [];
      var m = {}, i;
      for (i=0;i<arr.length;i++){
        var r = arr[i];
        var sym = (r.sembol || '').toUpperCase();
        if (sym) m[sym] = {n: r.nvs, l: r.nvs_label, dc: r.gunluk_degisim, g: r.guven_skoru};
      }
      NVS = m; loaded = true;
      if (cb) cb();
    }, function(){ loading = false; });
  }

  function addStyle(){
    if (document.getElementById('kss-nvs-style')) return;
    var s = document.createElement('style');
    s.id = 'kss-nvs-style';
    s.textContent =
      '.kss-nvs{display:inline-flex;flex-direction:column;align-items:center;' +
      'justify-content:center;min-width:42px;padding:2px 5px;border-radius:5px;' +
      'margin-right:6px;line-height:1.1;flex-shrink:0}' +
      '.kss-nvs .nv{font-size:14px;font-weight:800}' +
      '.kss-nvs .nl{font-size:7px;font-weight:700;opacity:.85;letter-spacing:.3px}' +
      '.kss-nvs .gs{font-size:8px;font-weight:800;color:#e8b84b;margin-top:1px;letter-spacing:.2px}';
    document.head.appendChild(s);
  }

  function makeBadge(sym){
    var info = NVS[sym];
    var n = info ? info.n : null;
    var g = info ? info.g : null;
    var col = nvsColor(n);
    var b = document.createElement('div');
    b.className = 'kss-nvs';
    b.setAttribute('data-nvs-for', sym);
    b.setAttribute('data-nvs-val', String(n));
    b.style.background = col + '1f';
    b.style.border = '1px solid ' + col + '55';
    b.innerHTML = '<span class="nv" style="color:' + col + '">' +
                  (n != null ? Math.round(n) : '—') + '</span>' +
                  '<span class="nl" style="color:' + col + '">NVS·' + nvsShort(n) + '</span>' +
                  '<span class="gs">GS ' + (g != null ? Math.round(g) : '—') + '</span>';
    return b;
  }

  var working = false;
  function applyBadges(){
    if (working) return;
    var rows = document.querySelectorAll('.xc-row');
    if (!rows || rows.length === 0) return;
    working = true;
    try {
      var i;
      for (i=0;i<rows.length;i++){
        var row = rows[i];
        var sym = (row.getAttribute('data-symbol') || '').toUpperCase();
        if (!sym) continue;
        var info = NVS[sym];

        // ── EN SAĞ % → GÜN İÇİ (günlük) değişim (/scan gunluk_degisim) ──
        // Panel haftalık değişimi basıyor; biz onu günlük ile değiştiriyoruz.
        var pctEl = row.querySelector('.xc-pct');
        if (pctEl && info && info.dc != null && !isNaN(info.dc)){
          var dc = Number(info.dc);
          pctEl.textContent = (dc >= 0 ? '+' : '') + dc.toFixed(2) + '%';
          pctEl.className = 'xc-pct ' + (dc > 0 ? 'up' : (dc < 0 ? 'down' : 'zero'));
        }

        var valStr = info && info.n != null ? String(info.n) : 'null';
        var ex = row.querySelector('.kss-nvs');
        if (ex){
          if (ex.getAttribute('data-nvs-val') === valStr) continue;
          ex.parentNode.removeChild(ex);
        }
        // En sola, .xc-left'ten ÖNCE ekle → NVS ilk görünür
        var badge = makeBadge(sym);
        if (row.firstChild) row.insertBefore(badge, row.firstChild);
        else row.appendChild(badge);
      }
    } catch(e){}
    setTimeout(function(){ working = false; }, 60);
  }

  var deb = null;
  function onMut(){
    // KSŞ satırı var mı? Varsa NVS yükle + rozetle
    if (document.querySelector('.xc-row')){
      if (!loaded){ loadNVS(function(){ applyBadges(); }); }
      else {
        if (deb) clearTimeout(deb);
        deb = setTimeout(applyBadges, 150);
      }
    }
  }

  // 📊 SİNYAL DOĞRULAMA butonu — artık üst "Sırala" satırında, KSŞ'nin yanında.
  // KSŞ butonu (xover-btn-main) crossover-inject.js tarafından geç eklenebildiği
  // için onu bekleyip hemen sağına yerleştiriyoruz. Bulunamazsa #sortbar sonuna,
  // o da yoksa son çare eski sabit (köşe) konuma düşer.
  function addTrackerButton(){
    if (document.getElementById('trk-fab')) return;
    var tries = 0;
    function place(){
      if (document.getElementById('trk-fab')) return;
      tries++;
      var b = document.createElement('button');
      b.id = 'trk-fab';
      b.type = 'button';
      b.textContent = '📊';
      b.title = 'Sinyal Doğrulama Paneli';
      b.style.cssText = 'flex-shrink:0;margin-left:5px;background:rgba(96,165,250,.16);' +
        'border:1px solid #60a5fa;color:#9fd;font-size:13px;font-weight:700;' +
        'border-radius:7px;padding:6px 10px;cursor:pointer;line-height:1';
      b.onclick = function(){ window.location.href = '/tracker/dashboard'; };

      var ksb = document.getElementById('xover-btn-main');
      if (ksb && ksb.parentNode){
        if (ksb.nextSibling) ksb.parentNode.insertBefore(b, ksb.nextSibling);
        else ksb.parentNode.appendChild(b);
        return;
      }
      var sortbar = document.getElementById('sortbar');
      if (sortbar){
        sortbar.appendChild(b);
        return;
      }
      if (tries < 40){ setTimeout(place, 250); return; }
      // Son çare: eski sabit (köşe) konum
      b.style.cssText = 'position:fixed;right:12px;top:180px;z-index:99998;' +
        'width:50px;height:50px;border-radius:50%;background:rgba(96,165,250,.18);' +
        'border:1.5px solid #60a5fa;color:#9fd;font-size:20px;cursor:pointer;' +
        'display:flex;align-items:center;justify-content:center;box-shadow:0 2px 12px rgba(0,0,0,.5)';
      document.body.appendChild(b);
    }
    place();
  }

  function openFromUrl(){
    var m = location.search.match(/[?&]sym=([^&]+)/);
    if (!m) return;
    var sym = '';
    try { sym = decodeURIComponent(m[1]).toUpperCase(); } catch(e){ sym = m[1].toUpperCase(); }
    if (!/^[A-ZÇĞİÖŞÜ0-9]{2,8}$/.test(sym)) return;
    var tries = 0;
    function tryOpen(){
      tries++;
      if (typeof window.openDetail === 'function'){
        try { window.openDetail(sym); } catch(e){}
        // URL'i temizle ki yenilemede tekrar açılmasın
        try { if (history.replaceState) history.replaceState(null, '', location.pathname); } catch(e){}
        return;
      }
      if (tries < 40) setTimeout(tryOpen, 300);
    }
    setTimeout(tryOpen, 500);
  }

  function autoRunLabFrak(){
    // Detay paneli TAM render olunca (renderDetail bitince) FRAKTAL + LAB çalıştır.
    // Kritik: renderDetail bitmeden çalışırsan, sonra renderDetail paneli yeniden
    // çizip fraktal sonucunu siler. rbig "NVS ..." gösterince renderDetail bitmiştir.
    var n = 0;
    var iv = setInterval(function(){
      n++;
      var rbig = document.getElementById('rbig');
      var frCard = document.getElementById('fr-detail-card');
      var rendered = frCard && rbig && /NVS/.test(rbig.textContent || '');
      if (rendered){
        clearInterval(iv);
        // renderDetail bitti + panel oturdu → kısa bekle, sonra çalıştır
        setTimeout(function(){
          try { if (typeof window.repFraktal === 'function') window.repFraktal(); } catch(e){}
          // LAB'ı biraz sonra (fraktal render'ı bitsin, ikisi çakışmasın)
          setTimeout(function(){
            try { if (typeof window.repLab === 'function') window.repLab(); } catch(e){}
          }, 900);
        }, 350);
      } else if (n > 45){
        clearInterval(iv);
      }
    }, 200);
  }

  function installAutoRun(){
    if (window.__kss_autorun) return;
    var tries = 0;
    var iv = setInterval(function(){
      tries++;
      if (typeof window.openDetail === 'function' && !window.openDetail.__wrapped){
        clearInterval(iv);
        var orig = window.openDetail;
        var wrapped = function(){
          var ret;
          try { ret = orig.apply(this, arguments); } catch(e){}
          autoRunLabFrak();
          return ret;
        };
        wrapped.__wrapped = true;
        window.openDetail = wrapped;
        window.__kss_autorun = true;
      } else if (tries > 60){
        clearInterval(iv);
      }
    }, 250);
  }

  function start(){
    addStyle();
    addTrackerButton();
    installAutoRun();
    openFromUrl();
    var mo = new MutationObserver(onMut);
    mo.observe(document.body, {childList:true, subtree:true});
    // KSŞ paneli açılmadan da NVS'i önden yükle (panel açılınca anında bassın)
    setTimeout(function(){ loadNVS(function(){ applyBadges(); }); }, 2000);
    console.log('[kss-nvs] aktif');
  }

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', start);
  } else { start(); }
})();
"""


_router = APIRouter(tags=["kss-nvs-integration"])


@_router.get("/alpha-inject.js")
async def serve_inject_js():
    return PlainTextResponse(
        content=INJECT_JS,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=60"},
    )


INJECT_TAG = '<script src="/alpha-inject.js" defer></script>'


def install_alpha_tab(app: FastAPI) -> None:
    app.include_router(_router)

    # ── OTONOM 18:30 ZAMANLAYICI (kendi kendine öğrenen döngü) ──────────
    # main.py'ya dokunmadan, burada (zaten import edilen bir modülde) başlatılır.
    # İçeride tek-sefer guard var; install iki kez çağrılsa bile bir kez başlar.
    try:
        from auto_scheduler import start_scheduler
        start_scheduler()
    except Exception as _e:
        print("[auto_scheduler] başlatılamadı:", str(_e)[:160])

    @app.middleware("http")
    async def _kss_nvs_middleware(request: Request, call_next):
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
