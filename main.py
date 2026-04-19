from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import time
import math
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import yfinance as yf

from indicators import analyze_symbol
from symbols import get_all, to_yf, from_yf

app = FastAPI(title="Fraktal Kahin", version="1.0.0")

# CORS ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)

# ═══════════════════════════════════════════════════════════
# CACHE MEKANİZMALARI
# ═══════════════════════════════════════════════════════════
CACHE: Dict[str, Dict] = {}
SCAN_CACHE: Optional[Dict] = None
CACHE_TTL = 900   # 15 dakika
SCAN_TTL = 1800   # 30 dakika

def _cached(sym: str) -> Optional[Dict]:
    entry = CACHE.get(sym)
    if entry and (time.time() - entry['t']) < CACHE_TTL:
        return entry['data']
    return None

def _cache_set(sym: str, data: Dict):
    CACHE[sym] = {'t': time.time(), 'data': data}


# ═══════════════════════════════════════════════════════════
# JSON SAFE — NaN/Inf temizliği (yfinance bazen NaN döndürür)
# ═══════════════════════════════════════════════════════════
def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


# ═══════════════════════════════════════════════════════════
# OHLC ÇEKİMİ — yfinance üzerinden
# ═══════════════════════════════════════════════════════════
def fetch_ohlc(symbol: str, period: str = "1y") -> Optional[pd.DataFrame]:
    """Yahoo Finance'tan OHLCV verisi çeker. Hata olursa None döndürür."""
    try:
        yf_sym = to_yf(symbol)
        df = yf.download(
            yf_sym,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False
        )
        if df is None or df.empty or len(df) < 60:
            return None
        # MultiIndex sütunları düzleştir (yfinance bazen tuple döndürür)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).lower() for c in df.columns]
        # Gerekli sütunlar var mı?
        required = ['open', 'high', 'low', 'close']
        if not all(c in df.columns for c in required):
            return None
        if 'volume' not in df.columns:
            df['volume'] = 0
        return df
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# TEK HİSSE ANALİZİ
# ═══════════════════════════════════════════════════════════
def analyze_one(symbol: str, use_cache: bool = True) -> Dict:
    symbol = symbol.upper().replace('.IS', '')
    if use_cache:
        c = _cached(symbol)
        if c:
            return c
    df = fetch_ohlc(symbol, period="1y")
    if df is None:
        result = {
            "sembol": symbol,
            "hata": "Veri çekilemedi (yfinance)",
            "sinyal": "VERI_YOK",
            "guc": 0.0
        }
    else:
        try:
            result = analyze_symbol(df, symbol)
        except Exception as e:
            result = {
                "sembol": symbol,
                "hata": f"Analiz hatası: {str(e)[:100]}",
                "sinyal": "HATA",
                "guc": 0.0
            }
    result = _json_safe(result)
    _cache_set(symbol, result)
    return result


# ═══════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {
        "servis": "Fraktal Kahin v1.0",
        "durum": "OK",
        "cache_boyut": len(CACHE),
        "endpoints": [
            "/analyze/{symbol}",
            "/scan",
            "/dips",
            "/peaks",
            "/symbols",
            "/_debug_routes"
        ]
    }


@app.get("/symbols")
def list_symbols():
    syms = get_all()
    return {"toplam": len(syms), "semboller": syms}


@app.get("/analyze/{symbol}")
def analyze_endpoint(symbol: str, cache: bool = Query(True)):
    symbol = symbol.upper().replace('.IS', '').strip()
    if not symbol.isalnum() or len(symbol) > 8:
        raise HTTPException(400, "Geçersiz sembol formatı")
    return analyze_one(symbol, use_cache=cache)


@app.get("/scan")
def scan_all(
    limit: int = Query(50, ge=5, le=630),
    force: bool = Query(False)
):
    """Tüm BIST'i tara, sonuçları skor sırasına göre döndür."""
    global SCAN_CACHE
    if not force and SCAN_CACHE and (time.time() - SCAN_CACHE['t']) < SCAN_TTL:
        return SCAN_CACHE['data']

    syms = get_all()[:limit]
    results = []
    errors = 0

    def worker(s):
        return analyze_one(s, use_cache=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(worker, s): s for s in syms}
        for fut in as_completed(futures):
            try:
                r = fut.result(timeout=30)
                if r and r.get('sinyal') not in ('VERI_YOK', 'HATA', 'VERI_YETERSIZ'):
                    results.append(r)
                else:
                    errors += 1
            except Exception:
                errors += 1

    # Skora göre azalan sırala
    results.sort(key=lambda x: x.get('guc', 0), reverse=True)

    payload = {
        "tarama_zamani": pd.Timestamp.utcnow().isoformat(),
        "tarananlar": len(syms),
        "basarili": len(results),
        "hatali": errors,
        "sonuclar": results
    }
    SCAN_CACHE = {'t': time.time(), 'data': payload}
    return payload


@app.get("/dips")
def dips_endpoint(
    limit: int = Query(50, ge=5, le=630),
    min_score: float = Query(0.50, ge=0.0, le=1.0)
):
    """Sadece DIP yönünde sinyal veren hisseleri listele."""
    scan = scan_all(limit=limit, force=False)
    dips = [
        r for r in scan.get('sonuclar', [])
        if r.get('yön') == 'DIP' and r.get('guc', 0) >= min_score
    ]
    return {
        "toplam": len(dips),
        "min_skor": min_score,
        "hisseler": dips
    }


@app.get("/peaks")
def peaks_endpoint(
    limit: int = Query(50, ge=5, le=630),
    min_score: float = Query(0.50, ge=0.0, le=1.0)
):
    """Sadece TEPE yönünde sinyal veren hisseleri listele."""
    scan = scan_all(limit=limit, force=False)
    peaks = [
        r for r in scan.get('sonuclar', [])
        if r.get('yön') == 'TEPE' and r.get('guc', 0) >= min_score
    ]
    return {
        "toplam": len(peaks),
        "min_skor": min_score,
        "hisseler": peaks
    }


@app.get("/_debug_routes")
def debug_routes():
    return {"routes": [r.path for r in app.routes]}
