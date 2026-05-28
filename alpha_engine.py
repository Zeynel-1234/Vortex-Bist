"""
═══════════════════════════════════════════════════════════════
alpha_engine.py — FRAKTAL KAHIN · ALPHA ENGINE v3.0
───────────────────────────────────────────────────────────────
Bilimsel çok faktörlü cross-sectional BIST sıralama motoru.

v3 mimari (v1/v2'den fark):
  - VERİ KAYNAĞI: TradingView bulk (alpha_tv.py), yfinance YOK
  - HIZ: 630 hisse ~2 saniye (eskiden 10 dk idi)
  - Scheduler YOK, disk cache YOK — in-memory 5 dk TTL (mevcut /scan gibi)
  - Mevcut sisteme SIFIR müdahale: tüm dosyalar ek, hiçbiri değişmiyor

Faktörler (literatür dayanaklı):
  - mean_rev  (%30): Bildik & Gülay 2007 — son ay düşenler toparlanır
  - momentum  (%25): 12-1 ay (Perf.Y − Perf.1M), Jegadeesh-Titman
  - low_vol   (%20): aylık volatilite, BIST düşük-vol anomalisi
  - quality   (%15): ROE − borç/özsermaye (TV temel verisi varsa)
  - trend     (%10): EMA20/50/200 hizalanması (Adaptive Markets)

Skor: cross-sectional Z-score → 0-100 → 5 seviyeli karar.
Hiçbir performans rakamı şişirilmez. Garanti getiri vaadi yoktur.
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import time
import math
import threading
from typing import Dict, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from alpha_tv import fetch_alpha_bulk, fetch_index_regime_data


# ── Konfigürasyon ───────────────────────────────────────────────
FACTOR_WEIGHTS = {
    "mean_rev": 0.30,
    "momentum": 0.25,
    "low_vol":  0.20,
    "quality":  0.15,
    "trend":    0.10,
}

REGIME_RISK_ON  = "RISK_ON"
REGIME_NEUTRAL  = "NEUTRAL"
REGIME_RISK_OFF = "RISK_OFF"

# Likidite filtresi: çok düşük hacimli hisseleri sıralamadan dışla
MIN_AVG_VOLUME = 100_000   # adet/gün (kaba; istenirse TL bazlı yapılır)

ALPHA_TTL = 300  # 5 dakika in-memory cache
_CACHE = {"t": 0.0, "data": None}
_LOCK = threading.Lock()


# ── JSON güvenli temizleyici ────────────────────────────────────
# KRİTİK: Starlette JSONResponse allow_nan=False kullanır. NaN/inf veya
# numpy tipleri (np.bool_, np.float64) → HTTP 500. Bu fonksiyon tüm
# payload'ı native Python tiplerine çevirir ve NaN/inf'i None yapar.
def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        f = float(o)
        return None if (f != f or f in (float("inf"), float("-inf"))) else f
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    return o


# ── Skor dönüşümleri ────────────────────────────────────────────
def z_to_score(z: Optional[float]) -> int:
    if z is None or not np.isfinite(z):
        return 0
    return int(max(0, min(100, round(50.0 + z * 16.67))))

def z_to_decision(z: Optional[float]) -> str:
    if z is None or not np.isfinite(z):
        return "VERI_YOK"
    if z > 1.5:  return "GÜÇLÜ AL"
    if z > 0.5:  return "AL"
    if z > -0.5: return "BEKLE"
    if z > -1.5: return "KAÇIN"
    return "GÜÇLÜ KAÇIN"


# ── Cross-sectional yardımcılar ─────────────────────────────────
def _winsorize(arr: np.ndarray, p: float = 0.02) -> np.ndarray:
    finite = arr[np.isfinite(arr)]
    if len(finite) < 10:
        return arr
    lo, hi = np.nanpercentile(finite, [p * 100, (1 - p) * 100])
    return np.clip(arr, lo, hi)

def _zscore(arr: np.ndarray) -> np.ndarray:
    arr = _winsorize(arr.astype(float))
    mu = np.nanmean(arr)
    sd = np.nanstd(arr)
    if not np.isfinite(sd) or sd < 1e-9:
        return np.zeros_like(arr)
    z = (arr - mu) / sd
    return np.nan_to_num(z, nan=0.0)


# ── Rejim tespiti (XU100) ───────────────────────────────────────
def detect_regime() -> Dict:
    d = fetch_index_regime_data()
    if not d or d.get('ema200') is None:
        return {"regime": REGIME_NEUTRAL, "reason": "no_index_data",
                "ema_aligned": False}
    e20, e50, e200 = d['ema20'], d['ema50'], d['ema200']
    vol_m = d.get('vol_m')
    bullish = (e20 is not None and e50 is not None and e200 is not None
               and e20 > e50 > e200)
    bearish = (e20 is not None and e50 is not None and e200 is not None
               and e20 < e50 < e200)
    # Volatilite eşiği: aylık vol > 12 yüksek sayılır (BIST için kaba)
    high_vol = vol_m is not None and vol_m > 12.0
    if bullish and not high_vol:
        regime = REGIME_RISK_ON
    elif bearish or high_vol:
        regime = REGIME_RISK_OFF
    else:
        regime = REGIME_NEUTRAL
    return {
        "regime": regime,
        "ema20": e20, "ema50": e50, "ema200": e200,
        "ema_aligned": bool(bullish),
        "vol_monthly": vol_m,
        "high_vol": bool(high_vol),
        "perf_1m": d.get('perf_1m'),
        "reason": "bull" if bullish else ("bear" if bearish else "mixed"),
    }


# ── Ana tarama ──────────────────────────────────────────────────
def run_alpha_scan(force: bool = False) -> Dict:
    """
    Tüm BIST için çok faktör cross-sectional skorlama.
    TradingView bulk → ~2 saniye. 5 dk cache.
    """
    now = time.time()
    if not force and _CACHE["data"] and (now - _CACHE["t"]) < ALPHA_TTL:
        return _CACHE["data"]

    t0 = time.time()
    bulk = fetch_alpha_bulk(limit=700)
    if not bulk["ok"]:
        raise HTTPException(502, f"ALPHA TV hata: {bulk.get('error')}")

    raw = bulk["data"]  # {SYMBOL: {factors}}
    syms = list(raw.keys())
    if not syms:
        raise HTTPException(502, "ALPHA: hisse verisi boş")

    # Likidite filtresi (hacim None ise dahil et — TV bazen vermez)
    filtered = []
    for s in syms:
        v = raw[s].get('vol_avg') or raw[s].get('volume')
        if v is None or v >= MIN_AVG_VOLUME:
            filtered.append(s)
    if len(filtered) < 20:
        filtered = syms  # filtre çok agresifse iptal

    def col(name):
        return np.array([
            raw[s].get(name) if raw[s].get(name) is not None else np.nan
            for s in filtered
        ], dtype=float)

    z_mom = _zscore(col("momentum"))
    z_mr  = _zscore(col("mean_rev"))
    z_lv  = _zscore(col("low_vol"))
    z_tr  = _zscore(col("trend"))

    has_q = bool(bulk.get("has_fundamentals")) and int(np.isfinite(col("quality")).sum()) >= 20
    if has_q:
        z_q = _zscore(col("quality"))
        w = FACTOR_WEIGHTS
    else:
        # Quality yoksa ağırlığını momentum+mean_rev'e dağıt
        z_q = np.zeros(len(filtered))
        w = dict(FACTOR_WEIGHTS)
        spill = w["quality"]
        w = {**w, "quality": 0.0,
             "mean_rev": w["mean_rev"] + spill * 0.6,
             "momentum": w["momentum"] + spill * 0.4}

    composite_raw = (w["momentum"] * z_mom + w["mean_rev"] * z_mr +
                     w["low_vol"] * z_lv + w["trend"] * z_tr +
                     w["quality"] * z_q)

    # KRİTİK: kompoziti tekrar standardize et.
    # Ağırlıklı toplamın std'si ~0.47 olur (bağımsız faktörler).
    # Tekrar z-score'lamazsak "Z>1.5 = GÜÇLÜ AL" eşiği ~3 sigma olur,
    # neredeyse hiç tetiklenmez. Yeniden standardize → eşikler doğru çalışır:
    # GÜÇLÜ AL ~ top %7, AL ~ sonraki %23, vb.
    composite = _zscore(composite_raw)

    order = np.argsort(-composite)
    ranks = np.empty(len(filtered), dtype=int)
    for r, idx in enumerate(order):
        ranks[idx] = r + 1

    results = []
    for i, s in enumerate(filtered):
        z = float(composite[i])
        f = raw[s]
        agree = sum([
            f.get("momentum") is not None and f["momentum"] > 0,
            f.get("mean_rev") is not None and f["mean_rev"] > 0,
            f.get("low_vol") is not None,
            f.get("trend") is not None and f["trend"] > 0,
        ]) / 4.0
        conf = float(min(1.0, 0.6 * agree + 0.4 * min(1.0, abs(z) / 2.0)))
        results.append({
            "sembol": s,
            "composite_z": round(z, 3),
            "score": z_to_score(z),
            "rank": int(ranks[i]),
            "decision": z_to_decision(z),
            "confidence": round(conf, 2),
            "z_mom": round(float(z_mom[i]), 2),
            "z_mr": round(float(z_mr[i]), 2),
            "z_lv": round(float(z_lv[i]), 2),
            "z_tr": round(float(z_tr[i]), 2),
            "z_q": round(float(z_q[i]), 2) if has_q else None,
            "close": f.get("close"),
            "change": f.get("change"),
        })

    results.sort(key=lambda x: x["rank"])
    regime = detect_regime()

    payload = {
        "tarama_zamani": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sure_ms": int((time.time() - t0) * 1000),
        "tier": bulk.get("tier"),
        "has_fundamentals": has_q,
        "weights_used": w,
        "n_total": len(results),
        "regime": regime,
        "sonuclar": results,
    }
    payload = _clean(payload)
    with _LOCK:
        _CACHE["t"] = time.time()
        _CACHE["data"] = payload
    return payload


def get_symbol_info(symbol: str) -> Dict:
    """Tek hisse için ALPHA bilgisi (cache'den; yoksa tarar)."""
    symbol = symbol.upper().replace(".IS", "").strip()
    try:
        scan = run_alpha_scan()
    except HTTPException as e:
        return {"sembol": symbol, "available": False,
                "reason": "scan_error", "detail": str(e.detail),
                "regime": {"regime": REGIME_NEUTRAL}}
    target = next((r for r in scan["sonuclar"] if r["sembol"] == symbol), None)
    if target is None:
        return {"sembol": symbol, "available": False,
                "reason": "not_in_universe",
                "regime": scan["regime"],
                "tarama_zamani": scan["tarama_zamani"]}
    return {
        "sembol": symbol,
        "available": True,
        "rank": target["rank"],
        "universe_size": scan["n_total"],
        "score": target["score"],
        "composite_z": target["composite_z"],
        "decision": target["decision"],
        "confidence": target["confidence"],
        "factors": {
            "momentum": target["z_mom"],
            "mean_rev": target["z_mr"],
            "low_vol": target["z_lv"],
            "trend": target["z_tr"],
            "quality": target["z_q"],
        },
        "regime": scan["regime"],
        "tarama_zamani": scan["tarama_zamani"],
    }


# ── FastAPI Router ──────────────────────────────────────────────
alpha_router = APIRouter(prefix="/alpha", tags=["alpha"])

@alpha_router.get("/health")
def api_health():
    c = _CACHE["data"]
    age = round((time.time() - _CACHE["t"]) / 60, 1) if c else None
    return {
        "engine": "alpha_v3.0_tv",
        "source": "tradingview-bulk",
        "cache_present": c is not None,
        "cache_age_min": age,
        "n_cached": c["n_total"] if c else 0,
        "weights": FACTOR_WEIGHTS,
        "min_avg_volume": MIN_AVG_VOLUME,
    }

@alpha_router.get("/regime")
def api_regime():
    return _clean(detect_regime())

@alpha_router.get("/scan")
def api_scan(top_n: int = Query(700, ge=1, le=1000),
             sort_by: str = Query("composite_z"),
             force: bool = Query(False)):
    scan = run_alpha_scan(force=force)
    rows = list(scan["sonuclar"])
    valid = {"composite_z", "score", "rank",
             "z_mom", "z_mr", "z_lv", "z_tr"}
    if sort_by not in valid:
        sort_by = "composite_z"
    if sort_by == "rank":
        rows.sort(key=lambda x: x["rank"])
    else:
        rows.sort(key=lambda x: x.get(sort_by) if x.get(sort_by) is not None else -99,
                  reverse=True)
    out = dict(scan)
    out["sonuclar"] = rows[:top_n]
    out["sort_by"] = sort_by
    out["n_returned"] = min(top_n, len(rows))
    return _clean(out)

@alpha_router.get("/info/{symbol}")
def api_info(symbol: str):
    return _clean(get_symbol_info(symbol))
