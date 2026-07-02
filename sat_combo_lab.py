"""
═══════════════════════════════════════════════════════════════════════════
SAT KOMBO LAB · Stoch RSI × Chande Kroll Stop — "Tepede Sat" Eş-Güdüm Motoru
───────────────────────────────────────────────────────────────────────────
AMAÇ: İki göstergenin (Stochastic RSI + Chande Kroll Stop) sayısal
parametrelerini bir IZGARADA tarayıp, bir hissenin TEPESİNDE ikisinin
EŞ-GÜDÜMLÜ (birbirini teyit eden) bir SAT sinyali üretmesini sağlayan
en iyi kombinasyonu bulur ve test eder.

YÖNTEM (dürüst, aşırı-uyum'a karşı korumalı):
  • Her hissenin geçmişi TRAIN(%70) / TEST(%30) diye bölünür.
  • Izgara TRAIN'de sıralanır, kazananın TEST metrikleri raporlanır.
  • Metrikler:
      - precision  : sinyal verince ertesi `fwd` barda fiyat ≥`drop` düştü mü
      - top_capture: gerçek tepeleri (sonrası ≥%X düşen) yakalama oranı
      - med_fwd    : sinyal sonrası medyan `fwd` getirisi (NEGATİF olmalı)
      - agreement  : iki göstergenin tepe civarında ne sıklıkta TEYİTLEŞTİĞİ
  • "Eş-güdümlü sinyal": biri ATEŞLERKEN diğeri son `window` bar içinde de
    ateşlemişse (nedensel/causal — geleceğe bakmaz) → tek SAT sinyali.

NOT: Gerçek optimizasyon sunucuda /satlab/optimize ile çalışır (yfinance orada).
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import itertools
import statistics
from collections import defaultdict
from typing import Dict, List, Callable, Optional

import numpy as np
import pandas as pd


# ════════════════════════════════════════════════════════════
# GÖSTERGELER (standalone — dış bağımlılık yok)
# ════════════════════════════════════════════════════════════
def _rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def stoch_rsi(close: pd.Series, rsi_len: int, stoch_len: int,
              k_smooth: int, d_smooth: int):
    """TradingView 'Stoch RSI' ile aynı: RSI → stokastik → %K(SMA) → %D(SMA)."""
    r = _rsi(close, rsi_len)
    mn = r.rolling(stoch_len).min()
    mx = r.rolling(stoch_len).max()
    sr = ((r - mn) / (mx - mn).replace(0, np.nan)) * 100.0
    K = sr.rolling(k_smooth).mean()
    D = K.rolling(d_smooth).mean()
    return K, D


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
    pc = close.shift()
    tr = pd.concat([(high - low), (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def chande_kroll(high: pd.Series, low: pd.Series, close: pd.Series,
                 p: int, x: float, q: int):
    """Chande Kroll Stop. long_stop = uzun pozisyon takip-stopu (fiyatın altında).
    Klasik tanım: highStop=HH(p)-x·ATR(p); lowStop=LL(p)+x·ATR(p);
    longStop=HH(highStop,q); shortStop=LL(lowStop,q)."""
    atr = _atr(high, low, close, p)
    high_stop = high.rolling(p).max() - x * atr
    low_stop = low.rolling(p).min() + x * atr
    long_stop = high_stop.rolling(q).max()
    short_stop = low_stop.rolling(q).min()
    return long_stop, short_stop


# ════════════════════════════════════════════════════════════
# SAT TETİKLERİ
# ════════════════════════════════════════════════════════════
def stoch_sell(K: pd.Series, D: pd.Series, ob: float) -> pd.Series:
    """Aşırı-alımda DÖNÜŞ: %K aşırı-alım bölgesindeyken %D'yi AŞAĞI keser."""
    cross_dn = (K.shift(1) >= D.shift(1)) & (K < D)
    ob_zone = (K.shift(1) >= ob) | (D.shift(1) >= ob)
    return (cross_dn & ob_zone).fillna(False)


def chande_sell(close: pd.Series, long_stop: pd.Series) -> pd.Series:
    """Uzun-pozisyon stopu kırıldı: kapanış long_stop'un ALTINA düşer."""
    return ((close.shift(1) >= long_stop.shift(1)) & (close < long_stop)).fillna(False)


def coordinated_sell(sr_sell: pd.Series, ck_sell: pd.Series, window: int) -> pd.Series:
    """EŞ-GÜDÜM: biri ATEŞLERKEN diğeri son `window` bar içinde de ateşlemiş.
    Nedensel (geleceğe bakmaz) → canlı kullanılabilir."""
    w = max(1, window) + 1
    sr_recent = sr_sell.rolling(w, min_periods=1).max().astype(bool)
    ck_recent = ck_sell.rolling(w, min_periods=1).max().astype(bool)
    fire_now = sr_sell | ck_sell
    return (fire_now & sr_recent & ck_recent).fillna(False)


# ── ZIGZAG KESİCİ KATMANLAR (sadece GERÇEK zirvede tek sinyal) ──────────
def peak_zone(high: pd.Series, close: pd.Series,
              win: int = 40, frac: float = 0.06) -> pd.Series:
    """Fiyat son `win` barın zirvesine ≤`frac` yakınsa True. Düşüş ortasındaki
    küçük dönüşleri eler — sinyal yalnızca çok-haftalık ZİRVE bölgesinde geçerli."""
    if frac is None:
        return pd.Series(True, index=close.index)
    roll_max = high.rolling(win, min_periods=5).max()
    return (close >= roll_max * (1.0 - frac)).fillna(False)


def apply_cooldown(sig: pd.Series, cooldown: int) -> pd.Series:
    """Kümelenmeyi tek sinyale indirger: bir sinyalden sonra `cooldown` bar
    boyunca yeni sinyal bastırılır (zigzag kümeleri → tek zirve sinyali)."""
    if cooldown <= 0:
        return sig
    vals = sig.values.copy()
    last = -10 ** 9
    for i in range(len(vals)):
        if vals[i]:
            if i - last < cooldown:
                vals[i] = False
            else:
                last = i
    return pd.Series(vals, index=sig.index)


def major_top_sell(close, high, low, sr: dict, ck: dict, window: int,
                   peak_win: int = 40, peak_frac: float = 0.06,
                   cooldown: int = 10):
    """Tam zincir: Stoch RSI dönüş + Chande Kroll stop kırılımı (eş-güdüm)
    + zirve-bölgesi filtresi + cooldown → GERÇEK zirvede tek 'SAT' sinyali."""
    K, D = stoch_rsi(close, sr["rsi_len"], sr["stoch_len"], sr["k"], sr["d"])
    ls, ss = chande_kroll(high, low, close, ck["p"], ck["x"], ck["q"])
    sr_sell = stoch_sell(K, D, sr["ob"])
    ck_sell = chande_sell(close, ls)
    co = coordinated_sell(sr_sell, ck_sell, window)
    co = co & peak_zone(high, close, peak_win, peak_frac)
    co = apply_cooldown(co, cooldown)
    return co, {"K": K, "D": D, "long_stop": ls,
                "sr_sell": sr_sell, "ck_sell": ck_sell}


# ════════════════════════════════════════════════════════════
# DEĞERLENDİRME YARDIMCILARI
# ════════════════════════════════════════════════════════════
def _forward_drop_mask(close: pd.Series, fwd: int, drop: float) -> pd.Series:
    """Her bar için: sonraki `fwd` bar içinde fiyat ≥`drop` (oran) düştü mü?"""
    arr = close.values
    n = len(arr)
    out = np.zeros(n, dtype=bool)
    for i in range(n - 1):
        end = min(i + fwd, n - 1)
        window_min = arr[i + 1:end + 1].min() if end > i else arr[i]
        if arr[i] > 0 and (window_min / arr[i] - 1.0) <= -drop:
            out[i] = True
    return pd.Series(out, index=close.index)


def _fwd_return(close: pd.Series, fwd: int) -> pd.Series:
    return (close.shift(-fwd) / close - 1.0)


def _significant_tops(high: pd.Series, close: pd.Series, pivot: int,
                      fwd: int, peak_drop: float) -> List[int]:
    """Yerel tepe (pivot penceresinde en yüksek) ve sonrasında ≥peak_drop düşen
    'gerçek tepe' indekslerini döndürür (top_capture/recall için)."""
    h = high.values
    c = close.values
    n = len(h)
    tops = []
    for i in range(pivot, n - 1):
        lo = max(0, i - pivot)
        hi = min(n - 1, i + pivot)
        if h[i] != h[lo:hi + 1].max():
            continue
        end = min(i + fwd, n - 1)
        if end <= i:
            continue
        future_min = c[i + 1:end + 1].min()
        if c[i] > 0 and (future_min / c[i] - 1.0) <= -peak_drop:
            tops.append(i)
    return tops


# ════════════════════════════════════════════════════════════
# TEK HİSSE: tüm kombolar için sinyalleri üret + sayaçları topla
# ════════════════════════════════════════════════════════════
def _eval_symbol(df: pd.DataFrame, sr_keys, ck_keys, windows,
                 split: float, fwd: int, drop: float,
                 peak_pivot: int, peak_drop: float, capture_k: int,
                 peak_win: int, peak_frac: float, cooldown: int,
                 agg: Dict):
    close = pd.to_numeric(df["Close"], errors="coerce")
    high = pd.to_numeric(df.get("High", close), errors="coerce")
    low = pd.to_numeric(df.get("Low", close), errors="coerce")
    mask = close.notna() & high.notna() & low.notna()
    close, high, low = close[mask], high[mask], low[mask]
    n = len(close)
    if n < 200:
        return
    cut = int(n * split)

    good = _forward_drop_mask(close, fwd, drop).values
    fret = _fwd_return(close, fwd).values
    tops = _significant_tops(high, close, peak_pivot, fwd, peak_drop)
    tops_train = [t for t in tops if t < cut]
    tops_test = [t for t in tops if t >= cut]

    # Önbellek: ağır göstergeleri sadece benzersiz parametre için hesapla
    sr_cache = {}
    for (rl, sl, ks, ds, ob) in sr_keys:
        base = (rl, sl, ks, ds)
        if base not in sr_cache:
            sr_cache[base] = stoch_rsi(close, rl, sl, ks, ds)
    sr_sell_cache = {}
    for key in sr_keys:
        rl, sl, ks, ds, ob = key
        K, D = sr_cache[(rl, sl, ks, ds)]
        sr_sell_cache[key] = stoch_sell(K, D, ob)

    ck_sell_cache = {}
    for (p, x, q) in ck_keys:
        ls, ss = chande_kroll(high, low, close, p, x, q)
        ck_sell_cache[(p, x, q)] = chande_sell(close, ls)

    # Zirve-bölgesi maskesi (combo'dan bağımsız → bir kez)
    pz = peak_zone(high, close, peak_win, peak_frac).values

    idx_pos = np.arange(n)
    for sr_key in sr_keys:
        sr_sell = sr_sell_cache[sr_key].values
        for ck_key in ck_keys:
            ck_sell = ck_sell_cache[ck_key].values
            for w in windows:
                co_arr = coordinated_sell(
                    pd.Series(sr_sell), pd.Series(ck_sell), w).values
                co_arr = co_arr & pz                       # zirve-bölgesi filtresi
                co_arr = apply_cooldown(pd.Series(co_arr), cooldown).values
                sig = co_arr
                combo = (sr_key, ck_key, w)
                a = agg[combo]
                # train / test ayrımı
                for part, lo, hi, toplist in (
                        ("tr", 0, cut, tops_train),
                        ("te", cut, n, tops_test)):
                    sig_idx = idx_pos[lo:hi][sig[lo:hi]]
                    a[part + "_sig"] += len(sig_idx)
                    for i in sig_idx:
                        if good[i]:
                            a[part + "_good"] += 1
                        if not np.isnan(fret[i]):
                            a[part + "_fret"].append(float(fret[i]))
                    # top_capture: tepe [t, t+capture_k] aralığında sinyal var mı
                    a[part + "_tops"] += len(toplist)
                    for t in toplist:
                        lo2, hi2 = t, min(n - 1, t + capture_k)
                        if sig[lo2:hi2 + 1].any():
                            a[part + "_topshit"] += 1
                # eş-güdüm istatistiği (tüm seri, window'a bağlı)
                sr_c = int(sr_sell.sum())
                ck_c = int(ck_sell.sum())
                co_c = int(sig.sum())
                a["sr_count"] += sr_c
                a["ck_count"] += ck_c
                a["co_count"] += co_c


def _finalize(agg: Dict, min_signals: int) -> List[Dict]:
    rows = []
    for combo, a in agg.items():
        sr_key, ck_key, w = combo

        def met(pfx):
            sig = a[pfx + "_sig"]
            good = a[pfx + "_good"]
            tops = a[pfx + "_tops"]
            th = a[pfx + "_topshit"]
            fr = a[pfx + "_fret"]
            prec = (good / sig) if sig else 0.0
            cap = (th / tops) if tops else 0.0
            med = statistics.median(fr) if fr else 0.0
            return {"signals": sig, "precision": round(prec, 4),
                    "top_capture": round(cap, 4), "med_fwd": round(med, 4)}

        tr = met("tr")
        te = met("te")
        denom = min(a["sr_count"], a["ck_count"]) or 1
        agreement = round(a["co_count"] / denom, 4)
        rows.append({
            "stoch_rsi": {"rsi_len": sr_key[0], "stoch_len": sr_key[1],
                          "k": sr_key[2], "d": sr_key[3], "ob": sr_key[4]},
            "chande_kroll": {"p": ck_key[0], "x": ck_key[1], "q": ck_key[2]},
            "window": w,
            "train": tr, "test": te,
            "agreement": agreement,
        })
    # TRAIN'de sırala (precision yüksek + yeterli sinyal), aşırı-uyumu önlemek
    # için min_signals altı elenip TEST'iyle raporlanır.
    eligible = [r for r in rows if r["train"]["signals"] >= min_signals]
    eligible.sort(key=lambda r: (r["train"]["precision"],
                                 r["train"]["top_capture"],
                                 -r["train"]["med_fwd"]), reverse=True)
    return eligible


# ════════════════════════════════════════════════════════════
# IZGARALAR (varsayılan — makul ve hızlı; query ile genişletilebilir)
# ════════════════════════════════════════════════════════════
DEFAULT_SR_GRID = {
    "rsi_len": [9, 14, 21], "stoch_len": [14, 21, 50, 80],
    "k": [3, 5], "d": [3], "ob": [80, 90],
}
DEFAULT_CK_GRID = {"p": [10, 14, 20], "x": [1.0, 2.0, 3.0], "q": [9]}
DEFAULT_WINDOWS = [2, 3, 5]

DEFAULT_BASKET = ["EGPRO", "THYAO", "ASELS", "SISE", "EREGL", "KCHOL",
                  "GARAN", "TUPRS", "FROTO", "BIMAS", "TOASO", "SAHOL",
                  "PGSUS", "KRDMD", "HEKTS"]


def _expand(grid_sr, grid_ck, windows):
    sr_keys = [tuple(c) for c in itertools.product(
        grid_sr["rsi_len"], grid_sr["stoch_len"], grid_sr["k"],
        grid_sr["d"], grid_sr["ob"])]
    ck_keys = [tuple(c) for c in itertools.product(
        grid_ck["p"], grid_ck["x"], grid_ck["q"])]
    return sr_keys, ck_keys, list(windows)


def optimize(symbols: List[str], fetch_ohlc: Callable,
             period: str = "10y", split: float = 0.7,
             min_signals: int = 8, fwd: int = 10, drop: float = 0.03,
             peak_pivot: int = 5, peak_drop: float = 0.05, capture_k: int = 3,
             peak_win: int = 40, peak_frac: float = 0.06, cooldown: int = 10,
             grid_sr=None, grid_ck=None, windows=None,
             top_n: int = 15) -> Dict:
    grid_sr = grid_sr or DEFAULT_SR_GRID
    grid_ck = grid_ck or DEFAULT_CK_GRID
    windows = windows or DEFAULT_WINDOWS
    sr_keys, ck_keys, windows = _expand(grid_sr, grid_ck, windows)

    agg = defaultdict(lambda: {
        "tr_sig": 0, "tr_good": 0, "tr_tops": 0, "tr_topshit": 0, "tr_fret": [],
        "te_sig": 0, "te_good": 0, "te_tops": 0, "te_topshit": 0, "te_fret": [],
        "sr_count": 0, "ck_count": 0, "co_count": 0})

    used, skipped = [], []
    for sym in symbols:
        try:
            df = fetch_ohlc(sym, period=period)
        except Exception:
            df = None
        if df is None or len(df) < 200:
            skipped.append(sym)
            continue
        _eval_symbol(df, sr_keys, ck_keys, windows, split, fwd, drop,
                     peak_pivot, peak_drop, capture_k,
                     peak_win, peak_frac, cooldown, agg)
        used.append(sym)

    ranked = _finalize(agg, min_signals)
    return {
        "config": {"period": period, "split": split, "min_signals": min_signals,
                   "fwd": fwd, "drop": drop, "peak_drop": peak_drop,
                   "capture_k": capture_k, "peak_win": peak_win,
                   "peak_frac": peak_frac, "cooldown": cooldown,
                   "combos_tested": len(sr_keys) * len(ck_keys) * len(windows)},
        "symbols_used": used, "symbols_skipped": skipped,
        "best": ranked[:top_n],
    }


def check_symbol(df: pd.DataFrame, sr: Dict, ck: Dict, window: int,
                 peak_win: int = 40, peak_frac: float = 0.06,
                 cooldown: int = 10) -> Dict:
    """Tek hisse için seçili parametrelerle ANLIK durum + son sinyal.
    Zirve-bölgesi filtresi + cooldown ile ZIGZAG temizlenmiş tek-zirve sinyali."""
    close = pd.to_numeric(df["Close"], errors="coerce")
    high = pd.to_numeric(df.get("High", close), errors="coerce")
    low = pd.to_numeric(df.get("Low", close), errors="coerce")
    co, comp = major_top_sell(close, high, low, sr, ck, window,
                              peak_win, peak_frac, cooldown)
    K, D, ls = comp["K"], comp["D"], comp["long_stop"]
    sr_sell, ck_sell = comp["sr_sell"], comp["ck_sell"]
    last = -1
    idx = np.where(co.values)[0]
    last_idx = int(idx[-1]) if len(idx) else None
    return {
        "fiyat": round(float(close.iloc[last]), 4),
        "stoch_K": round(float(K.iloc[last]), 2) if pd.notna(K.iloc[last]) else None,
        "stoch_D": round(float(D.iloc[last]), 2) if pd.notna(D.iloc[last]) else None,
        "long_stop": round(float(ls.iloc[last]), 4) if pd.notna(ls.iloc[last]) else None,
        "stoch_sat_bugun": bool(sr_sell.iloc[last]),
        "chande_sat_bugun": bool(ck_sell.iloc[last]),
        "ESGUDUM_SAT_bugun": bool(co.iloc[last]),
        "son_zirve_sat_tarihi": (str(close.index[last_idx])[:10]
                                 if last_idx is not None else None),
        "son_sinyalden_bu_yana_bar": (len(close) - 1 - last_idx
                                      if last_idx is not None else None),
        "toplam_zirve_sat_sayisi": int(len(idx)),
    }


# ════════════════════════════════════════════════════════════
# ENDPOINT KURULUMU
# ════════════════════════════════════════════════════════════
def install_sat_combo(app, fetch_ohlc: Callable) -> None:
    from fastapi import Query

    @app.get("/satlab/optimize")
    def satlab_optimize(symbols: str = Query("", description="virgülle; boşsa varsayılan sepet"),
                        period: str = Query("10y"),
                        split: float = Query(0.7, ge=0.4, le=0.9),
                        min_signals: int = Query(8, ge=1, le=200),
                        fwd: int = Query(10, ge=2, le=40),
                        drop: float = Query(0.03, ge=0.005, le=0.2),
                        peak_drop: float = Query(0.05, ge=0.01, le=0.4),
                        peak_win: int = Query(40, ge=10, le=120),
                        peak_frac: float = Query(0.06, ge=0.0, le=0.3),
                        cooldown: int = Query(10, ge=0, le=60),
                        top_n: int = Query(15, ge=1, le=50)):
        syms = ([s.strip().upper() for s in symbols.split(",") if s.strip()]
                or DEFAULT_BASKET)
        return optimize(syms, fetch_ohlc, period=period, split=split,
                        min_signals=min_signals, fwd=fwd, drop=drop,
                        peak_drop=peak_drop, peak_win=peak_win,
                        peak_frac=peak_frac, cooldown=cooldown, top_n=top_n)

    @app.get("/satlab/check/{symbol}")
    def satlab_check(symbol: str,
                     rsi_len: int = Query(14), stoch_len: int = Query(14),
                     k: int = Query(3), d: int = Query(3), ob: float = Query(80),
                     p: int = Query(10), x: float = Query(1.0), q: int = Query(9),
                     window: int = Query(3),
                     peak_win: int = Query(40), peak_frac: float = Query(0.06),
                     cooldown: int = Query(10)):
        df = fetch_ohlc(symbol.upper(), period="3y")
        if df is None or len(df) < 60:
            return {"sembol": symbol.upper(), "hata": "yetersiz veri"}
        sr = {"rsi_len": rsi_len, "stoch_len": stoch_len, "k": k, "d": d, "ob": ob}
        ck = {"p": p, "x": x, "q": q}
        out = check_symbol(df, sr, ck, window, peak_win, peak_frac, cooldown)
        out["sembol"] = symbol.upper()
        return out
