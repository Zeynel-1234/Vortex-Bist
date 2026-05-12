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
# DİNAMİK DİRENÇ HATTI TESPİTİ — Zeynel'in talep ettiği TAM TEPE motorunun çekirdeği
# ─────────────────────────────────────────────────────────────────────────
# Çoklu yerel tepelerden geçen LİNEER REGRESYON ile direnç çizgisi çizilir.
# Fiyat bu çizgiye değdiği barda + bearish kapanış → SAT sinyali.
#
# KARSN gibi grafiklerde:
#   - 2024 Q3-Q4: Yükselen tepeler (yukarı eğimli direnç hattı)
#   - 2025: Düşen tepeler (aşağı eğimli direnç hattı)
#   - Tepe bar her zaman bu çizgiye DEĞER ve ondan REDDEDİLİR
# ═══════════════════════════════════════════════════════════════════════════
def find_all_local_peaks(df: pd.DataFrame, pivot_window: int = 5) -> List[Tuple[int, float]]:
    """Tüm yerel tepeleri (lokal max) bul - pivot_window=5 → 11-bar pencerede max."""
    if 'high' not in df.columns:
        return []
    high = df['high'].values
    n = len(df)
    pivots = []
    for i in range(pivot_window, n - pivot_window):
        window_max = high[i - pivot_window:i + pivot_window + 1].max()
        if high[i] >= window_max - 1e-9:
            pivots.append((i, float(high[i])))
    return pivots


def fit_resistance_line(pivots: List[Tuple[int, float]],
                        n_recent: int = 3) -> Optional[Dict]:
    """
    En son n_recent pivot noktasından geçen lineer regresyon doğrusu.
    Returns: {slope, intercept, pivots, n_pivots} veya None.
    """
    if len(pivots) < 2:
        return None
    recent = pivots[-n_recent:] if len(pivots) >= n_recent else pivots
    if len(recent) < 2:
        return None
    xs = np.array([p[0] for p in recent], dtype=float)
    ys = np.array([p[1] for p in recent], dtype=float)
    slope, intercept = np.polyfit(xs, ys, 1)
    return {
        'slope': float(slope),
        'intercept': float(intercept),
        'pivots': recent,
        'n_pivots': len(recent)
    }


def resistance_line_touch(df: pd.DataFrame,
                          pivot_window: int = 5,
                          n_pivots: int = 3,
                          tolerance_pct: float = 2.0,
                          min_runup_pct: float = 8.0) -> pd.Series:
    """
    Her bar için: o bar dinamik direnç hattına değdi ve REDDEDİLDİ mi?
    
    Sinyal koşulu (hepsi aynı barda):
      1. Önceki barlarda en az n_pivots yerel tepe var
      2. Bu tepelerden geçen çizgi var (lineer regresyon)
      3. Bu bar'ın high'ı çizgiye tolerance_pct içinde
      4. Bu bar bearish kapandı (close < open) — REDDEDİLME teyidi
      5. Son 90 günde anlamlı bir yükseliş olmuş (min_runup_pct)
         → tepe pattern'i için anlamlı bir ralli gerekli
    """
    out = pd.Series(False, index=df.index)
    n = len(df)
    if n < 50:
        return out
    if 'high' not in df.columns or 'close' not in df.columns:
        return out
    
    high = df['high'].values
    close = df['close'].values
    open_ = df['open'].values if 'open' in df.columns else close
    
    # Tüm lokal tepeleri bir kez bul (O(n))
    all_pivots = []
    for i in range(pivot_window, n - pivot_window):
        if high[i] >= max(high[i - pivot_window:i + pivot_window + 1]) - 1e-9:
            all_pivots.append((i, float(high[i])))
    
    if len(all_pivots) < n_pivots:
        return out
    
    # Min runup için close serisinde rolling min hesapla
    close_series = pd.Series(close)
    rolling_min = close_series.rolling(90, min_periods=20).min().values
    
    # Her bar için (50'den itibaren) touch kontrolü
    pivot_idx = 0  # iterator için
    for i in range(50, n):
        # i'den önceki pivotları geç (mevcut bar geçmişine kadar olanlar)
        valid_pivots = [(p_idx, p_val) for p_idx, p_val in all_pivots if p_idx < i]
        if len(valid_pivots) < n_pivots:
            continue
        
        # Son n_pivots
        recent = valid_pivots[-n_pivots:]
        xs = np.array([p[0] for p in recent], dtype=float)
        ys = np.array([p[1] for p in recent], dtype=float)
        
        try:
            slope, intercept = np.polyfit(xs, ys, 1)
        except Exception:
            continue
        
        line_value = slope * i + intercept
        if line_value <= 0:
            continue
        
        # Touch kontrolü: high'ın çizgiye uzaklığı
        distance_pct = (high[i] - line_value) / line_value * 100
        if abs(distance_pct) > tolerance_pct:
            continue
        
        # Bearish bar zorunlu (reddedilme teyidi)
        if close[i] >= open_[i]:
            continue
        
        # Anlamlı runup kontrolü
        if not np.isnan(rolling_min[i]) and rolling_min[i] > 0:
            runup = (close[i] - rolling_min[i]) / rolling_min[i] * 100
            if runup < min_runup_pct:
                continue
        
        out.iloc[i] = True
    
    return out


def get_current_resistance_status(df: pd.DataFrame,
                                   pivot_window: int = 5,
                                   n_pivots: int = 3,
                                   tolerance_pct: float = 2.0) -> Dict:
    """
    MEVCUT bar için direnç hattı durumu (anlık karar için).
    Bu fonksiyon /sell_v2/{symbol} endpoint'inde "BUGÜN dokundu mu?" cevabı verir.
    """
    n = len(df)
    if n < 50 or 'high' not in df.columns:
        return {'touched': False, 'reason': f'Yetersiz veri (n={n})'}
    
    high = df['high'].values
    close = df['close'].values
    open_ = df['open'].values if 'open' in df.columns else close
    
    # Tüm lokal tepeleri bul
    all_pivots = find_all_local_peaks(df, pivot_window=pivot_window)
    
    if len(all_pivots) < n_pivots:
        return {
            'touched': False,
            'reason': f'Yetersiz tepe ({len(all_pivots)} bulundu, en az {n_pivots} gerekli)',
            'n_pivots_found': len(all_pivots)
        }
    
    # Son n_pivots'i kullan
    line = fit_resistance_line(all_pivots, n_recent=n_pivots)
    if line is None:
        return {'touched': False, 'reason': 'Çizgi fit edilemedi'}
    
    # Mevcut bar için çizgi değeri
    last_idx = n - 1
    line_value = line['slope'] * last_idx + line['intercept']
    
    if line_value <= 0:
        return {'touched': False, 'reason': 'Çizgi değeri negatif'}
    
    today_high = float(high[last_idx])
    today_close = float(close[last_idx])
    today_open = float(open_[last_idx])
    
    distance_pct = (today_high - line_value) / line_value * 100
    touched_geometric = abs(distance_pct) <= tolerance_pct
    bearish_today = today_close < today_open
    
    # Direnç hattının trendi
    # slope > 0: yükselen direnç (boğa kanalı tavanı)
    # slope < 0: azalan direnç (klasik düşüş)
    # slope ≈ 0: yatay direnç
    if abs(line['slope']) < 0.01:
        line_trend = 'YATAY'
    elif line['slope'] > 0:
        line_trend = 'YÜKSELEN'
    else:
        line_trend = 'AZALAN'
    
    return {
        'touched': bool(touched_geometric and bearish_today),
        'touched_geometric': bool(touched_geometric),
        'bearish_today': bool(bearish_today),
        'high_today': today_high,
        'close_today': today_close,
        'open_today': today_open,
        'line_value_today': float(line_value),
        'distance_pct': float(distance_pct),
        'slope': float(line['slope']),
        'line_trend': line_trend,
        'n_pivots_used': line['n_pivots'],
        'pivots': [{'idx': int(p[0]), 'high': p[1]} for p in line['pivots']],
        'tolerance_pct': tolerance_pct
    }


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
# DİNAMİK DİRENÇ HATTI TESPİTİ — KARSN gibi hisselerde son tepe yakalama
# ───────────────────────────────────────────────────────────────────────────
# Algoritma:
#   1. Son N bardaki tüm yerel tepe noktalarını (pivot highs) bul
#   2. En güncel n_pivots tepe alın
#   3. Bu noktalara lineer regresyon: y = mx + b (direnç çizgisi)
#   4. Her bar için line_value = m * idx + b hesapla
#   5. high / line_value yakınlığı ≤ tolerance_pct → ÇİZGİYE DOKUNDU
#   6. + bearish kapanış + son 90 barda yeterli yükseliş → SAT TETİKLE
# ═══════════════════════════════════════════════════════════════════════════
def find_all_local_peaks(high_series: pd.Series, pivot_window: int = 5) -> List[Tuple[int, float]]:
    """
    Yerel tepe noktalarını bulur. Bar pivot high'tır eğer
    pivot_window kadar bar etrafında en yüksek high'a sahipse.
    
    Returns: [(bar_idx, high_value), ...]
    """
    if len(high_series) < 2 * pivot_window + 1:
        return []
    
    pivots = []
    highs = high_series.values
    n = len(highs)
    
    for i in range(pivot_window, n - pivot_window):
        # Bar i, etrafındaki pivot_window bar boyunca en yüksek olmalı
        left = highs[i - pivot_window:i]
        right = highs[i + 1:i + pivot_window + 1]
        if highs[i] >= left.max() and highs[i] >= right.max():
            pivots.append((i, float(highs[i])))
    
    return pivots


def fit_resistance_line(pivots: List[Tuple[int, float]],
                         n_recent: int = 3) -> Optional[Dict]:
    """
    Son n_recent pivot high noktasından lineer regresyon ile direnç çizgisi.
    
    Returns: {'slope': m, 'intercept': b, 'pivots_used': [...], 'n': N}
             veya None (yeterli pivot yoksa)
    """
    if len(pivots) < n_recent:
        return None
    
    recent = pivots[-n_recent:]
    xs = np.array([p[0] for p in recent], dtype=float)
    ys = np.array([p[1] for p in recent], dtype=float)
    
    # Lineer regresyon (numpy polyfit)
    try:
        slope, intercept = np.polyfit(xs, ys, 1)
    except Exception:
        return None
    
    return {
        'slope': float(slope),
        'intercept': float(intercept),
        'pivots_used': [{'idx': int(p[0]), 'high': float(p[1])} for p in recent],
        'n_pivots': len(recent)
    }


def resistance_line_touch(df: pd.DataFrame,
                          pivot_window: int = 5,
                          n_pivots: int = 3,
                          tolerance_pct: float = 2.0,
                          min_runup_pct: float = 8.0,
                          near_max_pct: float = 0.92) -> pd.Series:
    """
    Dinamik direnç çizgisine dokunma sinyali.
    
    Bir bar SAT sinyali verir eğer:
      a) Fiyat dinamik direnç hattının ≤tolerance_pct yakınında (TEMAS)
      b) Bearish kapanış (close < open)
      c) Son 90 barda dipten ≥min_runup_pct yükseliş (rally olmuş)
    
    Args:
      df: OHLC DataFrame
      pivot_window: Pivot high tespiti için pencere (5 = lokal max)
      n_pivots: Lineer regresyon için kullanılacak son pivot sayısı (3 = klasik trend)
      tolerance_pct: Çizgiye dokunma toleransı (%2 = makul yakınlık)
      min_runup_pct: Sinyalden önce minimum yükseliş (%8 = anlamlı rally)
      near_max_pct: Bonus filtre — fiyat son 60g max'ın bu oranında olmalı
    
    Returns: pd.Series[bool] — her bar için sinyal aktif mi
    """
    n = len(df)
    out = pd.Series(False, index=df.index)
    
    if n < max(2 * pivot_window + 1, 90):
        return out
    
    if 'high' not in df.columns or 'close' not in df.columns or 'open' not in df.columns:
        return out
    
    high = df['high']
    close = df['close']
    open_ = df['open']
    
    # Tüm pivot high'ları bul
    all_pivots = find_all_local_peaks(high, pivot_window=pivot_window)
    
    if len(all_pivots) < n_pivots:
        return out
    
    # Her bar için: o bardan ÖNCEKİ pivotlarla çizgi çiz, o bara dokunuyor mu kontrol et
    # Bu sayede backtest doğru olur (look-ahead bias yok)
    highs_arr = high.values
    closes_arr = close.values
    opens_arr = open_.values
    
    for i in range(2 * pivot_window + 1, n):
        # i. bardan önceki pivot'lar (gelecek bilgi sızmasın)
        past_pivots = [(p_idx, p_high) for (p_idx, p_high) in all_pivots if p_idx < i - pivot_window]
        if len(past_pivots) < n_pivots:
            continue
        
        # Son n_pivots tepe ile direnç çizgisi
        line = fit_resistance_line(past_pivots, n_recent=n_pivots)
        if line is None:
            continue
        
        # Bu bardaki line değeri
        line_val = line['slope'] * i + line['intercept']
        if line_val <= 0:
            continue
        
        # high çizgiye yakın mı? (çizgiye değme veya çok yakın aşma)
        distance_pct = (highs_arr[i] - line_val) / line_val * 100
        # high çizgiye değmiş VE üstüne çıkmamış olmalı (veya hafif aşmış)
        if not (-tolerance_pct <= distance_pct <= tolerance_pct):
            continue
        
        # Bearish kapanış konfirmasyonu
        if closes_arr[i] >= opens_arr[i]:
            continue
        
        # Son 90 barda dipten yükseliş kontrolü (anlamlı rally olmuş mu?)
        start_idx = max(0, i - 90)
        recent_min = float(np.min(closes_arr[start_idx:i + 1]))
        runup_pct = (closes_arr[i] / recent_min - 1) * 100 if recent_min > 0 else 0
        if runup_pct < min_runup_pct:
            continue
        
        out.iloc[i] = True
    
    return out.astype(bool)


def get_current_resistance_status(df: pd.DataFrame,
                                    pivot_window: int = 5,
                                    n_pivots: int = 3,
                                    tolerance_pct: float = 2.0) -> Dict:
    """
    BUGÜNKÜ dinamik direnç çizgisi durumu — UI raporu için.
    
    Returns:
      {
        'cizgi_var': bool,
        'yon': 'YÜKSELEN'/'AZALAN'/'YATAY',
        'slope': float,
        'cizgi_degeri_bugun': float,
        'son_high': float,
        'son_close': float,
        'uzaklik_pct': float (pozitif=high üstte, negatif=high altta),
        'dokundu_mu': bool,
        'pivots_used': [{'tarih': '...', 'high': X}, ...]
      }
    """
    if 'high' not in df.columns or len(df) < 60:
        return {'cizgi_var': False, 'sebep': 'Yetersiz veri'}
    
    pivots = find_all_local_peaks(df['high'], pivot_window=pivot_window)
    if len(pivots) < n_pivots:
        return {'cizgi_var': False, 'sebep': f'Yetersiz pivot ({len(pivots)} < {n_pivots})'}
    
    line = fit_resistance_line(pivots, n_recent=n_pivots)
    if line is None:
        return {'cizgi_var': False, 'sebep': 'Çizgi fit edilemedi'}
    
    today_idx = len(df) - 1
    line_value_today = line['slope'] * today_idx + line['intercept']
    today_high = float(df['high'].iloc[-1])
    today_close = float(df['close'].iloc[-1])
    distance_pct = (today_high - line_value_today) / line_value_today * 100 if line_value_today > 0 else 0
    
    # Çizgi yönü (slope bar başına TL → %'ye çevir)
    slope_pct_per_bar = (line['slope'] / line_value_today * 100) if line_value_today > 0 else 0
    if slope_pct_per_bar > 0.05:
        yon = "YÜKSELEN"
    elif slope_pct_per_bar < -0.05:
        yon = "AZALAN"
    else:
        yon = "YATAY"
    
    # Pivot tarih bilgisi (varsa)
    pivots_with_dates = []
    for p in line['pivots_used']:
        idx = p['idx']
        try:
            tarih = str(df.index[idx].date()) if hasattr(df.index[idx], 'date') else f"bar {idx}"
        except Exception:
            tarih = f"bar {idx}"
        pivots_with_dates.append({'tarih': tarih, 'high': p['high'], 'idx': idx})
    
    return {
        'cizgi_var': True,
        'yon': yon,
        'slope': float(line['slope']),
        'slope_pct': float(slope_pct_per_bar),
        'cizgi_degeri_bugun': float(line_value_today),
        'son_high': float(today_high),
        'son_close': float(today_close),
        'uzaklik_pct': float(distance_pct),
        'dokundu_mu': bool(abs(distance_pct) <= tolerance_pct),
        'pivots_used': pivots_with_dates,
        'n_pivots': line['n_pivots']
    }


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
    # YENİ: Dinamik direnç çizgisi dokunması — KARSN gibi grafiklerin son tepesini yakalar
    'resist_line':  (resistance_line_touch,        {'pivot_window': [5, 7],
                                                     'n_pivots': [3],
                                                     'tolerance_pct': [1.5, 2.0, 3.0],
                                                     'min_runup_pct': [8.0, 12.0]}),
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
    
    # SADECE 2 ETİKET: GUCLU veya BEKLE
    # GUCLU = bu DNA train+test güvenilir + 4 kapı kontrol için hazır
    # BEKLE = motor bu hisse için yeterli sinyal üretemiyor
    if combined_quality >= 25 and chosen_test['n_signals'] >= 2 and not overfit:
        dna_status = 'GUCLU'
        dna_reason = (f"Motor güvenilir · {chosen_test['n_signals']} test sinyali · "
                       f"%{chosen_test['success_rate']:.0f} başarı · "
                       f"ort %{chosen_test['avg_max_drop']:.0f} düşüş yakaladı")
    else:
        dna_status = 'BEKLE'
        n = chosen_test['n_signals']
        if n == 0:
            dna_reason = "Bu hisse için tepe-dönüş sinyali tetiklenmedi (yatay seyir veya düşüş trendi)"
        else:
            dna_reason = (f"Yetersiz veri (sadece {n} test sinyali) — "
                          f"motor bu hissede güvenilir değil")
    
    return {
        'symbol': symbol,
        'side': 'SELL_V2',
        'version': 'v3.0_4kapi',
        'dna_status': dna_status,         # 'GUCLU' veya 'BEKLE' (sadece DNA güvenilirliği)
        'dna_reason': dna_reason,
        'mode': chosen_mode,
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


# ═══════════════════════════════════════════════════════════════════════════
# 4 KAPILI SAT KARAR MOTORU — AL motorunun SİMETRİĞİ
# ───────────────────────────────────────────────────────────────────────────
# AL Sistemi (mevcut, çalışıyor):
#   Kapı 1: NVS ≥ 65          → "genel teknik sağlık iyi"
#   Kapı 2: Fraktal ≥ 65      → "zirveden alma yok"
#   Kapı 3: LAB DNA ≥ 50      → "hisseye özel strateji güvenilir"
#   Kapı 4: Momentum risk ≤ 1 → "kısa vade yukarı veya yatay"
#
# SAT Sistemi (AL'ın simetriği):
#   Kapı 1: AL KOŞULU DÜŞMÜŞ  → NVS < 65 VEYA Fraktal < 65
#   Kapı 2: TEPE BÖLGESİNDE   → fiyat son 60 günün max'ının %92'sinde
#   Kapı 3: SAT DNA GÜVENİLİR → Quality ≥ 25 + en az 2 test sinyali
#   Kapı 4: MOMENTUM AŞAĞI    → risk_skoru ≥ 1 (YATAY/AŞAĞI_ZAYIF/AŞAĞI_GÜÇLÜ)
#                              YANİ momentum YUKARI değil
#
# Dört kapı GEÇERSE → GÜÇLÜ SAT
# En az BİRİ geçmezse → BEKLE
#
# Bu sistem AL ve SAT'ın AYNI HİSSE için aynı anda tetiklenmesini ENGELLER.
# ═══════════════════════════════════════════════════════════════════════════
def current_sat_decision(df: pd.DataFrame,
                         dna_quality: Optional[float] = None,
                         dna_test_n: Optional[int] = None,
                         nvs_score: Optional[float] = None,
                         fraktal_score: Optional[float] = None,
                         momentum_risk: Optional[int] = None,
                         momentum_yorum: Optional[str] = None,
                         momentum_r3: Optional[float] = None) -> Dict:
    """
    4 kapılı SAT karar motoru.
    
    Args:
        df: Son veriler (peak zone kontrolü için)
        dna_quality: SAT v2 DNA kalite skoru (0-100)
        dna_test_n: Test penceresindeki sinyal sayısı
        nvs_score: Mevcut NVS skoru
        fraktal_score: Mevcut Fraktal skoru
        momentum_risk: Momentum risk_skoru (-1, 0, 1, 2, 3)
        momentum_yorum: Momentum yorumu (YUKARI_GÜÇLÜ vb)
        momentum_r3: Son 3 bar % getiri
    
    Returns:
        dict: {karar, kapi1, kapi2, kapi3, kapi4, aciklama, detay}
    """
    # ─── KAPI 1: AL KOŞULU DÜŞMÜŞ ───────────────────────────────────────
    # AL için: NVS >= 65 VE Fraktal >= 65 olmalıydı
    # SAT için: en az BİRİ düşmüş olmalı (NVS<65 VEYA Fraktal<65)
    if nvs_score is None or fraktal_score is None:
        kapi1 = None  # bilinmiyor
        kapi1_detay = "NVS/Fraktal bilgisi yok"
    else:
        kapi1 = (nvs_score < 65) or (fraktal_score < 65)
        if kapi1:
            kapi1_detay = f"AL koşulu düştü (NVS={nvs_score:.0f}, Fraktal={fraktal_score:.0f})"
        else:
            kapi1_detay = f"AL koşulları HÂLÂ GEÇERLİ (NVS={nvs_score:.0f}≥65, Fraktal={fraktal_score:.0f}≥65)"
    
    # ─── KAPI 2: TEPE BÖLGESİNDE ────────────────────────────────────────
    # Fiyat son 60 günün max'ının %92'sinde + son 90'da %12+ yükseliş var
    if df is not None and len(df) >= 30:
        close = df['close'].astype(float)
        at_peak = _at_peak_zone(close)
        kapi2 = bool(at_peak.iloc[-1])
        
        # Detay için son fiyat ve max
        last_price = float(close.iloc[-1])
        lookback = min(60, len(close))
        recent_max = float(close.iloc[-lookback:].max())
        proximity_pct = (last_price / recent_max * 100) if recent_max > 0 else 0
        
        if kapi2:
            kapi2_detay = f"Tepe bölgesinde (son 60g max'ın %{proximity_pct:.0f}'i)"
        else:
            kapi2_detay = f"Tepeden uzakta (max'ın %{proximity_pct:.0f}'i, %92 gerekli)"
    else:
        kapi2 = None
        kapi2_detay = "Yetersiz veri"
    
    # ─── KAPI 3: SAT DNA GÜVENİLİR ──────────────────────────────────────
    # Quality ≥ 25 VE test penceresinde en az 2 sinyal var
    if dna_quality is None:
        kapi3 = None
        kapi3_detay = "SAT DNA henüz üretilmemiş"
    else:
        kapi3 = (dna_quality >= 25) and ((dna_test_n or 0) >= 2)
        if kapi3:
            kapi3_detay = f"DNA güvenilir (kalite={dna_quality:.0f}, test n={dna_test_n})"
        elif dna_quality < 25:
            kapi3_detay = f"DNA kalitesi yetersiz ({dna_quality:.0f} < 25)"
        else:
            kapi3_detay = f"Yetersiz test sinyali (n={dna_test_n}, en az 2 gerekli)"
    
    # ─── KAPI 4: MOMENTUM AŞAĞI ─────────────────────────────────────────
    # risk_skoru ≥ 1 (YATAY veya aşağı yönlü). risk -1 veya 0 ise YUKARI demek.
    if momentum_risk is None:
        kapi4 = None
        kapi4_detay = "Momentum bilgisi yok"
    else:
        kapi4 = momentum_risk >= 1  # 1=YATAY, 2=AŞAĞI_ZAYIF, 3=AŞAĞI_GÜÇLÜ
        if kapi4:
            yorum_text = momentum_yorum or "?"
            r3_text = f" (r3={momentum_r3:+.1f}%)" if momentum_r3 is not None else ""
            kapi4_detay = f"Momentum {yorum_text}{r3_text} — yukarı yönlü DEĞİL"
        else:
            yorum_text = momentum_yorum or "?"
            r3_text = f" (r3={momentum_r3:+.1f}%)" if momentum_r3 is not None else ""
            kapi4_detay = f"Momentum HÂLÂ YUKARI {yorum_text}{r3_text} — SAT yanlış olur"
    
    # ─── KARAR ──────────────────────────────────────────────────────────
    # Tüm kapılar bilinen ve geçenler için
    kapilar = [kapi1, kapi2, kapi3, kapi4]
    bilinen = [k for k in kapilar if k is not None]
    
    if not bilinen:
        karar = 'BEKLE'
        aciklama = 'Yeterli veri yok — analiz tamamlanmamış'
    elif all(k is True for k in bilinen) and len(bilinen) == 4:
        # 4 kapının HEPSİ geçti
        karar = 'GÜÇLÜ_SAT'
        aciklama = '🔴 4 SAT kapısı geçti — tepe yakalandı'
    else:
        # En az biri geçmedi veya eksik
        karar = 'BEKLE'
        # İlk geçmeyen kapıyı bul
        if kapi1 is False:
            aciklama = '🟢 AL koşulları hâlâ geçerli — SAT için ERKEN'
        elif kapi2 is False:
            aciklama = '🟡 Fiyat tepe bölgesinde değil — yükseliş alanı var'
        elif kapi3 is False:
            aciklama = '🟡 SAT DNA yeterince güvenilir değil'
        elif kapi4 is False:
            aciklama = '🟢 Momentum hâlâ yukarı yönlü — SAT vermek YANLIŞ'
        else:
            aciklama = 'Bazı veriler eksik — DNA üretilmedi veya momentum yok'
    
    return {
        'karar': karar,
        'kapi1': kapi1,
        'kapi2': kapi2,
        'kapi3': kapi3,
        'kapi4': kapi4,
        'kapi1_detay': kapi1_detay,
        'kapi2_detay': kapi2_detay,
        'kapi3_detay': kapi3_detay,
        'kapi4_detay': kapi4_detay,
        'aciklama': aciklama,
        'girdiler': {
            'nvs': nvs_score,
            'fraktal': fraktal_score,
            'dna_quality': dna_quality,
            'dna_test_n': dna_test_n,
            'momentum_risk': momentum_risk,
            'momentum_yorum': momentum_yorum,
            'momentum_r3': momentum_r3
        }
    }
