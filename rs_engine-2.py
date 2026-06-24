"""
═══════════════════════════════════════════════════════════════
rs_engine.py — Faz 2: GÖRECELİ GÜÇ (RS) + LİKİDİTE FİLTRESİ  v1.0
───────────────────────────────────────────────────────────────
BİLİMSEL TEMEL:
  • Kesitsel momentum / göreceli güç (Jegadeesh-Titman 1993,
    Rouwenhorst 1998 gelişen piyasalar, Asness-Moskowitz-Pedersen
    2013): endekse göre GÜÇLÜ hisseler gelecekte de güçlü kalır.
    Etki ilk 4-8 haftada en belirgin → kısa/orta vade için 1-3 ay
    ağırlıklı.  BIST'te momentum zayıf-orta ama mevcut.
  • BIST likidite: illikit küçük capler manipülasyona açık
    (Imisiker et al.). KISA VADELİ İŞLEM için bunları ELE.

NE YAPAR:
  Tüm evren için XU100'e göre 1ay/3ay/6ay FAZLA getiriyi hesaplar,
  yüzdelik sıraya (percentile) çevirir, kısa/orta vadeye göre
  ağırlıklı tek bir RS skoru (0-100) üretir. Ayrıca 20-gün ortalama
  TL hacmiyle likidite katmanı + "işlenebilir mi" bayrağı verir.

ENDPOINTLER:
  /rs/refresh · /rs/rank · /rs/{symbol} · /rs/status · /rs/dashboard

KURULUM (main.py'a 2 satır):
    from rs_engine import install_rs
    install_rs(app)
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
import json
import datetime as dt
import threading

import numpy as np
import pandas as pd

try:
    import requests
except Exception:
    requests = None
try:
    import yfinance as yf
except Exception:
    yf = None

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import HTMLResponse


# ════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════
BASE_URL      = os.environ.get("OGREN_BASE_URL", "").rstrip("/")
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "").strip()
RS_GIST_ID    = os.environ.get("RS_GIST_ID", "").strip()
GIST_FILENAME = "rs_state.json"
TMP_PATH      = "/tmp/rs_state.json"

XU100_TICKERS = ["XU100.IS", "XU100.IST", "^XU100", "XU100"]

LOOKBACKS  = {"1ay": 21, "3ay": 63, "6ay": 126}        # işlem günü
RS_WEIGHTS = {"1ay": 0.40, "3ay": 0.40, "6ay": 0.20}   # kısa/orta vade vurgusu

ADV_WINDOW = 20          # likidite: son 20 gün ortalama TL hacmi
LIQ_TIERS = [
    (50_000_000, "YUKSEK"),
    (10_000_000, "ORTA"),
    (2_000_000,  "DUSUK"),
]
TRADABLE_MIN_ADV = 2_000_000   # altı: işlenebilir değil (illikit/manipülasyon riski)

FETCH_PERIOD = "9mo"
BATCH = 40
FETCH_WORKERS = 6        # tek-sembol paralel indirme havuzu (Yahoo rate-limit'e nazik)

_lock = threading.Lock()
_state = None
_scanning = {"on": False, "progress": 0, "total": 0}


# ════════════════════════════════════════════════════════════════
# Yardımcılar
# ════════════════════════════════════════════════════════════════
def _self_base():
    if BASE_URL:
        return BASE_URL
    return "http://127.0.0.1:" + str(os.environ.get("PORT", "10000"))


def _get_json(url, timeout=120):
    try:
        if requests is not None:
            r = requests.get(url, timeout=timeout)
            return r.json() if 200 <= r.status_code < 300 else None
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "rs/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _gist_headers():
    return {"Authorization": "token " + GITHUB_TOKEN,
            "Accept": "application/vnd.github+json", "User-Agent": "rs-engine"}


def load_state():
    global _state
    if _state is not None:
        return _state
    if requests and GITHUB_TOKEN and RS_GIST_ID:
        try:
            r = requests.get("https://api.github.com/gists/" + RS_GIST_ID,
                             headers=_gist_headers(), timeout=30)
            if r.status_code == 200:
                f = r.json().get("files", {}).get(GIST_FILENAME)
                if f and f.get("content"):
                    _state = json.loads(f["content"]); return _state
        except Exception:
            pass
    try:
        if os.path.exists(TMP_PATH):
            with open(TMP_PATH, encoding="utf-8") as fp:
                _state = json.load(fp); return _state
    except Exception:
        pass
    _state = {"updated": None, "rows": [], "storage": "tmp"}
    return _state


def save_state(state):
    global _state, RS_GIST_ID
    _state = state
    try:
        with open(TMP_PATH, "w", encoding="utf-8") as fp:
            json.dump(state, fp, ensure_ascii=False)
    except Exception:
        pass
    if requests and GITHUB_TOKEN:
        state["storage"] = "gist"
        if not RS_GIST_ID:
            try:
                payload = {"description": "Vortex-BIST RS durum", "public": False,
                           "files": {GIST_FILENAME: {"content": json.dumps(state, ensure_ascii=False)}}}
                r = requests.post("https://api.github.com/gists",
                                  headers=_gist_headers(), json=payload, timeout=30)
                if r.status_code in (200, 201):
                    RS_GIST_ID = r.json().get("id")
                    state.setdefault("notes", []).append("RS_GIST_ID=" + RS_GIST_ID)
            except Exception:
                pass
        else:
            try:
                requests.patch("https://api.github.com/gists/" + RS_GIST_ID,
                               headers=_gist_headers(),
                               json={"files": {GIST_FILENAME: {"content": json.dumps(state, ensure_ascii=False)}}},
                               timeout=30)
            except Exception:
                pass
    else:
        state["storage"] = "tmp"


# ════════════════════════════════════════════════════════════════
# RS + LİKİDİTE HESABI  (saf fonksiyonlar — test edilebilir)
# ════════════════════════════════════════════════════════════════
def _ret(series, n):
    """n işlem günü önceki kapanışa göre getiri (oran)."""
    if series is None:
        return None
    s = series.dropna()
    if len(s) <= n:
        return None
    a = float(s.iloc[-1]); b = float(s.iloc[-1 - n])
    if b <= 0:
        return None
    return a / b - 1.0


def compute_rs_rows(prices: dict, xu100) -> list:
    """prices: {sym: DataFrame(Close,Volume)} · xu100: Close serisi VEYA None.
    Her hisse için fazla getiri (excess) + RS skoru + likidite üretir,
    sonra RS yüzdelik sırasını (0-100) ekler.

    NOT: RS skoru kesitsel yüzdelik sıralamadır. Her hisseden AYNI XU100
    getirisini çıkarmak sıralamayı değiştirmez. Bu yüzden XU100 yoksa
    HAM getiri kullanılır → RS skoru yine de doğru üretilir (sadece
    ekrandaki "fazla %" sayısı ham getiriye döner)."""
    idx_ret = {k: _ret(xu100, n) for k, n in LOOKBACKS.items()}
    has_index = any(v is not None for v in idx_ret.values())
    rows = []
    for sym, df in prices.items():
        if df is None or len(df) < 30 or "Close" not in df:
            continue
        close = pd.to_numeric(df["Close"], errors="coerce")
        vol = pd.to_numeric(df.get("Volume", pd.Series(dtype=float)), errors="coerce")
        exc = {}
        for k, n in LOOKBACKS.items():
            r = _ret(close, n)
            ir = idx_ret.get(k)
            if r is None:
                exc[k] = None
            elif ir is not None:
                exc[k] = r - ir          # endekse göre fazla getiri
            else:
                exc[k] = r               # XU100 yoksa ham getiri (sıralama aynı)
        adv = None
        try:
            tl = (close * vol).dropna()
            if len(tl) >= 5:
                adv = float(tl.tail(ADV_WINDOW).mean())
        except Exception:
            adv = None
        tier = "RISKLI"
        if adv is not None:
            for thr, name in LIQ_TIERS:
                if adv >= thr:
                    tier = name; break
        tradable = (adv is not None and adv >= TRADABLE_MIN_ADV)
        rows.append({
            "symbol": sym,
            "exc_1ay": None if exc["1ay"] is None else round(exc["1ay"] * 100, 2),
            "exc_3ay": None if exc["3ay"] is None else round(exc["3ay"] * 100, 2),
            "exc_6ay": None if exc["6ay"] is None else round(exc["6ay"] * 100, 2),
            "_exc": exc,
            "adv_tl": None if adv is None else round(adv, 0),
            "likidite": tier,
            "tradable": tradable,
        })

    # Her lookback için yüzdelik sıra → ağırlıklı RS skoru (0-100)
    for k in LOOKBACKS:
        vals = [(i, r["_exc"][k]) for i, r in enumerate(rows) if r["_exc"][k] is not None]
        if not vals:
            for r in rows:
                r.setdefault("_pct", {})[k] = None
            continue
        order = sorted(vals, key=lambda t: t[1])
        m = len(order)
        for rank_i, (i, _) in enumerate(order):
            pct = 100.0 * rank_i / (m - 1) if m > 1 else 50.0
            rows[i].setdefault("_pct", {})[k] = pct
        for r in rows:
            if r.get("_pct", {}).get(k) is None:
                r.setdefault("_pct", {})[k] = None

    for r in rows:
        num = 0.0; wsum = 0.0
        for k, w in RS_WEIGHTS.items():
            p = r.get("_pct", {}).get(k)
            if p is not None:
                num += w * p; wsum += w
        r["rs_score"] = round(num / wsum, 1) if wsum > 0 else None
        r.pop("_exc", None); r.pop("_pct", None)

    rows.sort(key=lambda r: (r["rs_score"] is not None, r["rs_score"] or 0), reverse=True)
    return rows


# ════════════════════════════════════════════════════════════════
# Veri çekme + tarama
# ════════════════════════════════════════════════════════════════
def _universe_symbols():
    data = _get_json(_self_base() + "/scan?limit=900", timeout=120) or {}
    rows = data.get("sonuclar") or data.get("results") or data.get("rows") or []
    syms = []
    for r in rows:
        s = (r.get("sembol") or r.get("symbol") or "").upper().strip()
        if s:
            syms.append(s)
    return syms


def _yf_one(yf_symbol, period):
    """Kanıtlanmış tek-sembol indirme (momentum/BVI ile aynı yol).
    threads=False, MultiIndex düzleştirir, Close+Volume döndürür."""
    if yf is None:
        return None
    try:
        df = yf.download(yf_symbol, period=period, interval="1d",
                         progress=False, auto_adjust=True, threads=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        cols = {str(c).lower(): c for c in df.columns}
        if "close" not in cols:
            return None
        out = pd.DataFrame()
        out["Close"] = pd.to_numeric(df[cols["close"]], errors="coerce")
        out["Volume"] = (pd.to_numeric(df[cols["volume"]], errors="coerce")
                         if "volume" in cols else 0.0)
        return out.dropna(subset=["Close"])
    except Exception:
        return None


def _fetch_stock(sym):
    """Tek hisse: .IS → .IST → (eksiz) sırayla dener (fetch_ohlc ile aynı mantık)."""
    base = sym.upper().replace(".IS", "").strip()
    for suffix in (".IS", ".IST", ""):
        ys = (base + suffix) if suffix else base
        df = _yf_one(ys, FETCH_PERIOD)
        if df is not None and len(df) >= 30:
            return df
    return None


def _fetch_xu100():
    """XU100 endeksini tek-sembol yoluyla dener. Başarısız olursa None —
    bu DURUMDA tarama İPTAL OLMAZ (RS skoru endekssiz de hesaplanır)."""
    for tk in XU100_TICKERS:
        df = _yf_one(tk, FETCH_PERIOD)
        if df is not None and len(df) >= 30:
            return df["Close"]
    return None


def run_rs_scan() -> dict:
    if _scanning["on"]:
        return {"status": "zaten çalışıyor"}
    _scanning.update({"on": True, "progress": 0, "total": 0})
    try:
        # XU100 OPSİYONEL — çekilemezse tarama iptal OLMAZ (RS sıralaması endekssiz de doğru).
        xu = _fetch_xu100()
        index_used = xu is not None

        syms = _universe_symbols()
        _scanning["total"] = len(syms)
        prices = {}
        if yf is not None and syms:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            done = 0
            with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
                futs = {ex.submit(_fetch_stock, s): s for s in syms}
                for fut in as_completed(futs):
                    s = futs[fut]
                    try:
                        df = fut.result()
                        if df is not None:
                            prices[s] = df
                    except Exception:
                        pass
                    done += 1
                    _scanning["progress"] = done

        rows = compute_rs_rows(prices, xu)
        state = {
            "updated": dt.datetime.now().isoformat(timespec="seconds"),
            "n": len(rows),
            "index_used": index_used,        # XU100 bulundu mu (değilse ham getiri)
            "fetched": len(prices),          # kaç hisse fiyatı çekilebildi
            "universe": len(syms),
            "rows": rows,
            "params": {"lookbacks": LOOKBACKS, "weights": RS_WEIGHTS,
                       "adv_window": ADV_WINDOW, "tradable_min_adv": TRADABLE_MIN_ADV},
        }
        with _lock:
            save_state(state)
        return {"status": "ok", "n": len(rows), "fetched": len(prices),
                "universe": len(syms), "index_used": index_used}
    except Exception as e:
        return {"status": "hata", "detay": str(e)[:200]}
    finally:
        _scanning["on"] = False


# ════════════════════════════════════════════════════════════════
# ROUTER
# ════════════════════════════════════════════════════════════════
rs_router = APIRouter(prefix="/rs", tags=["rs-likidite"])


@rs_router.get("/refresh")
def refresh(background: BackgroundTasks):
    if _scanning["on"]:
        return {"status": "çalışıyor", "progress": _scanning["progress"], "total": _scanning["total"]}
    background.add_task(run_rs_scan)
    return {"status": "başladı"}


@rs_router.get("/status")
def status():
    st = load_state()
    return {"updated": st.get("updated"), "n": st.get("n", 0),
            "fetched": st.get("fetched"), "universe": st.get("universe"),
            "index_used": st.get("index_used"),
            "storage": st.get("storage"), "scanning": _scanning["on"],
            "progress": _scanning["progress"], "total": _scanning["total"]}


@rs_router.get("/rank")
def rank(limit: int = 50, tradable_only: bool = True):
    st = load_state()
    rows = st.get("rows", [])
    if tradable_only:
        rows = [r for r in rows if r.get("tradable")]
    return {"updated": st.get("updated"), "count": len(rows), "rows": rows[:limit]}


@rs_router.get("/{symbol}")
def one(symbol: str):
    symbol = symbol.upper().strip()
    st = load_state()
    for r in st.get("rows", []):
        if r["symbol"] == symbol:
            return r
    return {"symbol": symbol, "hata": "bulunamadı (henüz taranmadı veya evren dışı)"}


@rs_router.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    st = load_state()
    rows = [r for r in st.get("rows", []) if r.get("tradable")][:40]
    tr = ""
    for r in rows:
        sc = r.get("rs_score")
        bar = int(round(sc)) if sc is not None else 0
        col = "#7ed321" if (sc or 0) >= 70 else ("#f5c542" if (sc or 0) >= 50 else "#888")
        adv = r.get("adv_tl")
        advs = ("%.1fM" % (adv / 1e6)) if adv else "—"
        tr += ("<tr><td>%s</td>"
               "<td><div style='background:#1a2a1a;border-radius:4px;height:14px;width:110px'>"
               "<div style='background:%s;height:14px;border-radius:4px;width:%d%%'></div></div> %s</td>"
               "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>") % (
            r["symbol"], col, bar, ("%.0f" % sc) if sc is not None else "—",
            ("%+.1f" % r["exc_1ay"]) if r.get("exc_1ay") is not None else "—",
            ("%+.1f" % r["exc_3ay"]) if r.get("exc_3ay") is not None else "—",
            r.get("likidite", "—"), advs)
    html = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'><title>RS</title><style>
body{background:#050505;color:#ddd;font:14px system-ui;margin:0;padding:16px}
h1{color:#7ed321;font-size:18px}table{width:100%%;border-collapse:collapse;font-size:13px}
td,th{padding:6px 8px;border-bottom:1px solid #161616;text-align:left}th{color:#7ed321}
.muted{color:#777;font-size:12px}.btn{display:inline-block;background:#1a2a1a;color:#7ed321;
border:1px solid #7ed321;padding:8px 14px;border-radius:8px;text-decoration:none;margin-right:8px}
</style></head><body>
<h1>📈 GÖRECELİ GÜÇ (RS vs XU100) + Likidite</h1>
<div class=muted>Endekse göre fazla getiri · 1ay+3ay ağırlıklı · sadece işlenebilir (likit) hisseler · güncelleme: %s</div>
<table><tr><th>Sembol</th><th>RS skoru (0-100)</th><th>1ay fazla%%</th><th>3ay fazla%%</th><th>Likidite</th><th>Hacim/gün</th></tr>%s</table>
<div style='margin-top:14px'><a class=btn href='/rs/refresh'>▶ YENİDEN TARA</a>
<a class=btn href='/rs/rank'>RANK (JSON)</a></div>
<div class=muted style='margin-top:10px'>RS yüksek = endeksten güçlü (momentum). Likit olmayanlar listede yok (manipülasyon/işlem riski).</div>
</body></html>""" % (st.get("updated", "—"), tr or "<tr><td colspan=6 class=muted>Henüz tarama yok — /rs/refresh çalıştır</td></tr>")
    return HTMLResponse(html)


def install_rs(app) -> None:
    app.include_router(rs_router)
