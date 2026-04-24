"""
═══════════════════════════════════════════════════════════════
FRAKTAL KAHİN LAB — AŞAMA 1: İNDİKATÖR KÜTÜPHANESİ
───────────────────────────────────────────────────────────────
30 gerçek teknik indikatör, saf NumPy/Pandas ile.
Her fonksiyon: DataFrame (open, high, low, close, volume) alır,
             pandas.Series veya dict döner.

Kategoriler:
  Trend (11):    ema, sma, wma, dema, tema, hull_ma, lsma,
                 supertrend, parabolic_sar, ichimoku, kama
  Momentum (10): rsi, stoch_rsi, stochastic, macd, cmo, roc,
                 williams_r, trix, ultimate_osc, cci
  Volatilite (5): bollinger, keltner, donchian, atr, adx
  Hacim (4):     obv, cmf, mfi, vwap

AŞAMA 2'DE KULLANILACAK: lab_optimizer.py buradaki fonksiyonları
ızgara taraması ile parametrelerini değiştirerek çağıracak.
═══════════════════════════════════════════════════════════════
"""
from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════
def _safe_series(s, name='val') -> pd.Series:
    """None/NaN güvenli series."""
    if s is None:
        return pd.Series([], name=name, dtype=float)
    if not isinstance(s, pd.Series):
        s = pd.Series(s, name=name)
    return s.astype(float)


def _rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's RMA (Running Moving Average). RSI ve ADX için kullanılır."""
    alpha = 1.0 / period
    return series.ewm(alpha=alpha, adjust=False).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    """True Range = max(high-low, |high-prev_close|, |low-prev_close|)"""
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    prev_close = df['close'].astype(float).shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr


# ═══════════════════════════════════════════════════════════════
# 1-11: TREND İNDİKATÖRLERİ
# ═══════════════════════════════════════════════════════════════
def ema(df: pd.DataFrame, length: int = 20, source: str = 'close') -> pd.Series:
    """Exponential Moving Average."""
    return df[source].astype(float).ewm(span=length, adjust=False).mean()


def sma(df: pd.DataFrame, length: int = 20, source: str = 'close') -> pd.Series:
    """Simple Moving Average."""
    return df[source].astype(float).rolling(window=length).mean()


def wma(df: pd.DataFrame, length: int = 20, source: str = 'close') -> pd.Series:
    """Weighted Moving Average (ağırlık = pozisyon)."""
    s = df[source].astype(float)
    weights = np.arange(1, length + 1, dtype=float)
    def _w(window):
        return np.dot(window, weights) / weights.sum()
    return s.rolling(window=length).apply(_w, raw=True)


def dema(df: pd.DataFrame, length: int = 20, source: str = 'close') -> pd.Series:
    """Double EMA — 2*EMA(price) − EMA(EMA(price))."""
    e1 = ema(df, length, source)
    e2 = e1.ewm(span=length, adjust=False).mean()
    return 2 * e1 - e2


def tema(df: pd.DataFrame, length: int = 20, source: str = 'close') -> pd.Series:
    """Triple EMA — 3*e1 − 3*e2 + e3."""
    e1 = ema(df, length, source)
    e2 = e1.ewm(span=length, adjust=False).mean()
    e3 = e2.ewm(span=length, adjust=False).mean()
    return 3 * e1 - 3 * e2 + e3


def hull_ma(df: pd.DataFrame, length: int = 20, source: str = 'close') -> pd.Series:
    """Hull Moving Average — WMA(2*WMA(n/2) − WMA(n), sqrt(n))."""
    half = max(2, length // 2)
    sqrt_len = max(2, int(round(np.sqrt(length))))
    s = df[source].astype(float)

    # İç WMA'lar
    w_half = wma(df.assign(_s=s), half, '_s')
    w_full = wma(df.assign(_s=s), length, '_s')
    raw = 2 * w_half - w_full

    tmp = pd.DataFrame({'_r': raw})
    return wma(tmp, sqrt_len, '_r')


def lsma(df: pd.DataFrame, length: int = 25, source: str = 'close') -> pd.Series:
    """Least Squares Moving Average (Linear Regression End-Point)."""
    s = df[source].astype(float).values
    n = len(s)
    out = np.full(n, np.nan)
    if n < length:
        return pd.Series(out, index=df.index)

    x = np.arange(length, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    for i in range(length - 1, n):
        window = s[i - length + 1: i + 1]
        if np.isnan(window).any():
            continue
        y_mean = window.mean()
        slope = ((x - x_mean) * (window - y_mean)).sum() / x_var
        intercept = y_mean - slope * x_mean
        out[i] = intercept + slope * (length - 1)

    return pd.Series(out, index=df.index)


def supertrend(df: pd.DataFrame, length: int = 10, mult: float = 3.0) -> pd.DataFrame:
    """Supertrend — ATR bazlı trend göstergesi. 'dir': +1 up, -1 down."""
    atr_val = _rma(_true_range(df), length)
    hl2 = (df['high'] + df['low']) / 2
    upper_basic = hl2 + mult * atr_val
    lower_basic = hl2 - mult * atr_val

    n = len(df)
    upper = upper_basic.copy()
    lower = lower_basic.copy()
    direction = np.ones(n, dtype=int)
    st = pd.Series(index=df.index, dtype=float)

    close = df['close'].astype(float)
    for i in range(1, n):
        if not (pd.isna(upper.iat[i]) or pd.isna(upper.iat[i - 1])):
            if upper_basic.iat[i] < upper.iat[i - 1] or close.iat[i - 1] > upper.iat[i - 1]:
                upper.iat[i] = upper_basic.iat[i]
            else:
                upper.iat[i] = upper.iat[i - 1]

        if not (pd.isna(lower.iat[i]) or pd.isna(lower.iat[i - 1])):
            if lower_basic.iat[i] > lower.iat[i - 1] or close.iat[i - 1] < lower.iat[i - 1]:
                lower.iat[i] = lower_basic.iat[i]
            else:
                lower.iat[i] = lower.iat[i - 1]

        if direction[i - 1] == 1:
            direction[i] = 1 if close.iat[i] > lower.iat[i] else -1
        else:
            direction[i] = -1 if close.iat[i] < upper.iat[i] else 1

        st.iat[i] = lower.iat[i] if direction[i] == 1 else upper.iat[i]

    return pd.DataFrame({
        'st': st, 'dir': pd.Series(direction, index=df.index),
        'upper': upper, 'lower': lower
    })


def parabolic_sar(df: pd.DataFrame, af_start: float = 0.02,
                  af_inc: float = 0.02, af_max: float = 0.2) -> pd.DataFrame:
    """Parabolic SAR. 'dir': +1 up, -1 down."""
    high = df['high'].astype(float).values
    low = df['low'].astype(float).values
    n = len(df)
    if n < 2:
        return pd.DataFrame({'sar': [np.nan] * n, 'dir': [0] * n}, index=df.index)

    sar = np.zeros(n)
    direction = np.zeros(n, dtype=int)
    af = af_start
    ep = high[0]
    sar[0] = low[0]
    direction[0] = 1

    for i in range(1, n):
        prev_sar = sar[i - 1]
        prev_dir = direction[i - 1]

        if prev_dir == 1:
            sar[i] = prev_sar + af * (ep - prev_sar)
            sar[i] = min(sar[i], low[i - 1], low[max(0, i - 2)])
            if low[i] < sar[i]:
                direction[i] = -1
                sar[i] = ep
                ep = low[i]
                af = af_start
            else:
                direction[i] = 1
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_inc, af_max)
        else:
            sar[i] = prev_sar - af * (prev_sar - ep)
            sar[i] = max(sar[i], high[i - 1], high[max(0, i - 2)])
            if high[i] > sar[i]:
                direction[i] = 1
                sar[i] = ep
                ep = high[i]
                af = af_start
            else:
                direction[i] = -1
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_inc, af_max)

    return pd.DataFrame({
        'sar': pd.Series(sar, index=df.index),
        'dir': pd.Series(direction, index=df.index)
    })


def ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26,
             senkou_b: int = 52) -> pd.DataFrame:
    """Ichimoku — tenkan (conversion) + kijun (base) + spans."""
    high = df['high'].astype(float)
    low = df['low'].astype(float)

    tenkan_sen = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    kijun_sen = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2
    senkou_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
    senkou_b_line = ((high.rolling(senkou_b).max() + low.rolling(senkou_b).min()) / 2).shift(kijun)

    return pd.DataFrame({
        'tenkan': tenkan_sen, 'kijun': kijun_sen,
        'senkou_a': senkou_a, 'senkou_b': senkou_b_line
    })


def kama(df: pd.DataFrame, length: int = 14, fast: int = 2,
         slow: int = 30, source: str = 'close') -> pd.Series:
    """Kaufman's Adaptive Moving Average — volatiliteye göre uyarlanır."""
    s = df[source].astype(float).values
    n = len(s)
    if n < length + 1:
        return pd.Series(np.full(n, np.nan), index=df.index)

    change = np.abs(s - np.concatenate([np.full(length, np.nan), s[:-length]]))
    volatility = np.array([
        np.abs(np.diff(s[max(0, i - length):i + 1])).sum() if i >= length else np.nan
        for i in range(n)
    ])

    er = np.where(volatility > 0, change / volatility, 0)
    sc_fast = 2.0 / (fast + 1)
    sc_slow = 2.0 / (slow + 1)
    sc = (er * (sc_fast - sc_slow) + sc_slow) ** 2

    k = np.full(n, np.nan)
    k[length] = s[length]
    for i in range(length + 1, n):
        if np.isnan(sc[i]) or np.isnan(k[i - 1]):
            k[i] = s[i]
        else:
            k[i] = k[i - 1] + sc[i] * (s[i] - k[i - 1])

    return pd.Series(k, index=df.index)


# ═══════════════════════════════════════════════════════════════
# 12-21: MOMENTUM İNDİKATÖRLERİ
# ═══════════════════════════════════════════════════════════════
def rsi(df: pd.DataFrame, length: int = 14, source: str = 'close') -> pd.Series:
    """Relative Strength Index (Wilder's)."""
    delta = df[source].astype(float).diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = _rma(gain, length)
    avg_loss = _rma(loss, length)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def stoch_rsi(df: pd.DataFrame, length: int = 14, rsi_length: int = 14,
              k: int = 3, d: int = 3) -> pd.DataFrame:
    """Stochastic RSI — RSI'nın Stochastic'i."""
    rsi_val = rsi(df, rsi_length)
    min_rsi = rsi_val.rolling(length).min()
    max_rsi = rsi_val.rolling(length).max()
    stoch = 100 * (rsi_val - min_rsi) / (max_rsi - min_rsi).replace(0, np.nan)
    k_line = stoch.rolling(k).mean()
    d_line = k_line.rolling(d).mean()
    return pd.DataFrame({'k': k_line, 'd': d_line})


def stochastic(df: pd.DataFrame, length: int = 14, k: int = 3,
               d: int = 3) -> pd.DataFrame:
    """Stochastic Oscillator (Klasik %K %D)."""
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    lowest = low.rolling(length).min()
    highest = high.rolling(length).max()
    raw_k = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
    k_line = raw_k.rolling(k).mean()
    d_line = k_line.rolling(d).mean()
    return pd.DataFrame({'k': k_line, 'd': d_line})


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26,
         signal: int = 9, source: str = 'close') -> pd.DataFrame:
    """MACD — fast EMA − slow EMA, sinyal = MACD'nin EMA'sı."""
    ef = ema(df, fast, source)
    es = ema(df, slow, source)
    macd_line = ef - es
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({'macd': macd_line, 'signal': signal_line, 'hist': hist})


def cmo(df: pd.DataFrame, length: int = 14, source: str = 'close') -> pd.Series:
    """Chande Momentum Oscillator. -100 ile +100 arası."""
    delta = df[source].astype(float).diff()
    gain = delta.where(delta > 0, 0.0).rolling(length).sum()
    loss = -delta.where(delta < 0, 0.0).rolling(length).sum()
    return 100 * (gain - loss) / (gain + loss).replace(0, np.nan)


def roc(df: pd.DataFrame, length: int = 14, source: str = 'close') -> pd.Series:
    """Rate of Change — yüzde değişim."""
    s = df[source].astype(float)
    return 100 * (s - s.shift(length)) / s.shift(length).replace(0, np.nan)


def williams_r(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Williams %R — Stochastic'in negatif versiyonu. -100 ile 0 arası."""
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    highest = high.rolling(length).max()
    lowest = low.rolling(length).min()
    return -100 * (highest - close) / (highest - lowest).replace(0, np.nan)


def trix(df: pd.DataFrame, length: int = 15, source: str = 'close') -> pd.Series:
    """TRIX — triple-smoothed EMA'nın ROC'si."""
    e1 = ema(df, length, source)
    e2 = e1.ewm(span=length, adjust=False).mean()
    e3 = e2.ewm(span=length, adjust=False).mean()
    return 100 * e3.diff() / e3.shift(1).replace(0, np.nan)


def ultimate_osc(df: pd.DataFrame, short: int = 7, medium: int = 14,
                 long: int = 28) -> pd.Series:
    """Ultimate Oscillator — 3 farklı zaman ufku ağırlıklı."""
    close = df['close'].astype(float)
    prev_close = close.shift(1)
    low = df['low'].astype(float)
    high = df['high'].astype(float)

    bp = close - pd.concat([low, prev_close], axis=1).min(axis=1)
    tr = pd.concat([high, prev_close], axis=1).max(axis=1) - \
         pd.concat([low, prev_close], axis=1).min(axis=1)

    avg_s = bp.rolling(short).sum() / tr.rolling(short).sum().replace(0, np.nan)
    avg_m = bp.rolling(medium).sum() / tr.rolling(medium).sum().replace(0, np.nan)
    avg_l = bp.rolling(long).sum() / tr.rolling(long).sum().replace(0, np.nan)

    return 100 * (4 * avg_s + 2 * avg_m + avg_l) / 7


def cci(df: pd.DataFrame, length: int = 20) -> pd.Series:
    """Commodity Channel Index."""
    tp = (df['high'] + df['low'] + df['close']) / 3
    ma = tp.rolling(length).mean()
    md = tp.rolling(length).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - ma) / (0.015 * md).replace(0, np.nan)


# ═══════════════════════════════════════════════════════════════
# 22-26: VOLATİLİTE İNDİKATÖRLERİ
# ═══════════════════════════════════════════════════════════════
def bollinger(df: pd.DataFrame, length: int = 20, mult: float = 2.0,
              source: str = 'close') -> pd.DataFrame:
    """Bollinger Bands."""
    mid = sma(df, length, source)
    std = df[source].astype(float).rolling(length).std()
    upper = mid + mult * std
    lower = mid - mult * std
    return pd.DataFrame({'upper': upper, 'mid': mid, 'lower': lower})


def keltner(df: pd.DataFrame, length: int = 20, mult: float = 2.0) -> pd.DataFrame:
    """Keltner Channels — EMA ± mult × ATR."""
    mid = ema(df, length)
    atr_val = _rma(_true_range(df), length)
    upper = mid + mult * atr_val
    lower = mid - mult * atr_val
    return pd.DataFrame({'upper': upper, 'mid': mid, 'lower': lower})


def donchian(df: pd.DataFrame, length: int = 20) -> pd.DataFrame:
    """Donchian Channels — son N bar min/max."""
    upper = df['high'].astype(float).rolling(length).max()
    lower = df['low'].astype(float).rolling(length).min()
    mid = (upper + lower) / 2
    return pd.DataFrame({'upper': upper, 'mid': mid, 'lower': lower})


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Average True Range."""
    return _rma(_true_range(df), length)


def adx(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    """ADX + +DI + -DI (Wilder's)."""
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = _true_range(df)
    atr_val = _rma(tr, length)
    plus_di = 100 * _rma(plus_dm, length) / atr_val.replace(0, np.nan)
    minus_di = 100 * _rma(minus_dm, length) / atr_val.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = _rma(dx, length)
    return pd.DataFrame({'adx': adx_val, 'plus_di': plus_di, 'minus_di': minus_di})


# ═══════════════════════════════════════════════════════════════
# 27-30: HACİM İNDİKATÖRLERİ
# ═══════════════════════════════════════════════════════════════
def obv(df: pd.DataFrame) -> pd.Series:
    """On Balance Volume."""
    close = df['close'].astype(float)
    vol = df['volume'].astype(float)
    sign = np.sign(close.diff().fillna(0))
    return (sign * vol).cumsum()


def cmf(df: pd.DataFrame, length: int = 20) -> pd.Series:
    """Chaikin Money Flow."""
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    vol = df['volume'].astype(float)
    mfm = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    mfv = mfm * vol
    return mfv.rolling(length).sum() / vol.rolling(length).sum().replace(0, np.nan)


def mfi(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Money Flow Index — hacim-ağırlıklı RSI."""
    tp = (df['high'] + df['low'] + df['close']) / 3
    mf = tp * df['volume'].astype(float)
    delta = tp.diff()
    pos_mf = mf.where(delta > 0, 0.0).rolling(length).sum()
    neg_mf = mf.where(delta < 0, 0.0).rolling(length).sum()
    mfr = pos_mf / neg_mf.replace(0, np.nan)
    return 100 - (100 / (1 + mfr))


def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume Weighted Average Price (kümülatif)."""
    tp = (df['high'] + df['low'] + df['close']) / 3
    vol = df['volume'].astype(float)
    return (tp * vol).cumsum() / vol.cumsum().replace(0, np.nan)


# ═══════════════════════════════════════════════════════════════
# KAYIT: İndikatör çağrı tablosu (AŞAMA 2 için)
# Her kayıt: ad → (fonksiyon, parametre ızgarası)
# ═══════════════════════════════════════════════════════════════
INDICATOR_REGISTRY = {
    # Trend (11)
    'ema':          (ema,          {'length': [10, 20, 50, 100, 200]}),
    'sma':          (sma,          {'length': [10, 20, 50, 100, 200]}),
    'wma':          (wma,          {'length': [10, 20, 50, 100]}),
    'dema':         (dema,         {'length': [14, 21, 50]}),
    'tema':         (tema,         {'length': [14, 21, 50]}),
    'hull_ma':      (hull_ma,      {'length': [9, 20, 55]}),
    'lsma':         (lsma,         {'length': [14, 25, 50, 100, 200]}),
    'supertrend':   (supertrend,   {'length': [7, 10, 14], 'mult': [2.0, 3.0, 4.0]}),
    'parabolic_sar':(parabolic_sar,{'af_start': [0.02], 'af_inc': [0.01, 0.02], 'af_max': [0.2]}),
    'ichimoku':     (ichimoku,     {'tenkan': [9], 'kijun': [26], 'senkou_b': [52]}),
    'kama':         (kama,         {'length': [10, 14, 21], 'fast': [2], 'slow': [30]}),

    # Momentum (10)
    'rsi':          (rsi,          {'length': [7, 14, 21, 30]}),
    'stoch_rsi':    (stoch_rsi,    {'length': [14], 'rsi_length': [14], 'k': [3], 'd': [3]}),
    'stochastic':   (stochastic,   {'length': [14, 21], 'k': [3, 5], 'd': [3]}),
    'macd':         (macd,         {'fast': [12], 'slow': [26], 'signal': [9]}),
    'cmo':          (cmo,          {'length': [9, 14, 21]}),
    'roc':          (roc,          {'length': [10, 14, 21]}),
    'williams_r':   (williams_r,   {'length': [10, 14, 21]}),
    'trix':         (trix,         {'length': [14, 15, 21]}),
    'ultimate_osc': (ultimate_osc, {'short': [7], 'medium': [14], 'long': [28]}),
    'cci':          (cci,          {'length': [14, 20, 30]}),

    # Volatilite (5)
    'bollinger':    (bollinger,    {'length': [20], 'mult': [1.5, 2.0, 2.5]}),
    'keltner':      (keltner,      {'length': [20], 'mult': [1.5, 2.0, 2.5]}),
    'donchian':     (donchian,     {'length': [20, 55]}),
    'atr':          (atr,          {'length': [14, 21]}),
    'adx':          (adx,          {'length': [14, 21]}),

    # Hacim (4)
    'obv':          (obv,          {}),
    'cmf':          (cmf,          {'length': [14, 20, 30]}),
    'mfi':          (mfi,          {'length': [14, 21]}),
    'vwap':         (vwap,         {}),
}


def list_indicators() -> Dict:
    """Registry özeti."""
    return {
        'toplam': len(INDICATOR_REGISTRY),
        'adlar': list(INDICATOR_REGISTRY.keys()),
        'parametre_sayisi': {
            name: int(np.prod([len(v) for v in params.values()])) if params else 1
            for name, (_, params) in INDICATOR_REGISTRY.items()
        }
    }


# ═══════════════════════════════════════════════════════════════
# TEST (python lab_indicators.py)
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    # Sentetik OHLCV — 500 bar
    np.random.seed(7)
    n = 500
    close = 100 + np.cumsum(np.random.normal(0, 1, n))
    high = close + np.abs(np.random.normal(0.5, 0.3, n))
    low = close - np.abs(np.random.normal(0.5, 0.3, n))
    open_ = close + np.random.normal(0, 0.2, n)
    vol = np.abs(np.random.normal(10000, 3000, n))
    df = pd.DataFrame({
        'open': open_, 'high': high, 'low': low, 'close': close, 'volume': vol
    }, index=pd.date_range('2024-01-01', periods=n))

    print("=" * 60)
    print(f"LAB İNDİKATÖR KÜTÜPHANESİ — {len(INDICATOR_REGISTRY)} indikatör")
    print("=" * 60)

    ok = 0
    fail = 0
    for name, (func, params) in INDICATOR_REGISTRY.items():
        try:
            # Varsayılan parametrelerle çağır
            default = {k: v[0] for k, v in params.items()} if params else {}
            result = func(df, **default)
            last = None
            if isinstance(result, pd.Series):
                last = result.iloc[-1]
                kind = 'Series'
            elif isinstance(result, pd.DataFrame):
                last = result.iloc[-1].to_dict()
                kind = 'DataFrame'
            else:
                kind = type(result).__name__
            print(f"  ✓ {name:15s} [{kind:10s}] → {last}")
            ok += 1
        except Exception as e:
            print(f"  ✗ {name:15s} — HATA: {str(e)[:80]}")
            fail += 1

    print("=" * 60)
    print(f"Başarılı: {ok}/{len(INDICATOR_REGISTRY)}  ·  Başarısız: {fail}")
    print("=" * 60)

    # Parametre ızgarası istatistiği
    total_combos = sum(
        int(np.prod([len(v) for v in p.values()])) if p else 1
        for _, (_, p) in INDICATOR_REGISTRY.items()
    )
    print(f"Tekli parametre kombinasyonu sayısı: {total_combos}")
    print(f"Hisse başına tekli tarama: ~{total_combos} backtest")
    print(f"630 hisse × {total_combos} = {630 * total_combos:,} tekli backtest")
