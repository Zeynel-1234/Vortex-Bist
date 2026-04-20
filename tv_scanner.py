"""
═══════════════════════════════════════════════════════════════
TradingView Scanner API Wrapper
───────────────────────────────────────────────────────────────
Sunucu tarafından TradingView'e istek atar (CORS yok).
b-165.html'in tarayıcıda yaptığı işin sunucu versiyonu.

Endpoint: scanner.tradingview.com/turkey/scan
Pazar: BIST (Borsa Istanbul)
═══════════════════════════════════════════════════════════════
"""

import requests
import time
from typing import Dict, List, Optional, Any

TV_URL = "https://scanner.tradingview.com/turkey/scan"

# TradingView'den çekilecek alanlar (b-165 ile uyumlu)
# Günlük (D) için tam set
FIELDS_DAILY = [
    "Recommend.All",         # rec
    "RSI",                   # rsi
    "Stoch.K",              # stoch
    "MACD.macd",            # macd değeri
    "MACD.signal",          # macd signal (histogram için)
    "EMA20",                # ema20 fiyat ile karşılaştırılacak
    "EMA50",                # ema50
    "EMA200",               # ema200
    "ADX",                  # adx
    "volume",               # vol
    "average_volume_10d_calc",  # vol_avg
    "close",                # current price
    "change",               # günlük değişim %
    "change|1W",            # haftalık değişim
    "change|1M",            # aylık değişim
]

# Haftalık (W) için
FIELDS_WEEKLY = [
    "Recommend.All|1W",
    "RSI|1W",
    "Stoch.K|1W",
    "MACD.macd|1W",
    "MACD.signal|1W",
    "EMA20|1W",
    "EMA50|1W",
    "close",
]

# Aylık (M) için
FIELDS_MONTHLY = [
    "Recommend.All|1M",
    "RSI|1M",
    "Stoch.K|1M",
    "MACD.macd|1M",
    "MACD.signal|1M",
    "EMA20|1M",
    "EMA50|1M",
    "close",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}


def _process_data(symbol: str, raw: List, fields: List[str], close: Optional[float] = None) -> Dict:
    """
    TradingView ham verisini işlenmiş formata çevir.
    EMA değerleri close ile karşılaştırılıp +/- yüzde farkına dönüştürülür.
    """
    out = {}
    for i, field in enumerate(fields):
        if i >= len(raw):
            break
        val = raw[i]
        if val is None:
            continue
        
        # Field adını sadeleştir
        key = field.lower()
        key = key.replace('|1w', '').replace('|1m', '').replace('|1d', '')
        
        # EMA değerlerini fark olarak hesapla
        if key.startswith('ema') and close and close > 0 and val > 0:
            # EMA değerinden fiyatın ne kadar uzakta olduğu (yüzde)
            diff = (close - val) / close
            out[key] = diff  # positif = fiyat üstünde, negatif = altında
        else:
            out[key] = val
    
    # MACD histogram = macd - signal
    if 'macd.macd' in out and 'macd.signal' in out:
        out['macd_hist'] = out['macd.macd'] - out['macd.signal']
    
    # Eski isimlere de map et (nvs.py uyumu için)
    if 'recommend.all' in out:
        out['rec'] = out['recommend.all']
    if 'rsi' in out:
        out['rsi'] = out['rsi']
    if 'stoch.k' in out:
        out['stoch'] = out['stoch.k']
    if 'macd_hist' in out:
        out['macd'] = out['macd_hist']
    if 'average_volume_10d_calc' in out:
        out['vol_avg'] = out['average_volume_10d_calc']
    if 'volume' in out:
        out['vol'] = out['volume']
    
    return out


def fetch_tv_data(symbol: str, timeframe: str = 'D') -> Optional[Dict]:
    """
    Tek bir hisse için TradingView'den indikatör verilerini çek.
    
    symbol: 'THYAO' (BIST: prefix otomatik eklenir)
    timeframe: 'D' (daily), 'W' (weekly), 'M' (monthly)
    
    Returns: işlenmiş veri dict, veya None (hata)
    """
    fields_map = {'D': FIELDS_DAILY, 'W': FIELDS_WEEKLY, 'M': FIELDS_MONTHLY}
    fields = fields_map.get(timeframe, FIELDS_DAILY)
    
    payload = {
        "symbols": {
            "tickers": [f"BIST:{symbol}"],
            "query": {"types": []}
        },
        "columns": fields
    }
    
    try:
        r = requests.post(TV_URL, json=payload, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return {"_error": f"HTTP {r.status_code}", "_status": r.status_code}
        
        data = r.json()
        if not data.get('data') or len(data['data']) == 0:
            return {"_error": "Boş yanıt", "_raw": str(data)[:200]}
        
        raw = data['data'][0].get('d', [])
        close = None
        # close field'ı bul (her timeframe'de var)
        if 'close' in fields:
            try:
                close_idx = fields.index('close')
                if close_idx < len(raw):
                    close = raw[close_idx]
            except ValueError:
                pass
        
        result = _process_data(symbol, raw, fields, close)
        result['_symbol'] = symbol
        result['_timeframe'] = timeframe
        result['_close'] = close
        return result
        
    except requests.exceptions.Timeout:
        return {"_error": "Timeout (10s)"}
    except requests.exceptions.RequestException as e:
        return {"_error": f"İstek hatası: {str(e)[:100]}"}
    except Exception as e:
        return {"_error": f"Beklenmeyen: {str(e)[:100]}"}


def fetch_all_timeframes(symbol: str) -> Dict:
    """
    Bir hisse için günlük + haftalık + aylık verileri çek.
    NVS hesaplaması için gerekli tüm veriler.
    """
    return {
        'symbol': symbol,
        'd': fetch_tv_data(symbol, 'D'),
        'w': fetch_tv_data(symbol, 'W'),
        'm': fetch_tv_data(symbol, 'M'),
    }
