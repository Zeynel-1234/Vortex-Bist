from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
import os
import time
import math
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf

from indicators import analyze_symbol
from symbols import get_all, to_yf, from_yf
from nvs import (analyze_nvs, adaptive_base_score, calc_cs, comp_score,
                 macro_score, calc_nvs, top_factors, nvs_label)
from tv_scanner import fetch_tv_data, fetch_all_timeframes, fetch_tv_bulk
from backtest import backtest_symbol

app = FastAPI(title="Fraktal Kahin", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)

# ═══════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════
CACHE: Dict[str, Dict] = {}
SCAN_CACHE: Optional[Dict] = None
NVS_CACHE: Dict[str, Dict] = {}
BACKTEST_CACHE: Dict[str, Dict] = {}

CACHE_TTL = 900        # 15 dk — eski yfinance tabanlı analyze
SCAN_TTL = 300         # 5 dk — yeni NVS tabanlı bulk scan
NVS_TTL = 300          # 5 dk — tek hisse NVS
BACKTEST_TTL = 86400   # 24 saat


def _cached(sym: str) -> Optional[Dict]:
    entry = CACHE.get(sym)
    if entry and (time.time() - entry['t']) < CACHE_TTL:
        return entry['data']
    return None


def _cache_set(sym: str, data: Dict):
    CACHE[sym] = {'t': time.time(), 'data': data}


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj


# ═══════════════════════════════════════════════════════════
# OHLC (yfinance) — eski sistem için korundu
# ═══════════════════════════════════════════════════════════
def fetch_ohlc(symbol: str, period: str = "1y") -> Optional[pd.DataFrame]:
    try:
        yf_sym = to_yf(symbol)
        df = yf.download(yf_sym, period=period, interval="1d",
                         progress=False, auto_adjust=True, threads=False)
        if df is None or df.empty or len(df) < 60:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).lower() for c in df.columns]
        if not all(c in df.columns for c in ['open', 'high', 'low', 'close']):
            return None
        if 'volume' not in df.columns:
            df['volume'] = 0
        return df
    except Exception:
        return None


def analyze_one(symbol: str, use_cache: bool = True) -> Dict:
    """Eski yfinance tabanlı analiz — sadece /analyze/{symbol} için."""
    symbol = symbol.upper().replace('.IS', '')
    if use_cache:
        c = _cached(symbol)
        if c:
            return c
    df = fetch_ohlc(symbol, period="1y")
    if df is None:
        result = {"sembol": symbol, "hata": "Veri çekilemedi (yfinance)",
                  "sinyal": "VERI_YOK", "guc": 0.0}
    else:
        try:
            result = analyze_symbol(df, symbol)
        except Exception as e:
            result = {"sembol": symbol, "hata": f"Analiz hatası: {str(e)[:100]}",
                      "sinyal": "HATA", "guc": 0.0}
    result = _json_safe(result)
    _cache_set(symbol, result)
    return result


# ═══════════════════════════════════════════════════════════
# NVS HELPER — Bir hissenin D/W/M dict'lerini nvs.py formatına çevir
# ═══════════════════════════════════════════════════════════
def _build_nvs_inputs(d_raw: Dict, w_raw: Dict, m_raw: Dict):
    """fetch_tv_bulk/fetch_all_timeframes çıktısını nvs.py girdisine çevirir."""
    d_data = {
        'rec': d_raw.get('rec'), 'rsi': d_raw.get('rsi'),
        'stoch': d_raw.get('stoch'), 'macd': d_raw.get('macd'),
        'ema20': d_raw.get('ema20'), 'ema50': d_raw.get('ema50'),
        'ema200': d_raw.get('ema200'),
        'vol': d_raw.get('vol'), 'vol_avg': d_raw.get('vol_avg'),
        'adx': d_raw.get('adx'),
    }
    w_data = {
        'rec': w_raw.get('rec'), 'rsi': w_raw.get('rsi'),
        'stoch': w_raw.get('stoch'), 'macd': w_raw.get('macd'),
        'ema20': w_raw.get('ema20'), 'ema50': w_raw.get('ema50'),
    }
    m_data = {
        'rec': m_raw.get('rec'), 'rsi': m_raw.get('rsi'),
        'stoch': m_raw.get('stoch'), 'macd': m_raw.get('macd'),
        'ema20': m_raw.get('ema20'), 'ema50': m_raw.get('ema50'),
    }
    return d_data, w_data, m_data


def _compact_scan_row(symbol: str, tf: Dict) -> Optional[Dict]:
    """
    Bulk fetch'ten gelen tek bir satırı NVS'le ve ana liste için
    kompakt (küçük) bir dict döndür — 630 hisse için hafif payload.
    """
    d_raw = tf.get('d') or {}
    w_raw = tf.get('w') or {}
    m_raw = tf.get('m') or {}
    if d_raw.get('_error'):
        return None
    # Ham veri yoksa (delisted/yeni) atla
    if d_raw.get('rsi') is None and d_raw.get('rec') is None:
        return None

    d_data, w_data, m_data = _build_nvs_inputs(d_raw, w_raw, m_raw)
    try:
        result = analyze_nvs(symbol, d_data, w_data, m_data)
    except Exception:
        return None

    return {
        'sembol': symbol,
        'nvs': result.get('nvs'),
        'nvs_label': result.get('nvs_label'),
        'nvs_color': result.get('nvs_color'),
        'bkm': result.get('bkm'),
        'gunluk': result.get('gunluk'),
        'haftalik': result.get('haftalik'),
        'aylik': result.get('aylik'),
        'makro': result.get('makro'),
        'guven_skoru': result.get('guven_skoru'),
        'guven_label': result.get('guven_label'),
        'fiyat': d_raw.get('_close') or d_raw.get('close'),
        'gunluk_degisim': d_raw.get('change'),
    }


# ═══════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════
@app.get("/")
async def root():
    if os.path.exists("fkahin-index.html"):
        return FileResponse("fkahin-index.html")
    return {
        "servis": "Fraktal Kahin v2.0",
        "durum": "OK",
        "cache_boyut": len(CACHE),
        "endpoints": [
            "/app", "/analyze/{symbol}", "/scan", "/nvs/{symbol}",
            "/nvs_debug/{symbol}", "/backtest/{symbol}", "/backtest_all",
            "/symbols", "/_debug_routes"
        ]
    }


@app.get("/symbols")
def list_symbols():
    syms = get_all()
    return {"toplam": len(syms), "semboller": syms,
            "not": "symbols.py eski — tarama artık TV bulk fetch ile."}


@app.get("/analyze/{symbol}")
def analyze_endpoint(symbol: str, cache: bool = Query(True)):
    """Eski yfinance tabanlı analiz. NVS için /nvs/{symbol} kullanın."""
    symbol = symbol.upper().replace('.IS', '').strip()
    if not symbol.isalnum() or len(symbol) > 8:
        raise HTTPException(400, "Geçersiz sembol formatı")
    return analyze_one(symbol, use_cache=cache)


@app.get("/_debug_routes")
def debug_routes():
    return {"routes": [r.path for r in app.routes]}


# ═══════════════════════════════════════════════════════════
# SCAN — NVS tabanlı toplu tarama (FAZ 4.1b)
# Tek TradingView query ile 630+ hisseyi çeker, NVS hesaplar, sıralar.
# ═══════════════════════════════════════════════════════════
@app.get("/scan")
def scan_all(
    limit: int = Query(700, ge=5, le=1000),
    min_nvs: int = Query(0, ge=0, le=100),
    sort_by: str = Query("nvs", pattern="^(nvs|bkm|gunluk|guven_skoru|gunluk_degisim|sembol)$"),
    force: bool = Query(False)
):
    """
    BIST'in tamamını NVS ile tarar.
    - limit: kaç hisse çekilsin (default 700 → hepsi)
    - min_nvs: minimum NVS filtresi (ör. min_nvs=65 sadece AL ve üzeri)
    - sort_by: sıralama (nvs/bkm/gunluk/guven_skoru/gunluk_degisim/sembol)
    - force: cache atla
    """
    global SCAN_CACHE

    # Cache
    if not force and SCAN_CACHE:
        if (time.time() - SCAN_CACHE['t']) < SCAN_TTL:
            data = SCAN_CACHE['data']
            return _apply_scan_filters(data, min_nvs, sort_by)

    t0 = time.time()
    bulk = fetch_tv_bulk(limit=limit)

    # Hata kontrolü
    if not bulk:
        raise HTTPException(502, "TradingView: veri gelmedi")
    if '_error' in bulk[0]:
        raise HTTPException(502, f"TradingView: {bulk[0].get('_error')}")

    results: List[Dict] = []
    for row in bulk:
        symbol = row.get('symbol', '').strip().upper()
        if not symbol:
            continue
        compact = _compact_scan_row(symbol, row)
        if compact is not None:
            results.append(compact)

    # NVS dağılımı
    dist = {'gucl_al': 0, 'al': 0, 'notr': 0, 'sat': 0, 'gucl_sat': 0}
    for r in results:
        n = r.get('nvs') or 0
        if n >= 80: dist['gucl_al'] += 1
        elif n >= 65: dist['al'] += 1
        elif n >= 45: dist['notr'] += 1
        elif n >= 30: dist['sat'] += 1
        else: dist['gucl_sat'] += 1

    payload = {
        "tarama_zamani": pd.Timestamp.utcnow().isoformat(),
        "kaynak": "tradingview-bulk",
        "sure_ms": int((time.time() - t0) * 1000),
        "cekilen": len(bulk),
        "gecerli": len(results),
        "nvs_dagilimi": dist,
        "sonuclar": results
    }
    payload = _json_safe(payload)

    SCAN_CACHE = {'t': time.time(), 'data': payload}
    return _apply_scan_filters(payload, min_nvs, sort_by)


def _apply_scan_filters(data: Dict, min_nvs: int, sort_by: str) -> Dict:
    """Cache'li sonuca filtre + sıralama uygula (cache payload'ı değişmez)."""
    out = dict(data)
    rows = list(out.get('sonuclar') or [])

    if min_nvs > 0:
        rows = [r for r in rows if (r.get('nvs') or 0) >= min_nvs]

    reverse = True
    if sort_by == 'sembol':
        reverse = False
        rows.sort(key=lambda x: x.get('sembol') or '')
    else:
        rows.sort(key=lambda x: (x.get(sort_by) if x.get(sort_by) is not None else -9999),
                  reverse=reverse)

    out['sonuclar'] = rows
    out['filtre'] = {'min_nvs': min_nvs, 'sort_by': sort_by,
                     'filtrelenmis': len(rows)}
    return out


# ═══════════════════════════════════════════════════════════
# DIPS / PEAKS — NVS tabanlı
# ═══════════════════════════════════════════════════════════
@app.get("/dips")
def dips_endpoint(
    limit: int = Query(700, ge=5, le=1000),
    max_nvs: int = Query(30, ge=0, le=50)
):
    """DIP adayları: NVS ≤ max_nvs (default 30 → GÜÇLÜ SAT bölgesi, dipten dönebilir)."""
    scan = scan_all(limit=limit, force=False)
    rows = [r for r in scan.get('sonuclar', [])
            if r.get('nvs') is not None and r['nvs'] <= max_nvs]
    rows.sort(key=lambda x: x['nvs'])
    return {"toplam": len(rows), "max_nvs": max_nvs, "hisseler": rows}


@app.get("/peaks")
def peaks_endpoint(
    limit: int = Query(700, ge=5, le=1000),
    min_nvs: int = Query(65, ge=50, le=100)
):
    """TEPE adayları: NVS ≥ min_nvs (default 65 → AL ve üzeri)."""
    scan = scan_all(limit=limit, force=False)
    rows = [r for r in scan.get('sonuclar', [])
            if r.get('nvs') is not None and r['nvs'] >= min_nvs]
    rows.sort(key=lambda x: x['nvs'], reverse=True)
    return {"toplam": len(rows), "min_nvs": min_nvs, "hisseler": rows}


# ═══════════════════════════════════════════════════════════
# TEK HİSSE NVS
# ═══════════════════════════════════════════════════════════
@app.get("/nvs/{symbol}")
def nvs_endpoint(symbol: str, force: bool = Query(False)):
    symbol = symbol.upper().replace('.IS', '').strip()
    if not symbol.isalnum() or len(symbol) > 8:
        raise HTTPException(400, "Geçersiz sembol formatı")

    if not force and symbol in NVS_CACHE:
        entry = NVS_CACHE[symbol]
        if (time.time() - entry['t']) < NVS_TTL:
            return entry['data']

    tv = fetch_all_timeframes(symbol)
    d_raw = tv.get('d') or {}
    w_raw = tv.get('w') or {}
    m_raw = tv.get('m') or {}

    if d_raw.get('_error'):
        return {"sembol": symbol,
                "hata": f"TradingView: {d_raw['_error']}",
                "nvs": None}

    d_data, w_data, m_data = _build_nvs_inputs(d_raw, w_raw, m_raw)
    result = analyze_nvs(symbol, d_data, w_data, m_data)

    result['fiyat'] = d_raw.get('_close') or d_raw.get('close')
    result['gunluk_degisim'] = d_raw.get('change')
    result['ham_indikatorler'] = {
        'daily': d_data, 'weekly': w_data, 'monthly': m_data
    }
    result['_cached_at'] = int(time.time())

    result = _json_safe(result)
    NVS_CACHE[symbol] = {'t': time.time(), 'data': result}
    return result


@app.get("/nvs_debug/{symbol}")
def nvs_debug(symbol: str):
    symbol = symbol.upper().strip()
    tv = fetch_all_timeframes(symbol)
    d_raw = tv.get('d') or {}
    w_raw = tv.get('w') or {}
    m_raw = tv.get('m') or {}
    if d_raw.get('_error'):
        return {"hata": d_raw['_error']}

    change = d_raw.get('change')
    suspicious = change is not None and abs(change) > 10.1

    return _json_safe({
        "sembol": symbol,
        "TIMEFRAME_KONTROL": {
            "change_value": change,
            "beklenen": "BIST için günlük maksimum ±%10",
            "suspicious": suspicious,
            "uyari": "Change %10'u geciyorsa veri günlük DEĞİL!" if suspicious else "OK"
        },
        "HAM_VERI": {
            "daily_rsi": d_raw.get('rsi'),
            "daily_stoch": d_raw.get('stoch'),
            "daily_change": d_raw.get('change'),
            "daily_close": d_raw.get('_close'),
            "weekly_rsi": w_raw.get('rsi'),
            "monthly_rsi": m_raw.get('rsi'),
        }
    })


# ═══════════════════════════════════════════════════════════
# BACKTEST
# ═══════════════════════════════════════════════════════════
@app.get("/backtest/{symbol}")
def backtest_endpoint(symbol: str, period: str = Query("2y"),
                      force: bool = Query(False)):
    symbol = symbol.upper().replace('.IS', '').strip()
    if not symbol.isalnum() or len(symbol) > 8:
        raise HTTPException(400, "Geçersiz sembol formatı")
    cache_key = f"{symbol}_{period}"
    if not force and cache_key in BACKTEST_CACHE:
        entry = BACKTEST_CACHE[cache_key]
        if (time.time() - entry['t']) < BACKTEST_TTL:
            return entry['data']

    df = fetch_ohlc(symbol, period=period)
    if df is None:
        return {"sembol": symbol, "hata": "Veri çekilemedi",
                "yeterli_veri": False}
    result = backtest_symbol(df, symbol)
    result = _json_safe(result)
    BACKTEST_CACHE[cache_key] = {'t': time.time(), 'data': result}
    return result


@app.get("/backtest_all")
def backtest_all_endpoint(
    limit: int = Query(50, ge=5, le=200),
    min_quality: int = Query(0, ge=0, le=100),
    force: bool = Query(False)
):
    cache_key = f"all_{limit}"
    if not force and cache_key in BACKTEST_CACHE:
        entry = BACKTEST_CACHE[cache_key]
        if (time.time() - entry['t']) < BACKTEST_TTL:
            data = entry['data']
            filtered = [r for r in data['sonuclar']
                        if r.get('kalite_skoru', 0) >= min_quality]
            return {**data, "filtrelenmis": len(filtered),
                    "sonuclar": filtered}

    syms = get_all()[:limit]
    results = []

    def worker(s):
        df = fetch_ohlc(s, period="2y")
        if df is None:
            return None
        try:
            return backtest_symbol(df, s)
        except Exception as e:
            return {"sembol": s, "hata": str(e)[:80],
                    "yeterli_veri": False}

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(worker, s): s for s in syms}
        for fut in as_completed(futures):
            try:
                r = fut.result(timeout=120)
                if r and r.get('yeterli_veri'):
                    results.append(_json_safe(r))
            except Exception:
                continue

    results.sort(key=lambda x: x.get('kalite_skoru', 0), reverse=True)

    payload = {
        "tarama_zamani": pd.Timestamp.utcnow().isoformat(),
        "tarananlar": len(syms),
        "basarili": len(results),
        "yuksek_kalite": len([r for r in results if r.get('kalite_skoru', 0) >= 70]),
        "orta_kalite": len([r for r in results if 50 <= r.get('kalite_skoru', 0) < 70]),
        "sonuclar": results
    }
    BACKTEST_CACHE[cache_key] = {'t': time.time(), 'data': payload}

    if min_quality > 0:
        filtered = [r for r in payload['sonuclar']
                    if r.get('kalite_skoru', 0) >= min_quality]
        return {**payload, "filtrelenmis": len(filtered),
                "sonuclar": filtered}
    return payload


# ═══════════════════════════════════════════════════════════
# FRONTEND
# ═══════════════════════════════════════════════════════════
@app.get("/app", response_class=HTMLResponse)
def serve_app():
    html_path = os.path.join(os.path.dirname(__file__), "fkahin-index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path, media_type="text/html; charset=utf-8")
    return HTMLResponse("<h1>fkahin-index.html bulunamadi</h1>",
                        status_code=404)


# ═══════════════════════════════════════════════════════════
# TV TEST — Geriye uyum için korundu
# ═══════════════════════════════════════════════════════════
@app.get("/tv_test/{symbol}")
def tv_test(symbol: str):
    symbol = symbol.upper().replace('.IS', '').strip()
    result = fetch_all_timeframes(symbol)
    return _json_safe(result)


@app.get("/nvs_test")
def nvs_test():
    """HUBVC sabit değerlerle test — nvs.py regresyon kontrolü."""
    test_d = {
        'rec': 0.291, 'rsi': 48.1, 'stoch': 33.7, 'macd': 0.0108,
        'ema20': 1, 'ema50': -1, 'ema200': 1,
        'vol': 2.0, 'vol_avg': 1.0, 'adx': 35.0
    }
    test_w = {
        'rec': 0.288, 'rsi': 52.9, 'stoch': 33.7, 'macd': 0.0108,
        'ema20': 1, 'ema50': 1
    }
    test_m = test_w.copy()
    return analyze_nvs('HUBVC', test_d, test_w, test_m)
