"""
================================================================
Vortex-BIST · Kesişim Tab Entegrasyonu
================================================================
Ana sayfaya (/) "🎯 KSŞ" tabı ekler. HTML dosyana DOKUNMAZ.
Crossover scanner'ı tam ekran iframe overlay olarak açar.

KURULUM (main.py'a 2 satır):
    from tab_integration import install_crossover_tab
    install_crossover_tab(app)

GERİ ALMA: yukarıdaki 2 satırı sil — sistem bit-aynı eski haline döner.

NASIL ÇALIŞIR:
  1. /crossover-inject.js → küçük bir JS dosyası servisi
  2. Middleware → sadece "/" path'i HTML ise </body> öncesi
                  tek <script src="/crossover-inject.js"> ekler
  3. Diğer endpoint'ler (NVS, FRAK, LAB, SAT, BCKT, PRT, /crossover/,
                          tüm API'ler) hiç etkilenmez.

GÜVENLİK:
  - Sadece request.url.path == "/" işlenir
  - Sadece content-type "text/html" yanıtlar işlenir
  - </body> yoksa script sonuna eklenir
  - Decode hatası varsa orijinal body olduğu gibi döner
  - Hata durumunda yanıt değişmeden geçer (try/except)
================================================================
"""

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import PlainTextResponse


# ================================================================
# INJECT JS — ana sayfada çalışıp tab ekleyen JavaScript
# ================================================================

INJECT_JS = r"""
/*! Vortex-BIST Crossover Tab Injector v1.0 */
(function(){
  'use strict';

  var FLAG = '__xover_tab_injected__';
  if (window[FLAG]) return;
  window[FLAG] = true;

  var MAX_TRIES = 60;     // 60 * 200ms = 12 saniye
  var POLL_MS   = 200;
  var tries     = 0;

  // ------------------------------------------------------------
  // Tab bar tespiti — text matching ile defensive
  // ------------------------------------------------------------
  function findTabBar() {
    var sel = 'button, a, div, span, li';
    var els = document.querySelectorAll(sel);
    var nvsEl = null;

    // "NVS" içeren küçük element bul
    for (var i = 0; i < els.length; i++) {
      var t = (els[i].textContent || '').trim();
      if (t.length === 0 || t.length > 30) continue;
      if (t.indexOf('NVS') === -1) continue;
      // "NVS Sırala" gibi başlıkları ekarte et
      if (t.toLowerCase().indexOf('sırala') !== -1) continue;
      // Tab benzeri kısa text
      if (t.length < 20) {
        nvsEl = els[i];
        break;
      }
    }
    if (!nvsEl) return null;

    // Parent zincirinde FRAK + LAB + SAT içeren ilk container = tab bar
    var p = nvsEl.parentNode;
    for (var d = 0; d < 6 && p && p !== document.body; d++) {
      var pt = (p.textContent || '');
      if (pt.indexOf('FRAK') !== -1 &&
          pt.indexOf('LAB')  !== -1 &&
          pt.indexOf('SAT')  !== -1 &&
          pt.indexOf('BCKT') !== -1) {
        return { bar: p, sample: nvsEl };
      }
      p = p.parentNode;
    }
    return null;
  }

  // ------------------------------------------------------------
  // Stil ekleme — mevcut tema ile uyumlu
  // ------------------------------------------------------------
  function addStyles() {
    if (document.getElementById('xover-style')) return;
    var s = document.createElement('style');
    s.id = 'xover-style';
    s.textContent = (
      '#xover-tab-btn{display:inline-flex;align-items:center;gap:4px;' +
      'padding:8px 12px;margin:0 2px;background:transparent;' +
      'border:1px solid transparent;color:#7ed321;font:inherit;' +
      'font-size:14px;cursor:pointer;border-radius:6px;' +
      'transition:background .15s,border-color .15s;' +
      'letter-spacing:.3px;white-space:nowrap;}' +
      '#xover-tab-btn:hover{border-color:rgba(126,211,33,.5);' +
      'background:rgba(126,211,33,.06);}' +
      '#xover-tab-btn.active{border-color:#7ed321;' +
      'background:rgba(126,211,33,.12);}' +
      '#xover-overlay{position:fixed;inset:0;background:#000;' +
      'z-index:99999;display:none;flex-direction:column;}' +
      '#xover-overlay.open{display:flex;}' +
      '#xover-bar{display:flex;align-items:center;gap:10px;' +
      'padding:10px 14px;background:#0a0a0a;' +
      'border-bottom:1px solid #1f1f1f;color:#7ed321;' +
      'font:600 15px system-ui,-apple-system,sans-serif;' +
      'letter-spacing:.5px;}' +
      '#xover-title{flex:1;}' +
      '#xover-close{background:#1a1a1a;color:#fff;' +
      'border:1px solid #2a2a2a;padding:8px 14px;border-radius:6px;' +
      'font:500 14px system-ui,sans-serif;cursor:pointer;' +
      'transition:background .15s;}' +
      '#xover-close:hover{background:#222;}' +
      '#xover-close:active{background:#333;}' +
      '#xover-frame{flex:1;border:none;width:100%;background:#0a0a0a;}' +
      '#xover-fab{position:fixed;bottom:84px;right:14px;z-index:9998;' +
      'padding:12px 18px;border-radius:26px;background:#0a0a0a;' +
      'border:1px solid #7ed321;color:#7ed321;font-size:15px;' +
      'box-shadow:0 4px 14px rgba(0,0,0,.7);cursor:pointer;' +
      'font-weight:600;}'
    );
    document.head.appendChild(s);
  }

  // ------------------------------------------------------------
  // Overlay (iframe) inşa
  // ------------------------------------------------------------
  function buildOverlay() {
    if (document.getElementById('xover-overlay')) {
      return openOverlayHandle(document.getElementById('xover-overlay'));
    }
    var o = document.createElement('div');
    o.id = 'xover-overlay';

    var bar = document.createElement('div');
    bar.id = 'xover-bar';

    var title = document.createElement('span');
    title.id = 'xover-title';
    title.textContent = '🎯 KESİŞİM TARAYICI · Supertrend × LSMA';

    var closeBtn = document.createElement('button');
    closeBtn.id = 'xover-close';
    closeBtn.type = 'button';
    closeBtn.textContent = '✕ Kapat';

    bar.appendChild(title);
    bar.appendChild(closeBtn);

    var frame = document.createElement('iframe');
    frame.id = 'xover-frame';
    frame.setAttribute('src', 'about:blank');

    o.appendChild(bar);
    o.appendChild(frame);
    document.body.appendChild(o);

    var loaded = false;
    closeBtn.addEventListener('click', function(){
      o.classList.remove('open');
      var btn = document.getElementById('xover-tab-btn');
      if (btn) btn.classList.remove('active');
    });

    return {
      open: function(){
        if (!loaded) { frame.src = '/crossover/'; loaded = true; }
        o.classList.add('open');
      }
    };
  }

  function openOverlayHandle(o) {
    return { open: function(){ o.classList.add('open'); } };
  }

  // ------------------------------------------------------------
  // Floating fallback button (tab bar bulunamazsa)
  // ------------------------------------------------------------
  function addFloatingButton(overlay) {
    if (document.getElementById('xover-fab')) return;
    var fb = document.createElement('button');
    fb.id = 'xover-fab';
    fb.type = 'button';
    fb.textContent = '🎯 KSŞ';
    fb.title = 'Kesişim Tarayıcı';
    fb.addEventListener('click', function(e){
      e.preventDefault();
      e.stopPropagation();
      overlay.open();
    });
    document.body.appendChild(fb);
  }

  // ------------------------------------------------------------
  // Ana inject akışı
  // ------------------------------------------------------------
  function tryInject() {
    if (document.getElementById('xover-tab-btn')) return;

    var info = findTabBar();
    if (!info) {
      tries++;
      if (tries < MAX_TRIES) {
        setTimeout(tryInject, POLL_MS);
      } else {
        // Son çare: floating buton
        addStyles();
        var ov = buildOverlay();
        addFloatingButton(ov);
      }
      return;
    }

    addStyles();
    var overlay = buildOverlay();

    var btn = document.createElement('button');
    btn.id = 'xover-tab-btn';
    btn.type = 'button';
    btn.textContent = '🎯 KSŞ';
    btn.title = 'Kesişim Tarayıcı (Supertrend × LSMA)';
    btn.addEventListener('click', function(e){
      e.preventDefault();
      e.stopPropagation();
      btn.classList.add('active');
      overlay.open();
    });

    try {
      info.bar.appendChild(btn);
    } catch (err) {
      addFloatingButton(overlay);
    }
  }

  function start() {
    setTimeout(tryInject, 150);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
"""


# ================================================================
# ROUTER — /crossover-inject.js
# ================================================================

_router = APIRouter(tags=["crossover-tab-integration"])


@_router.get("/crossover-inject.js")
async def serve_inject_js():
    return PlainTextResponse(
        content=INJECT_JS,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=300"},
    )


# ================================================================
# MIDDLEWARE — </body> öncesi <script> inject
# ================================================================

INJECT_TAG = '<script src="/crossover-inject.js" defer></script>'


def install_crossover_tab(app: FastAPI) -> None:
    """
    Ana FastAPI uygulamasına Kesişim Tab entegrasyonunu kurar.

    Kullanım (main.py'a 2 satır):
        from tab_integration import install_crossover_tab
        install_crossover_tab(app)

    Bu fonksiyon:
      • /crossover-inject.js endpoint'ini açar (~5 KB JS).
      • Sadece "/" path'i için bir HTTP middleware ekler.
      • Yanıt HTML değilse ya da hata olursa karışmaz, olduğu gibi geçirir.

    Mevcut hiçbir endpoint, hiçbir API, hiçbir HTML dosyası değişmez.
    """
    # Router'ı dahil et
    app.include_router(_router)

    # Middleware: sadece "/" için HTML yanıta script inject
    @app.middleware("http")
    async def _xover_tab_middleware(request: Request, call_next):
        # 1) Sadece tam kök path
        if request.url.path not in ("/", ""):
            return await call_next(request)

        # 2) Sadece GET
        if request.method.upper() != "GET":
            return await call_next(request)

        # 3) Yanıtı al
        try:
            response = await call_next(request)
        except Exception:
            raise

        # 4) HTML mi?
        ct = (response.headers.get("content-type", "") or "").lower()
        if "text/html" not in ct:
            return response

        # 4b) Sıkıştırılmış mı? Karışma (gzip/br/deflate decode etmiyoruz)
        ce = (response.headers.get("content-encoding", "") or "").lower().strip()
        if ce and ce not in ("identity", ""):
            return response

        # 5) Body'yi topla (streaming/normal fark etmez)
        try:
            chunks = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                chunks.append(chunk)
            body = b"".join(chunks)
        except Exception:
            return response

        # 6) Decode + inject
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            # UTF-8 değilse karışma — orijinal byte'ları geri ver
            return Response(
                content=body,
                status_code=response.status_code,
                headers={
                    k: v for k, v in response.headers.items()
                    if k.lower() not in ("content-length", "content-encoding")
                },
                media_type=response.media_type,
            )

        # Çift inject olmasın
        if "crossover-inject.js" in text:
            new_text = text
        else:
            idx = text.rfind("</body>")
            if idx == -1:
                # </body> yoksa sonuna ekle
                new_text = text + "\n" + INJECT_TAG + "\n"
            else:
                new_text = text[:idx] + INJECT_TAG + "\n" + text[idx:]

        new_body = new_text.encode("utf-8")

        # 7) Header'ları temizle (length/encoding)
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
