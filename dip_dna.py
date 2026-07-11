"""
═══════════════════════════════════════════════════════════════════════════
DİP DNA MOTORU · Mum Orjini Tabanlı %30+ Patlama Parmak İzi (hisse-özel)
───────────────────────────────────────────────────────────────────────────
FELSEFE (Price Action Origin protokolü):
  Her hissenin TÜM günlük bar tarihi taranır; dipten ≥%TARGET yükselişle
  sonuçlanan her epizodun ORJİN MUMU bulunur ve 6 anatomik özellik çıkarılır:
    1. alt_fitil : son 3 barın alt-iğne oranı (stop-avı fitilleri)
    2. govde     : orjin mumun gövde/menzil oranı (kurumsal emilim imzası)
    3. hacim_z   : 60 günlük hacim z-skoru (tahtaya giren devasa hacim)
    4. cokus     : 120g zirveden düşüş derinliği (dip ne kadar dip?)
    5. sikisma   : ATR14/ATR100 (patlama öncesi menzil daralması)
    6. dip_yakin : 252g dibe yakınlık
  Epizodların özellik ZARFI (%10-%90 bandı) = hissenin DİP DNA'sı.
  BUGÜN ≥5/6 özellik zarfın içindeyse → eşleşme. Motor, eşleşme kuralının
  hissenin KENDİ geçmişindeki isabetini de raporlar (kaç eşleşme, kaçı %30+).

DÜRÜSTLÜK SÖZLEŞMESİ:
  · %100 isabet imkânsız — motor bunun yerine AZ ve KANITLI konuşur.
  · Epizod < 4 ise: "DNA örneklemi yetersiz" der, sinyal VERMEZ.
  · Tarihsel isabet zayıfsa eşleşmeyi söyler ama GÜÇLÜ damgası basmaz.
  · İstatistik hissenin kendi geçmişi üzerindendir (in-sample); bu açıkça
    yazılır — gelecek garantisi değil, karakter kanıtıdır.
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import statistics
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

TARGET = 0.30       # dip→tepe hedef
HORIZON = 120       # işlem günü (~6 ay: "kısa/orta vade")
PIVOT = 5           # dip pivotu penceresi
MIN_EPISODES = 4
MATCH_MIN = 5       # 6 özellikten en az kaçı zarf içinde olmalı

FEATS = ["alt_fitil", "govde", "hacim_z", "cokus", "sikisma", "dip_yakin"]
FEAT_AD = {"alt_fitil": "Alt fitil (stop-avı)", "govde": "Gövde/menzil (emilim)",
           "hacim_z": "Hacim z-skoru", "cokus": "Zirveden çöküş",
           "sikisma": "Menzil sıkışması", "dip_yakin": "252g dibe yakınlık"}


def _norm_cols(df):
    if df is None:
        return None
    ren = {}
    for c in df.columns:
        lc = str(c).lower()
        if lc in ("open", "high", "low", "close", "volume"):
            ren[c] = lc.capitalize()
    return df.rename(columns=ren)


def _features(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Tüm seri için 6 anatomik özellik (nedensel — geleceğe bakmaz)."""
    df = _norm_cols(df)
    if df is None or len(df) < 300:
        return None
    o = pd.to_numeric(df["Open"], errors="coerce")
    h = pd.to_numeric(df["High"], errors="coerce")
    l = pd.to_numeric(df["Low"], errors="coerce")
    c = pd.to_numeric(df["Close"], errors="coerce")
    v = pd.to_numeric(df.get("Volume", pd.Series(0, index=c.index)), errors="coerce").fillna(0)
    rng = (h - l).replace(0, np.nan)

    alt_fitil = ((pd.concat([o, c], axis=1).min(axis=1) - l) / rng).rolling(3).mean()
    govde = ((c - o).abs() / rng)
    hacim_z = (v - v.rolling(60).mean()) / v.rolling(60).std().replace(0, np.nan)
    cokus = c / c.rolling(120).max() - 1.0
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr100 = tr.ewm(alpha=1 / 100, adjust=False).mean()
    sikisma = atr14 / atr100.replace(0, np.nan)
    dip_yakin = c / c.rolling(252).min().replace(0, np.nan) - 1.0

    out = pd.DataFrame({"close": c, "alt_fitil": alt_fitil, "govde": govde,
                        "hacim_z": hacim_z, "cokus": cokus,
                        "sikisma": sikisma, "dip_yakin": dip_yakin})
    return out


def _find_episodes(close: pd.Series, target: float, horizon: int) -> List[int]:
    """Dip orjinleri: pivot-dip VE sonrasında horizon içinde ≥target yükseliş."""
    c = close.values
    n = len(c)
    eps = []
    for i in range(PIVOT, n - 1):
        lo, hi = max(0, i - PIVOT), min(n - 1, i + PIVOT)
        if not np.isfinite(c[i]) or c[i] != np.nanmin(c[lo:hi + 1]):
            continue
        j = min(i + horizon, n - 1)
        if j > i and np.nanmax(c[i + 1:j + 1]) / c[i] - 1.0 >= target:
            eps.append(i)
    return eps


def build_dna(df: pd.DataFrame, target: float = TARGET,
              horizon: int = HORIZON) -> Optional[Dict]:
    F = _features(df)
    if F is None:
        return None
    eps = _find_episodes(F["close"], target, horizon)
    if len(eps) < 1:
        return {"episodes": 0, "F": F, "env": None, "eps": []}
    # Epizod özellik matrisi → %10-%90 zarf (az epizodda min-max'a genişler)
    env = {}
    for f in FEATS:
        vals = [float(F[f].iloc[i]) for i in eps if np.isfinite(F[f].iloc[i])]
        if len(vals) < 2:
            env[f] = None
            continue
        lo = np.percentile(vals, 10) if len(vals) >= 8 else min(vals)
        hi = np.percentile(vals, 90) if len(vals) >= 8 else max(vals)
        pad = (hi - lo) * 0.15 + 1e-9
        env[f] = (lo - pad, hi + pad)
    return {"episodes": len(eps), "F": F, "env": env, "eps": eps}


def _match_row(F: pd.DataFrame, env: Dict, i: int):
    ok, det = 0, {}
    for f in FEATS:
        e = env.get(f)
        val = F[f].iloc[i]
        inside = bool(e and np.isfinite(val) and e[0] <= float(val) <= e[1])
        det[f] = {"deger": (round(float(val), 3) if np.isfinite(val) else None),
                  "zarf": ([round(e[0], 3), round(e[1], 3)] if e else None),
                  "uyum": inside}
        ok += int(inside)
    return ok, det


def historical_precision(dna: Dict, target: float, horizon: int) -> Dict:
    """Eşleşme kuralının hissenin KENDİ geçmişindeki isabeti (in-sample, şeffaf)."""
    F, env = dna["F"], dna["env"]
    c = F["close"].values
    n = len(c)
    matches, hits = 0, 0
    last = -10 ** 9
    for i in range(260, n - horizon):
        ok, _ = _match_row(F, env, i)
        if ok >= MATCH_MIN and i - last >= 10:      # kümelenme önlemi
            last = i
            matches += 1
            if np.nanmax(c[i + 1:i + horizon + 1]) / c[i] - 1.0 >= target:
                hits += 1
    return {"eslesme": matches, "isabet": hits,
            "oran": round(hits / matches, 3) if matches else None}


def analyze_dip_dna(df: pd.DataFrame, target: float = TARGET,
                    horizon: int = HORIZON) -> Dict:
    dna = build_dna(df, target, horizon)
    if dna is None:
        return {"hata": "yetersiz veri (min 300 gün)"}
    F = dna["F"]
    n = len(F)
    if dna["episodes"] < MIN_EPISODES or not dna["env"]:
        return {"episodes": dna["episodes"],
                "verdict": "DNA ÖRNEKLEMİ YETERSİZ",
                "not": ("Bu hissede dip→%%%d epizodu %d kez oluşmuş (min %d gerekir). "
                        "Motor dürüstlük gereği sinyal ÜRETMEZ.") %
                       (int(target * 100), dna["episodes"], MIN_EPISODES)}
    ok, det, bar_geri = 0, None, 0
    for k in (1, 2, 3):                       # dip anatomisi 1-3 bara yayılır
        o2, d2 = _match_row(F, dna["env"], n - k)
        if o2 > ok or det is None:
            ok, det, bar_geri = o2, d2, k - 1
    hp = historical_precision(dna, target, horizon)
    eslesti = ok >= MATCH_MIN
    guclu = eslesti and (hp["oran"] or 0) >= 0.5 and hp["eslesme"] >= 5
    if guclu:
        verdict, renk = "DİP DNA EŞLEŞMESİ · GÜÇLÜ", "#22c55e"
    elif eslesti:
        verdict, renk = "EŞLEŞME VAR · TARİHSEL KANIT ZAYIF", "#e8b84b"
    else:
        verdict, renk = "EŞLEŞME YOK", "#7a8798"
    # Karakter patenti: epizodlarda evrensel medyandan en çok sapan 2 özellik
    patent = []
    for f in FEATS:
        allv = F[f].dropna()
        epv = [float(F[f].iloc[i]) for i in dna["eps"] if np.isfinite(F[f].iloc[i])]
        if len(epv) >= 2 and len(allv) > 50 and allv.std() > 0:
            z = abs((statistics.median(epv) - allv.median()) / allv.std())
            patent.append((z, f, statistics.median(epv)))
    patent.sort(reverse=True)
    imza = " + ".join("%s≈%.2f" % (FEAT_AD[f], m) for _, f, m in patent[:2])
    return {
        "episodes": dna["episodes"], "verdict": verdict, "renk": renk,
        "bugun_uyum": "%d/6" % ok, "uyum_bari": bar_geri, "ozellikler": det,
        "tarihsel_isabet": hp,
        "karakter_patenti": "Bu hissenin dip imzası: " + (imza or "belirsiz"),
        "son_epizod": str(F.index[dna["eps"][-1]])[:10],
        "not": ("İstatistik hissenin KENDİ geçmişi üzerindendir (in-sample) — "
                "karakter kanıtıdır, gelecek garantisi değildir."),
    }


def install_dipdna(app, fetch_ohlc: Callable) -> None:
    from fastapi import Query

    @app.get("/dna/dip/{symbol}")
    def dip_dna(symbol: str,
                target: float = Query(TARGET, ge=0.1, le=1.0),
                horizon: int = Query(HORIZON, ge=30, le=300)):
        sym = symbol.upper().strip()
        try:
            df = fetch_ohlc(sym, period="max")
        except Exception:
            df = None
        if df is None or len(df) < 300:
            return {"sembol": sym, "hata": "yetersiz veri"}
        out = analyze_dip_dna(df, target, horizon)
        out["sembol"] = sym
        return out
