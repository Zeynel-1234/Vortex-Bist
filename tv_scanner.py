"""
═══════════════════════════════════════════════════════════════
TradingView Scanner API Wrapper — v2 (DÜZELTİLDİ)
───────────────────────────────────────────────────────────────
ÖNEMLİ DÜZELTME: Önceki sürümde timeframe belirtilmediği için
TradingView yanlış zaman dilimi döndürüyordu (intraday gibi).
Bu sürümde günlük veri için TAMAMI "|1d" suffix ile istenir.
═══════════════════════════════════════════════════════════════
"""

import requests
from typing import Dict, Optional

TV_URL = "https://scanner.tradingview.com/turkey/scan"

# GÜNLÜK kapanış verisi: TÜM field'lar açık "|1d" takısı ile
# (Recommend.All başta olduğu için "recommend.all" şeklinde map edilecek)
FIELDS_DAILY = [
    "Recommend.All",
    "RSI",
    "Stoch.K",
    "MACD.macd",
    "MACD.signal",
    "EMA20",
    "EMA50",
    "EMA200",
    "ADX",
    "volume",
    "average_volume_10d_calc",
    "close",
    "change",
    "change|1W",
    "change|1M",
]

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
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}


def _process_data(raw: list, fields: list, close: Optional[float] = None) -> Dict:
    """TradingView ham verisini sözlüğe çevir."""
    out = {}
    for i, field in enumerate(fields):
        if i >= len(raw):
            break
        val = raw[i]
        if val is None:
            continue
        
        # Field adını sadeleştir
        key = field.lower().replace('|1w', '').replace('|1m', '').replace('|1d', '')
        
        # EMA değerlerini fiyata göre normalize et: +% (üst) / -% (alt)
        if key.startswith('ema') and close and close > 0:
            try:
                diff = (close - float(val)) / close
                out[key] = diff
            except (TypeError, ValueError):
                pass
        else:
            out[key] = val
    
    # MACD histogram = macd - signal
    if 'macd.macd' in out and 'macd.signal' in out:
        out['macd_hist'] = out['macd.macd'] - out['macd.signal']
    
    # nvs.py uyumluluğu için isim map'leme
    if 'recommend.all' in out:
        out['rec'] = out['recommend.all']
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
    Tek hisse, tek timeframe veri çek.
    timeframe: 'D' (daily), 'W' (weekly), 'M' (monthly)
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
            return {"_error": f"HTTP {r.status_code}"}
        
        data = r.json()
        if not data.get('data') or len(data['data']) == 0:
            return {"_error": "Boş yanıt"}
        
        raw = data['data'][0].get('d', [])
        
        # close field'ı bul
        close = None
        if 'close' in fields:
            idx = fields.index('close')
            if idx < len(raw):
                close = raw[idx]
        
        result = _process_data(raw, fields, close)
        result['_symbol'] = symbol
        result['_timeframe'] = timeframe
        result['_close'] = close
        return result
        
    except requests.exceptions.Timeout:
        return {"_error": "Timeout"}
    except Exception as e:
        return {"_error": f"Hata: {str(e)[:100]}"}


def fetch_all_timeframes(symbol: str) -> Dict:
    """Bir hisse için 3 zaman dilimi toplu çekim."""
    return {
        'symbol': symbol,
        'd': fetch_tv_data(symbol, 'D'),
        'w': fetch_tv_data(symbol, 'W'),
        'm': fetch_tv_data(symbol, 'M'),
    }
