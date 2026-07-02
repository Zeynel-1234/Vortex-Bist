"""
═══════════════════════════════════════════════════════════════════════════
FAKTÖR MOTORU · 1-3 AYLIK ÇOK-FAKTÖRLÜ KOMPOZİT SKOR (akademik temelli)
───────────────────────────────────────────────────────────────────────────
Araştırma raporunun koda dökülmüş hâli. 5 ORTOGONAL faktörü hesaplar, evren
içinde KESİTSEL yüzdelik sıralar (0-100), eşit ağırlıkla birleştirir; XU100
rejim filtresi ve tradability (işlem yapılabilirlik) korumasıyla sunar.

FAKTÖRLER (hepsi "yüksek skor = 1-3 ayda daha olumlu" yönüne çevrilir):
  1) 12-1 Momentum (Jegadeesh-Titman): son 12 ayın getirisi, EN SON AY hariç.
  2) 52-Hafta Yükseği Yakınlığı (George-Hwang): fiyat / 52h en yüksek.
  3) 1-Ay Reversal (Bildik-Gülay, BIST contrarian): son ay DÜŞÜK getiri = iyi.
  4) Düşük Volatilite (low-vol anomali): son 63g getiri std'si DÜŞÜK = iyi.
  5) Amihud İllikidite Primi (BIST'te güçlü): ortalama |getiri|/TL-hacim.

REJİM: XU100 > 200g MA ise "long" ortamı; değilse skorlar riskli işaretlenir.
TRADABILITY: son 21g ortalama TL hacim eşiği altındaki hisseler uyarılır.

DÜRÜST ÇERÇEVE: Bu bir KESİN AL/SAT kapısı değil, KANIT-TEMELLİ olasılık
bilgisidir. Küçük örneklemde tekil doğruluk %60'a saf sinyalle çıkmaz;
kompozit + rejim, aylık endekse-göreli isabeti ~%50'den %58-62'ye taşımayı
hedefler. Skor yüksek diye garanti yoktur.
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import os
import json
import threading
import datetime as dt
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

try:
    import requests
except Exception:
    requests = None

from fastapi import APIRouter

# ════════════════════════════════════════════════════════════════
# KONFİG
# ════════════════════════════════════════════════════════════════
BASE_URL      = os.environ.get("BASE_URL", "").strip().rstrip("/")
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "").strip()
FACTOR_GIST_ID = os.environ.get("FACTOR_GIST_ID", "").strip()
GIST_FILENAME = "factor_state.json"
TMP_PATH      = "/tmp/factor_state.json"

FETCH_PERIOD  = "2y"        # ~500 bar; 252 bar (12-1 mom + 52h) için yeterli. 3y→2y = ~%33 daha az RAM
FETCH_WORKERS = 2           # 6→2: Render free tier (512MB) OOM önlemi
MIN_BARS      = 252         # ~1 yıl işlem günü

# Faktör pencereleri (işlem günü)
MOM_LOOKBACK  = 252         # 12 ay
MOM_SKIP      = 21          # en son 1 ayı atla (kısa vadeli reversal kirliliği)
HIGH_WIN      = 252         # 52 hafta
REV_WIN       = 21          # 1 ay reversal
VOL_WIN       = 63          # 3 ay volatilite
ILLIQ_WIN     = 63          # 3 ay Amihud
TRAD_WIN      = 21          # tradability penceresi
TRADABLE_MIN_TL = 2_000_000.0   # son 21g ort. günlük TL hacim eşiği

# Eşit ağırlık (araştırma: eşit-ağırlık out-of-sample en dayanıklı)
FACTOR_KEYS = ["mom", "high52", "reversal", "lowvol", "illiq"]

_state = None
_scanning = {"on": False, "progress": 0, "total": 0,
             "last_error": None, "last_result": None}
_lock = threading.Lock()
_autostart_done = {"on": False}


# ════════════════════════════════════════════════════════════════
# Yardımcılar (RS motoruyla aynı desen)
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
        req = urllib.request.Request(url, headers={"User-Agent": "factor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _gist_headers():
    return {"Authorization": "token " + GITHUB_TOKEN,
            "Accept": "application/vnd.github+json", "User-Agent": "factor-engine"}


def load_state():
    global _state
    if _state is not None:
        return _state
    if requests and GITHUB_TOKEN and FACTOR_GIST_ID:
        try:
            r = requests.get("https://api.github.com/gists/" + FACTOR_GIST_ID,
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
    _state = {"updated": None, "rows": {}, "storage": "tmp"}
    return _state


def save_state(state):
    global _state, FACTOR_GIST_ID
    _state = state
    try:
        with open(TMP_PATH, "w", encoding="utf-8") as fp:
            json.dump(state, fp, ensure_ascii=False)
    except Exception:
        pass
    if requests and GITHUB_TOKEN:
        state["storage"] = "gist"
        if not FACTOR_GIST_ID:
            try:
                payload = {"description": "Vortex-BIST Faktör durum", "public": False,
                           "files": {GIST_FILENAME: {"content": json.dumps(state, ensure_ascii=False)}}}
                r = requests.post("https://api.github.com/gists",
                                  headers=_gist_headers(), json=payload, timeout=30)
                if r.status_code in (200, 201):
                    FACTOR_GIST_ID = r.json().get("id")
                    state.setdefault("notes", []).append("FACTOR_GIST_ID=" + FACTOR_GIST_ID)
            except Exception:
                pass
        else:
            try:
                requests.patch("https://api.github.com/gists/" + FACTOR_GIST_ID,
                               headers=_gist_headers(),
                               json={"files": {GIST_FILENAME: {"content": json.dumps(state, ensure_ascii=False)}}},
                               timeout=30)
            except Exception:
                pass
    else:
        state["storage"] = "tmp"


def _universe_symbols():
    data = _get_json(_self_base() + "/scan?limit=900", timeout=120) or {}
    rows = data.get("sonuclar") or data.get("results") or data.get("rows") or []
    out = []
    for r in rows:
        s = (r.get("sembol") or r.get("symbol") or "").upper().strip()
        if s:
            out.append(s)
    return out


# ════════════════════════════════════════════════════════════════
# FAKTÖR HESAPLARI (tek hisse ham değerleri)
# ════════════════════════════════════════════════════════════════
def compute_raw_factors(df: pd.DataFrame) -> Optional[Dict]:
    """Bir hissenin ham faktör değerlerini döndürür (henüz sıralanmamış)."""
    if df is None or len(df) < MIN_BARS:
        return None
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    high = pd.to_numeric(df.get("High", close), errors="coerce").reindex(close.index)
    vol = pd.to_numeric(df.get("Volume", pd.Series(index=close.index, dtype=float)),
                        errors="coerce").reindex(close.index).fillna(0.0)
    if len(close) < MIN_BARS:
        return None
    c = close.values
    ret = close.pct_change()

    # 1) 12-1 momentum: (P[t-skip] / P[t-lookback]) - 1
    try:
        mom = (c[-MOM_SKIP] / c[-MOM_LOOKBACK]) - 1.0
    except Exception:
        mom = None

    # 2) 52-hafta yükseği yakınlığı: fiyat / 52h en yüksek (0-1, yüksek=iyi)
    hh = float(high.iloc[-HIGH_WIN:].max())
    high52 = (float(c[-1]) / hh) if hh > 0 else None

    # 3) 1-ay reversal: son 21g getiri (DÜŞÜK = iyi → sonra ters çevrilecek)
    try:
        reversal = (c[-1] / c[-REV_WIN]) - 1.0
    except Exception:
        reversal = None

    # 4) Volatilite: son 63g günlük getiri std (DÜŞÜK = iyi)
    lowvol = float(ret.iloc[-VOL_WIN:].std())
    if not np.isfinite(lowvol):
        lowvol = None

    # 5) Amihud illikidite: mean(|getiri| / TL-hacim) (YÜKSEK = iyi, prim)
    tl_vol = (close * vol).replace(0, np.nan)
    amihud = (ret.abs() / tl_vol).iloc[-ILLIQ_WIN:]
    illiq = float(amihud.mean()) if amihud.notna().any() else None

    # Tradability: son 21g ort. günlük TL hacim
    adv_tl = float((close * vol).iloc[-TRAD_WIN:].mean())

    return {"mom": mom, "high52": high52, "reversal": reversal,
            "lowvol": lowvol, "illiq": illiq,
            "adv_tl": adv_tl, "fiyat": round(float(c[-1]), 4)}


def _pct_rank(values: List[Optional[float]], invert: bool = False) -> List[Optional[float]]:
    """Kesitsel yüzdelik sıra (0-100). invert=True ise düşük değer yüksek skor alır."""
    arr = np.array([np.nan if v is None else v for v in values], dtype=float)
    valid = ~np.isnan(arr)
    out = [None] * len(values)
    n = int(valid.sum())
    if n <= 1:
        return out
    order = pd.Series(arr[valid]).rank(method="average", pct=True) * 100.0
    ov = order.values
    if invert:
        ov = 100.0 - ov
    j = 0
    for i in range(len(values)):
        if valid[i]:
            out[i] = round(float(ov[j]), 1); j += 1
    return out


# ════════════════════════════════════════════════════════════════
# XU100 REJİM FİLTRESİ
# ════════════════════════════════════════════════════════════════
def compute_regime(fetch_ohlc: Callable) -> Dict:
    """XU100 > 200g MA ise long ortamı. HİÇBİR durumda istisna fırlatmaz."""
    for tk in ("XU100", "XU100.IS"):
        try:
            df = fetch_ohlc(tk, period=FETCH_PERIOD)
            if df is None or len(df) < 200:
                continue
            close = pd.to_numeric(df["Close"], errors="coerce").dropna()
            if len(close) < 200:
                continue
            ma200 = close.rolling(200).mean()
            if pd.isna(ma200.iloc[-1]):
                continue
            on = bool(close.iloc[-1] > ma200.iloc[-1])
            return {"regime_on": on, "xu100": round(float(close.iloc[-1]), 2),
                    "ma200": round(float(ma200.iloc[-1]), 2), "available": True}
        except Exception as e:
            print("[factor_engine] rejim hesabı hatası (%s): %s" % (tk, str(e)[:120]))
            continue
    return {"regime_on": None, "available": False}


# ════════════════════════════════════════════════════════════════
# EVREN TARAMASI → kesitsel sıralama → kompozit
# ════════════════════════════════════════════════════════════════
def run_factor_scan(fetch_ohlc: Callable) -> Dict:
    if _scanning["on"]:
        return {"status": "zaten çalışıyor"}
    _scanning.update({"on": True, "progress": 0, "total": 0})
    try:
        regime = compute_regime(fetch_ohlc)
        syms = _universe_symbols()
        _scanning["total"] = len(syms)

        raw = {}
        if syms:
            import gc
            from concurrent.futures import ThreadPoolExecutor, as_completed
            done = 0
            with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
                futs = {}
                for s in syms:
                    futs[ex.submit(_safe_fetch_factors, fetch_ohlc, s)] = s
                for fut in as_completed(futs):
                    s = futs[fut]
                    try:
                        rf = fut.result()
                        if rf is not None:
                            raw[s] = rf
                    except Exception:
                        pass
                    done += 1
                    _scanning["progress"] = done
                    if done % 50 == 0:
                        gc.collect()   # RAM'i düz tut (512MB OOM önlemi)
            gc.collect()

        # Kesitsel yüzdelik sıralama
        order_syms = list(raw.keys())
        pct = {}
        pct["mom"]      = _pct_rank([raw[s]["mom"] for s in order_syms], invert=False)
        pct["high52"]   = _pct_rank([raw[s]["high52"] for s in order_syms], invert=False)
        pct["reversal"] = _pct_rank([raw[s]["reversal"] for s in order_syms], invert=True)   # düşük getiri = iyi
        pct["lowvol"]   = _pct_rank([raw[s]["lowvol"] for s in order_syms], invert=True)      # düşük vol = iyi
        pct["illiq"]    = _pct_rank([raw[s]["illiq"] for s in order_syms], invert=False)      # yüksek illikidite = iyi

        rows = {}
        for i, s in enumerate(order_syms):
            parts = {k: pct[k][i] for k in FACTOR_KEYS}
            valid = [v for v in parts.values() if v is not None]
            composite = round(sum(valid) / len(valid), 1) if valid else None
            tradable = raw[s]["adv_tl"] >= TRADABLE_MIN_TL
            rows[s] = {
                "composite": composite,
                "factors": parts,
                "raw": {"mom": _r(raw[s]["mom"]), "high52": _r(raw[s]["high52"]),
                        "reversal": _r(raw[s]["reversal"]), "lowvol": _r(raw[s]["lowvol"]),
                        "adv_tl": round(raw[s]["adv_tl"], 0)},
                "fiyat": raw[s]["fiyat"],
                "tradable": tradable,
            }

        state = {
            "updated": dt.datetime.now().isoformat(timespec="seconds"),
            "n": len(rows), "universe": len(syms),
            "regime": regime, "rows": rows,
            "params": {"mom_lookback": MOM_LOOKBACK, "mom_skip": MOM_SKIP,
                       "vol_win": VOL_WIN, "tradable_min_tl": TRADABLE_MIN_TL,
                       "weights": "eşit (5 faktör)"},
        }
        with _lock:
            save_state(state)
        res = {"status": "ok", "n": len(rows), "universe": len(syms),
               "regime_on": regime.get("regime_on")}
        _scanning["last_result"] = res
        _scanning["last_error"] = None
        print("[factor_engine] tarama tamam ·", res)
        return res
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("[factor_engine] TARAMA HATASI:\n" + tb)
        _scanning["last_error"] = (str(e)[:300] or repr(e))
        try:
            with _lock:
                save_state({"updated": dt.datetime.now().isoformat(timespec="seconds"),
                            "n": 0, "rows": {},
                            "last_error": _scanning["last_error"]})
        except Exception:
            pass
        return {"status": "hata", "detay": str(e)[:200]}
    finally:
        _scanning["on"] = False


def _safe_fetch_factors(fetch_ohlc, sym):
    try:
        df = fetch_ohlc(sym, period=FETCH_PERIOD)
    except Exception:
        return None
    return compute_raw_factors(df)


def _r(v):
    return round(float(v), 4) if (v is not None and np.isfinite(v)) else None


# ════════════════════════════════════════════════════════════════
# VERDİKT
# ════════════════════════════════════════════════════════════════
def verdict_for(composite: Optional[float], regime_on: Optional[bool],
                tradable: bool) -> Dict:
    if composite is None:
        return {"label": "VERİ YOK", "renk": "#7a8798", "not": "Yeterli geçmiş yok."}
    if regime_on is False:
        return {"label": "PİYASA RİSKLİ", "renk": "#e8b84b",
                "not": "XU100 200g MA altında — long ortamı zayıf, skor yüksek olsa da temkinli ol."}
    if composite >= 70:
        lbl, renk = "GÜÇLÜ", "#3fb950"
    elif composite >= 55:
        lbl, renk = "OLUMLU", "#7ee787"
    elif composite >= 45:
        lbl, renk = "NÖTR", "#7a8798"
    else:
        lbl, renk = "ZAYIF", "#f85149"
    note = "1-3 aylık çok-faktörlü kompozit (kesitsel sıra)."
    if not tradable:
        note += " ⚠ Düşük likidite — giriş/çıkış zor olabilir."
    return {"label": lbl, "renk": renk, "not": note}


# ════════════════════════════════════════════════════════════════
# ROUTER
# ════════════════════════════════════════════════════════════════
factor_router = APIRouter(prefix="/factor", tags=["factor"])


@factor_router.get("/status")
def status():
    st = load_state()
    return {"updated": st.get("updated"), "n": st.get("n", 0),
            "universe": st.get("universe"), "regime": st.get("regime"),
            "storage": st.get("storage"), "scanning": _scanning["on"],
            "progress": _scanning["progress"], "total": _scanning["total"],
            "last_error": _scanning.get("last_error") or st.get("last_error"),
            "last_result": _scanning.get("last_result")}


@factor_router.get("/{symbol}")
def get_symbol(symbol: str):
    sym = symbol.upper().strip()
    st = load_state()
    rows = st.get("rows") or {}
    regime = st.get("regime") or {}
    regime_on = regime.get("regime_on")
    r = rows.get(sym)
    if not r:
        return {"sembol": sym, "hata": "taranmadı",
                "not": "Faktör taraması bu hisseyi içermiyor. /factor/refresh çalıştır.",
                "regime": regime}
    v = verdict_for(r.get("composite"), regime_on, r.get("tradable", True))
    return {
        "sembol": sym,
        "composite": r.get("composite"),
        "verdict": v["label"], "renk": v["renk"], "not": v["not"],
        "faktorler": r.get("factors"),
        "ham": r.get("raw"),
        "fiyat": r.get("fiyat"),
        "tradable": r.get("tradable"),
        "regime": regime,
        "updated": st.get("updated"),
    }


def install_factor(app, fetch_ohlc: Callable) -> None:
    app.include_router(factor_router)

    # NOT: Router app'e eklendikten SONRA router'a route eklemek FastAPI'de
    # kayıt OLMAZ (önceki sürümdeki bug → /factor/refresh/run hep 404'tü).
    # Bu yüzden refresh'i doğrudan app'e kaydediyoruz.
    @app.get("/factor/refresh/run")
    def factor_refresh():
        import threading as _t
        _t.Thread(target=lambda: run_factor_scan(fetch_ohlc), daemon=True).start()
        return {"status": "başladı", "not": "1-3 dk sürer, /factor/status ile izle"}

    off = os.environ.get("FACTOR_AUTOSTART_OFF", "").strip() in ("1", "true", "True", "yes")
    if not off and not _autostart_done["on"]:
        _autostart_done["on"] = True

        def _autostart():
            import time as _t
            _t.sleep(300)   # RS taraması önce başlasın ve büyük ölçüde bitsin
            # RS hâlâ tarıyorsa BEKLE — iki ağır tarama AYNI ANDA çalışırsa
            # Render free tier (512MB) OOM ile prosesi öldürüyor.
            try:
                import rs_engine as _rs
                waited = 0
                while _rs._scanning.get("on") and waited < 900:
                    _t.sleep(30); waited += 30
            except Exception:
                pass
            try:
                st = load_state()
                if st.get("rows"):
                    print("[factor_engine] startup: dolu → tarama atlandı")
                    return
                print("[factor_engine] startup: boş → otomatik faktör taraması")
                res = run_factor_scan(fetch_ohlc)
                print("[factor_engine] startup tarama bitti ·", res)
            except Exception as e:
                print("[factor_engine] startup hata:", str(e)[:160])

        threading.Thread(target=_autostart, daemon=True).start()
