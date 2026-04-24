"""
═══════════════════════════════════════════════════════════════
FRAKTAL KAHİN — FAZ 5A: Zirveden Alma Hatası Filtresi
───────────────────────────────────────────────────────────────
AMAÇ: NVS'in tespit ettiği "sağlıklı görünen" hisseler arasından
      sadece GERÇEK DİP DÖNÜŞÜ yaşayanları ayıklamak.

STRATEJİ (5 koşul, her biri bir şart, toplam 100 puan):

  1. LSMA25 > LSMA200        (beyaz yeşili yukarı kesmiş)       - 25p
  2. LSMA200 slope > 0       (yeşilin eğimi yukarı dönmüş)      - 25p
  3. Dip geçmişi var         (son 90 günde ≥15 gün yeşil altı)  - 20p
  4. Aşırı yükseliş YOK      (son 20g'de %25'ten fazla yükselmemiş) - 15p
  5. Hacim onayı             (son 5 gün ort. ≥ 20g ort. × 1.2)  - 15p

KARAR EŞİKLERİ:
  >= 85  → GERÇEK AL       (tüm koşullar sağlam)
  >= 65  → BEKLE           (2-3 koşul eksik, gözlem)
  <  65  → GEÇERSİZ        (zirveden alma riski, veya henüz dönmedi)
═══════════════════════════════════════════════════════════════
"""
from typing import Dict, Optional, List
import math
import numpy as np
import pandas as pd


def lsma(series: pd.Series, period: int) -> pd.Series:
    """LSMA = her bar için son 'period' barlık regresyonun son noktası."""
    values = series.values.astype(float)
    n = len(values)
    out = np.full(n, np.nan)
    if n < period:
        return pd.Series(out, index=series.index)

    x = np.arange(period, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    for i in range(period - 1, n):
        window = values[i - period + 1: i + 1]
        if np.isnan(window).any():
            continue
        y_mean = window.mean()
        slope = ((x - x_mean) * (window - y_mean)).sum() / x_var
        intercept = y_mean - slope * x_mean
        out[i] = intercept + slope * (period - 1)

    return pd.Series(out, index=series.index)


def lsma_slope(lsma_series: pd.Series, lookback: int = 10) -> Optional[float]:
    """LSMA'nın kendi eğimi: son 'lookback' bar yüzdesel değişim."""
    vals = lsma_series.dropna().values
    if len(vals) < lookback + 1:
        return None
    ref = vals[-lookback - 1]
    if ref == 0 or np.isnan(ref):
        return None
    return float((vals[-1] - ref) / ref * 100.0)


def _cond_crossover(close: float, lsma25: float, lsma200: float) -> Dict:
    if any(x is None or (isinstance(x, float) and math.isnan(x))
           for x in [close, lsma25, lsma200]):
        return {'gecti': False, 'puan': 0, 'aciklama': 'Veri eksik'}
    gecti = lsma25 > lsma200
    fark_pct = (lsma25 - lsma200) / lsma200 * 100 if lsma200 else 0
    return {
        'gecti': bool(gecti),
        'puan': 25 if gecti else 0,
        'aciklama': f"LSMA25={lsma25:.2f}, LSMA200={lsma200:.2f}, fark=%{fark_pct:+.1f}"
    }


def _cond_slope(slope_pct: Optional[float]) -> Dict:
    if slope_pct is None:
        return {'gecti': False, 'puan': 0, 'aciklama': 'Slope hesaplanamadı'}
    gecti = slope_pct > 0
    if slope_pct >= 1.0:
        puan = 25
    elif slope_pct > 0:
        puan = 15
    else:
        puan = 0
    return {
        'gecti': bool(gecti),
        'puan': puan,
        'aciklama': f"Son 10g slope: %{slope_pct:+.2f}"
    }


def _cond_dip_history(close_series: pd.Series,
                      lsma200_series: pd.Series,
                      lookback: int = 90,
                      min_below_days: int = 15) -> Dict:
    if len(close_series) < lookback or len(lsma200_series) < lookback:
        return {'gecti': False, 'puan': 0, 'aciklama': 'Yeterli geçmiş yok'}
    c = close_series.tail(lookback).values
    l = lsma200_series.tail(lookback).values
    mask = ~(np.isnan(c) | np.isnan(l))
    if mask.sum() < lookback * 0.5:
        return {'gecti': False, 'puan': 0, 'aciklama': 'Çok fazla NaN'}
    below_days = int(((c < l) & mask).sum())
    gecti = below_days >= min_below_days
    puan = 20 if below_days >= min_below_days else \
           int(20 * below_days / min_below_days) if below_days > 0 else 0
    return {
        'gecti': bool(gecti),
        'puan': int(puan),
        'aciklama': f"Son {lookback}g içinde {below_days}g yeşilin altında (min {min_below_days})"
    }


def _cond_no_blowoff(close_series: pd.Series,
                     window: int = 20,
                     max_gain_pct: float = 25.0) -> Dict:
    if len(close_series) < window + 1:
        return {'gecti': False, 'puan': 0, 'aciklama': 'Veri az'}
    recent = close_series.tail(window + 1).values
    start, end = recent[0], recent[-1]
    if start <= 0 or np.isnan(start) or np.isnan(end):
        return {'gecti': False, 'puan': 0, 'aciklama': 'Fiyat geçersiz'}
    gain = (end - start) / start * 100.0

    if gain <= max_gain_pct * 0.6:
        puan = 15
    elif gain <= max_gain_pct:
        puan = 8
    else:
        puan = 0
    return {
        'gecti': bool(gain <= max_gain_pct),
        'puan': puan,
        'aciklama': f"Son {window}g getirisi: %{gain:+.1f} (maks %{max_gain_pct})"
    }


def _cond_volume(vol_series: pd.Series,
                 short_win: int = 5,
                 long_win: int = 20,
                 min_ratio: float = 1.2) -> Dict:
    if len(vol_series) < long_win:
        return {'gecti': False, 'puan': 0, 'aciklama': 'Hacim verisi az'}
    vs = vol_series.dropna()
    if len(vs) < long_win:
        return {'gecti': False, 'puan': 0, 'aciklama': 'Hacim NaN çok'}
    short_avg = vs.tail(short_win).mean()
    long_avg = vs.tail(long_win).mean()
    if long_avg <= 0:
        return {'gecti': False, 'puan': 0, 'aciklama': 'Hacim ortalaması 0'}
    ratio = short_avg / long_avg

    if ratio >= min_ratio:
        puan = 15
    elif ratio >= 1.0:
        puan = 8
    else:
        puan = 0
    return {
        'gecti': bool(ratio >= min_ratio),
        'puan': puan,
        'aciklama': f"Son {short_win}g/ son {long_win}g hacim: {ratio:.2f}× (min {min_ratio}×)"
    }


def analyze_fraktal(df: pd.DataFrame, symbol: str = "") -> Dict:
    """OHLCV dataframe'den Fraktal Kahin skorunu hesaplar."""
    cols_lower = {str(c).lower(): c for c in df.columns}
    if 'close' not in cols_lower:
        return {'sembol': symbol, 'hata': 'close sütunu yok',
                'fraktal_skor': None, 'yeterli_veri': False}

    close = df[cols_lower['close']].astype(float)
    volume = df[cols_lower['volume']].astype(float) if 'volume' in cols_lower \
             else pd.Series([0.0] * len(df), index=df.index)

    if len(close) < 220:
        return {'sembol': symbol, 'hata': 'En az 220 gün veri gerekli',
                'fraktal_skor': None, 'yeterli_veri': False,
                'mevcut_bar': len(close)}

    l25 = lsma(close, 25)
    l200 = lsma(close, 200)
    slope = lsma_slope(l200, lookback=10)

    current_close = float(close.iloc[-1])
    current_l25 = float(l25.iloc[-1]) if not math.isnan(l25.iloc[-1]) else None
    current_l200 = float(l200.iloc[-1]) if not math.isnan(l200.iloc[-1]) else None

    c1 = _cond_crossover(current_close, current_l25, current_l200)
    c2 = _cond_slope(slope)
    c3 = _cond_dip_history(close, l200)
    c4 = _cond_no_blowoff(close)
    c5 = _cond_volume(volume)

    total = c1['puan'] + c2['puan'] + c3['puan'] + c4['puan'] + c5['puan']
    gecen = sum(1 for c in (c1, c2, c3, c4, c5) if c['gecti'])

    if total >= 85:
        karar = 'GERÇEK AL'
        karar_renk = '#22c55e'
    elif total >= 65:
        karar = 'BEKLE'
        karar_renk = '#e8b84b'
    else:
        karar = 'GEÇERSİZ'
        karar_renk = '#ef4444'

    try:
        ret_20 = float((close.iloc[-1] - close.iloc[-21]) / close.iloc[-21] * 100)
    except Exception:
        ret_20 = None

    return {
        'sembol': symbol,
        'yeterli_veri': True,
        'fraktal_skor': int(total),
        'karar': karar,
        'karar_renk': karar_renk,
        'gecen_kosul': gecen,
        'kosullar': {
            '1_crossover': c1,
            '2_slope': c2,
            '3_dip_history': c3,
            '4_no_blowoff': c4,
            '5_volume': c5,
        },
        'degerler': {
            'close': round(current_close, 2),
            'lsma25': round(current_l25, 2) if current_l25 else None,
            'lsma200': round(current_l200, 2) if current_l200 else None,
            'lsma200_slope_pct': round(slope, 3) if slope is not None else None,
            'ret_20g_pct': round(ret_20, 2) if ret_20 is not None else None,
        }
    }
