"""
Fraktal Kahin · Railway FastAPI Backend
Endpoints:
  GET  /              → healthcheck
  GET  /analyze/{sym} → tek hisse detaylı analiz
  GET  /scan          → tüm BIST hızlı tarama (sinyal dağılımı)
  GET  /dips          → en güçlü dip adayları
  GET  /peaks         → en güçlü tepe adayları
  GET  /symbols       → desteklenen semboller
"""

import asyncio
import os
import time
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import pandas as pd
import yfinance as yf

from indicators import analyze_symbol
from symbols import get_all, to_yf, from_yf

app = FastAPI(
    title="Fraktal Kahin",
    description="BIST · Fraktal analiz motoru · Hurst + FFT + ATR + FYI + LRK",
    version="1.0.0"
)

# CORS: HTML frontend her yerden erişebilsin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════
# CACHE (in-memory, TTL bazlı)
# Railway tek process — global cache yeterli
# ═══════════════════════════════════════════════════════════

CACHE: Dict[str, Dict] = {}
SCAN_CACHE: Optional[Dict] = None
CACHE_TTL = 900  # 15 dk — günlük veri için yeterli
SCAN_TTL = 1800  # 30 dk — tarama için


def _cached(sym: str) -> Optional[Dict]:
    entry = CACHE.get(sym)
    if entry and (time.time() - entry['t']) < CACHE_TTL:
        return entry['data']
    return None


def _cache_set(sym: str, data: Dict):
    CACHE[sym] = {'t': time.time(), 'data': data}


# ═══════════════════════════════════════════════════════════
# DATA FETCH: Yahoo Finance
# ═══════════════════════════════════════════════════════════

def fetch_ohlc(symbol_yf: str, period: str = "2y") -> Optional[pd.DataFrame]:
    """Yahoo Finance'den OHLCV çek. Başarısızlıkta None döner."""
    try:
        import requests
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        df = yf.download(
            symbol_yf,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False,
            session=session
        )
        if df is None or df.empty or len(df) < 60:
            return None
        # MultiIndex varsa düzleştir
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return None


def analyze_one(sym: str, use_cache: bool = True) -> Dict:
    """Tek sembol için tam analiz."""
    sym = sym.upper().replace('.IS', '')
    if use_cache:
        cached = _cached(sym)
        if cached:
            return {**cached, "cache": True}

    yf_sym = to_yf(sym)
    df = fetch_ohlc(yf_sym, period="2y")
    if df is None:
        return {
            "sembol": sym,
            "hata": "Yahoo Finance verisi alınamadı",
            "sinyal": "VERI_YOK",
            "guc": 0.0
        }
    try:
        result = analyze_symbol(df, sym)
        _cache_set(sym, result)
        return result
    except Exception as e:
        return {
            "sembol": sym,
            "hata": f"Analiz hatası: {str(e)[:120]}",
            "sinyal": "HATA",
            "guc": 0.0
        }


# ═══════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════

@app.get("/")
def root():
    """Healthcheck"""
    return {
        "servis": "Fraktal Kahin v1.0",
        "durum": "OK",
        "cache_boyut": len(CACHE),
        "endpoints": [
            "/analyze/{symbol}",
            "/scan",
            "/dips",
            "/peaks",
            "/symbols"
        ],
    }


@app.get("/symbols")
def list_symbols():
    """Desteklenen BIST sembolleri"""
    syms = get_all()
    return {"toplam": len(syms), "semboller": syms}


@app.get("/analyze/{symbol}")
def analyze_endpoint(symbol: str, cache: bool = Query(True)):
    """Tek hisse detaylı Fraktal analiz"""
    symbol = symbol.upper().replace('.IS', '')
    if not symbol.isalnum() or len(symbol) > 8:
        raise HTTPException(400, "Geçersiz sembol formatı")
    return analyze_one(symbol, use_cache=cache)


@app.get("/scan")
def scan_all(limit: int = Query(100, ge=10, le=630), force: bool = Query(False)):
    """Tüm BIST'i tara, sinyal dağılımını döndür."""
    global SCAN_CACHE
    if not force and SCAN_CACHE and (time.time() - SCAN_CACHE['t']) < SCAN_TTL:
        return SCAN_CACHE['data']

    syms = get_all()[:limit]
    results = []
    errors = 0

    # ThreadPool ile paralel fetch (yfinance I/O-bound)
    def worker(s):
        return analyze_one(s, use_cache=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(worker, syms):
            if r.get('sinyal') in ('VERI_YOK', 'HATA', 'VERI_YETERSIZ'):
                errors += 1
            else:
                results.append(r)

    # Sinyal tiplerine göre say
    dagilim = {
        'GUCLU_AL': 0, 'AL': 0, 'ZAYIF_AL': 0,
        'NOTR': 0,
        'ZAYIF_SAT': 0, 'SAT': 0, 'GUCLU_SAT': 0
    }
    for r in results:
        s = r.get('sinyal', 'NOTR')
        if s in dagilim:
            dagilim[s] += 1

    data = {
        "zaman": pd.Timestamp.utcnow().isoformat(),
        "taranan": len(syms),
        "basarili": len(results),
        "hata": errors,
        "dagilim": dagilim,
        "top_dipler": sorted(
            [r for r in results if r.get('yön') == 'DIP' and r.get('guc', 0) >= 0.5],
            key=lambda x: -x.get('guc', 0)
        )[:15],
        "top_tepeler": sorted(
            [r for r in results if r.get('yön') == 'TEPE' and r.get('guc', 0) >= 0.5],
            key=lambda x: -x.get('guc', 0)
        )[:15],
    }
    SCAN_CACHE = {'t': time.time(), 'data': data}
    return data


@app.get("/dips")
def top_dips(limit: int = Query(20, ge=5, le=100), min_score: float = Query(0.5)):
    """En güçlü dip adayları (scan cache'inden)"""
    scan = scan_all(limit=630)  # full scan
    return {
        "zaman": scan['zaman'],
        "liste": [r for r in scan['top_dipler'] if r.get('guc', 0) >= min_score][:limit]
    }


@app.get("/peaks")
def top_peaks(limit: int = Query(20, ge=5, le=100), min_score: float = Query(0.5)):
    """En güçlü tepe uyarıları"""
    scan = scan_all(limit=630)
    return {
        "zaman": scan['zaman'],
        "liste": [r for r in scan['top_tepeler'] if r.get('guc', 0) >= min_score][:limit]
    }


# ═══════════════════════════════════════════════════════════
# Railway için: PORT env var
# ═══════════════════════════════════════════════════════════

