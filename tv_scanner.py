"""
═══════════════════════════════════════════════════════════════
TradingView Scanner v5 — Multi-Timeframe + Bulk Fetch
───────────────────────────────────────────────────────────────
v4 ÖZELLİKLERİ:
  - Multi-timeframe tek query (|1W, |1M suffix'leri)
  - Timeframe bug çözüldü

v5 YENİLİKLERİ:
  - fetch_tv_bulk(): Tüm Türk hisselerini tek query ile çeker.
    b-165'in ana tarama yöntemi. ~630+ hisse için ~1-2 saniye.
  - symbols.py'ye artık ihtiyaç yok — evren TV'nin kendisi sağlıyor.
═══════════════════════════════════════════════════════════════
"""
from tradingview_screener import Query, col
from typing import Dict, Optional, List

# Her zaman dilimi için çekilen ortak sütunlar
_BASE_COLS = ['Recommend.All', 'RSI', 'Stoch.K',
              'MACD.macd', 'MACD.signal', 'EMA20', 'EMA50']

# Sadece günlükte çekilen ekstralar (EMA200, volume, ADX, ATR, change, close)
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

    # EMA'lar yönlü fark olarak (close - EMA) / close
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


def _row_to_tf_dict(row: Dict) -> Dict:
    """
    Bir TV satırını D/W/M dict'lerine çevirir.
    Hem single-symbol hem bulk fetch tarafından kullanılır.
    """
    close = _safe_num(row.get('close'))

    d = _process_tf(row, close, suffix='')
    d['_close'] = close
    d['close'] = close
    d['change'] = _safe_num(row.get('change'))
    d['vol'] = _safe_num(row.get('volume'))
    d['vol_avg'] = _safe_num(row.get('average_volume_10d_calc'))
    d['adx'] = _safe_num(row.get('ADX'))
    d['atr'] = _safe_num(row.get('ATR'))

    w = _process_tf(row, close, suffix='1W')
    w['_close'] = close

    m = _process_tf(row, close, suffix='1M')
    m['_close'] = close

    return {'d': d, 'w': w, 'm': m}


def _extract_symbol(row_dict: Dict, idx) -> Optional[str]:
    """
    Satırdan sembol kodunu çıkar. 'name' sütunu öncelikli,
    yoksa DataFrame index'i fallback (index 'BIST:THYAO' formatında).
    """
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


# ══════════════════════════════════════════════════════════
# TEK HİSSE FETCH — NVS endpoint'i ve detay paneli için
# ══════════════════════════════════════════════════════════
def fetch_all_timeframes(symbol: str) -> Dict:
    """
    Bir hisse için Günlük + Haftalık + Aylık verileri
    TEK TradingView query ile birden çeker.
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

    tf = _row_to_tf_dict(row)
    return {'symbol': symbol, 'd': tf['d'], 'w': tf['w'], 'm': tf['m']}


# ══════════════════════════════════════════════════════════
# BULK FETCH — Ana tarama için, /scan endpoint'inde kullanılacak
# ══════════════════════════════════════════════════════════
def fetch_tv_bulk(limit: int = 700) -> List[Dict]:
    """
    Tek TV query ile tüm Türk hisselerini çeker.
    b-165'in ana tarama yöntemi.

    Returns: Her biri şu formatta liste:
        [{'symbol': 'THYAO', 'd': {...}, 'w': {...}, 'm': {...}}, ...]

    Hata durumunda: [{'_error': '...'}] ya da boş liste.
    """
    try:
        cols = ['name'] + _build_columns()
        query = (Query()
                 .select(*cols)
                 .set_markets('turkey')
                 .limit(limit))
        count, df = query.get_scanner_data()
        if df is None or len(df) == 0:
            return []
    except Exception as e:
        return [{'_error': str(e)[:200]}]

    results: List[Dict] = []
    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        symbol = _extract_symbol(row_dict, idx)
        if not symbol:
            continue

        tf = _row_to_tf_dict(row_dict)
        results.append({
            'symbol': symbol,
            'd': tf['d'],
            'w': tf['w'],
            'm': tf['m']
        })

    return results


# ══════════════════════════════════════════════════════════
# GERİYE DÖNÜK UYUM
# ══════════════════════════════════════════════════════════
def fetch_tv_data(symbol: str, timeframe: str = 'D') -> Dict:
    """Tek timeframe getter — eski API için korundu."""
    all_tf = fetch_all_timeframes(symbol)
    key_map = {'D': 'd', 'W': 'w', 'M': 'm'}
    result = all_tf.get(key_map.get(timeframe, 'd'),
                        {'_error': 'geçersiz timeframe'})
    result = dict(result)
    result['_symbol'] = symbol
    result['_timeframe'] = timeframe
    return result


# ══════════════════════════════════════════════════════════
# MANUEL TEST: python tv_scanner.py
# ══════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("=" * 60)
    print("TEK HİSSE TESTİ — THYAO")
    print("=" * 60)
    r = fetch_all_timeframes('THYAO')
    d, w, m = r.get('d', {}), r.get('w', {}), r.get('m', {})
    print(f"Daily RSI:   {d.get('rsi')}")
    print(f"Weekly RSI:  {w.get('rsi')}")
    print(f"Monthly RSI: {m.get('rsi')}")
    print(f"Close: {d.get('_close')}")

    print("\n" + "=" * 60)
    print("BULK FETCH TESTİ — Tüm BIST")
    print("=" * 60)
    bulk = fetch_tv_bulk(limit=700)
    if bulk and '_error' in bulk[0]:
        print(f"HATA: {bulk[0]['_error']}")
    else:
        print(f"Çekilen hisse sayısı: {len(bulk)}")
        if bulk:
            print(f"İlk 10: {[s['symbol'] for s in bulk[:10]]}")
            thyao = next((s for s in bulk if s['symbol'] == 'THYAO'), None)
            if thyao:
                print(f"\nTHYAO bulk sonucu:")
                print(f"  Daily RSI:   {thyao['d'].get('rsi')}")
                print(f"  Weekly RSI:  {thyao['w'].get('rsi')}")
                print(f"  Monthly RSI: {thyao['m'].get('rsi')}")
    print("=" * 60)
