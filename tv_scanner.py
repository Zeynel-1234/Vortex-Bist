"""
═══════════════════════════════════════════════════════════════
TradingView Scanner v3 — tradingview-screener kütüphanesi ile
───────────────────────────────────────────────────────────────
Önceki iki sürümde timeframe sorunu vardı.
Bu sürüm hazır kütüphane kullanıyor, timeframe sorunu çözüldü.
═══════════════════════════════════════════════════════════════
"""

from tradingview_screener import Query, col
from typing import Dict, Optional


def _fetch_for_timeframe(symbol: str, interval: str) -> Dict:
    """
    Tek hisse, belirli timeframe için veri çek.
    interval: '1D' (günlük), '1W' (haftalık), '1M' (aylık)
    """
    try:
        columns = [
            'close', 'change', 'volume',
            'Recommend.All', 'RSI', 'Stoch.K',
            'MACD.macd', 'MACD.signal',
            'EMA20', 'EMA50', 'EMA200',
            'ADX', 'average_volume_10d_calc',
        ]
        
        query = (
            Query()
            .select(*columns)
            .set_markets('turkey')
            .where(col('name') == symbol)
            .set_property('preset', 'all_stocks')
        )
        
        if interval != '1D':
            query = query.set_property('interval', interval)
        
        count, df = query.get_scanner_data()
        
        if df is None or len(df) == 0:
            return {"_error": f"{symbol} bulunamadı"}
        
        row = df.iloc[0]
        
        result = {}
        for col_name in columns:
            val = row.get(col_name)
            if val is None or (isinstance(val, float) and (val != val)):  # NaN check
                continue
            
            key = col_name.lower().replace('.', '_')
            result[key] = float(val) if hasattr(val, 'item') else val
        
        return result
        
    except Exception as e:
        return {"_error": f"{str(e)[:150]}"}


def _process_row(raw: Dict) -> Dict:
    """Ham veriyi nvs.py uyumlu formata çevir (EMA → fark, isim mapping)."""
    if raw.get('_error'):
        return raw
    
    out = dict(raw)
    close = raw.get('close')
    
    # EMA'ları fark olarak normalize et
    for ema_key in ['ema20', 'ema50', 'ema200']:
        if ema_key in raw and close and close > 0:
            try:
                out[ema_key] = (close - float(raw[ema_key])) / close
            except (TypeError, ValueError):
                pass
    
    # MACD histogram
    if 'macd_macd' in raw and 'macd_signal' in raw:
        out['macd_hist'] = raw['macd_macd'] - raw['macd_signal']
        out['macd'] = out['macd_hist']
    
    # Alias'lar nvs.py için
    if 'recommend_all' in raw:
        out['rec'] = raw['recommend_all']
    if 'stoch_k' in raw:
        out['stoch'] = raw['stoch_k']
    if 'average_volume_10d_calc' in raw:
        out['vol_avg'] = raw['average_volume_10d_calc']
    if 'volume' in raw:
        out['vol'] = raw['volume']
    if 'adx' in raw:
        out['adx'] = raw['adx']
    if 'rsi' in raw:
        out['rsi'] = raw['rsi']
    
    out['_close'] = close
    return out


def fetch_tv_data(symbol: str, timeframe: str = 'D') -> Optional[Dict]:
    """Tek timeframe için wrapper."""
    interval_map = {'D': '1D', 'W': '1W', 'M': '1M'}
    interval = interval_map.get(timeframe, '1D')
    
    raw = _fetch_for_timeframe(symbol, interval)
    processed = _process_row(raw)
    processed['_symbol'] = symbol
    processed['_timeframe'] = timeframe
    return processed


def fetch_all_timeframes(symbol: str) -> Dict:
    """Günlük + Haftalık + Aylık toplu çekim."""
    return {
        'symbol': symbol,
        'd': fetch_tv_data(symbol, 'D'),
        'w': fetch_tv_data(symbol, 'W'),
        'm': fetch_tv_data(symbol, 'M'),
    }
