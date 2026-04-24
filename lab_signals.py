"""
═══════════════════════════════════════════════════════════════
FRAKTAL KAHİN LAB — AŞAMA 1: SİNYAL ÜRETİM MOTORU
───────────────────────────────────────────────────────────────
Her indikatör için "GÜÇLÜ AL" sinyalinin kuralları.
Çıktı: pd.Series (bool) — True = o bar AL sinyali verdi.

SİNYAL KURALI FELSEFESİ:
  • Oscillator'lar: oversold bölgeden yukarı DÖNÜŞ (sadece oversold
    olması yetmez; çıkış hareketi şart → lag yok ama sahte yok)
  • MA tabanlılar: fiyat MA'yı yukarı KESMELİ + MA eğimi yukarı
  • MACD/TRIX: histogram 0 altından pozitife DÖNMELİ
  • Bantlar: alt bandı test edip yukarı KAPANIŞ yapmalı
  • Trend (Supertrend/SAR/Ichimoku): trend yönü AŞAĞIDAN YUKARI dönmeli
  • Hacim: birikim sinyali + fiyat dip test pattern'i

DİP TEYİDİ (HEPSİ İÇİN ZORUNLU):
  Sinyalin geçerli sayılması için son 60 günde hisse %15+ düşmüş
  olmalı. Bu, "zirveden alma" hatasını engelleyen çekirdek filtre.

HER SİNYAL FONKSİYONU:
  signal_<indicator>(df, **params) → pd.Series(bool)
  
REGISTRY: SIGNAL_REGISTRY tüm fonksiyonları ve parametrelerini tutar.
═══════════════════════════════════════════════════════════════
"""
from typing import Dict, Optional, Callable
import numpy as np
import pandas as pd

from lab_indicators import (
    ema, sma, wma, dema, tema, hull_ma, lsma,
    supertrend, parabolic_sar, ichimoku, kama,
    rsi, stoch_rsi, stochastic, macd, cmo, roc,
    williams_r, trix, ultimate_osc, cci,
    bollinger, keltner, donchian, atr, adx,
    obv, cmf, mfi, vwap
)


# ═══════════════════════════════════════════════════════════════
# DİP TEYİDİ — TÜM SİNYALLERİN ÜZERİNDEN GEÇER
# ═══════════════════════════════════════════════════════════════
def _dip_filter(df: pd.DataFrame, lookback: int = 60,
                min_drawdown_pct: float = 15.0) -> pd.Series:
    """
    Her bar için: son 'lookback' bar içindeki zirveye göre
    fiyat en az %min_drawdown_pct düşmüş olmalı → dip bölgesindeyiz.
    
    Bu, "zirveden alma" hatasını engelleyen çekirdek filtre.
    """
    close = df['close'].astype(float)
    rolling_max = close.rolling(lookback, min_periods=20).max()
    drawdown_pct = 100 * (close - rolling_max) / rolling_max
    # drawdown_pct negatif. -%15 ve daha düşükse (daha büyük düşüş) dip bölgesi.
    return drawdown_pct <= -min_drawdown_pct


def _cross_above(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """fast, slow'u yukarı kesiyor mu (bu barda)."""
    prev_below = fast.shift(1) <= slow.shift(1)
    now_above = fast > slow
    return prev_below & now_above


def _cross_below(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """fast, slow'u aşağı kesiyor mu."""
    prev_above = fast.shift(1) >= slow.shift(1)
    now_below = fast < slow
    return prev_above & now_below


def _slope_up(series: pd.Series, lookback: int = 5) -> pd.Series:
    """Seri son 'lookback' bar boyunca yukarı eğimli mi."""
    return series > series.shift(lookback)


def _apply_dip_filter(signal: pd.Series, df: pd.DataFrame,
                      use_dip: bool = True) -> pd.Series:
    """Sinyale dip teyidi uygula."""
    if not use_dip:
        return signal.fillna(False).astype(bool)
    dip = _dip_filter(df)
    return (signal & dip).fillna(False).astype(bool)


# ═══════════════════════════════════════════════════════════════
# TREND — MA TABANLI SİNYALLER
# MA tabanlılarda: fiyat MA'yı yukarı keser + MA eğimi pozitif
# ═══════════════════════════════════════════════════════════════
def _ma_cross_signal(df: pd.DataFrame, ma_series: pd.Series,
                     use_dip: bool = True) -> pd.Series:
    """Fiyat MA'yı yukarı kesti + MA eğimi yukarı."""
    close = df['close'].astype(float)
    cross = _cross_above(close, ma_series)
    slope = _slope_up(ma_series, 5)
    return _apply_dip_filter(cross & slope, df, use_dip)


def signal_ema(df, length=20, source='close', use_dip=True) -> pd.Series:
    return _ma_cross_signal(df, ema(df, length, source), use_dip)

def signal_sma(df, length=20, source='close', use_dip=True) -> pd.Series:
    return _ma_cross_signal(df, sma(df, length, source), use_dip)

def signal_wma(df, length=20, source='close', use_dip=True) -> pd.Series:
    return _ma_cross_signal(df, wma(df, length, source), use_dip)

def signal_dema(df, length=20, source='close', use_dip=True) -> pd.Series:
    return _ma_cross_signal(df, dema(df, length, source), use_dip)

def signal_tema(df, length=20, source='close', use_dip=True) -> pd.Series:
    return _ma_cross_signal(df, tema(df, length, source), use_dip)

def signal_hull_ma(df, length=20, source='close', use_dip=True) -> pd.Series:
    return _ma_cross_signal(df, hull_ma(df, length, source), use_dip)

def signal_lsma(df, length=25, source='close', use_dip=True) -> pd.Series:
    return _ma_cross_signal(df, lsma(df, length, source), use_dip)

def signal_kama(df, length=14, fast=2, slow=30, source='close', use_dip=True) -> pd.Series:
    return _ma_cross_signal(df, kama(df, length, fast, slow, source), use_dip)


# ═══════════════════════════════════════════════════════════════
# TREND — YÖN DEĞİŞİM TABANLI (Supertrend, SAR, Ichimoku)
# ═══════════════════════════════════════════════════════════════
def signal_supertrend(df, length=10, mult=3.0, use_dip=True) -> pd.Series:
    """Supertrend yönü -1'den +1'e döndüğünde."""
    st = supertrend(df, length, mult)
    flip = (st['dir'] == 1) & (st['dir'].shift(1) == -1)
    return _apply_dip_filter(flip, df, use_dip)


def signal_parabolic_sar(df, af_start=0.02, af_inc=0.02, af_max=0.2,
                         use_dip=True) -> pd.Series:
    """SAR yönü -1'den +1'e döndüğünde."""
    sar = parabolic_sar(df, af_start, af_inc, af_max)
    flip = (sar['dir'] == 1) & (sar['dir'].shift(1) == -1)
    return _apply_dip_filter(flip, df, use_dip)


def signal_ichimoku(df, tenkan=9, kijun=26, senkou_b=52, use_dip=True) -> pd.Series:
    """Tenkan-sen Kijun-sen'i yukarı keser + fiyat bulut üstünde."""
    ichi = ichimoku(df, tenkan, kijun, senkou_b)
    close = df['close'].astype(float)
    cross = _cross_above(ichi['tenkan'], ichi['kijun'])
    cloud_top = pd.concat([ichi['senkou_a'], ichi['senkou_b']], axis=1).max(axis=1)
    above_cloud = close > cloud_top
    return _apply_dip_filter(cross & above_cloud, df, use_dip)


# ═══════════════════════════════════════════════════════════════
# MOMENTUM — OSCILLATOR'LAR
# Kural: Oversold bölgeden yukarı DÖNÜŞ (sadece oversold olması değil)
# ═══════════════════════════════════════════════════════════════
def signal_rsi(df, length=14, oversold=30, source='close', use_dip=True) -> pd.Series:
    """RSI oversold altına iner, sonra yukarı kesip geçer."""
    r = rsi(df, length, source)
    was_oversold = r.shift(1) < oversold
    now_above = r >= oversold
    return _apply_dip_filter(was_oversold & now_above, df, use_dip)


def signal_stoch_rsi(df, length=14, rsi_length=14, k=3, d=3,
                     oversold=20, use_dip=True) -> pd.Series:
    """StochRSI %K, %D'yi oversold bölgede yukarı keser."""
    sr = stoch_rsi(df, length, rsi_length, k, d)
    was_oversold = sr['k'].shift(1) < oversold
    cross = _cross_above(sr['k'], sr['d'])
    return _apply_dip_filter(was_oversold & cross, df, use_dip)


def signal_stochastic(df, length=14, k=3, d=3, oversold=20, use_dip=True) -> pd.Series:
    """Stochastic %K, %D'yi oversold bölgede yukarı keser."""
    st = stochastic(df, length, k, d)
    was_oversold = st['k'].shift(1) < oversold
    cross = _cross_above(st['k'], st['d'])
    return _apply_dip_filter(was_oversold & cross, df, use_dip)


def signal_macd(df, fast=12, slow=26, signal=9, source='close', use_dip=True) -> pd.Series:
    """MACD histogram 0 altından pozitife geçer."""
    m = macd(df, fast, slow, signal, source)
    cross_zero = (m['hist'] > 0) & (m['hist'].shift(1) <= 0)
    return _apply_dip_filter(cross_zero, df, use_dip)


def signal_cmo(df, length=14, oversold=-50, source='close', use_dip=True) -> pd.Series:
    """CMO oversold altından yukarı döner."""
    c = cmo(df, length, source)
    return _apply_dip_filter(
        (c.shift(1) < oversold) & (c >= oversold), df, use_dip
    )


def signal_roc(df, length=14, oversold=-10, source='close', use_dip=True) -> pd.Series:
    """ROC oversold altından yukarı döner."""
    r = roc(df, length, source)
    return _apply_dip_filter(
        (r.shift(1) < oversold) & (r >= oversold), df, use_dip
    )


def signal_williams_r(df, length=14, oversold=-80, use_dip=True) -> pd.Series:
    """Williams %R oversold bölgesinden çıkar."""
    w = williams_r(df, length)
    return _apply_dip_filter(
        (w.shift(1) < oversold) & (w >= oversold), df, use_dip
    )


def signal_trix(df, length=15, source='close', use_dip=True) -> pd.Series:
    """TRIX 0'ın altından pozitife geçer."""
    t = trix(df, length, source)
    return _apply_dip_filter(
        (t > 0) & (t.shift(1) <= 0), df, use_dip
    )


def signal_ultimate_osc(df, short=7, medium=14, long=28, oversold=30,
                        use_dip=True) -> pd.Series:
    """Ultimate Oscillator oversold bölgesinden çıkar."""
    u = ultimate_osc(df, short, medium, long)
    return _apply_dip_filter(
        (u.shift(1) < oversold) & (u >= oversold), df, use_dip
    )


def signal_cci(df, length=20, oversold=-100, use_dip=True) -> pd.Series:
    """CCI oversold (-100) altından yukarı döner."""
    c = cci(df, length)
    return _apply_dip_filter(
        (c.shift(1) < oversold) & (c >= oversold), df, use_dip
    )


# ═══════════════════════════════════════════════════════════════
# VOLATİLİTE — BANT VE TREND GÜCÜ
# ═══════════════════════════════════════════════════════════════
def signal_bollinger(df, length=20, mult=2.0, source='close', use_dip=True) -> pd.Series:
    """Fiyat alt banda değip yukarı kapanış yapar."""
    bb = bollinger(df, length, mult, source)
    close = df['close'].astype(float)
    low = df['low'].astype(float)
    touched = low <= bb['lower']
    closed_above = close > bb['lower']
    # Bir önceki barda test, bu barda kapanış üstte
    return _apply_dip_filter(touched.shift(1).fillna(False) & closed_above, df, use_dip)


def signal_keltner(df, length=20, mult=2.0, use_dip=True) -> pd.Series:
    """Keltner alt bant testi + yukarı kapanış."""
    kc = keltner(df, length, mult)
    close = df['close'].astype(float)
    low = df['low'].astype(float)
    touched = low <= kc['lower']
    closed_above = close > kc['lower']
    return _apply_dip_filter(touched.shift(1).fillna(False) & closed_above, df, use_dip)


def signal_donchian(df, length=20, use_dip=True) -> pd.Series:
    """Donchian alt bant testi + yukarı kapanış."""
    dc = donchian(df, length)
    close = df['close'].astype(float)
    low = df['low'].astype(float)
    touched = low <= dc['lower']
    closed_above = close > dc['lower']
    return _apply_dip_filter(touched.shift(1).fillna(False) & closed_above, df, use_dip)


def signal_atr(df, length=14, use_dip=True) -> pd.Series:
    """
    ATR tek başına sinyal üretmez. Volatilite gücünü ölçer.
    Bu kuralla: ATR son 5 bar yükseliyor + fiyat 3 bar yükselişte.
    """
    a = atr(df, length)
    close = df['close'].astype(float)
    atr_up = _slope_up(a, 5)
    price_up = close > close.shift(3)
    return _apply_dip_filter(atr_up & price_up, df, use_dip)


def signal_adx(df, length=14, min_adx=25, use_dip=True) -> pd.Series:
    """ADX trend gücünü onaylıyor + +DI -DI'yi yukarı keser."""
    a = adx(df, length)
    strong_trend = a['adx'] >= min_adx
    di_cross = _cross_above(a['plus_di'], a['minus_di'])
    return _apply_dip_filter(strong_trend & di_cross, df, use_dip)


# ═══════════════════════════════════════════════════════════════
# HACİM İNDİKATÖRLERİ
# ═══════════════════════════════════════════════════════════════
def signal_obv(df, length=20, use_dip=True) -> pd.Series:
    """OBV son 'length' bar boyunca yükselişte + fiyat dip test ediyor."""
    o = obv(df)
    obv_ma = o.rolling(length).mean()
    obv_rising = o > obv_ma
    price_near_low = df['close'] <= df['close'].rolling(length).quantile(0.25)
    return _apply_dip_filter(obv_rising & price_near_low, df, use_dip)


def signal_cmf(df, length=20, threshold=0.1, use_dip=True) -> pd.Series:
    """CMF negatiften pozitife geçer (alım baskısı başlıyor)."""
    c = cmf(df, length)
    flip = (c >= threshold) & (c.shift(1) < threshold)
    return _apply_dip_filter(flip, df, use_dip)


def signal_mfi(df, length=14, oversold=20, use_dip=True) -> pd.Series:
    """MFI oversold altından yukarı döner (hacim ağırlıklı RSI)."""
    m = mfi(df, length)
    return _apply_dip_filter(
        (m.shift(1) < oversold) & (m >= oversold), df, use_dip
    )


def signal_vwap(df, use_dip=True) -> pd.Series:
    """Fiyat VWAP'ı yukarı keser (kurumsal alım)."""
    v = vwap(df)
    close = df['close'].astype(float)
    return _apply_dip_filter(_cross_above(close, v), df, use_dip)


# ═══════════════════════════════════════════════════════════════
# SİNYAL REGISTRY — Optimizer bu tabloyu gezecek (AŞAMA 2)
# ═══════════════════════════════════════════════════════════════
SIGNAL_REGISTRY: Dict[str, tuple] = {
    # Trend MA (8)
    'ema':          (signal_ema,          {'length': [10, 20, 50, 100, 200]}),
    'sma':          (signal_sma,          {'length': [10, 20, 50, 100, 200]}),
    'wma':          (signal_wma,          {'length': [10, 20, 50, 100]}),
    'dema':         (signal_dema,         {'length': [14, 21, 50]}),
    'tema':         (signal_tema,         {'length': [14, 21, 50]}),
    'hull_ma':      (signal_hull_ma,      {'length': [9, 20, 55]}),
    'lsma':         (signal_lsma,         {'length': [14, 25, 50, 100, 200]}),
    'kama':         (signal_kama,         {'length': [10, 14, 21]}),

    # Trend yön (3)
    'supertrend':   (signal_supertrend,   {'length': [7, 10, 14], 'mult': [2.0, 3.0, 4.0]}),
    'parabolic_sar':(signal_parabolic_sar,{'af_inc': [0.01, 0.02]}),
    'ichimoku':     (signal_ichimoku,     {'tenkan': [9], 'kijun': [26]}),

    # Momentum oscillator (10)
    'rsi':          (signal_rsi,          {'length': [7, 14, 21], 'oversold': [25, 30, 35]}),
    'stoch_rsi':    (signal_stoch_rsi,    {'oversold': [15, 20, 25]}),
    'stochastic':   (signal_stochastic,   {'length': [14, 21], 'oversold': [15, 20]}),
    'macd':         (signal_macd,         {}),
    'cmo':          (signal_cmo,          {'length': [9, 14, 21], 'oversold': [-40, -50, -60]}),
    'roc':          (signal_roc,          {'length': [10, 14, 21], 'oversold': [-8, -10, -15]}),
    'williams_r':   (signal_williams_r,   {'length': [10, 14, 21], 'oversold': [-75, -80, -85]}),
    'trix':         (signal_trix,         {'length': [14, 15, 21]}),
    'ultimate_osc': (signal_ultimate_osc, {'oversold': [25, 30, 35]}),
    'cci':          (signal_cci,          {'length': [14, 20, 30], 'oversold': [-100, -150]}),

    # Volatilite (5)
    'bollinger':    (signal_bollinger,    {'length': [20], 'mult': [1.5, 2.0, 2.5]}),
    'keltner':      (signal_keltner,      {'length': [20], 'mult': [1.5, 2.0, 2.5]}),
    'donchian':     (signal_donchian,     {'length': [20, 55]}),
    'atr':          (signal_atr,          {'length': [14, 21]}),
    'adx':          (signal_adx,          {'length': [14], 'min_adx': [20, 25, 30]}),

    # Hacim (4)
    'obv':          (signal_obv,          {'length': [20, 50]}),
    'cmf':          (signal_cmf,          {'length': [14, 20], 'threshold': [0.05, 0.1]}),
    'mfi':          (signal_mfi,          {'length': [14, 21], 'oversold': [15, 20, 25]}),
    'vwap':         (signal_vwap,         {}),
}


def expand_params(params: Dict) -> list:
    """Parametre ızgarasını tüm kombinasyonlara açar."""
    if not params:
        return [{}]
    keys = list(params.keys())
    from itertools import product
    return [dict(zip(keys, combo)) for combo in product(*[params[k] for k in keys])]


def count_total_combos() -> Dict:
    """Toplam parametre kombinasyonu sayısı."""
    total = 0
    per = {}
    for name, (_, params) in SIGNAL_REGISTRY.items():
        combos = expand_params(params)
        per[name] = len(combos)
        total += len(combos)
    return {'toplam': total, 'indikatör_sayisi': len(SIGNAL_REGISTRY),
            'başina': per}


# ═══════════════════════════════════════════════════════════════
# TEST (python lab_signals.py)
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    # 500 bar sentetik: önce düşüş, sonra dip dönüşü
    np.random.seed(13)
    n = 500
    # İlk 350 bar düşüş, sonra 150 bar yükseliş
    trend = np.concatenate([
        np.linspace(100, 50, 350),
        np.linspace(50, 75, 150)
    ])
    noise = np.random.normal(0, 1.5, n)
    close = trend + noise
    high = close + np.abs(np.random.normal(0.5, 0.3, n))
    low = close - np.abs(np.random.normal(0.5, 0.3, n))
    open_ = close + np.random.normal(0, 0.2, n)
    vol = np.abs(np.random.normal(10000, 3000, n))
    df = pd.DataFrame({
        'open': open_, 'high': high, 'low': low,
        'close': close, 'volume': vol
    }, index=pd.date_range('2024-01-01', periods=n))

    print("=" * 65)
    print(f"SİNYAL MOTORU TESTİ — {len(SIGNAL_REGISTRY)} indikatör")
    print("Veri: 350 bar düşüş + 150 bar dip dönüşü")
    print("=" * 65)

    ok, fail = 0, 0
    total_signals = 0
    for name, (func, params) in SIGNAL_REGISTRY.items():
        try:
            default = {k: v[0] for k, v in params.items()} if params else {}
            sig = func(df, **default)
            count = int(sig.sum())
            total_signals += count
            last_signal_bar = int(sig[::-1].idxmax() if count > 0 else -1) if count > 0 else None
            print(f"  ✓ {name:15s} — toplam {count:3d} sinyal")
            ok += 1
        except Exception as e:
            print(f"  ✗ {name:15s} — HATA: {str(e)[:70]}")
            fail += 1

    print("=" * 65)
    print(f"Başarılı: {ok}/{len(SIGNAL_REGISTRY)}  ·  Başarısız: {fail}")
    print(f"Toplam sinyal sayısı (500 bar içinde): {total_signals}")
    print("=" * 65)

    stats = count_total_combos()
    print(f"\nToplam parametre kombinasyonu: {stats['toplam']}")
    print(f"630 hisse × {stats['toplam']} = {630 * stats['toplam']:,} tekli backtest")
