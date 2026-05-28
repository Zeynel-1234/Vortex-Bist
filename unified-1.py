"""
═══════════════════════════════════════════════════════════════
unified.py — FRAKTAL KAHIN · BİRLEŞİK KARAR MOTORU v1.0
───────────────────────────────────────────────────────────────
NVS (hisse sağlığı) + ALPHA (cross-sectional sıralama) tek skorda
birleşir. 4 kapı → 2 kapı. "Hesaplanmadı" sorunu kökten çözülür,
çünkü her iki kapı da TradingView'den anlık gelir (630 hisse için).

BİRLEŞİK SKOR = 0.55×NVS + 0.45×ALPHA   (ikisi de 0-100)

2 KAPI:
  Kapı 1 (Seçim):       Birleşik ≥ 60  → "iyi hisse, iyi sıralı"
  Kapı 2 (Giriş):       Trend↑ + RSI<72 → "güvenli giriş, zirvede değil"
                        (Fraktal'ın 'zirveden alma' korumasının ucuz hâli)

TUZAK TESPİTİ: NVS yüksek ama ALPHA düşükse (fark > 25) → uyarı.

Mevcut sisteme SIFIR müdahale: tv_scanner, nvs, alpha_engine
olduğu gibi kullanılır, hiçbiri değişmez.
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import time
import threading
from typing import Dict, Optional

import numpy as np
from fastapi import APIRouter, Query, HTTPException

from tv_scanner import fetch_tv_bulk
from nvs import analyze_nvs

# alpha_engine opsiyonel — bozuksa/yoksa unified NVS-only çalışır
try:
    import alpha_engine as ae
    _HAS_ALPHA = True
except Exception as _e:
    ae = None
    _HAS_ALPHA = False
    print("[unified] alpha_engine yüklenemedi, NVS-only mod:", str(_e)[:120])


# ── JSON güvenli temizleyici (KENDİ KENDİNE YETER — ae'ye bağlı değil) ──
# Starlette allow_nan=False kullanır; np.bool_/np.float64/NaN → HTTP 500.
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


# ── Konfigürasyon ───────────────────────────────────────────────
W_NVS = 0.55
W_ALPHA = 0.45

GATE1_MIN = 60          # Birleşik skor eşiği
RSI_OVERBOUGHT = 72     # üstünde "zirvede, bekle"
TRAP_GAP = 25           # NVS - ALPHA > 25 → tuzak uyarısı

# Karar eşikleri (birleşik skor + kapılar)
STRONG_BUY_MIN = 78
BUY_MIN = 68

UNIFIED_TTL = 300
_CACHE = {"t": 0.0, "data": None}
_LOCK = threading.Lock()


def _build_nvs_inputs(d_raw, w_raw, m_raw):
    """main.py'deki ile birebir aynı — NVS girdi yapısı."""
    d = {'rec': d_raw.get('rec'), 'rsi': d_raw.get('rsi'),
         'stoch': d_raw.get('stoch'), 'macd': d_raw.get('macd'),
         'ema20': d_raw.get('ema20'), 'ema50': d_raw.get('ema50'),
         'ema200': d_raw.get('ema200'), 'vol': d_raw.get('vol'),
         'vol_avg': d_raw.get('vol_avg'), 'adx': d_raw.get('adx')}
    w = {'rec': w_raw.get('rec'), 'rsi': w_raw.get('rsi'),
         'stoch': w_raw.get('stoch'), 'macd': w_raw.get('macd'),
         'ema20': w_raw.get('ema20'), 'ema50': w_raw.get('ema50')}
    m = {'rec': m_raw.get('rec'), 'rsi': m_raw.get('rsi'),
         'stoch': m_raw.get('stoch'), 'macd': m_raw.get('macd'),
         'ema20': m_raw.get('ema20'), 'ema50': m_raw.get('ema50')}
    return d, w, m


def _compute_nvs_all() -> Dict[str, Dict]:
    """Tüm BIST için NVS (mevcut tv_scanner + nvs akışı, dokunulmadan)."""
    bulk = fetch_tv_bulk(limit=700)
    if not bulk or (bulk and '_error' in bulk[0]):
        return {}
    out = {}
    for row in bulk:
        sym = (row.get('symbol') or '').strip().upper()
        if not sym:
            continue
        d_raw = row.get('d') or {}
        w_raw = row.get('w') or {}
        m_raw = row.get('m') or {}
        if d_raw.get('_error'):
            continue
        if d_raw.get('rsi') is None and d_raw.get('rec') is None:
            continue
        d, w, m = _build_nvs_inputs(d_raw, w_raw, m_raw)
        try:
            r = analyze_nvs(sym, d, w, m)
        except Exception:
            continue
        out[sym] = {
            "nvs": r.get("nvs"),
            "nvs_label": r.get("nvs_label"),
            "guven": r.get("guven_skoru"),
            "bkm": r.get("bkm"),
            "close": d_raw.get('_close') or d_raw.get('close'),
            "change": d_raw.get('change'),
            "rsi": d_raw.get('rsi'),
            # ema farkları: (close-EMA)/close, pozitif = fiyat üstte
            "ema20_diff": d_raw.get('ema20'),
            "ema50_diff": d_raw.get('ema50'),
            "ema200_diff": d_raw.get('ema200'),
        }
    return out


def _entry_health(nvs_row: Dict) -> Dict:
    """
    Kapı 2: Giriş sağlığı. TV günlük verisinden.
      - Trend yukarı: fiyat EMA20 üstünde (ema20_diff > 0)
      - Aşırı alım değil: RSI < 72
    Fraktal'ın 'zirveden alma' korumasının ucuz, hep-mevcut versiyonu.
    """
    rsi = nvs_row.get("rsi")
    e20 = nvs_row.get("ema20_diff")
    e50 = nvs_row.get("ema50_diff")

    trend_ok = (e20 is not None and e20 > 0) or \
               (e20 is not None and e50 is not None and e20 > e50)
    overbought = rsi is not None and rsi >= RSI_OVERBOUGHT
    not_ob = not overbought

    gate2 = bool(trend_ok and not_ob)
    if gate2:
        reason = "Trend↑, RSI normal"
    elif overbought:
        reason = "Aşırı alım (RSI≥72) — geri çekilme bekle"
    elif not trend_ok:
        reason = "Trend yukarı değil — izle"
    else:
        reason = "Giriş zayıf"
    return {"gate2": gate2, "trend_ok": bool(trend_ok),
            "overbought": bool(overbought), "rsi": rsi, "reason": reason}


def _decide(uni: float, nvs: Optional[float], alpha: Optional[float],
            gate2_info: Dict, regime: str) -> Dict:
    """2 kapı + tuzak + rejim → nihai karar."""
    gate1 = uni >= GATE1_MIN
    gate2 = gate2_info["gate2"]
    trap = (nvs is not None and alpha is not None and (nvs - alpha) > TRAP_GAP)

    if not gate1:
        karar = "İZLE"
        renk = "#6b7280"
        aciklama = "Birleşik skor " + str(round(uni)) + " < 60. Yeterince güçlü değil."
    elif not gate2:
        karar = "BEKLE"
        renk = "#e8b84b"
        aciklama = "Skor iyi (" + str(round(uni)) + ") ama giriş zamanlaması kötü: " + \
                   gate2_info["reason"] + "."
    else:
        # iki kapı da geçti
        if uni >= STRONG_BUY_MIN and not trap:
            karar = "GÜÇLÜ AL"
            renk = "#22c55e"
            poz = "Tam pozisyon (%15-20)"
        elif uni >= BUY_MIN:
            karar = "AL"
            renk = "#22c55e"
            poz = "Normal pozisyon (%10)"
        else:
            karar = "AL (zayıf)"
            renk = "#9acd32"
            poz = "Küçük pozisyon (%5-7)"
        aciklama = "2 kapı geçti · " + poz
        if trap:
            aciklama += " · ⚠ NVS yüksek ama ALPHA zayıf (tuzak riski) — pozisyonu küçült"
        if regime == "RISK_OFF":
            aciklama += " · ⚠ Piyasa RISK_OFF — yarım pozisyon, sıkı stop"

    return {"karar": karar, "renk": renk, "aciklama": aciklama,
            "gate1": bool(gate1), "gate2": bool(gate2), "trap": bool(trap)}


def run_unified_scan(force: bool = False) -> Dict:
    now = time.time()
    if not force and _CACHE["data"] and (now - _CACHE["t"]) < UNIFIED_TTL:
        return _CACHE["data"]

    t0 = time.time()
    try:
        nvs_all = _compute_nvs_all()
    except Exception as e:
        raise HTTPException(502, "Birleşik NVS hata: " + str(e)[:150])
    if not nvs_all:
        raise HTTPException(502, "Birleşik: NVS verisi gelmedi")

    # ALPHA opsiyonel — herhangi bir hata olursa NVS-only devam et
    alpha_map = {}
    alpha_regime = {"regime": "NEUTRAL"}
    if _HAS_ALPHA and ae is not None:
        try:
            alpha_scan = ae.run_alpha_scan(force=force)
            alpha_map = {r["sembol"]: r for r in alpha_scan.get("sonuclar", [])}
            alpha_regime = alpha_scan.get("regime") or {"regime": "NEUTRAL"}
        except Exception as e:
            print("[unified] ALPHA atlandı (NVS-only):", str(e)[:120])
    regime = alpha_regime.get("regime", "NEUTRAL")

    results = []
    for sym, nv in nvs_all.items():
        try:
            nvs = nv.get("nvs")
            a = alpha_map.get(sym)
            alpha_score = a.get("score") if a else None

            if nvs is not None and alpha_score is not None:
                uni = W_NVS * nvs + W_ALPHA * alpha_score
            elif nvs is not None:
                uni = nvs  # ALPHA yoksa NVS'e düş
            elif alpha_score is not None:
                uni = alpha_score
            else:
                continue

            g2 = _entry_health(nv)
            dec = _decide(uni, nvs, alpha_score, g2, regime)

            results.append({
                "sembol": sym,
                "birlesik": round(float(uni), 1),
                "nvs": nvs,
                "alpha": alpha_score,
                "alpha_z": a.get("composite_z") if a else None,
                "rank": None,
                "karar": dec["karar"],
                "renk": dec["renk"],
                "gate1": dec["gate1"],
                "gate2": dec["gate2"],
                "trap": dec["trap"],
                "rsi": nv.get("rsi"),
                "close": nv.get("close"),
                "change": nv.get("change"),
            })
        except Exception:
            continue

    # Birleşik skora göre sırala + rank ata
    results.sort(key=lambda x: x["birlesik"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    payload = {
        "tarama_zamani": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sure_ms": int((time.time() - t0) * 1000),
        "agirliklar": {"nvs": W_NVS, "alpha": W_ALPHA},
        "esikler": {"gate1_min": GATE1_MIN, "rsi_overbought": RSI_OVERBOUGHT,
                    "strong_buy": STRONG_BUY_MIN, "buy": BUY_MIN},
        "regime": alpha_regime,
        "n_total": len(results),
        "sonuclar": results,
    }
    payload = _clean(payload)
    with _LOCK:
        _CACHE["t"] = time.time()
        _CACHE["data"] = payload
    return payload


def get_unified_info(symbol: str) -> Dict:
    symbol = symbol.upper().replace(".IS", "").strip()
    try:
        scan = run_unified_scan()
    except HTTPException as e:
        return {"sembol": symbol, "available": False, "detail": str(e.detail)}
    target = next((r for r in scan["sonuclar"] if r["sembol"] == symbol), None)
    if target is None:
        return {"sembol": symbol, "available": False, "reason": "not_found",
                "regime": scan.get("regime")}
    # açıklamayı yeniden üret (decide içindeki metin)
    g2 = {"gate2": target["gate2"], "trend_ok": target["gate2"],
          "overbought": (target.get("rsi") or 0) >= RSI_OVERBOUGHT,
          "reason": "RSI " + str(target.get("rsi"))}
    regime = (scan.get("regime") or {}).get("regime", "NEUTRAL")
    dec = _decide(target["birlesik"], target["nvs"], target["alpha"], g2, regime)
    return _clean({
        "sembol": symbol,
        "available": True,
        "birlesik": target["birlesik"],
        "nvs": target["nvs"],
        "alpha": target["alpha"],
        "rank": target["rank"],
        "universe_size": scan["n_total"],
        "karar": dec["karar"],
        "renk": dec["renk"],
        "aciklama": dec["aciklama"],
        "gate1": dec["gate1"],
        "gate2": dec["gate2"],
        "trap": dec["trap"],
        "rsi": target.get("rsi"),
        "regime": scan.get("regime"),
        "tarama_zamani": scan["tarama_zamani"],
    })


# ── Router ──────────────────────────────────────────────────────
unified_router = APIRouter(prefix="/unified", tags=["unified"])

@unified_router.get("/health")
def u_health():
    c = _CACHE["data"]
    age = round((time.time() - _CACHE["t"]) / 60, 1) if c else None
    return {"engine": "unified_v1.0", "cache_present": c is not None,
            "cache_age_min": age, "n_cached": c["n_total"] if c else 0,
            "weights": {"nvs": W_NVS, "alpha": W_ALPHA}}

@unified_router.get("/scan")
def u_scan(top_n: int = Query(700, ge=1, le=1000),
           sort_by: str = Query("birlesik"),
           force: bool = Query(False)):
    scan = run_unified_scan(force=force)
    rows = list(scan["sonuclar"])
    valid = {"birlesik", "nvs", "alpha", "rank", "change"}
    if sort_by not in valid:
        sort_by = "birlesik"
    if sort_by == "rank":
        rows.sort(key=lambda x: x["rank"])
    else:
        rows.sort(key=lambda x: x.get(sort_by) if x.get(sort_by) is not None else -999,
                  reverse=True)
    out = dict(scan)
    out["sonuclar"] = rows[:top_n]
    out["sort_by"] = sort_by
    out["n_returned"] = min(top_n, len(rows))
    return _clean(out)

@unified_router.get("/info/{symbol}")
def u_info(symbol: str):
    return get_unified_info(symbol)
