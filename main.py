from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os
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
async def root():
    # Önce frontend HTML dosyasını sunmayı dene
    if os.path.exists("fkahin-index.html"):
        return FileResponse("fkahin-index.html")
    # Dosya yoksa eski API bilgisini döndür
    return {
        "servis": "Fraktal Kahin v1.0",
        "durum": "OK",
        "cache_boyut": len(CACHE),
       "endpoints": [
           "/app",
           "/analyze/{symbol}",
           "/scan",
           "/dips",
           "/peaks",
           "/symbols",
           "/backtest/{symbol}",
           "/backtest_all",
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
# ═══════════════════════════════════════════════════════════
# BACKTEST ENDPOINT'LERI — FAZ 1
# ═══════════════════════════════════════════════════════════
from backtest import backtest_symbol

BACKTEST_CACHE: Dict[str, Dict] = {}
BACKTEST_TTL = 86400  # 24 saat (backtest sonuçları yavaş değişir)


@app.get("/backtest/{symbol}")
def backtest_endpoint(symbol: str, period: str = Query("2y"), force: bool = Query(False)):
    """Tek bir hissenin geçmiş performansını ölçer."""
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
        return {"sembol": symbol, "hata": "Veri çekilemedi", "yeterli_veri": False}
    
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
    """Çoklu hisse backtest — kalite skoruna göre sıralı."""
    cache_key = f"all_{limit}"
    if not force and cache_key in BACKTEST_CACHE:
        entry = BACKTEST_CACHE[cache_key]
        if (time.time() - entry['t']) < BACKTEST_TTL:
            data = entry['data']
            filtered = [r for r in data['sonuclar'] if r.get('kalite_skoru', 0) >= min_quality]
            return {**data, "filtrelenmis": len(filtered), "sonuclar": filtered}
    
    syms = get_all()[:limit]
    results = []
    
    def worker(s):
        df = fetch_ohlc(s, period="2y")
        if df is None:
            return None
        try:
            return backtest_symbol(df, s)
        except Exception as e:
            return {"sembol": s, "hata": str(e)[:80], "yeterli_veri": False}
    
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(worker, s): s for s in syms}
        for fut in as_completed(futures):
            try:
                r = fut.result(timeout=120)
                if r and r.get('yeterli_veri'):
                    results.append(_json_safe(r))
            except Exception:
                continue
    
    # Kalite skoruna göre azalan
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
        filtered = [r for r in payload['sonuclar'] if r.get('kalite_skoru', 0) >= min_quality]
        return {**payload, "filtrelenmis": len(filtered), "sonuclar": filtered}
    return payload
# ═══════════════════════════════════════════════════════════
# FRONTEND HTML SERVISI
# ═══════════════════════════════════════════════════════════
from fastapi.responses import FileResponse, HTMLResponse
import os as _os

@app.get("/app", response_class=HTMLResponse)
def serve_app():
    html_path = _os.path.join(_os.path.dirname(__file__), "fkahin-index.html")
    if _os.path.exists(html_path):
        return FileResponse(html_path, media_type="text/html; charset=utf-8")
    return HTMLResponse("<h1>fkahin-index.html bulunamadi</h1>", status_code=404)
    # ═══════════════════════════════════════════════════════════
# FAZ 1 TEST — NVS hesaplama doğrulama
# ═══════════════════════════════════════════════════════════
from nvs import analyze_nvs as _analyze_nvs

@app.get("/nvs_test")
def nvs_test():
    """HUBVC'nin b-165'teki ekran değerleriyle test"""
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
    return _analyze_nvs('HUBVC', test_d, test_w, test_m)
# ═══════════════════════════════════════════════════════════
# FAZ 2 TEST — TradingView Scanner bağlantı testi
# ═══════════════════════════════════════════════════════════
from tv_scanner import fetch_tv_data, fetch_all_timeframes

@app.get("/tv_test/{symbol}")
def tv_test(symbol: str):
    """TradingView'den hisse verisi çek, ham haliyle döndür."""
    symbol = symbol.upper().replace('.IS', '').strip()
    result = fetch_all_timeframes(symbol)
    return _json_safe(result)
# ═══════════════════════════════════════════════════════════
# FAZ 3 — NVS Endpoint (TradingView + NVS hesaplama birleşik)
# ═══════════════════════════════════════════════════════════
from nvs import analyze_nvs

NVS_CACHE: Dict[str, Dict] = {}
NVS_TTL = 300  # 5 dakika cache


@app.get("/nvs/{symbol}")
def nvs_endpoint(symbol: str, force: bool = Query(False)):
    """
    Tek hisse için NVS hesaplaması.
    TradingView'den veriyi çeker, nvs.py ile hesaplar, sonucu döndürür.
    """
    symbol = symbol.upper().replace('.IS', '').strip()
    if not symbol.isalnum() or len(symbol) > 8:
        raise HTTPException(400, "Geçersiz sembol formatı")
    
    # Cache kontrolü
    if not force and symbol in NVS_CACHE:
        entry = NVS_CACHE[symbol]
        if (time.time() - entry['t']) < NVS_TTL:
            return entry['data']
    
    # TradingView'den 3 zaman diliminde veri çek
    tv = fetch_all_timeframes(symbol)
    
    d_raw = tv.get('d') or {}
    w_raw = tv.get('w') or {}
    m_raw = tv.get('m') or {}
    
    # Hata kontrolü
    if d_raw.get('_error'):
        return {
            "sembol": symbol,
            "hata": f"TradingView: {d_raw['_error']}",
            "nvs": None
        }
    
    # nvs.py'nin beklediği formata uyarla
    d_data = {
        'rec': d_raw.get('rec'),
        'rsi': d_raw.get('rsi'),
        'stoch': d_raw.get('stoch'),
        'macd': d_raw.get('macd'),  # macd_hist aslında
        'ema20': d_raw.get('ema20'),
        'ema50': d_raw.get('ema50'),
        'ema200': d_raw.get('ema200'),
        'vol': d_raw.get('vol'),
        'vol_avg': d_raw.get('vol_avg'),
        'adx': d_raw.get('adx'),
    }
    
    w_data = {
        'rec': w_raw.get('rec'),
        'rsi': w_raw.get('rsi'),
        'stoch': w_raw.get('stoch'),
        'macd': w_raw.get('macd'),
        'ema20': w_raw.get('ema20'),
        'ema50': w_raw.get('ema50'),
    }
    
    m_data = {
        'rec': m_raw.get('rec'),
        'rsi': m_raw.get('rsi'),
        'stoch': m_raw.get('stoch'),
        'macd': m_raw.get('macd'),
        'ema20': m_raw.get('ema20'),
        'ema50': m_raw.get('ema50'),
    }
    
    # NVS hesapla
    result = analyze_nvs(symbol, d_data, w_data, m_data)
    
    # Ek bilgiler ekle
    result['fiyat'] = d_raw.get('_close') or d_raw.get('close')
    result['gunluk_degisim'] = d_raw.get('change')
    result['haftalik_degisim'] = d_raw.get('change|1w') or d_raw.get('change|1W')
    result['aylik_degisim'] = d_raw.get('change|1m') or d_raw.get('change|1M')
    result['ham_indikatorler'] = {
        'daily': d_data,
        'weekly': w_data,
        'monthly': m_data,
    }
    result['_cached_at'] = int(time.time())
    
    # Cache'e kaydet
    result = _json_safe(result)
    NVS_CACHE[symbol] = {'t': time.time(), 'data': result}
    
    return result
    # ═══════════════════════════════════════════════════════════
# FAZ 3 DEBUG — Adım adım hesaplama izleme
# ═══════════════════════════════════════════════════════════
from nvs import (adaptive_base_score, calc_cs, comp_score, 
                  macro_score, calc_nvs, top_factors, nvs_label)

@app.get("/nvs_debug/{symbol}")
def nvs_debug(symbol: str):
    """Her ara hesabı adım adım göster — debug için."""
    symbol = symbol.upper().strip()
    tv = fetch_all_timeframes(symbol)
    d_raw = tv.get('d') or {}
    w_raw = tv.get('w') or {}
    m_raw = tv.get('m') or {}
    
    if d_raw.get('_error'):
        return {"hata": d_raw['_error']}
    
    # Ham veriler
    debug = {
        "sembol": symbol,
        "1_HAM_VERILER": {
            "daily": {
                "rec": d_raw.get('rec'),
                "rsi": d_raw.get('rsi'),
                "stoch": d_raw.get('stoch'),
                "macd_hist": d_raw.get('macd'),
                "ema20_diff": d_raw.get('ema20'),
                "ema50_diff": d_raw.get('ema50'),
                "ema200_diff": d_raw.get('ema200'),
                "vol": d_raw.get('vol'),
                "vol_avg": d_raw.get('vol_avg'),
                "adx": d_raw.get('adx'),
                "close": d_raw.get('_close'),
                "change": d_raw.get('change'),
            },
            "weekly": {
                "rec": w_raw.get('rec'),
                "rsi": w_raw.get('rsi'),
                "stoch": w_raw.get('stoch'),
                "macd_hist": w_raw.get('macd'),
                "ema20_diff": w_raw.get('ema20'),
                "ema50_diff": w_raw.get('ema50'),
            },
            "monthly": {
                "rec": m_raw.get('rec'),
                "rsi": m_raw.get('rsi'),
                "stoch": m_raw.get('stoch'),
                "macd_hist": m_raw.get('macd'),
                "ema20_diff": m_raw.get('ema20'),
                "ema50_diff": m_raw.get('ema50'),
            },
        }
    }
    
    # Günlük baz skor — adım adım
    wm = {k: 1.0 for k in ['rec','rsi','stoch','macd','ema20','ema50','ema200','vol','adx']}
    s = 50.0
    steps = [f"BAZ: 50"]
    
    rec = d_raw.get('rec')
    if rec is not None:
        delta = rec * 25 * wm['rec']
        s += delta
        steps.append(f"rec={rec:.3f} → +{delta:.2f} → {s:.2f}")
    
    rsi = d_raw.get('rsi')
    if rsi is not None:
        delta = (50 - rsi) / 50 * 20 * wm['rsi']
        s += delta
        steps.append(f"rsi={rsi:.1f} → {delta:+.2f} → {s:.2f}")
    
    stoch = d_raw.get('stoch')
    if stoch is not None:
        delta = (50 - stoch) / 50 * 12 * wm['stoch']
        s += delta
        steps.append(f"stoch={stoch:.1f} → {delta:+.2f} → {s:.2f}")
    
    mh = d_raw.get('macd')
    if mh is not None:
        delta = (7 if mh > 0 else -7) * wm['macd']
        s += delta
        steps.append(f"macd_hist={mh:.4f} → {delta:+.2f} → {s:.2f}")
    
    e20 = d_raw.get('ema20')
    if e20 is not None:
        delta = (6 if e20 > 0 else -6) * wm['ema20']
        s += delta
        steps.append(f"ema20_diff={e20:.4f} → {delta:+.2f} → {s:.2f}")
    
    e50 = d_raw.get('ema50')
    if e50 is not None:
        delta = (4 if e50 > 0 else -4) * wm['ema50']
        s += delta
        steps.append(f"ema50_diff={e50:.4f} → {delta:+.2f} → {s:.2f}")
    
    e200 = d_raw.get('ema200')
    if e200 is not None:
        delta = (3 if e200 > 0 else -3) * wm['ema200']
        s += delta
        steps.append(f"ema200_diff={e200:.4f} → {delta:+.2f} → {s:.2f}")
    
    vol = d_raw.get('vol')
    va = d_raw.get('vol_avg')
    if vol is not None and va is not None and va > 0:
        vr = vol / va
        if vr > 2.5:
            delta = 5 * wm['vol']
        elif vr > 1.8:
            delta = 3 * wm['vol']
        elif vr < 0.6:
            delta = -4 * wm['vol']
        else:
            delta = 0
        s += delta
        steps.append(f"vol_ratio={vr:.2f} → {delta:+.2f} → {s:.2f}")
    
    adx = d_raw.get('adx')
    if adx is not None and adx > 20 and rec is not None:
        delta = (1 if rec > 0 else -1) * (3 if adx > 30 else 1) * wm['adx']
        s += delta
        steps.append(f"adx={adx:.1f} & rec>0 → {delta:+.2f} → {s:.2f}")
    
    final_gunluk = int(max(0, min(100, round(s))))
    steps.append(f"FINAL Günlük: {final_gunluk}")
    
    debug["2_GUNLUK_ADIM_ADIM"] = steps
    debug["3_GUNLUK_FINAL"] = final_gunluk
    
    return _json_safe(debug)
