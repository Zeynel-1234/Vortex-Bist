"""
Fraktal Kahin · Özgün İndikatör Motoru
Tüm formüller: gerçek matematik, referans verilebilir kaynaklarla.
"""

import numpy as np
import pandas as pd
import hashlib
from typing import Dict, List, Optional


# ═══════════════════════════════════════════════════════════
# TEMEL YARDIMCILAR
# ═══════════════════════════════════════════════════════════

def _safe(v, default=0.0):
    """NaN/None/inf güvenli dönüşüm"""
    try:
        f = float(v)
        return f if np.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def atr_series(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's ATR"""
    hl = high - low
    hc = (high - close.shift()).abs()
    lc = (low - close.shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ═══════════════════════════════════════════════════════════
# 1) HURST EXPONENT (Fraktal bellek katsayısı)
# E[(X_t+τ - X_t)²] ~ τ^(2H)
# H > 0.5 trend kalıcı · H = 0.5 rastgele · H < 0.5 mean-reverting
# ═══════════════════════════════════════════════════════════

def hurst_exponent(prices: np.ndarray, max_lag: int = 50) -> float:
    prices = np.asarray(prices, dtype=float)
    prices = prices[~np.isnan(prices)]
    if len(prices) < 40:
        return 0.5
    max_lag = min(max_lag, len(prices) // 4)
    lags = range(2, max_lag)
    try:
        tau = [max(np.std(prices[lag:] - prices[:-lag]), 1e-10) for lag in lags]
        poly = np.polyfit(np.log(list(lags)), np.log(tau), 1)
        return float(max(0.1, min(0.9, poly[0])))
    except Exception:
        return 0.5


# ═══════════════════════════════════════════════════════════
# 2) R/S ANALYSIS (Rescaled Range)
# log(R/S) = H × log(n) + c
# ═══════════════════════════════════════════════════════════

def rescaled_range(prices: np.ndarray) -> float:
    prices = np.asarray(prices, dtype=float)
    prices = prices[~np.isnan(prices)]
    if len(prices) < 64:
        return 0.5
    returns = np.diff(np.log(prices + 1e-10))
    sizes = [s for s in (8, 16, 32, 64) if s <= len(returns) // 2]
    if len(sizes) < 2:
        return 0.5
    rs_values = []
    for size in sizes:
        rs_list = []
        for i in range(len(returns) // size):
            chunk = returns[i * size:(i + 1) * size]
            m = np.mean(chunk)
            cumdev = np.cumsum(chunk - m)
            R = np.max(cumdev) - np.min(cumdev)
            S = np.std(chunk)
            if S > 1e-10:
                rs_list.append(R / S)
        if rs_list:
            rs_values.append(np.mean(rs_list))
    if len(rs_values) < 2:
        return 0.5
    try:
        slope = float(np.polyfit(np.log(sizes[:len(rs_values)]),
                                  np.log(np.array(rs_values) + 1e-10), 1)[0])
        return max(0.1, min(0.9, slope))
    except Exception:
        return 0.5


# ═══════════════════════════════════════════════════════════
# 3) FFT DOMINANT CYCLE (Hisse karakteristik döngü uzunluğu)
# Kullanıcının isteği: "Ortalama Döngü Uzunluğu (FFT ile)"
# ═══════════════════════════════════════════════════════════

def dominant_cycle_fft(prices: np.ndarray, min_period: int = 10, max_period: int = 120) -> int:
    """
    FFT ile hissenin dominant döngü uzunluğunu bulur.
    Returns: baskın periyot (gün sayısı)
    """
    prices = np.asarray(prices, dtype=float)
    prices = prices[~np.isnan(prices)]
    if len(prices) < max_period * 2:
        return 21  # default: ~1 ay
    # Detrend: linear trendi çıkar
    x = np.arange(len(prices))
    trend = np.polyfit(x, prices, 1)
    detrended = prices - (trend[0] * x + trend[1])
    # FFT
    try:
        fft = np.fft.rfft(detrended)
        power = np.abs(fft) ** 2
        freqs = np.fft.rfftfreq(len(detrended))
        # min/max period → frekans aralığı
        min_f, max_f = 1.0 / max_period, 1.0 / min_period
        mask = (freqs >= min_f) & (freqs <= max_f)
        if not mask.any():
            return 21
        # Maske altındaki en güçlü frekans
        band_power = power.copy()
        band_power[~mask] = 0
        peak_idx = np.argmax(band_power)
        peak_freq = freqs[peak_idx]
        if peak_freq > 1e-10:
            period = int(round(1.0 / peak_freq))
            return max(min_period, min(max_period, period))
        return 21
    except Exception:
        return 21


# ═══════════════════════════════════════════════════════════
# 4) VOLATİLİTE REJİMİ
# Son 20 günün std'si vs son 100 günün std'si
# ═══════════════════════════════════════════════════════════

def volatility_regime(df: pd.DataFrame) -> Dict:
    """
    Returns: {'rejim': str, 'current_vol': %, 'baseline_vol': %, 'ratio': float}
    rejim: 'DÜŞÜK' | 'NORMAL' | 'YÜKSEK' | 'AŞIRI'
    """
    if len(df) < 100:
        return {'rejim': 'BİLİNMİYOR', 'current_vol': 0, 'baseline_vol': 0, 'ratio': 1.0}
    try:
        returns = df['close'].pct_change().dropna()
        curr = float(returns.tail(20).std() * np.sqrt(252) * 100)  # annualized %
        base = float(returns.tail(100).std() * np.sqrt(252) * 100)
        ratio = curr / base if base > 1e-6 else 1.0
        if ratio < 0.7:
            rejim = 'DÜŞÜK'
        elif ratio < 1.3:
            rejim = 'NORMAL'
        elif ratio < 1.8:
            rejim = 'YÜKSEK'
        else:
            rejim = 'AŞIRI'
        return {
            'rejim': rejim,
            'current_vol': round(curr, 2),
            'baseline_vol': round(base, 2),
            'ratio': round(ratio, 2)
        }
    except Exception:
        return {'rejim': 'BİLİNMİYOR', 'current_vol': 0, 'baseline_vol': 0, 'ratio': 1.0}


# ═══════════════════════════════════════════════════════════
# 5) ATR KANALLARI
# ═══════════════════════════════════════════════════════════

def atr_channels(df: pd.DataFrame, period: int = 14, mult: float = 2.0) -> Dict:
    if len(df) < period + 20:
        return {'atr': 0, 'upper': 0, 'lower': 0, 'mid': 0, 'konum': 0.5}
    atr_val = float(atr_series(df['high'], df['low'], df['close'], period).iloc[-1])
    close_val = float(df['close'].iloc[-1])
    mid = float(df['close'].rolling(20).mean().iloc[-1])
    upper = mid + atr_val * mult
    lower = mid - atr_val * mult
    width = upper - lower
    konum = (close_val - lower) / width if width > 1e-10 else 0.5
    return {
        'atr': round(atr_val, 4),
        'upper': round(upper, 2),
        'lower': round(lower, 2),
        'mid': round(mid, 2),
        'konum': round(max(0, min(1, konum)), 3)
    }


# ═══════════════════════════════════════════════════════════
# 6) FRAKTAL YORGUNLUK İNDEKSİ (FYI) — KULLANICININ FORMÜLÜ
# FYI = (Kapanış − 20g En Düşük) / (20g ATR × √20)
# Düşük FYI = fiyat dibe yakın, volatilite normalize
# ═══════════════════════════════════════════════════════════

def fractal_fatigue_index(df: pd.DataFrame) -> float:
    if len(df) < 25:
        return 0.0
    try:
        close = float(df['close'].iloc[-1])
        low20 = float(df['low'].rolling(20).min().iloc[-1])
        atr20 = float(atr_series(df['high'], df['low'], df['close'], 20).iloc[-1])
        if atr20 < 1e-6:
            return 0.0
        fyi = (close - low20) / (atr20 * np.sqrt(20))
        return round(_safe(fyi), 3)
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════
# 7) LİKİDİTE REZONANS KATSAYISI (LRK) — KULLANICININ FORMÜLÜ
# LRK = (Hurst × log(Hacim)) / Günlük Volatilite
# Yüksek = hacim+trend+düşük gürültü kombinasyonu
# ═══════════════════════════════════════════════════════════

def liquidity_resonance(df: pd.DataFrame, hurst: float) -> float:
    if len(df) < 20 or 'volume' not in df.columns:
        return 0.0
    try:
        avg_vol = float(df['volume'].tail(20).mean())
        if avg_vol < 1:
            return 0.0
        log_vol = np.log(avg_vol)
        daily_vol = float(df['close'].pct_change().tail(20).std() * 100)
        if daily_vol < 1e-6:
            return 0.0
        lrk = (hurst * log_vol) / daily_vol
        return round(_safe(lrk), 4)
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════
# 8) RSI (Wilder) — bağımsız kontrol göstergesi
# ═══════════════════════════════════════════════════════════

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    ag = gain.ewm(alpha=1 / period, adjust=False).mean()
    al = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = ag / (al + 1e-10)
    return 100 - (100 / (1 + rs))


# ═══════════════════════════════════════════════════════════
# 9) ELMAS — DİP TESPİTİ (Çok faktörlü, spec'teki Schrödinger yerine)
# ═══════════════════════════════════════════════════════════

def detect_dip(df: pd.DataFrame, atr_info: Dict, hurst: float, fyi: float, lrk: float,
               vol_regime: Dict) -> Dict:
    if len(df) < 30:
        return {'score': 0.0, 'reasons': [], 'signal': 'VERI_YETERSIZ'}
    score = 0.0
    reasons = []
    close = float(df['close'].iloc[-1])

    # (1) RSI aşırı satım + dönüş  (25p)
    rsi_s = rsi(df['close'], 14)
    if len(rsi_s) >= 3:
        r_now = float(rsi_s.iloc[-1])
        r_prev = float(rsi_s.iloc[-2])
        if r_now < 35 and r_now > r_prev:
            score += 0.25
            reasons.append(f"RSI dönüşü: {r_now:.0f} > {r_prev:.0f}")
        elif r_now < 30:
            score += 0.15
            reasons.append(f"RSI aşırı satım: {r_now:.0f}")

    # (2) FYI düşük = fiyat dibin yakınında, volatiliteye göre (25p)
    if fyi < 0.5:
        score += 0.25
        reasons.append(f"FYI derin dip: {fyi:.2f}")
    elif fyi < 1.0:
        score += 0.15
        reasons.append(f"FYI dip bölgesi: {fyi:.2f}")

    # (3) ATR kanalı alt yakını (20p)
    konum = atr_info.get('konum', 0.5)
    if konum < 0.15:
        score += 0.20
        reasons.append(f"ATR alt band sınırı ({konum:.2f})")
    elif konum < 0.30:
        score += 0.10
        reasons.append(f"ATR alt yarı ({konum:.2f})")

    # (4) Hacim climax + dipten toparlanma (15p)
    if 'volume' in df.columns and len(df) >= 20:
        vol = df['volume']
        va = vol.rolling(20).mean()
        if va.iloc[-1] > 0:
            vr = float(vol.iloc[-1] / va.iloc[-1])
            low = float(df['low'].iloc[-1])
            high = float(df['high'].iloc[-1])
            if high > low:
                recovery = (close - low) / (high - low)
                if vr > 1.8 and recovery > 0.5:
                    score += 0.15
                    reasons.append(f"Hacim climax ({vr:.1f}×, dipten toparlanma)")
                elif vr > 1.3 and recovery > 0.4:
                    score += 0.07

    # (5) Hurst + LRK kombinasyonu (15p)
    if hurst < 0.45 and lrk > 0:
        score += 0.15
        reasons.append(f"Mean-reverting + likidite (H={hurst:.2f}, LRK={lrk:.2f})")
    elif hurst < 0.50:
        score += 0.07

    # Volatilite rejimi ayarı
    if vol_regime.get('rejim') == 'AŞIRI':
        score *= 0.85  # yüksek vol = teyit güvenilirliği düşer
        reasons.append("Volatilite rejimi: AŞIRI (skor düşürüldü)")

    if score >= 0.70:
        signal = 'GUCLU_AL'  # ELMAS seviyesi
    elif score >= 0.50:
        signal = 'AL'
    elif score >= 0.30:
        signal = 'ZAYIF_AL'
    else:
        signal = 'NOTR'
    return {'score': round(min(1.0, score), 3), 'reasons': reasons[:5], 'signal': signal}


# ═══════════════════════════════════════════════════════════
# 10) TEPE TESPİTİ
# ═══════════════════════════════════════════════════════════

def detect_peak(df: pd.DataFrame, atr_info: Dict, hurst: float, fyi: float,
                vol_regime: Dict) -> Dict:
    if len(df) < 30:
        return {'score': 0.0, 'reasons': [], 'signal': 'VERI_YETERSIZ'}
    score = 0.0
    reasons = []
    close = float(df['close'].iloc[-1])

    rsi_s = rsi(df['close'], 14)
    if len(rsi_s) >= 3:
        r_now = float(rsi_s.iloc[-1])
        r_prev = float(rsi_s.iloc[-2])
        if r_now > 70 and r_now < r_prev:
            score += 0.25
            reasons.append(f"RSI tepe dönüşü: {r_now:.0f} < {r_prev:.0f}")
        elif r_now > 75:
            score += 0.20
            reasons.append(f"RSI aşırı alım: {r_now:.0f}")

    # FYI yüksek = fiyat tepeye yakın
    if fyi > 3.5:
        score += 0.25
        reasons.append(f"FYI aşırı yüksek: {fyi:.2f}")
    elif fyi > 2.5:
        score += 0.15
        reasons.append(f"FYI tepe bölgesi: {fyi:.2f}")

    konum = atr_info.get('konum', 0.5)
    if konum > 0.85:
        score += 0.20
        reasons.append(f"ATR üst band ({konum:.2f})")
    elif konum > 0.70:
        score += 0.10

    # Dağıtım: yüksek hacim + günün dibine yakın kapanış
    if 'volume' in df.columns and len(df) >= 20:
        vol = df['volume']
        va = vol.rolling(20).mean()
        if va.iloc[-1] > 0:
            vr = float(vol.iloc[-1] / va.iloc[-1])
            low = float(df['low'].iloc[-1])
            high = float(df['high'].iloc[-1])
            if high > low:
                recovery = (close - low) / (high - low)
                if vr > 1.8 and recovery < 0.3:
                    score += 0.20
                    reasons.append(f"Dağıtım ({vr:.1f}×, zayıf kapanış)")

    if hurst > 0.70:
        score += 0.10
        reasons.append(f"Hurst aşırı trendli ({hurst:.2f})")

    if vol_regime.get('rejim') == 'AŞIRI':
        score *= 0.85

    if score >= 0.70:
        signal = 'GUCLU_SAT'
    elif score >= 0.50:
        signal = 'SAT'
    elif score >= 0.30:
        signal = 'ZAYIF_SAT'
    else:
        signal = 'NOTR'
    return {'score': round(min(1.0, score), 3), 'reasons': reasons[:5], 'signal': signal}


# ═══════════════════════════════════════════════════════════
# 11) FINGERPRINT HASH (Hisse Parmak İzi / DNA Kodu)
# Kullanıcının isteği: Hurst + Dominant Cycle + Vol Regime → hash
# ═══════════════════════════════════════════════════════════

def fingerprint(symbol: str, hurst: float, cycle: int, vol_regime: Dict, rs: float) -> str:
    key = f"{symbol}|H{hurst:.2f}|C{cycle}|V{vol_regime.get('rejim','')}|RS{rs:.2f}"
    h = hashlib.sha256(key.encode()).hexdigest().upper()
    return f"FKDNA-{h[:4]}-{h[4:8]}-{h[8:10]}"


# ═══════════════════════════════════════════════════════════
# 12) MASTER ANALIZ FONKSİYONU
# ═══════════════════════════════════════════════════════════

def analyze_symbol(df_daily: pd.DataFrame, symbol: str) -> Dict:
    """
    Bir hissenin günlük OHLCV verisi ile tam Fraktal Kahin analizi.
    Returns: Frontend'e gönderilecek tam JSON.
    """
    if df_daily is None or len(df_daily) < 60:
        return {
            "sembol": symbol,
            "hata": "Yetersiz veri (< 60 gün)",
            "sinyal": "VERI_YETERSIZ",
            "guc": 0.0
        }

    df = df_daily.copy()
    df.columns = [c.lower() for c in df.columns]
    df = df.dropna(subset=['close'])

    if len(df) < 60:
        return {
            "sembol": symbol,
            "hata": "Temiz veri yetersiz",
            "sinyal": "VERI_YETERSIZ",
            "guc": 0.0
        }

    # Tüm göstergeleri hesapla
    closes = df['close'].values
    h_exp = hurst_exponent(closes, 50)
    rs_val = rescaled_range(closes)
    cycle = dominant_cycle_fft(closes)
    vol_rej = volatility_regime(df)
    atr_info = atr_channels(df)
    fyi = fractal_fatigue_index(df)
    lrk = liquidity_resonance(df, h_exp)
    dip = detect_dip(df, atr_info, h_exp, fyi, lrk, vol_rej)
    peak = detect_peak(df, atr_info, h_exp, fyi, vol_rej)

    # Ana sinyal: dip veya tepe'den güçlü olan
    if dip['score'] > peak['score']:
        signal = dip['signal']
        score = dip['score']
        reasons = dip['reasons']
        yön = 'DIP'
    else:
        signal = peak['signal']
        score = peak['score']
        reasons = peak['reasons']
        yön = 'TEPE'

    if score < 0.30:
        signal = 'NOTR'
        yön = 'NOTR'

    close_val = float(df['close'].iloc[-1])
    prev_close = float(df['close'].iloc[-2]) if len(df) >= 2 else close_val
    daily_change = (close_val - prev_close) / prev_close * 100 if prev_close > 1e-6 else 0.0
    monthly_low = float(df['low'].rolling(20).min().iloc[-1])
    dist_support = (close_val - monthly_low) / close_val * 100 if close_val > 1e-6 else 0.0

    dna = fingerprint(symbol, h_exp, cycle, vol_rej, rs_val)

    # Beklenen vade
    if yön == 'DIP':
        if score >= 0.70: vade = f"{max(10, cycle//2)}-{cycle*2} iş günü"
        elif score >= 0.50: vade = f"{max(15, cycle)}-{cycle*3} iş günü"
        else: vade = f"{cycle}-{cycle*4} iş günü"
    elif yön == 'TEPE':
        vade = "Kısa vade: koruma/çıkış"
    else:
        vade = "Netleşme bekleniyor"

    # Yaratıcı not
    notlar = []
    if h_exp > 0.65 and fyi < 1.0:
        notlar.append("Güçlü trend + derin çekilme kombinasyonu")
    if vol_rej['rejim'] == 'DÜŞÜK' and dip['score'] > 0.5:
        notlar.append("Düşük volatilite + dip teyidi = sıkışmış yay")
    if lrk > 1.5:
        notlar.append(f"Yüksek likidite rezonansı (LRK={lrk:.2f})")
    if atr_info['konum'] < 0.1 and signal in ('AL', 'GUCLU_AL'):
        notlar.append("ATR alt band + dip = nadir fırsat bölgesi")
    if cycle < 15:
        notlar.append(f"Kısa döngülü hisse ({cycle}g) — hızlı dönüş")
    elif cycle > 60:
        notlar.append(f"Uzun döngülü hisse ({cycle}g) — sabır gerekir")
    if not notlar:
        notlar.append(f"Standart konfigürasyon (H={h_exp:.2f})")

    return {
        "sembol": symbol,
        "zaman": pd.Timestamp.utcnow().isoformat(),
        "dna_kodu": dna,
        "sinyal": signal,
        "yön": yön,
        "guc": round(score, 3),
        "fiyat": round(close_val, 2),
        "gunluk_degisim": round(daily_change, 2),
        "bilimsel_gerekce": {
            "hurst": round(h_exp, 3),
            "rs_analiz": round(rs_val, 3),
            "dominant_cycle": cycle,
            "volatilite_rejimi": vol_rej,
            "fyi": fyi,
            "lrk": lrk,
            "atr_kanal": atr_info,
            "destek_uzaklik_yuzde": round(dist_support, 2)
        },
        "tetiklenen_faktorler": reasons,
        "beklenen_vade": vade,
        "yaratici_not": " · ".join(notlar),
        "dip_skor": dip['score'],
        "tepe_skor": peak['score']
    }
