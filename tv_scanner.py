"""
═══════════════════════════════════════════════════════════════
TradingView Scanner v4 — Multi-Timeframe Tek Query
───────────────────────────────────────────────────────────────
v3 BUG: .set_property('interval', ...) TradingView Scanner API'sinde
        işe yaramıyordu; daily/weekly/monthly için aynı veri geliyordu.

v4 ÇÖZÜM: b-165.html'in yöntemini birebir kopyala — sütun isimlerine
         TradingView timeframe suffix'i ekle (RSI|1W, RSI|1M) ve tek
         query'de üç zaman dilimini birden çek.

Avantaj: 3× daha hızlı (tek HTTP round-trip) + timeframe bug'ı çözüldü.
═══════════════════════════════════════════════════════════════
"""
from tradingview_screener import Query, col
from typing import Dict, Optional

# Her zaman dilimi için çekilen ortak sütunlar
_BASE_COLS = ['Recommend.All', 'RSI', 'Stoch.K',
              'MACD.macd', 'MACD.signal', 'EMA20', 'EMA50']

# Sadece günlükte çekilen ekstralar (EMA200, volume, ADX, ATR, change)
_DAILY_EXTRA = ['close', 'change', 'volume',
                'EMA200', 'ADX', 'ATR',
                'average_volume_10d_calc']


def _build_columns() -> list:
    """Günlük + Haftalık + Aylık toplam sütun listesi."""
    cols = list(_DAILY_EXTRA) + list(_BASE_COLS)
    cols += [f'{c}|1W' for c in _BASE_COLS]
    cols += [f'{c}|1M' for c in _BASE_COLS]
    return cols


def _safe_num(v) -> Optional[float]:
    """None/NaN → None, aksi halde float."""
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None


def _process_tf(row: Dict, close: Optional[float], suffix: str = '') -> Dict:
    """
    Tek timeframe için ham satırdan nvs.py uyumlu dict çıkar.
    suffix='' → günlük, '1W' → haftalık, '1M' → aylık.
    """
    sfx = f'|{suffix}' if suffix else ''
    out: Dict = {}

    out['rec'] = _safe_num(row.get(f'Recommend.All{sfx}'))
    out['rsi'] = _safe_num(row.get(f'RSI{sfx}'))
    out['stoch'] = _safe_num(row.get(f'Stoch.K{sfx}'))

    # MACD histogram = macd_line - signal_line (b-165 ile aynı)
    mm = _safe_num(row.get(f'MACD.macd{sfx}'))
    ms = _safe_num(row.get(f'MACD.signal{sfx}'))
    out['macd'] = (mm - ms) if (mm is not None and ms is not None) else None

    # EMA'lar yönlü fark olarak (close - EMA) / close — b-165 ile uyumlu
    ema_keys = ['EMA20', 'EMA50']
    if not suffix:  # günlükte EMA200 da var
        ema_keys.append('EMA200')
    for ek in ema_keys:
        raw_ema = _safe_num(row.get(f'{ek}{sfx}'))
        k = ek.lower()
        if raw_ema is not None and close and close > 0:
            out[k] = (close - raw_ema) / close
        else:
            out[k] = None

    return out


def fetch_all_timeframes(symbol: str) -> Dict:
    """
    Bir hisse için Günlük + Haftalık + Aylık verileri
    TEK TradingView query ile birden çeker.

    Çıktı: {'symbol', 'd': {...}, 'w': {...}, 'm': {...}}
    Her alt dict nvs.py'nin analyze_nvs() fonksiyonuna hazır formatta.
    """
    try:
        cols = _build_columns()
        query = (Query()
                 .select(*cols)
                 .set_markets('turkey')
                 .where(col('name') == symbol))
        count, df = query.get_scanner_data()
        if df is None or len(df) == 0:
            err = {'_error': f'{symbol} bulunamadı'}
            return {'symbol': symbol, 'd': err,
                    'w': dict(err), 'm': dict(err)}
        row = df.iloc[0].to_dict()
    except Exception as e:
        err = {'_error': str(e)[:150]}
        return {'symbol': symbol, 'd': err,
                'w': dict(err), 'm': dict(err)}

    close = _safe_num(row.get('close'))

    # ── Günlük (suffix yok) + ekstra alanlar ──
    d = _process_tf(row, close, suffix='')
    d['_close'] = close
    d['close'] = close
    d['change'] = _safe_num(row.get('change'))
    d['vol'] = _safe_num(row.get('volume'))
    d['vol_avg'] = _safe_num(row.get('average_volume_10d_calc'))
    d['adx'] = _safe_num(row.get('ADX'))
    d['atr'] = _safe_num(row.get('ATR'))

    # ── Haftalık (|1W) ──
    w = _process_tf(row, close, suffix='1W')
    w['_close'] = close

    # ── Aylık (|1M) ──
    m = _process_tf(row, close, suffix='1M')
    m['_close'] = close

    return {'symbol': symbol, 'd': d, 'w': w, 'm': m}


def fetch_tv_data(symbol: str, timeframe: str = 'D') -> Dict:
    """Tek timeframe getter — geriye dönük uyum için korundu."""
    all_tf = fetch_all_timeframes(symbol)
    key_map = {'D': 'd', 'W': 'w', 'M': 'm'}
    result = all_tf.get(key_map.get(timeframe, 'd'),
                        {'_error': 'geçersiz timeframe'})
    result = dict(result)
    result['_symbol'] = symbol
    result['_timeframe'] = timeframe
    return result


# ── Hızlı manuel test: python tv_scanner.py ──
if __name__ == '__main__':
    import json
    r = fetch_all_timeframes('THYAO')

    def _brief(tf_dict):
        if tf_dict.get('_error'):
            return f"HATA: {tf_dict['_error']}"
        return {k: round(v, 3) if isinstance(v, float) else v
                for k, v in tf_dict.items()
                if k in ('rsi', 'stoch', 'rec', 'macd',
                         'ema20', 'ema50', 'ema200',
                         'change', 'adx', 'vol', 'vol_avg')}

    print("=" * 60)
    print(f"THYAO · Çok Zaman Dilimi Testi")
    print("=" * 60)
    print(f"close     : {r['d'].get('_close')}")
    print(f"DAILY     : {_brief(r['d'])}")
    print(f"WEEKLY    : {_brief(r['w'])}")
    print(f"MONTHLY   : {_brief(r['m'])}")
    print("=" * 60)
    print("BAŞARI KRİTERİ: daily_rsi, weekly_rsi, monthly_rsi üçü de FARKLI")
    d_rsi = r['d'].get('rsi')
    w_rsi = r['w'].get('rsi')
    m_rsi = r['m'].get('rsi')
    if d_rsi and w_rsi and m_rsi:
        all_same = (abs(d_rsi - w_rsi) < 0.01 and abs(d_rsi - m_rsi) < 0.01)
        print(f"→ {'❌ BUG DEVAM EDİYOR' if all_same else '✅ TİMEFRAME AYRIMI OK'}")
