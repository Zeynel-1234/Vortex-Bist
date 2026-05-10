"""
═══════════════════════════════════════════════════════════════════════════
URİS SAT v2.0 — TAM TEPE BAR'DA SİNYAL ÜRETİM MOTORU
───────────────────────────────────────────────────────────────────────────
v1.0 vs v2.0 FELSEFE FARKI:

v1.0 yaklaşımı (post-peak confirmation):
  • RSI overbought DÖNÜŞ
  • MACD histogram FLIP
  • SuperTrend YÖN değişimi
  • → Hepsi "tepe oluştuktan SONRA" tetiklenir
  • → Ortalama 5.2 bar gecikme (önceki ölçümde)

v2.0 yaklaşımı (pre-peak prediction + climax detection):
  ŞART A — PRE-PEAK (tepeden 1-3 bar ÖNCE uyarı):
    • Bearish Divergence: Fiyat HH yapıyor ama momentum LH
      → 5 türde: RSI, MACD, MFI, OBV, CCI
  ŞART B — CLIMAX BAR (peak bar'ın TAM ÜZERİNDE, lag=0):
    • Reversal Candle Patterns: Doji, Shooting Star, Bearish Engulfing,
      Evening Star, Gravestone Doji, Hanging Man
    • Volume Climax: 3x avg vol + bearish close
    • Z-Score Outlier: fiyat 20-bar ort'dan >2.5 std uzakta
    • Multi-Indicator Convergence: 3+ overbought aynı barda
  
  KARAR:
    • Sadece B (climax bar) → ZAYIF SAT (anlık dönüş işareti)
    • Sadece A (pre-peak div) → İZLE (yakında dönüş gelecek)
    • A + B aynı 3-bar window'da → GUCLU SAT (TAM TEPE)
    • A + B + v1 confirmation → KESIN SAT (üçlü teyit)

ZARAR YOK:
  • Mevcut lab_*.py dosyalarına dokunulmadı
  • Mevcut lab_sell_*.py (v1) ile yan yana çalışır
  • Ayrı namespace: /data/dna_sell_v2_cards/
═══════════════════════════════════════════════════════════════════════════
"""
from typing import Dict, List, Optional, Tuple, Callable
from itertools import combinations
import time
import json
import os
import numpy as np
import pandas as pd

# Mevcut indikatör kütüphanesini kullan (DOKUNULMADI)
from lab_indicators import (
    rsi, macd, mfi, obv, cci, stochastic, stoch_rsi,
    williams_r, bollinger, ema, sma, atr
)


# ═══════════════════════════════════════════════════════════════════════════
# YARDIMCI: YEREL MAKSİMUM TESPİTİ (divergence için kritik)
# ═══════════════════════════════════════════════════════════════════════════
def _find_recent_peaks(series: pd.Series, lookback: int = 25,
                       window: int = 3) -> List[int]:
    """
    Son 'lookback' bar içinde 2 yerel maksimum bul.
    window: bir noktanın "yerel max" sayılabilmesi için kaç komşusunu
    yenmesi gerektiği (window=3 → 7-bar pencere içinde max).
    """
    s = series.values[-lookback:] if len(series) > lookback else series.values
    if len(s) < 2 * window + 1:
        return []
    peaks = []
    for i in range(window, len(s) - window):
        local = s[i - window:i + window + 1]
        if s[i] == np.max(local) and not np.isnan(s[i]):
            peaks.append(i)
    return peaks


def _bearish_divergence_at(price: pd.Series, momentum: pd.Series,
                           bar_idx: int, lookback: int = 25) -> bool:
    """
    bar_idx noktasında bearish divergence var mı?
    
    Mantık:
      • Son lookback bar'da fiyat ve momentum'da yerel maxima bul
      • SON 2 maximum'u karşılaştır
      • Fiyatta HH (yeni yüksek) + momentum'da LH (daha düşük) → DIVERGENCE
    """
    if bar_idx < lookback:
        return False
    
    # Son lookback + bar_idx penceresi
    p_window = price.iloc[bar_idx - lookback + 1: bar_idx + 1]
    m_window = momentum.iloc[bar_idx - lookback + 1: bar_idx + 1]
    
    if len(p_window) < 15 or p_window.isna().any() or m_window.isna().any():
        return False
    
    p_peaks = _find_recent_peaks(p_window, lookback=lookback, window=3)
    if len(p_peaks) < 2:
        return False
    
    last = p_peaks[-1]
    prev = p_peaks[-2]
    
    # Son tepe son barda olmalı (veya 1-2 bar önce)
    if (len(p_window) - 1 - last) > 3:
        return False
    
    # HH check: fiyat yeni yüksek
    p_vals = p_window.values
    m_vals = m_window.values
    
    if p_vals[last] <= p_vals[prev]:
        return False  # HH yok
    
    # LH check: momentum daha düşük
    if m_vals[last] >= m_vals[prev]:
        return False  # LH yok
    
    # Ek filtre: fark anlamlı olmalı (gürültü değil)
    momentum_drop_pct = (m_vals[prev] - m_vals[last]) / abs(m_vals[prev] + 1e-10) * 100
    if momentum_drop_pct < 5:  # en az %5 momentum düşüşü olmalı
        return False
    
    return True


# ═══════════════════════════════════════════════════════════════════════════
# PRE-PEAK SİNYALLER — 5 farklı bearish divergence
# Bunlar tepenin TAM ÜZERİNDE veya 1-3 bar ÖNCESİNDE tetiklenir
# ═══════════════════════════════════════════════════════════════════════════
def divergence_rsi(df: pd.DataFrame, length: int = 14,
                   lookback: int = 25) -> pd.Series:
    """RSI Bearish Divergence — fiyat HH, RSI LH."""
    r = rsi(df, length)
    close = df['close'].astype(float)
    out = pd.Series(False, index=df.index)
    for i in range(lookback, len(df)):
        if _bearish_divergence_at(close, r, i, lookback):
            out.iloc[i] = True
    return out


def divergence_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26,
                    signal: int = 9, lookback: int = 25) -> pd.Series:
    """MACD Bearish Divergence — fiyat HH, MACD line LH."""
    m = macd(df, fast, slow, signal)
    close = df['close'].astype(float)
    out = pd.Series(False, index=df.index)
    for i in range(lookback, len(df)):
        if _bearish_divergence_at(close, m['macd'], i, lookback):
            out.iloc[i] = True
    return out


def divergence_mfi(df: pd.DataFrame, length: int = 14,
                   lookback: int = 25) -> pd.Series:
    """MFI Bearish Divergence — fiyat HH, MFI LH (hacim ağırlıklı)."""
    m = mfi(df, length)
    close = df['close'].astype(float)
    out = pd.Series(False, index=df.index)
    for i in range(lookback, len(df)):
        if _bearish_divergence_at(close, m, i, lookback):
            out.iloc[i] = True
    return out


def divergence_obv(df: pd.DataFrame, lookback: int = 25) -> pd.Series:
    """OBV Bearish Divergence — fiyat HH, OBV LH (hacim akışı tükeniyor)."""
    o = obv(df)
    close = df['close'].astype(float)
    out = pd.Series(False, index=df.index)
    for i in range(lookback, len(df)):
        if _bearish_divergence_at(close, o, i, lookback):
            out.iloc[i] = True
    return out


def divergence_cci(df: pd.DataFrame, length: int = 20,
                   lookback: int = 25) -> pd.Series:
    """CCI Bearish Divergence."""
    c = cci(df, length)
    close = df['close'].astype(float)
    out = pd.Series(False, index=df.index)
    for i in range(lookback, len(df)):
        if _bearish_divergence_at(close, c, i, lookback):
            out.iloc[i] = True
    return out


# ═══════════════════════════════════════════════════════════════════════════
# CLIMAX BAR SİNYALLERİ — peak bar'ın TAM ÜZERİNDE (gecikme 0)
# ═══════════════════════════════════════════════════════════════════════════

def _at_peak_zone(price: pd.Series, lookback: int = 60,
                  near_max_pct: float = 0.92,
                  min_runup_pct: float = 12.0,
                  runup_lookback: int = 90) -> pd.Series:
    """
    Tepe bölgesi tanımı — İKİ ŞART birden:
      1. Fiyat son 'lookback' günün maksimumunun en az 'near_max_pct'i kadar
         (yani yakın tepelere yakın)
      2. Son 'runup_lookback' günde dipten en az 'min_runup_pct' yükseliş
         (yani anlamlı bir ralli yaşanmış)
    
    Bu kombinasyon yatay/sıkışmış dönemlerde yanlış sat sinyali önler.
    """
    rolling_max = price.rolling(lookback, min_periods=20).max()
    near_max = price >= rolling_max * near_max_pct
    
    rolling_min = price.rolling(runup_lookback, min_periods=20).min()
    runup = 100 * (price - rolling_min) / rolling_min.replace(0, np.nan)
    significant_runup = runup >= min_runup_pct
    
    return (near_max & significant_runup).fillna(False)


def candle_doji_at_top(df: pd.DataFrame, body_ratio: float = 0.15,
                       lookback: int = 60,
                       near_max_pct: float = 0.92) -> pd.Series:
    """
    Doji + tepe bölgesinde olma.
    Tepe bölgesi = son 60 günün maksimumunun %92'si veya üstünde.
    """
    o = df['open'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    c = df['close'].astype(float)
    
    body = (c - o).abs()
    bar_range = (h - l).replace(0, np.nan)
    is_doji = (body / bar_range) < body_ratio
    at_peak = _at_peak_zone(c, lookback, near_max_pct)
    
    return (is_doji & at_peak).fillna(False).astype(bool)


def candle_shooting_star(df: pd.DataFrame, wick_ratio: float = 2.0,
                         lookback: int = 60,
                         near_max_pct: float = 0.92) -> pd.Series:
    """
    Shooting Star: küçük body + büyük üst fitil + küçük alt fitil + tepede.
    """
    o = df['open'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    c = df['close'].astype(float)
    
    body = (c - o).abs()
    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
    lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l
    
    is_shooting = (
        (upper_wick > wick_ratio * body.replace(0, np.nan)) &
        (lower_wick < body) &
        (body > 0)
    )
    at_peak = _at_peak_zone(c, lookback, near_max_pct)
    return (is_shooting & at_peak).fillna(False).astype(bool)


def candle_bearish_engulfing(df: pd.DataFrame, lookback: int = 60,
                             near_max_pct: float = 0.92) -> pd.Series:
    """
    Bearish Engulfing: önceki bar bullish, mevcut bar onu yutmuş bearish.
    """
    o = df['open'].astype(float)
    c = df['close'].astype(float)
    
    prev_bullish = c.shift(1) > o.shift(1)
    curr_bearish = c < o
    engulfs = (o > c.shift(1)) & (c < o.shift(1))
    
    is_engulfing = prev_bullish & curr_bearish & engulfs
    at_peak = _at_peak_zone(c, lookback, near_max_pct)
    return (is_engulfing & at_peak).fillna(False).astype(bool)


def candle_evening_star(df: pd.DataFrame, lookback: int = 60,
                        near_max_pct: float = 0.92) -> pd.Series:
    """
    Evening Star: 3 bar pattern. Bullish big → small body (gap up) → bearish big.
    """
    o = df['open'].astype(float)
    c = df['close'].astype(float)
    h = df['high'].astype(float)
    
    body = (c - o).abs()
    avg_body = body.rolling(20, min_periods=5).mean()
    
    bar_2_bullish = (c.shift(2) > o.shift(2)) & (body.shift(2) > 0.7 * avg_body)
    bar_1_small = body.shift(1) < 0.5 * avg_body
    bar_1_above = h.shift(1) > h.shift(2)
    bar_0_bearish = c < o
    bar_0_deep = c < (o.shift(2) + c.shift(2)) / 2
    
    is_pattern = bar_2_bullish & bar_1_small & bar_1_above & bar_0_bearish & bar_0_deep
    at_peak = _at_peak_zone(c, lookback, near_max_pct)
    return (is_pattern & at_peak).fillna(False).astype(bool)


def volume_climax_reversal(df: pd.DataFrame, vol_mult: float = 2.5,
                           wick_ratio: float = 0.4,
                           vol_lookback: int = 20,
                           lookback: int = 60,
                           near_max_pct: float = 0.92) -> pd.Series:
    """
    Hacim climax + bearish reversal candle (RTALB tipi blow-off detector).
    """
    if 'volume' not in df.columns:
        return pd.Series(False, index=df.index)
    
    vol = df['volume'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    c = df['close'].astype(float)
    o = df['open'].astype(float)
    
    vol_ma = vol.rolling(vol_lookback, min_periods=5).mean()
    is_climax_vol = vol > vol_mult * vol_ma
    
    bar_range = (h - l).replace(0, np.nan)
    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
    big_upper_wick = (upper_wick / bar_range) > wick_ratio
    bearish_close = c < o
    at_peak = _at_peak_zone(c, lookback, near_max_pct)
    
    return (is_climax_vol & big_upper_wick & bearish_close & at_peak).fillna(False).astype(bool)


def zscore_extreme_reversal(df: pd.DataFrame, length: int = 20,
                            z_threshold: float = 2.5,
                            lookback: int = 60,
                            near_max_pct: float = 0.92) -> pd.Series:
    """
    Fiyat 20-bar ort'dan >2.5 std uzakta + bearish bar.
    İstatistiksel outlier olduğu için "uzun süre devam edemez" tepe sinyali.
    """
    c = df['close'].astype(float)
    o = df['open'].astype(float)
    
    ma = c.rolling(length, min_periods=10).mean()
    std = c.rolling(length, min_periods=10).std()
    z = (c - ma) / std.replace(0, np.nan)
    
    extreme_high = z > z_threshold
    bearish_bar = c < o
    at_peak = _at_peak_zone(c, lookback, near_max_pct)
    return (extreme_high & bearish_bar & at_peak).fillna(False).astype(bool)


def multi_oscillator_convergence(df: pd.DataFrame,
                                 rsi_th: float = 70,
                                 stoch_th: float = 80,
                                 wr_th: float = -20,
                                 lookback: int = 60,
                                 near_max_pct: float = 0.92) -> pd.Series:
    """
    3+ momentum oscillator AYNI BARDA overbought + dönüş başlamış.
    Convergence = farklı zaman dilimli osilatörler aynı şeyi söylüyor.
    """
    r = rsi(df, 14)
    s = stochastic(df, 14)
    w = williams_r(df, 14)
    
    rsi_overbought_turn = (r > rsi_th) & (r < r.shift(1))
    stoch_overbought_turn = (s['k'] > stoch_th) & (s['k'] < s['k'].shift(1))
    wr_overbought_turn = (w > wr_th) & (w < w.shift(1))
    
    count = (rsi_overbought_turn.astype(int) +
             stoch_overbought_turn.astype(int) +
             wr_overbought_turn.astype(int))
    convergence = count >= 2
    
    c = df['close'].astype(float)
    at_peak = _at_peak_zone(c, lookback, near_max_pct)
    return (convergence & at_peak).fillna(False).astype(bool)


# ═══════════════════════════════════════════════════════════════════════════
# v2 SİNYAL REGISTRY
# ═══════════════════════════════════════════════════════════════════════════
PRE_PEAK_REGISTRY: Dict[str, Tuple[Callable, Dict]] = {
    'div_rsi':   (divergence_rsi,   {'length': [9, 14, 21], 'lookback': [20, 25, 30]}),
    'div_macd':  (divergence_macd,  {'lookback': [20, 25, 30]}),
    'div_mfi':   (divergence_mfi,   {'length': [10, 14, 21], 'lookback': [20, 25]}),
    'div_obv':   (divergence_obv,   {'lookback': [20, 25, 30]}),
    'div_cci':   (divergence_cci,   {'length': [14, 20], 'lookback': [20, 25]}),
}

CLIMAX_REGISTRY: Dict[str, Tuple[Callable, Dict]] = {
    'doji':         (candle_doji_at_top,           {'near_max_pct': [0.90, 0.92, 0.95]}),
    'shooting':     (candle_shooting_star,         {'near_max_pct': [0.90, 0.92, 0.95]}),
    'engulfing':    (candle_bearish_engulfing,     {'near_max_pct': [0.90, 0.92, 0.95]}),
    'evening':      (candle_evening_star,          {'near_max_pct': [0.90, 0.92]}),
    'vol_climax':   (volume_climax_reversal,       {'vol_mult': [2.0, 2.5, 3.0],
                                                     'near_max_pct': [0.90, 0.92]}),
    'z_extreme':    (zscore_extreme_reversal,      {'z_threshold': [2.0, 2.5],
                                                     'near_max_pct': [0.90, 0.92]}),
    'multi_osc':    (multi_oscillator_convergence, {'near_max_pct': [0.90, 0.92]}),
}


def expand_params(params: Dict) -> List[Dict]:
    if not params:
        return [{}]
    keys = list(params.keys())
    from itertools import product
    return [dict(zip(keys, combo)) for combo in product(*[params[k] for k in keys])]


# ═══════════════════════════════════════════════════════════════════════════
# v2 KARAR MOTORU — Pre-peak + Climax birleştirme
# ═══════════════════════════════════════════════════════════════════════════
def detect_v2_sell_signals(df: pd.DataFrame,
                            pre_peak_params: Optional[Dict] = None,
                            climax_params: Optional[Dict] = None,
                            confluence_window: int = 1) -> pd.DataFrame:
    """
    v2 sat sinyali tespiti. Her bar için:
      - pre_peak_count: kaç bearish divergence tetiklendi
      - climax_count: kaç climax pattern tetiklendi
      - confluence_window: A ve B kaç bar içinde aynı anda olmalı
      - signal_strength: 0=NOTR, 1=ZAYIF, 2=ORTA, 3=GUCLU, 4=KESIN
    """
    n = len(df)
    pre_peak_total = pd.Series(0, index=df.index)
    climax_total = pd.Series(0, index=df.index)
    
    pre_p = pre_peak_params or {}
    cl_p = climax_params or {}
    
    # Pre-peak sinyallerinin toplamı
    for name, (func, _) in PRE_PEAK_REGISTRY.items():
        try:
            params = pre_p.get(name, {})
            sig = func(df, **params)
            pre_peak_total = pre_peak_total + sig.astype(int)
        except Exception:
            continue
    
    # Climax sinyallerinin toplamı
    for name, (func, _) in CLIMAX_REGISTRY.items():
        try:
            params = cl_p.get(name, {})
            sig = func(df, **params)
            climax_total = climax_total + sig.astype(int)
        except Exception:
            continue
    
    # Confluence window: pre_peak'in son 'window' bar içinde olup olmadığı
    pre_peak_in_window = pre_peak_total.rolling(
        confluence_window, min_periods=1).max()
    climax_in_window = climax_total.rolling(
        confluence_window, min_periods=1).max()
    
    # Karar matrisi (DAHA SIKI - false positive azaltma):
    #   tek climax (climax==1, pre==0): 0 (NOTR — yetmez)
    #   2+ climax aynı barda: 1 (ZAYIF — climax convergence)
    #   pre var, climax yok: 1 (IZLE — divergence uyarısı)
    #   pre + 1 climax (confluence): 3 (GUCLU)
    #   pre + 2+ climax: 4 (KESIN)
    #   2+ pre + 1+ climax: 4 (KESIN — divergence convergence + climax)
    signal_strength = pd.Series(0, index=df.index)
    
    # ZAYIF: tek başlarına bilgi
    multi_climax = (climax_total >= 2) & (pre_peak_in_window == 0)
    only_pre = (pre_peak_total > 0) & (climax_in_window == 0)
    signal_strength[multi_climax] = 1
    signal_strength[only_pre] = 1
    
    # GUCLU: pre + climax confluence
    confluence = (pre_peak_in_window > 0) & (climax_total >= 1)
    signal_strength[confluence] = 3
    
    # KESIN: yüksek konfüzyon
    strong_confluence = (
        ((pre_peak_in_window >= 2) & (climax_total >= 1)) |
        ((pre_peak_in_window >= 1) & (climax_total >= 2))
    )
    signal_strength[strong_confluence] = 4
    
    return pd.DataFrame({
        'pre_peak_count': pre_peak_total,
        'climax_count': climax_total,
        'pre_peak_in_window': pre_peak_in_window,
        'climax_in_window': climax_in_window,
        'signal_strength': signal_strength,
        'is_strong': signal_strength >= 3,
        'is_definite': signal_strength >= 4
    }, index=df.index)


# ═══════════════════════════════════════════════════════════════════════════
# v2 PERFORMANS DEĞERLENDİRME
# ═══════════════════════════════════════════════════════════════════════════
def evaluate_v2_signals(df: pd.DataFrame, signal: pd.Series,
                        forward_window: int = 60) -> Dict:
    """
    v2 sinyallerinin gerçek performansı.
    Kritik metrik: PEAK PROXIMITY (sinyalin gerçek tepeye uzaklığı).
    """
    close = df['close'].astype(float)
    close_vals = close.values
    sig_vals = signal.values.astype(bool)
    n = len(close_vals)
    
    signal_indices = np.where(sig_vals)[0]
    valid_indices = [i for i in signal_indices if i + forward_window < n]
    
    if not valid_indices:
        return {
            'n_signals': 0, 'success_rate': 0.0, 'avg_max_drop': 0.0,
            'avg_reverse_run': 0.0, 'avg_peak_lag': 999.0,
            'pct_at_peak_0_2': 0.0, 'pct_at_peak_0_5': 0.0,
            'quality': 0.0
        }
    
    max_drops = []
    reverse_runs = []
    peak_lags = []
    
    for idx in valid_indices:
        entry = close_vals[idx]
        if entry <= 0 or np.isnan(entry):
            continue
        
        # Forward window analizi
        fw = close_vals[idx + 1: idx + 1 + forward_window]
        if len(fw) == 0:
            continue
        trough = np.nanmin(fw)
        peak = np.nanmax(fw)
        drop = (entry - trough) / entry * 100
        reverse = max(0.0, (peak - entry) / entry * 100)
        
        # Peak lag: sinyalden geri bakıp gerçek tepeyi bul
        # Kısa pencerede (15 bar) geri bakıyoruz çünkü "yakın tepe" arıyoruz
        lookback_window = 15
        lookback_data = close_vals[max(0, idx - lookback_window): idx + 1]
        if len(lookback_data) > 0:
            local_peak_offset = int(np.argmax(lookback_data))
            lag = (len(lookback_data) - 1) - local_peak_offset
        else:
            lag = 0
        
        max_drops.append(max(0.0, drop))
        reverse_runs.append(reverse)
        peak_lags.append(lag)
    
    if not max_drops:
        return {
            'n_signals': 0, 'success_rate': 0.0, 'avg_max_drop': 0.0,
            'avg_reverse_run': 0.0, 'avg_peak_lag': 999.0,
            'pct_at_peak_0_2': 0.0, 'pct_at_peak_0_5': 0.0,
            'quality': 0.0
        }
    
    n_sig = len(max_drops)
    arr_d = np.array(max_drops)
    arr_r = np.array(reverse_runs)
    arr_l = np.array(peak_lags)
    
    # GEVŞEK SUCCESS KRİTERLERİ — gerçek BIST kalibrasyonu
    success_count = int((arr_d >= 8.0).sum())    # %8+ düşüş = başarı
    big_success = int((arr_d >= 15.0).sum())     # %15+ düşüş = büyük başarı
    success_rate = success_count / n_sig * 100
    
    avg_drop = float(arr_d.mean())
    avg_reverse = float(arr_r.mean())
    avg_lag = float(arr_l.mean())
    
    # PEAK PROXIMITY metrikleri
    pct_lag_0_2 = float((arr_l <= 2).sum()) / n_sig * 100
    pct_lag_0_5 = float((arr_l <= 5).sum()) / n_sig * 100
    
    # Composite quality — yeni kalibrasyon
    norm_drop = min(avg_drop / 25.0 * 100, 100)       # 40 → 25 (daha gerçekçi)
    norm_reverse = min(avg_reverse / 30.0 * 100, 100)  # 20 → 30 (daha hoşgörülü)
    proximity_score = pct_lag_0_2
    
    quality = (
        success_rate * 0.30 +       # %8+ düşüş başarısı (ana faktör)
        norm_drop * 0.25 +           # ortalama düşüş
        proximity_score * 0.25 +     # peak proximity
        min(n_sig / 8 * 100, 100) * 0.10 -  # adequacy
        norm_reverse * 0.10          # yanlış yön cezası
    )
    quality = max(0.0, min(100.0, quality))
    
    return {
        'n_signals': n_sig,
        'success_rate': round(success_rate, 2),
        'big_success_rate': round(big_success / n_sig * 100, 2),
        'avg_max_drop': round(avg_drop, 2),
        'avg_reverse_run': round(avg_reverse, 2),
        'avg_peak_lag': round(avg_lag, 2),
        'pct_at_peak_0_2': round(pct_lag_0_2, 2),
        'pct_at_peak_0_5': round(pct_lag_0_5, 2),
        'quality': round(quality, 2)
    }


# ═══════════════════════════════════════════════════════════════════════════
# v2 ANA FONKSİYON: build_sell_v2_dna
# ═══════════════════════════════════════════════════════════════════════════
MIN_BARS_TOTAL = 500
MAX_BARS_TOTAL = 5000
TRAIN_RATIO = 0.65
TEST_RATIO = 0.30


def build_sell_v2_dna(df: pd.DataFrame, symbol: str = '') -> Dict:
    """
    v2 SAT DNA üretici. Pre-peak + climax sinyallerinin EN İYİ
    ağırlıklı kombinasyonunu bulur.
    
    v1'den farkı: parametre optimizasyonu yapmaz (her sinyal kendi içinde
    iyi kalibre edilmiş), bunun yerine GUCLU ve KESIN sinyalleri çıkarır.
    """
    t0 = time.time()
    total = len(df)
    
    if total < MIN_BARS_TOTAL:
        return {
            'symbol': symbol, 'status': 'FAIL',
            'reason': f'Yetersiz geçmiş: {total} bar, en az {MIN_BARS_TOTAL} gerekli',
            'quality': None, 'build_time_sec': 0.0
        }
    
    if total > MAX_BARS_TOTAL:
        df = df.tail(MAX_BARS_TOTAL).copy()
    df = df.reset_index(drop=True)
    
    # Train/test split
    train_end = int(len(df) * TRAIN_RATIO)
    test_start = train_end + int(len(df) * 0.05)  # %5 purge
    
    train_df = df.iloc[:train_end].copy()
    test_df = df.iloc[test_start:].copy()
    
    # v2 sinyalleri tespit et (default parametrelerle)
    train_sigs = detect_v2_sell_signals(train_df)
    test_sigs = detect_v2_sell_signals(test_df)
    
    # GUCLU (strength >= 3) sinyallerin performansı
    train_strong = train_sigs['is_strong']
    test_strong = test_sigs['is_strong']
    
    train_perf = evaluate_v2_signals(train_df, train_strong)
    test_perf = evaluate_v2_signals(test_df, test_strong)
    
    # KESIN (strength >= 4) sinyallerin performansı
    train_definite = train_sigs['is_definite']
    test_definite = test_sigs['is_definite']
    
    train_perf_definite = evaluate_v2_signals(train_df, train_definite)
    test_perf_definite = evaluate_v2_signals(test_df, test_definite)
    
    # SİNYAL TİPİ — durum etiketlerinden farklı isim
    if test_perf_definite['n_signals'] >= 2:
        chosen_mode = 'KESIN_SAT'      # 2+ pre-peak + 1+ climax (en güçlü)
        chosen_train = train_perf_definite
        chosen_test = test_perf_definite
    else:
        chosen_mode = 'GUCLU_SAT'      # 1 pre-peak + 1 climax (standart güçlü)
        chosen_train = train_perf
        chosen_test = test_perf
    
    combined_quality = (chosen_train['quality'] + chosen_test['quality']) / 2
    
    overfit = False
    if chosen_train['quality'] > 0:
        drop = (chosen_train['quality'] - chosen_test['quality']) / chosen_train['quality']
        if drop > 0.40:
            overfit = True
    
    # 4 SEVİYELİ DURUM SİSTEMİ — açık ve net
    if combined_quality >= 45 and chosen_test['n_signals'] >= 3 and not overfit:
        status = 'GUVENILIR'
        reason = (f"🟢 Güvenilir SAT motoru · test penceresinde "
                  f"{chosen_test['n_signals']} sinyal · "
                  f"%{chosen_test['success_rate']:.0f} başarı · "
                  f"ortalama %{chosen_test['avg_max_drop']:.0f} düşüş")
    elif combined_quality >= 25 and chosen_test['n_signals'] >= 2:
        status = 'ORTA'
        reason = (f"🟡 Orta güven seviyesi · {chosen_test['n_signals']} test sinyali · "
                  f"%{chosen_test['success_rate']:.0f} başarı · "
                  f"daha çok geçmiş veriyle iyileşebilir")
    elif combined_quality >= 8 and chosen_test['n_signals'] >= 1:
        status = 'ZAYIF'
        reason = (f"🟠 Zayıf güven · sadece {chosen_test['n_signals']} test sinyali · "
                  f"istatistiksel anlamlılık düşük · sinyallere dikkatle yaklaş")
    elif chosen_test['n_signals'] >= 1:
        status = 'BELIRSIZ'
        reason = (f"🟠 Sinyaller var ama tutarlılık yetersiz · "
                  f"{chosen_test['n_signals']} sinyal · "
                  f"yanlış yön kaçma yüksek")
    else:
        status = 'YETERSIZ'
        reason = ("🔴 Test penceresinde anlamlı SAT sinyali yok · "
                  "bu hisse SAT v2 ile uyumsuz olabilir veya yatay seyirde")
    
    return {
        'symbol': symbol,
        'side': 'SELL_V2',
        'version': 'v2.0_pre_peak_climax',
        'status': status,
        'mode': chosen_mode,
        'reason': reason,
        'quality': round(combined_quality, 2),
        'train_perf': chosen_train,
        'test_perf': chosen_test,
        'overfit': overfit,
        'guclu_train': train_perf,
        'guclu_test': test_perf,
        'kesin_train': train_perf_definite,
        'kesin_test': test_perf_definite,
        'kullanilan_bar': len(df),
        'train_bars': train_end,
        'test_bars': len(df) - test_start,
        'build_time_sec': round(time.time() - t0, 2)
    }


# ═══════════════════════════════════════════════════════════════════════════
# v2 STORAGE (ayrı namespace, mevcut sisteme zarar yok)
# ═══════════════════════════════════════════════════════════════════════════
def _v2_storage_dir() -> str:
    if os.path.exists('/data') and os.access('/data', os.W_OK):
        d = '/data/dna_sell_v2_cards'
    else:
        d = '/tmp/dna_sell_v2_cards'
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


V2_STORAGE_DIR = _v2_storage_dir()


def save_sell_v2_dna(symbol: str, dna_data: Dict, ttl_days: int = 30) -> bool:
    if not symbol:
        return False
    clean = ''.join(c for c in symbol.upper() if c.isalnum())
    path = os.path.join(V2_STORAGE_DIR, f'{clean}.json')
    tmp = path + '.tmp'
    record = {
        **dna_data,
        '_stored_at': int(time.time()),
        '_ttl_days': ttl_days,
        '_expires_at': int(time.time()) + ttl_days * 86400
    }
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(record, f, ensure_ascii=False, default=str)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"[SELL_V2_STORE] save hata: {e}")
        return False


def load_sell_v2_dna(symbol: str) -> Optional[Dict]:
    if not symbol:
        return None
    clean = ''.join(c for c in symbol.upper() if c.isalnum())
    path = os.path.join(V2_STORAGE_DIR, f'{clean}.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            record = json.load(f)
        if record.get('_expires_at', 0) > 0 and time.time() > record['_expires_at']:
            return None
        return record
    except Exception as e:
        print(f"[SELL_V2_STORE] load hata: {e}")
        return None


def list_sell_v2_dna() -> List[Dict]:
    summaries = []
    try:
        for filename in os.listdir(V2_STORAGE_DIR):
            if not filename.endswith('.json'):
                continue
            symbol = filename[:-5]
            record = load_sell_v2_dna(symbol)
            if record is None:
                continue
            summaries.append({
                'symbol': record.get('symbol', symbol),
                'status': record.get('status'),
                'mode': record.get('mode'),
                'quality': record.get('quality'),
                'peak_lag': record.get('test_perf', {}).get('avg_peak_lag'),
                'success_rate': record.get('test_perf', {}).get('success_rate'),
                'stored_at': record.get('_stored_at')
            })
    except Exception as e:
        print(f"[SELL_V2_STORE] list hata: {e}")
    summaries.sort(key=lambda x: x.get('quality') or -1, reverse=True)
    return summaries


def sell_v2_storage_info() -> Dict:
    try:
        files = [f for f in os.listdir(V2_STORAGE_DIR) if f.endswith('.json')]
        return {
            'storage_dir': V2_STORAGE_DIR,
            'is_persistent': V2_STORAGE_DIR.startswith('/data'),
            'v2_dna_count': len(files),
            'files': sorted(files)
        }
    except Exception as e:
        return {'storage_dir': V2_STORAGE_DIR, 'error': str(e), 'v2_dna_count': 0}
