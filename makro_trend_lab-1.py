"""
═══════════════════════════════════════════════════════════════════════════
MAKRO TREND LAB · Gerçek Trend Başlangıcı Dedektörü (AYLIK)
───────────────────────────────────────────────────────────────────────────
AMAÇ: Kırmızı bölgeleri (sahte/verimsiz dalgalanma) matematiksel olarak
filtreleyip, yeşil bölgeleri (hacim+momentum destekli, orta vadede %30+
potansiyelli makro kırılım) İŞARETLEMEK.

MİMARİ (3 katman):
  1) YANILTMA ÇARPANI (Deception Index, 0-100): piyasanın "sahte sinyal
     üretme eğilimi". Yüksekse TÜM sinyaller bastırılır → NÖTR/BEKLE.
       DI = 100·[ w_er·(1−ER) + w_flip·min(flip6/3,1) + w_vol·kuru_hacim ]
       · ER  (Kaufman Etkinlik Oranı, 10 ay): |net yol| / Σ|aylık adım|
              → düşük ER = fiyat çok kıpırdıyor ama yol almıyor (kırmızı imza)
       · flip6: son 6 ayda SuperTrend yön değişimi sayısı (testere imzası)
       · kuru_hacim: max(0, 1 − max(volZ,0)/2) → hacim genişlemesi yoksa 1
       Varsayılan ağırlıklar w=(0.4, 0.3, 0.3) — ÖNSEL, veriyle fit edilmedi
       (aşırı-uyum yok); backtest bunları doğrulamak içindir.

  2) GERÇEK TREND ŞARTLARI (yeşil bölge senkronizasyonu):
       ZORUNLU KAPILAR (hepsi):
         G1 · SuperTrend yönü YUKARI (aylık)
         G2 · Kapanış > EMA20(high)
         G3 · Hacim z-skoru ≥ 1.0  (24 aylık pencerede standart sapma artışı)
       KIRILIM TEYİDİ (≥2/3):
         T1 · Kapanış, Chande Kroll AŞAĞI-stopunun (short_stop) ÜSTÜNE kırdı
         T2 · Kapanış ≥ son 9 aylık en yüksek kapanışın %98'i (taban kırılımı)
         T3 · Stokastik dönüşü: %K > %D, %K yükseliyor ve son 6 ayda %K < 45
              bölgesinden dönmüş (aşırı satımdan çıkış)
       FİLTRE: DI < 55 değilse sinyal İPTAL → "BEKLE (yanıltma bölgesi)"

  3) AĞIRLIK MATRİSİ (skor 0-100, hüküm için):
       Kapılar geçti → taban 40
       T1 (CK kırılımı)      +20   ← en güçlü tekil kanıt (grafiklerde
       T2 (taban kırılımı)   +15      yeşil bölgeler hep CK kırılımıyla başlıyor)
       T3 (stokastik dönüş)  +10
       volZ ≥ 1.5 bonusu     +10
       DI payı               +5·(55−DI)/55
     HÜKÜM:
       skor ≥ 70 ve DI < 55 → "GÜÇLÜ AL · TREND BAŞLANGICI"
       55 ≤ skor < 70        → "İZLE"
       kapı düşük / DI ≥ 55  → "NÖTR/BEKLE"

  DÜRÜSTLÜK: Aylık barlarda örneklem KÜÇÜKTÜR; backtest train/test (70/30)
  ayrımıyla raporlanır, eşikler öncel (fit edilmemiş) tutulur. %30 hedef
  "sonraki 9 ayda max kapanış getirisi ≥ %30" olarak etiketlenir. Hiçbir
  filtre sahte sinyali %100 elemez — hedef isabet/yakalama dengesidir.
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import statistics
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

# ── PARAMETRELER (öncel; /makro/backtest bunları doğrular) ──────────────
ST_PERIOD, ST_MULT = 10, 3.0        # aylık SuperTrend (TV varsayılanı)
EMA_LEN, EMA_SRC = 20, "High"
CK_P, CK_X, CK_Q = 10, 1.0, 9
STOCH_N, STOCH_S = 14, 3
ER_WIN = 10                          # Etkinlik Oranı penceresi (ay)
FLIP_WIN = 6                         # ST flip sayım penceresi
VOLZ_WIN = 24                        # hacim z-skor penceresi
HIGHBRK_WIN = 9                      # taban kırılımı penceresi
DI_W = (0.40, 0.30, 0.30)            # (ER, flip, kuru hacim) ağırlıkları
DI_MAX = 55.0                        # bunun üstü = yanıltma bölgesi
TARGET, HORIZON = 0.30, 9            # %30 hedef · 9 aylık ufuk
MIN_MONTHS = 36


def _norm_cols(df):
    """fetch_ohlc küçük-harf sütun döndürür (close, high...). Normalize et."""
    if df is None:
        return None
    ren = {}
    for c in df.columns:
        lc = str(c).lower()
        if lc in ("open", "high", "low", "close", "volume"):
            ren[c] = lc.capitalize()
    return df.rename(columns=ren)


# ── AYLIK RESAMPLE (ay başı çapalı, güncel yarım ay dahil) ──────────────
def to_monthly(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    df = _norm_cols(df)
    if df is None or len(df) == 0:
        return None
    d = df.copy()
    try:
        d.index = pd.to_datetime(d.index)
    except Exception:
        return None
    ms = d.index.to_period("M").to_timestamp()
    agg = {}
    for c, f in (("Open", "first"), ("High", "max"), ("Low", "min"), ("Close", "last")):
        if c in d.columns:
            agg[c] = (c, f)
    if "Volume" in d.columns:
        agg["Volume"] = ("Volume", "sum")
    try:
        return d.groupby(ms).agg(**agg).sort_index().dropna(how="all")
    except Exception:
        return None


# ── GÖSTERGELER ─────────────────────────────────────────────────────────
def _atr(h, l, c, n):
    pc = c.shift()
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def supertrend(h, l, c, period=ST_PERIOD, mult=ST_MULT):
    """Standart SuperTrend. dir: +1 yukarı(yeşil) / -1 aşağı(kırmızı)."""
    atr = _atr(h, l, c, period)
    mid = (h + l) / 2.0
    ub, lb = mid + mult * atr, mid - mult * atr
    n = len(c)
    fub = ub.copy(); flb = lb.copy()
    d = pd.Series(1, index=c.index)
    for i in range(1, n):
        fub.iloc[i] = ub.iloc[i] if (ub.iloc[i] < fub.iloc[i-1] or c.iloc[i-1] > fub.iloc[i-1]) else fub.iloc[i-1]
        flb.iloc[i] = lb.iloc[i] if (lb.iloc[i] > flb.iloc[i-1] or c.iloc[i-1] < flb.iloc[i-1]) else flb.iloc[i-1]
        if d.iloc[i-1] == 1:
            d.iloc[i] = -1 if c.iloc[i] < flb.iloc[i] else 1
        else:
            d.iloc[i] = 1 if c.iloc[i] > fub.iloc[i] else -1
    line = pd.Series(np.where(d == 1, flb, fub), index=c.index)
    return line, d


def chande_kroll(h, l, c, p=CK_P, x=CK_X, q=CK_Q):
    atr = _atr(h, l, c, p)
    hs = h.rolling(p).max() - x * atr
    ls = l.rolling(p).min() + x * atr
    long_stop = hs.rolling(q).max()     # uzun stop (fiyat altı)
    short_stop = ls.rolling(q).min()    # kısa stop (aşağı trendde fiyat üstü)
    return long_stop, short_stop


def stochastic(h, l, c, n=STOCH_N, s=STOCH_S):
    ll, hh = l.rolling(n).min(), h.rolling(n).max()
    k = ((c - ll) / (hh - ll).replace(0, np.nan)) * 100.0
    K = k.rolling(s).mean()
    D = K.rolling(s).mean()
    return K, D


def efficiency_ratio(c, n=ER_WIN):
    """Kaufman ER: |net yol| / Σ|adım|. 1=düz trend, 0=testere."""
    net = (c - c.shift(n)).abs()
    path = c.diff().abs().rolling(n).sum()
    return (net / path.replace(0, np.nan)).clip(0, 1)


def vol_zscore(v, n=VOLZ_WIN):
    m = v.rolling(n).mean()
    s = v.rolling(n).std()
    return (v - m) / s.replace(0, np.nan)


def deception_index(c, st_dir, volz):
    """0-100 · yüksek = sahte-sinyal ortamı (kırmızı bölge imzası)."""
    er = efficiency_ratio(c, ER_WIN)
    flips = st_dir.diff().abs().div(2).rolling(FLIP_WIN).sum()
    dry = (1.0 - (volz.clip(lower=0) / 2.0)).clip(0, 1)
    w1, w2, w3 = DI_W
    di = 100.0 * (w1 * (1 - er.fillna(0.5))
                  + w2 * (flips.fillna(0) / 3.0).clip(0, 1)
                  + w3 * dry.fillna(1.0))
    return di.clip(0, 100)


# ── SİNYAL MOTORU (tüm seri; nedensel — geleceğe bakmaz) ────────────────
def compute_signals(dfm: pd.DataFrame) -> Optional[pd.DataFrame]:
    if dfm is None or len(dfm) < MIN_MONTHS:
        return None
    c = pd.to_numeric(dfm["Close"], errors="coerce")
    h = pd.to_numeric(dfm.get("High", c), errors="coerce")
    l = pd.to_numeric(dfm.get("Low", c), errors="coerce")
    v = pd.to_numeric(dfm.get("Volume", pd.Series(0, index=c.index)), errors="coerce").fillna(0)

    st_line, st_dir = supertrend(h, l, c)
    ema = h.ewm(span=EMA_LEN, adjust=False).mean() if EMA_SRC == "High" else c.ewm(span=EMA_LEN, adjust=False).mean()
    lstop, sstop = chande_kroll(h, l, c)
    K, D = stochastic(h, l, c)
    volz = vol_zscore(v)
    di = deception_index(c, st_dir, volz)

    # Zorunlu kapılar
    g1 = st_dir == 1
    g2 = c > ema
    g3 = volz >= 1.0
    # Kırılım teyitleri
    t1 = (c > sstop) & (c.shift(1) <= sstop.shift(1))          # CK aşağı-stop kırılımı
    t1 = t1.rolling(3, min_periods=1).max().astype(bool)       # kırılım tazeliği: son 3 ay
    t2 = c >= c.rolling(HIGHBRK_WIN).max().shift(1) * 0.98     # taban/tepe kırılımı
    k_turn = (K > D) & (K > K.shift(1)) & (K.rolling(6).min() < 45)
    t3 = k_turn.fillna(False)

    teyit = t1.astype(int) + t2.fillna(False).astype(int) + t3.astype(int)
    gates = g1 & g2 & g3

    skor = pd.Series(0.0, index=c.index)
    skor[gates] = 40.0
    skor += t1.astype(int) * 20 + t2.fillna(False).astype(int) * 15 + t3.astype(int) * 10
    skor += (volz >= 1.5).astype(int) * 10
    skor += (5.0 * (DI_MAX - di).clip(lower=0) / DI_MAX)
    skor = skor.where(gates, other=skor * 0.4).clip(0, 100)    # kapısız skor kırpılır

    sig = gates & (teyit >= 2) & (di < DI_MAX) & (skor >= 70)
    izle = gates & (teyit >= 1) & (di < DI_MAX) & (skor >= 55) & (~sig)

    out = pd.DataFrame({
        "close": c, "ema": ema, "st_dir": st_dir, "st_line": st_line,
        "ck_short": sstop, "ck_long": lstop, "K": K, "D": D,
        "volz": volz, "er": efficiency_ratio(c), "di": di,
        "g1": g1, "g2": g2, "g3": g3, "t1": t1, "t2": t2.fillna(False), "t3": t3,
        "teyit": teyit, "skor": skor, "SINYAL": sig, "IZLE": izle,
    })
    return out


def verdict_last(sigdf: pd.DataFrame) -> Dict:
    r = sigdf.iloc[-1]
    if bool(r["SINYAL"]):
        v, renk = "GÜÇLÜ AL · TREND BAŞLANGICI", "#22c55e"
    elif bool(r["IZLE"]):
        v, renk = "İZLE", "#7ee787"
    elif float(r["di"]) >= DI_MAX:
        v, renk = "BEKLE · YANILTMA BÖLGESİ", "#e8b84b"
    else:
        v, renk = "NÖTR/BEKLE", "#7a8798"
    return {"verdict": v, "renk": renk,
            "skor": round(float(r["skor"]), 1),
            "deception_index": round(float(r["di"]), 1),
            "etkinlik_orani": round(float(r["er"]), 3) if pd.notna(r["er"]) else None,
            "hacim_z": round(float(r["volz"]), 2) if pd.notna(r["volz"]) else None,
            "kapilar": {"ST_yukari": bool(r["g1"]), "EMA_ustu": bool(r["g2"]), "hacim_z>=1": bool(r["g3"])},
            "teyitler": {"CK_kirilim": bool(r["t1"]), "taban_kirilim": bool(r["t2"]),
                         "stokastik_donus": bool(r["t3"]), "sayi": int(r["teyit"])}}


# ── BACKTEST (train/test · %30 hedef · aşırı-uyumsuz) ───────────────────
def backtest_symbol(dfm: pd.DataFrame, split=0.7) -> Optional[Dict]:
    s = compute_signals(dfm)
    if s is None:
        return None
    c = s["close"].values
    n = len(c)
    cut = int(n * split)
    fmax = np.full(n, np.nan)
    for i in range(n - 1):
        j = min(i + HORIZON, n - 1)
        if j > i:
            fmax[i] = c[i+1:j+1].max() / c[i] - 1.0

    def seg(mask, lo, hi):
        idx = [i for i in range(lo, hi) if mask[i] and not np.isnan(fmax[i])]
        hits = [i for i in idx if fmax[i] >= TARGET]
        gains = [float(fmax[i]) for i in idx]
        return {"sinyal": len(idx), "isabet_30": len(hits),
                "precision": round(len(hits)/len(idx), 3) if idx else None,
                "medyan_max_kazanc": round(statistics.median(gains), 3) if gains else None}

    sig = s["SINYAL"].values
    return {"train": seg(sig, 0, cut), "test": seg(sig, cut, n - 1),
            "aylik_bar": n}


# ── ENDPOINTLER ─────────────────────────────────────────────────────────
DEFAULT_BASKET = ["LUKSK", "PRKAB", "PSDTC", "THYAO", "ASELS", "SISE",
                  "EREGL", "FROTO", "TOASO", "KRDMD", "PGSUS", "HEKTS"]


def install_makro(app, fetch_ohlc: Callable) -> None:
    from fastapi import Query

    @app.get("/makro/{symbol}")
    def makro_symbol(symbol: str):
        sym = symbol.upper().strip()
        try:
            df = fetch_ohlc(sym, period="10y")
        except Exception:
            df = None
        dfm = to_monthly(df)
        s = compute_signals(dfm) if dfm is not None else None
        if s is None:
            return {"sembol": sym, "hata": "yetersiz aylık veri (min %d ay)" % MIN_MONTHS}
        out = verdict_last(s)
        out["sembol"] = sym
        # son sinyal tarihi
        idx = np.where(s["SINYAL"].values)[0]
        out["son_sinyal"] = str(s.index[int(idx[-1])])[:10] if len(idx) else None
        out["toplam_sinyal"] = int(len(idx))
        return out

    @app.get("/makro/backtest/run")
    def makro_backtest(symbols: str = Query(""),
                       split: float = Query(0.7, ge=0.5, le=0.9)):
        syms = ([x.strip().upper() for x in symbols.split(",") if x.strip()]
                or DEFAULT_BASKET)
        agg = {"train": {"sinyal": 0, "isabet_30": 0},
               "test": {"sinyal": 0, "isabet_30": 0}}
        per = {}
        for sym in syms:                       # SIRALI — OOM önlemi (512MB)
            try:
                df = fetch_ohlc(sym, period="10y")
            except Exception:
                df = None
            r = backtest_symbol(to_monthly(df), split) if df is not None else None
            if r is None:
                per[sym] = {"hata": "veri yok"}
                continue
            per[sym] = r
            for part in ("train", "test"):
                agg[part]["sinyal"] += r[part]["sinyal"]
                agg[part]["isabet_30"] += r[part]["isabet_30"]
        for part in ("train", "test"):
            a = agg[part]
            a["precision"] = round(a["isabet_30"] / a["sinyal"], 3) if a["sinyal"] else None
        return {"hedef": "sonraki %d ayda max getiri >= %%%d" % (HORIZON, int(TARGET*100)),
                "toplam": agg, "hisseler": per,
                "not": "Aylık örneklem KÜÇÜKTÜR; test precision'ına bak, train'e değil."}
