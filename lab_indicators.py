"""
================================================================
lab_indicators.py · Standart Teknik Analiz İndikatör Kütüphanesi
================================================================
Fraktal Kahin LAB için 30 standart TA göstergesi.
Hepsi pandas/numpy ile, harici kütüphane gerektirmez.

Beklenen DataFrame şeması (lowercase columns):
  - 'open', 'high', 'low', 'close', 'volume'

API:
  Tek seri dönenler  → pd.Series
  Çoklu çıktı (k/d, dir, upper/lower) → pd.DataFrame

lab_signals.py içindeki tüm beklentilere göre yazıldı.
================================================================
"""

import numpy as np
import pandas as pd


# ════════════════════════════════════════════════════════════
# YARDIMCILAR
# ════════════════════════════════════════════════════════════
def _src(df, source='close'):
    """Source kolonunu güvenli al — büyük/küçük harf duyarsız."""
    if source in df.columns:
        return df[source].astype(float)
    cols = {c.lower(): c for c in df.columns}
    key = source.lower()
    if key in cols:
        return df[cols[key]].astype(float)
    raise KeyError("Source column '%s' not in DataFrame" % source)


def _col(df, name):
    """high/low/close/volume — case-insensitive."""
    if name in df.columns:
        return df[name].astype(float)
    cols = {c.lower(): c for c in df.columns}
    if name.lower() in cols:
        return df[cols[name.lower()]].astype(float)
    raise KeyError(name)


# ════════════════════════════════════════════════════════════
# MOVING AVERAGES (7 adet)
# ════════════════════════════════════════════════════════════
def ema(df, length=20, source='close'):
    s = _src(df, source)
    return s.ewm(span=length, adjust=False).mean()


def sma(df, length=20, source='close'):
    s = _src(df, source)
    return s.rolling(length, min_periods=1).mean()


def wma(df, length=20, source='close'):
    s = _src(df, source)
    weights = np.arange(1, length + 1, dtype=float)
    return s.rolling(length).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )


def dema(df, length=20, source='close'):
    e1 = ema(df, length, source)
    e2 = e1.ewm(span=length, adjust=False).mean()
    return 2 * e1 - e2


def tema(df, length=20, source='close'):
    e1 = ema(df, length, source)
    e2 = e1.ewm(span=length, adjust=False).mean()
    e3 = e2.ewm(span=length, adjust=False).mean()
    return 3 * e1 - 3 * e2 + e3


def hull_ma(df, length=20, source='close'):
    """Hull MA = WMA(2*WMA(n/2) - WMA(n), sqrt(n))"""
    half = max(1, length // 2)
    sqrt_n = max(1, int(round(np.sqrt(length))))
    wma_half = wma(df, half, source)
    wma_full = wma(df, length, source)
    diff_series = 2 * wma_half - wma_full
    weights = np.arange(1, sqrt_n + 1, dtype=float)
    return diff_series.rolling(sqrt_n).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )


def _linreg_endpoint(y):
    """Lineer regresyon doğrusunun son nokta değeri."""
    n = len(y)
    if n < 2:
        return y[-1] if n else np.nan
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    y_mean = y.mean()
    den = ((x - x_mean) ** 2).sum()
    if den < 1e-12:
        return y_mean
    slope = ((x - x_mean) * (y - y_mean)).sum() / den
    intercept = y_mean - slope * x_mean
    return intercept + slope * (n - 1)


def lsma(df, length=25, source='close'):
    """Linear Regression MA — son barda regresyon doğrusu değeri."""
    s = _src(df, source)
    return s.rolling(length).apply(_linreg_endpoint, raw=True)


def kama(df, length=14, fast=2, slow=30, source='close'):
    """Kaufman Adaptive Moving Average."""
    s = _src(df, source).values.astype(float)
    n = len(s)
    out = np.full(n, np.nan)
    if n < length + 1:
        return pd.Series(out, index=df.index)

    # Efficiency Ratio
    change = np.abs(s - np.roll(s, length))
    change[:length] = np.nan
    diffs = np.abs(np.diff(s, prepend=s[0]))
    vol = pd.Series(diffs).rolling(length).sum().values

    er = np.zeros(n)
    valid = (vol > 1e-12) & ~np.isnan(change)
    er[valid] = change[valid] / vol[valid]

    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2

    out[length] = s[length]
    for i in range(length + 1, n):
        out[i] = out[i - 1] + sc[i] * (s[i] - out[i - 1])
    return pd.Series(out, index=df.index)


# ════════════════════════════════════════════════════════════
# TREND — Yön takipli (3 adet)
# ════════════════════════════════════════════════════════════
def supertrend(df, length=10, mult=3.0):
    """Returns DataFrame with 'value' and 'dir' (+1 = up, -1 = down)."""
    h = _col(df, 'high').values
    l = _col(df, 'low').values
    c = _col(df, 'close').values
    n = len(c)

    if n == 0:
        return pd.DataFrame({'value': [], 'dir': []}, index=df.index)

    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))

    atr_arr = np.full(n, np.nan)
    if n >= length:
        atr_arr[length - 1] = np.mean(tr[:length])
        for i in range(length, n):
            atr_arr[i] = (atr_arr[i - 1] * (length - 1) + tr[i]) / length

    hl2 = (h + l) / 2.0
    ub_basic = hl2 + mult * atr_arr
    lb_basic = hl2 - mult * atr_arr

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)
    st_val = np.full(n, np.nan)

    start = length - 1
    if start >= n:
        return pd.DataFrame({'value': st_val, 'dir': direction}, index=df.index)

    upper[start] = ub_basic[start]
    lower[start] = lb_basic[start]
    direction[start] = 1
    st_val[start] = lower[start]

    for i in range(start + 1, n):
        if ub_basic[i] < upper[i - 1] or c[i - 1] > upper[i - 1]:
            upper[i] = ub_basic[i]
        else:
            upper[i] = upper[i - 1]
        if lb_basic[i] > lower[i - 1] or c[i - 1] < lower[i - 1]:
            lower[i] = lb_basic[i]
        else:
            lower[i] = lower[i - 1]
        if st_val[i - 1] == upper[i - 1]:
            direction[i] = -1 if c[i] <= upper[i] else 1
        else:
            direction[i] = 1 if c[i] >= lower[i] else -1
        st_val[i] = lower[i] if direction[i] == 1 else upper[i]

    return pd.DataFrame({'value': st_val, 'dir': direction}, index=df.index)


def parabolic_sar(df, af_start=0.02, af_inc=0.02, af_max=0.2):
    """Parabolic SAR. Returns DataFrame with 'value' and 'dir'."""
    h = _col(df, 'high').values
    l = _col(df, 'low').values
    n = len(h)
    if n < 2:
        return pd.DataFrame({
            'value': np.full(n, np.nan),
            'dir': np.zeros(n, dtype=int),
        }, index=df.index)

    sar = np.zeros(n)
    direction = np.zeros(n, dtype=int)
    direction[0] = 1
    sar[0] = l[0]
    ep = h[0]
    af = af_start

    for i in range(1, n):
        prev_sar = sar[i - 1]
        if direction[i - 1] == 1:
            sar[i] = prev_sar + af * (ep - prev_sar)
            sar[i] = min(sar[i], l[i - 1], l[max(0, i - 2)])
            if l[i] < sar[i]:
                direction[i] = -1
                sar[i] = ep
                ep = l[i]
                af = af_start
            else:
                direction[i] = 1
                if h[i] > ep:
                    ep = h[i]
                    af = min(af + af_inc, af_max)
        else:
            sar[i] = prev_sar + af * (ep - prev_sar)
            sar[i] = max(sar[i], h[i - 1], h[max(0, i - 2)])
            if h[i] > sar[i]:
                direction[i] = 1
                sar[i] = ep
                ep = h[i]
                af = af_start
            else:
                direction[i] = -1
                if l[i] < ep:
                    ep = l[i]
                    af = min(af + af_inc, af_max)

    return pd.DataFrame({'value': sar, 'dir': direction}, index=df.index)


def ichimoku(df, tenkan=9, kijun=26, senkou_b=52):
    """Ichimoku Cloud. Returns DataFrame: tenkan, kijun, senkou_a, senkou_b."""
    h = _col(df, 'high')
    l = _col(df, 'low')

    def midpoint(period):
        return (h.rolling(period).max() + l.rolling(period).min()) / 2

    tk = midpoint(tenkan)
    kj = midpoint(kijun)
    sa = ((tk + kj) / 2).shift(kijun)
    sb = midpoint(senkou_b).shift(kijun)

    return pd.DataFrame({
        'tenkan': tk,
        'kijun': kj,
        'senkou_a': sa,
        'senkou_b': sb,
    }, index=df.index)


# ════════════════════════════════════════════════════════════
# MOMENTUM OSCILLATORS (10 adet)
# ════════════════════════════════════════════════════════════
def rsi(df, length=14, source='close'):
    """Wilder RSI."""
    s = _src(df, source)
    delta = s.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    ag = gain.ewm(alpha=1.0 / length, adjust=False).mean()
    al = loss.ewm(alpha=1.0 / length, adjust=False).mean()
    rs = ag / (al + 1e-10)
    return 100 - (100 / (1 + rs))


def stoch_rsi(df, length=14, rsi_length=14, k=3, d=3):
    """Stochastic RSI. Returns 'k' and 'd' lines (0-100)."""
    r = rsi(df, rsi_length)
    rmin = r.rolling(length).min()
    rmax = r.rolling(length).max()
    rng = (rmax - rmin).replace(0, np.nan)
    stoch = 100 * (r - rmin) / rng
    k_line = stoch.rolling(k).mean()
    d_line = k_line.rolling(d).mean()
    return pd.DataFrame({'k': k_line, 'd': d_line}, index=df.index)


def stochastic(df, length=14, k=3, d=3):
    """Standart Stochastic."""
    h = _col(df, 'high')
    l = _col(df, 'low')
    c = _col(df, 'close')
    hh = h.rolling(length).max()
    ll = l.rolling(length).min()
    rng = (hh - ll).replace(0, np.nan)
    raw_k = 100 * (c - ll) / rng
    k_line = raw_k.rolling(k).mean()
    d_line = k_line.rolling(d).mean()
    return pd.DataFrame({'k': k_line, 'd': d_line}, index=df.index)


def macd(df, fast=12, slow=26, signal=9, source='close'):
    """MACD. Returns 'macd', 'signal', 'hist'."""
    s = _src(df, source)
    macd_line = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    sig_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - sig_line
    return pd.DataFrame({
        'macd': macd_line,
        'signal': sig_line,
        'hist': hist,
    }, index=df.index)


def cmo(df, length=14, source='close'):
    """Chande Momentum Oscillator (-100 to +100)."""
    s = _src(df, source)
    delta = s.diff()
    up = delta.where(delta > 0, 0.0).rolling(length).sum()
    down = (-delta.where(delta < 0, 0.0)).rolling(length).sum()
    return 100 * (up - down) / (up + down + 1e-10)


def roc(df, length=14, source='close'):
    """Rate of Change (%)."""
    s = _src(df, source)
    prev = s.shift(length)
    return 100 * (s - prev) / (prev.replace(0, np.nan))


def williams_r(df, length=14):
    """Williams %R (-100 to 0)."""
    h = _col(df, 'high')
    l = _col(df, 'low')
    c = _col(df, 'close')
    hh = h.rolling(length).max()
    ll = l.rolling(length).min()
    rng = (hh - ll).replace(0, np.nan)
    return -100 * (hh - c) / rng


def trix(df, length=15, source='close'):
    """TRIX — triple-smoothed EMA momentum (%)."""
    s = _src(df, source)
    e1 = s.ewm(span=length, adjust=False).mean()
    e2 = e1.ewm(span=length, adjust=False).mean()
    e3 = e2.ewm(span=length, adjust=False).mean()
    return 100 * e3.pct_change()


def ultimate_osc(df, short=7, medium=14, long=28):
    """Ultimate Oscillator (0-100)."""
    h = _col(df, 'high')
    l = _col(df, 'low')
    c = _col(df, 'close')
    prev_close = c.shift()
    true_low = pd.concat([l, prev_close], axis=1).min(axis=1)
    true_high = pd.concat([h, prev_close], axis=1).max(axis=1)
    bp = c - true_low
    tr = true_high - true_low

    def avg(p):
        return bp.rolling(p).sum() / tr.rolling(p).sum().replace(0, np.nan)

    a_short = avg(short)
    a_med = avg(medium)
    a_long = avg(long)
    return 100 * (4 * a_short + 2 * a_med + a_long) / 7


def cci(df, length=20):
    """Commodity Channel Index."""
    h = _col(df, 'high')
    l = _col(df, 'low')
    c = _col(df, 'close')
    tp = (h + l + c) / 3
    sma_tp = tp.rolling(length).mean()
    mad = tp.rolling(length).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    return (tp - sma_tp) / (0.015 * mad + 1e-10)


# ════════════════════════════════════════════════════════════
# VOLATİLİTE / BANTLAR (5 adet)
# ════════════════════════════════════════════════════════════
def bollinger(df, length=20, mult=2.0, source='close'):
    """Bollinger Bands. Returns 'mid', 'upper', 'lower'."""
    s = _src(df, source)
    mid = s.rolling(length).mean()
    std = s.rolling(length).std()
    return pd.DataFrame({
        'mid': mid,
        'upper': mid + mult * std,
        'lower': mid - mult * std,
    }, index=df.index)


def keltner(df, length=20, mult=2.0):
    """Keltner Channels: EMA(length) ± mult * ATR(length)."""
    c = _col(df, 'close')
    mid = c.ewm(span=length, adjust=False).mean()
    a = atr(df, length)
    return pd.DataFrame({
        'mid': mid,
        'upper': mid + mult * a,
        'lower': mid - mult * a,
    }, index=df.index)


def donchian(df, length=20):
    """Donchian Channels. Returns 'upper', 'lower', 'mid'."""
    h = _col(df, 'high')
    l = _col(df, 'low')
    upper = h.rolling(length).max()
    lower = l.rolling(length).min()
    return pd.DataFrame({
        'upper': upper,
        'lower': lower,
        'mid': (upper + lower) / 2,
    }, index=df.index)


def atr(df, length=14):
    """Average True Range (Wilder)."""
    h = _col(df, 'high')
    l = _col(df, 'low')
    c = _col(df, 'close')
    hl = h - l
    hc = (h - c.shift()).abs()
    lc = (l - c.shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False).mean()


def adx(df, length=14):
    """ADX with +DI, -DI. Returns 'adx', 'plus_di', 'minus_di'."""
    h = _col(df, 'high')
    l = _col(df, 'low')
    c = _col(df, 'close')

    up_move = h.diff()
    down_move = -l.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index,
    )

    tr_series = pd.concat(
        [h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
        axis=1,
    ).max(axis=1)

    atr_smooth = tr_series.ewm(alpha=1.0 / length, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1.0 / length, adjust=False).mean() / (atr_smooth + 1e-10)
    minus_di = 100 * minus_dm.ewm(alpha=1.0 / length, adjust=False).mean() / (atr_smooth + 1e-10)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx_val = dx.ewm(alpha=1.0 / length, adjust=False).mean()

    return pd.DataFrame({
        'adx': adx_val,
        'plus_di': plus_di,
        'minus_di': minus_di,
    }, index=df.index)


# ════════════════════════════════════════════════════════════
# HACİM (4 adet)
# ════════════════════════════════════════════════════════════
def obv(df):
    """On-Balance Volume (cumulative)."""
    c = _col(df, 'close')
    v = _col(df, 'volume')
    direction = np.sign(c.diff().fillna(0))
    return (direction * v).cumsum()


def cmf(df, length=20):
    """Chaikin Money Flow (-1 to +1)."""
    h = _col(df, 'high')
    l = _col(df, 'low')
    c = _col(df, 'close')
    v = _col(df, 'volume')
    rng = (h - l).replace(0, np.nan)
    mfm = ((c - l) - (h - c)) / rng
    mfv = mfm * v
    return mfv.rolling(length).sum() / v.rolling(length).sum().replace(0, np.nan)


def mfi(df, length=14):
    """Money Flow Index (0-100)."""
    h = _col(df, 'high')
    l = _col(df, 'low')
    c = _col(df, 'close')
    v = _col(df, 'volume')
    tp = (h + l + c) / 3
    rmf = tp * v
    delta = tp.diff()
    pos_mf = rmf.where(delta > 0, 0.0).rolling(length).sum()
    neg_mf = rmf.where(delta < 0, 0.0).rolling(length).sum()
    mfr = pos_mf / (neg_mf + 1e-10)
    return 100 - 100 / (1 + mfr)


def vwap(df):
    """VWAP — cumulative (günlük reset YOK)."""
    h = _col(df, 'high')
    l = _col(df, 'low')
    c = _col(df, 'close')
    v = _col(df, 'volume')
    tp = (h + l + c) / 3
    return (tp * v).cumsum() / v.cumsum().replace(0, np.nan)


# ════════════════════════════════════════════════════════════
# QUICK TEST
# ════════════════════════════════════════════════════════════
if __name__ == '__main__':
    np.random.seed(42)
    n = 300
    close = 100 + np.cumsum(np.random.normal(0, 1, n))
    high = close + np.abs(np.random.normal(0.5, 0.3, n))
    low = close - np.abs(np.random.normal(0.5, 0.3, n))
    open_ = close + np.random.normal(0, 0.2, n)
    vol = np.abs(np.random.normal(10000, 3000, n))
    df = pd.DataFrame({
        'open': open_, 'high': high, 'low': low,
        'close': close, 'volume': vol,
    }, index=pd.date_range('2024-01-01', periods=n))

    print("lab_indicators.py — smoke test")
    print("=" * 60)
    tests = [
        ('ema',           lambda: ema(df, 20)),
        ('sma',           lambda: sma(df, 20)),
        ('wma',           lambda: wma(df, 20)),
        ('dema',          lambda: dema(df, 20)),
        ('tema',          lambda: tema(df, 20)),
        ('hull_ma',       lambda: hull_ma(df, 20)),
        ('lsma',          lambda: lsma(df, 25)),
        ('kama',          lambda: kama(df, 14)),
        ('supertrend',    lambda: supertrend(df, 10, 3.0)),
        ('parabolic_sar', lambda: parabolic_sar(df)),
        ('ichimoku',      lambda: ichimoku(df)),
        ('rsi',           lambda: rsi(df, 14)),
        ('stoch_rsi',     lambda: stoch_rsi(df)),
        ('stochastic',    lambda: stochastic(df)),
        ('macd',          lambda: macd(df)),
        ('cmo',           lambda: cmo(df)),
        ('roc',           lambda: roc(df)),
        ('williams_r',    lambda: williams_r(df)),
        ('trix',          lambda: trix(df)),
        ('ultimate_osc',  lambda: ultimate_osc(df)),
        ('cci',           lambda: cci(df)),
        ('bollinger',     lambda: bollinger(df)),
        ('keltner',       lambda: keltner(df)),
        ('donchian',      lambda: donchian(df)),
        ('atr',           lambda: atr(df)),
        ('adx',           lambda: adx(df)),
        ('obv',           lambda: obv(df)),
        ('cmf',           lambda: cmf(df)),
        ('mfi',           lambda: mfi(df)),
        ('vwap',          lambda: vwap(df)),
    ]
    ok, fail = 0, 0
    for name, fn in tests:
        try:
            r = fn()
            kind = 'DataFrame' if isinstance(r, pd.DataFrame) else 'Series'
            last = r.iloc[-1] if isinstance(r, pd.Series) else 'multi'
            print("  %-15s OK   (%s)" % (name, kind))
            ok += 1
        except Exception as e:
            print("  %-15s FAIL %s" % (name, e))
            fail += 1
    print("=" * 60)
    print("OK: %d / %d" % (ok, len(tests)))
