"""
═══════════════════════════════════════════════════════════════
alpha_tv.py — ALPHA için TradingView faktör verisi (bulk)
───────────────────────────────────────────────────────────────
tv_scanner.py'nin kardeşi. ALPHA motorunun ihtiyaç duyduğu
EK kolonları (performans + volatilite + temel) tek bulk query ile çeker.

Neden ayrı dosya?
  - tv_scanner.py'yi BOZMAMAK için. O dosyaya hiç dokunmuyoruz.
  - ALPHA'nın faktörleri (momentum, mean-reversion, low-vol, quality)
    snapshot performans/volatilite kolonlarından hesaplanabilir.
  - 630 hisse ~1-2 saniyede gelir (yfinance YOK).

Kolon güvenliği:
  Geçmişte "bir geçersiz kolon tüm query'yi bozuyor" hatası yaşandı.
  Bu yüzden KADEMELI fetch: önce tam set, hata olursa azaltılmış set.
═══════════════════════════════════════════════════════════════
"""
from tradingview_screener import Query, col
from typing import Dict, List, Optional


def _safe_num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


# ── Kolon setleri (kademeli) ────────────────────────────────────
# TIER 1: yüksek güven — performans + volatilite + EMA + temel teknik
_TIER1 = [
    'name', 'close', 'change', 'volume',
    'RSI', 'ADX', 'EMA20', 'EMA50', 'EMA200',
    'Perf.W', 'Perf.1M', 'Perf.3M', 'Perf.6M', 'Perf.Y',
    'Volatility.D', 'Volatility.W', 'Volatility.M',
    'average_volume_10d_calc',
]

# TIER 2: temel veriler — bazı hisselerde null olabilir, sorun değil
_TIER2_FUND = [
    'return_on_equity', 'debt_to_equity',
]

# Minimal fallback (TIER1 bile patlarsa)
_MINIMAL = [
    'name', 'close', 'change', 'volume',
    'EMA20', 'EMA50', 'EMA200', 'Perf.1M', 'Perf.6M',
]


def _extract_symbol(row_dict: Dict, idx) -> Optional[str]:
    name = row_dict.get('name')
    if name:
        return str(name).strip().upper()
    try:
        raw = str(idx)
        if ':' in raw:
            return raw.split(':')[-1].strip().upper()
        return raw.strip().upper()
    except Exception:
        return None


def _try_query(cols: List[str], limit: int):
    """Tek bulk query dener. Başarılıysa df döner, değilse None."""
    try:
        q = (Query()
             .select(*cols)
             .set_markets('turkey')
             .limit(limit))
        count, df = q.get_scanner_data()
        if df is None or len(df) == 0:
            return None
        return df
    except Exception as e:
        print(f"[alpha_tv] query hata ({len(cols)} kolon): {str(e)[:120]}")
        return None


def _row_to_factors(row: Dict) -> Dict:
    """
    Bir TV satırını ALPHA faktör ham değerlerine çevirir.
    Tüm değerler None olabilir — cross-sectional katmanda handle edilir.
    """
    close = _safe_num(row.get('close'))

    # EMA'ları yönlü farka çevir: (close - EMA) / close
    def ema_diff(key):
        e = _safe_num(row.get(key))
        if e is not None and close and close > 0:
            return (close - e) / close
        return None

    e20 = ema_diff('EMA20')
    e50 = ema_diff('EMA50')
    e200 = ema_diff('EMA200')

    # Trend skoru: EMA200 farkı + hizalanma bonusu
    trend = None
    if e200 is not None:
        bonus = 0.0
        raw20 = _safe_num(row.get('EMA20'))
        raw50 = _safe_num(row.get('EMA50'))
        raw200 = _safe_num(row.get('EMA200'))
        if raw20 and raw50 and raw200:
            if raw20 > raw50 > raw200:
                bonus = 0.02
            elif raw20 < raw50 < raw200:
                bonus = -0.02
        trend = e200 + bonus

    perf_1m = _safe_num(row.get('Perf.1M'))
    perf_3m = _safe_num(row.get('Perf.3M'))
    perf_6m = _safe_num(row.get('Perf.6M'))
    perf_y = _safe_num(row.get('Perf.Y'))
    vol_d = _safe_num(row.get('Volatility.D'))
    vol_m = _safe_num(row.get('Volatility.M'))
    roe = _safe_num(row.get('return_on_equity'))
    de = _safe_num(row.get('debt_to_equity'))

    # Momentum 12-1 yaklaşımı: yıllık performanstan son ayı çıkar
    momentum = None
    if perf_y is not None and perf_1m is not None:
        momentum = perf_y - perf_1m
    elif perf_6m is not None:
        momentum = perf_6m
    elif perf_3m is not None:
        momentum = perf_3m

    # Mean-reversion: son ay düşenler yüksek skor (Bildik & Gülay edge)
    mean_rev = (-perf_1m) if perf_1m is not None else None

    # Low-vol: aylık volatilite, negatif (düşük vol = yüksek skor)
    low_vol = None
    if vol_m is not None and vol_m > 0:
        low_vol = -vol_m
    elif vol_d is not None and vol_d > 0:
        low_vol = -vol_d

    # Quality: ROE - debt/equity normalize edilmemiş ham, varsa
    quality = None
    if roe is not None:
        quality = roe - (0.1 * de if de is not None else 0.0)

    return {
        'close': close,
        'change': _safe_num(row.get('change')),
        'volume': _safe_num(row.get('volume')),
        'vol_avg': _safe_num(row.get('average_volume_10d_calc')),
        'rsi': _safe_num(row.get('RSI')),
        'adx': _safe_num(row.get('ADX')),
        # ham faktörler
        'momentum': momentum,
        'mean_rev': mean_rev,
        'low_vol': low_vol,
        'trend': trend,
        'quality': quality,
        # debug
        '_perf_1m': perf_1m, '_perf_6m': perf_6m, '_perf_y': perf_y,
        '_vol_m': vol_m, '_roe': roe, '_de': de,
        '_e20': e20, '_e50': e50, '_e200': e200,
    }


def fetch_alpha_bulk(limit: int = 700) -> Dict:
    """
    Tüm BIST için ALPHA faktör ham değerlerini tek bulk query ile çeker.

    Returns:
        {
          'ok': True/False,
          'tier': 'full'/'tier1'/'minimal',
          'has_fundamentals': bool,
          'count': int,
          'data': {SYMBOL: {factor dict}, ...},
          'error': str (varsa)
        }
    """
    df = None
    tier = None
    has_fund = False

    # Kademe 1: tam set (TIER1 + temel)
    df = _try_query(_TIER1 + _TIER2_FUND, limit)
    if df is not None:
        tier = 'full'
        has_fund = True
    else:
        # Kademe 2: sadece TIER1
        df = _try_query(_TIER1, limit)
        if df is not None:
            tier = 'tier1'
        else:
            # Kademe 3: minimal
            df = _try_query(_MINIMAL, limit)
            if df is not None:
                tier = 'minimal'

    if df is None:
        return {'ok': False, 'tier': None, 'has_fundamentals': False,
                'count': 0, 'data': {}, 'error': 'TradingView veri gelmedi (tüm kademeler başarısız)'}

    data: Dict[str, Dict] = {}
    for idx, row in df.iterrows():
        rd = row.to_dict()
        sym = _extract_symbol(rd, idx)
        if not sym:
            continue
        data[sym] = _row_to_factors(rd)

    return {
        'ok': True,
        'tier': tier,
        'has_fundamentals': has_fund,
        'count': len(data),
        'data': data,
        'error': None,
    }


# ── XU100 endeksi rejim verisi ──────────────────────────────────
def fetch_index_regime_data() -> Optional[Dict]:
    """
    XU100 için EMA20/50/200 + volatilite çek (rejim tespiti).
    TV'de endeks sembolü genelde 'XU100'.
    """
    try:
        cols = ['close', 'EMA20', 'EMA50', 'EMA200',
                'Volatility.M', 'Perf.1M', 'Perf.3M']
        q = (Query()
             .select(*cols)
             .set_markets('turkey')
             .where(col('name') == 'XU100'))
        count, df = q.get_scanner_data()
        if df is None or len(df) == 0:
            return None
        row = df.iloc[0].to_dict()
        return {
            'close': _safe_num(row.get('close')),
            'ema20': _safe_num(row.get('EMA20')),
            'ema50': _safe_num(row.get('EMA50')),
            'ema200': _safe_num(row.get('EMA200')),
            'vol_m': _safe_num(row.get('Volatility.M')),
            'perf_1m': _safe_num(row.get('Perf.1M')),
            'perf_3m': _safe_num(row.get('Perf.3M')),
        }
    except Exception as e:
        print(f"[alpha_tv] index regime hata: {str(e)[:120]}")
        return None
