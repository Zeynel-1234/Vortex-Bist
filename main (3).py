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
from fraktal import analyze_fraktal
from lab_optimizer import build_dna
from lab_signals import SIGNAL_REGISTRY  # ← AŞAMA 3.3 için
from lab_store import (save_dna, load_dna, is_cached, delete_dna,
                       list_all_dna, storage_info)

app = FastAPI(title="Fraktal Kahin", version="2.5.0")

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
FRAKTAL_CACHE: Dict[str, Dict] = {}
FRAKTAL_TOP_CACHE: Optional[Dict] = None
LAB_TODAY_CACHE: Optional[Dict] = None
MOMENTUM_CACHE: Dict[str, Dict] = {}  # ← v2.5 YENİ

CACHE_TTL = 900
SCAN_TTL = 300
NVS_TTL = 300
BACKTEST_TTL = 86400
FRAKTAL_TTL = 43200
FRAKTAL_TOP_TTL = 3600
LAB_TODAY_TTL = 3600  # 1 saat
MOMENTUM_TTL = 600    # ← v2.5 YENİ — 10 dakika


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
# OHLC FETCH — AKILLI RETRY
# ═══════════════════════════════════════════════════════════
def _yf_try_fetch(yf_symbol: str, period: str) -> Optional[pd.DataFrame]:
    try:
        df = yf.download(yf_symbol, period=period, interval="1d",
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


def fetch_ohlc(symbol: str, period: str = "1y") -> Optional[pd.DataFrame]:
    symbol = symbol.upper().replace('.IS', '').strip()
    suffixes_to_try = ['.IS', '.IST', '']
    for suffix in suffixes_to_try:
        yf_sym = f'{symbol}{suffix}' if suffix else symbol
        df = _yf_try_fetch(yf_sym, period)
        if df is not None and len(df) >= 60:
            return df
    return None


def analyze_one(symbol: str, use_cache: bool = True) -> Dict:
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


def _build_nvs_inputs(d_raw: Dict, w_raw: Dict, m_raw: Dict):
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
    d_raw = tf.get('d') or {}
    w_raw = tf.get('w') or {}
    m_raw = tf.get('m') or {}
    if d_raw.get('_error'):
        return None
    if d_raw.get('rsi') is None and d_raw.get('rec') is None:
        return None
    d_data, w_data, m_data = _build_nvs_inputs(d_raw, w_raw, m_raw)
    try:
        result = analyze_nvs(symbol, d_data, w_data, m_data)
    except Exception:
        return None
    return {
        'sembol': symbol,
        'nvs': result.get('nvs'), 'nvs_label': result.get('nvs_label'),
        'nvs_color': result.get('nvs_color'), 'bkm': result.get('bkm'),
        'gunluk': result.get('gunluk'), 'haftalik': result.get('haftalik'),
        'aylik': result.get('aylik'), 'makro': result.get('makro'),
        'guven_skoru': result.get('guven_skoru'),
        'guven_label': result.get('guven_label'),
        'fiyat': d_raw.get('_close') or d_raw.get('close'),
        'gunluk_degisim': d_raw.get('change'),
    }


# ═══════════════════════════════════════════════════════════
# ROOT
# ═══════════════════════════════════════════════════════════
@app.get("/")
async def root():
    if os.path.exists("fkahin-index.html"):
        return FileResponse("fkahin-index.html")
    return {
        "servis": "Fraktal Kahin v2.5",
        "durum": "OK",
        "endpoints": [
            "/app", "/analyze/{symbol}", "/scan",
            "/nvs/{symbol}", "/nvs_debug/{symbol}",
            "/fraktal/{symbol}", "/fraktal_top",
            "/lab/{symbol}", "/lab_test/{symbol}",
            "/lab_list", "/lab_storage",
            "/lab_today",
            "/momentum/{symbol}",  # ← v2.5 YENİ
            "/backtest/{symbol}", "/backtest_all",
            "/symbols", "/_debug_routes"
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


@app.get("/_debug_routes")
def debug_routes():
    return {"routes": [r.path for r in app.routes]}


# ═══════════════════════════════════════════════════════════
# SCAN / DIPS / PEAKS
# ═══════════════════════════════════════════════════════════
@app.get("/scan")
def scan_all(
    limit: int = Query(700, ge=5, le=1000),
    min_nvs: int = Query(0, ge=0, le=100),
    sort_by: str = Query("nvs",
        pattern="^(nvs|bkm|gunluk|guven_skoru|gunluk_degisim|sembol)$"),
    force: bool = Query(False)
):
    global SCAN_CACHE
    if not force and SCAN_CACHE and (time.time() - SCAN_CACHE['t']) < SCAN_TTL:
        return _apply_scan_filters(SCAN_CACHE['data'], min_nvs, sort_by)

    t0 = time.time()
    bulk = fetch_tv_bulk(limit=limit)
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
        "cekilen": len(bulk), "gecerli": len(results),
        "nvs_dagilimi": dist, "sonuclar": results
    }
    payload = _json_safe(payload)
    SCAN_CACHE = {'t': time.time(), 'data': payload}
    return _apply_scan_filters(payload, min_nvs, sort_by)


def _apply_scan_filters(data: Dict, min_nvs: int, sort_by: str) -> Dict:
    out = dict(data)
    rows = list(out.get('sonuclar') or [])
    if min_nvs > 0:
        rows = [r for r in rows if (r.get('nvs') or 0) >= min_nvs]
    reverse = True
    if sort_by == 'sembol':
        reverse = False
        rows.sort(key=lambda x: x.get('sembol') or '')
    else:
        rows.sort(
            key=lambda x: (x.get(sort_by) if x.get(sort_by) is not None else -9999),
            reverse=reverse)
    out['sonuclar'] = rows
    out['filtre'] = {'min_nvs': min_nvs, 'sort_by': sort_by,
                     'filtrelenmis': len(rows)}
    return out


@app.get("/dips")
def dips_endpoint(limit: int = Query(700, ge=5, le=1000),
                  max_nvs: int = Query(30, ge=0, le=50)):
    scan = scan_all(limit=limit, force=False)
    rows = [r for r in scan.get('sonuclar', [])
            if r.get('nvs') is not None and r['nvs'] <= max_nvs]
    rows.sort(key=lambda x: x['nvs'])
    return {"toplam": len(rows), "max_nvs": max_nvs, "hisseler": rows}


@app.get("/peaks")
def peaks_endpoint(limit: int = Query(700, ge=5, le=1000),
                   min_nvs: int = Query(65, ge=50, le=100)):
    scan = scan_all(limit=limit, force=False)
    rows = [r for r in scan.get('sonuclar', [])
            if r.get('nvs') is not None and r['nvs'] >= min_nvs]
    rows.sort(key=lambda x: x['nvs'], reverse=True)
    return {"toplam": len(rows), "min_nvs": min_nvs, "hisseler": rows}


# ═══════════════════════════════════════════════════════════
# NVS TEK HİSSE
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
                "hata": f"TradingView: {d_raw['_error']}", "nvs": None}

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
            "suspicious": suspicious,
            "uyari": "Change %10'u geciyorsa veri günlük DEĞİL!" if suspicious else "OK"
        },
        "HAM_VERI": {
            "daily_rsi": d_raw.get('rsi'), "daily_stoch": d_raw.get('stoch'),
            "daily_change": d_raw.get('change'), "daily_close": d_raw.get('_close'),
            "weekly_rsi": w_raw.get('rsi'), "monthly_rsi": m_raw.get('rsi'),
        }
    })


# ═══════════════════════════════════════════════════════════
# FRAKTAL TEK HİSSE
# ═══════════════════════════════════════════════════════════
def _compute_fraktal_for(symbol: str) -> Dict:
    symbol = symbol.upper().replace('.IS', '').strip()
    if symbol in FRAKTAL_CACHE:
        entry = FRAKTAL_CACHE[symbol]
        if (time.time() - entry['t']) < FRAKTAL_TTL:
            return entry['data']
    df = fetch_ohlc(symbol, period="2y")
    if df is None:
        result = {'sembol': symbol, 'yeterli_veri': False,
                  'hata': 'yfinance veri çekemedi', 'fraktal_skor': None}
    else:
        try:
            result = analyze_fraktal(df, symbol)
        except Exception as e:
            result = {'sembol': symbol, 'yeterli_veri': False,
                      'hata': f'Hesap hatası: {str(e)[:100]}', 'fraktal_skor': None}
    result = _json_safe(result)
    FRAKTAL_CACHE[symbol] = {'t': time.time(), 'data': result}
    return result


@app.get("/fraktal/{symbol}")
def fraktal_endpoint(symbol: str, force: bool = Query(False)):
    symbol = symbol.upper().replace('.IS', '').strip()
    if not symbol.isalnum() or len(symbol) > 8:
        raise HTTPException(400, "Geçersiz sembol formatı")
    if force and symbol in FRAKTAL_CACHE:
        del FRAKTAL_CACHE[symbol]
    return _compute_fraktal_for(symbol)


# ═══════════════════════════════════════════════════════════════════
# FRAKTAL TOP — TAMİR EDİLDİ (B SEÇENEĞİ)
# ───────────────────────────────────────────────────────────────────
# Eski sorun: 10 hisseyi paralel olarak yfinance'den çekerken
# bazı yavaş hisseler tüm endpoint'i timeout'a sokuyordu.
# Çözüm: per-worker timeout, kısmi sonuç döndürme, hatayı yutma.
# ═══════════════════════════════════════════════════════════════════
@app.get("/fraktal_top")
def fraktal_top_endpoint(
    top_k: int = Query(20, ge=5, le=50),
    min_nvs: int = Query(65, ge=0, le=100),
    force: bool = Query(False)
):
    global FRAKTAL_TOP_CACHE
    cache_key = f"{top_k}_{min_nvs}"
    if not force and FRAKTAL_TOP_CACHE and \
       FRAKTAL_TOP_CACHE.get('key') == cache_key and \
       (time.time() - FRAKTAL_TOP_CACHE['t']) < FRAKTAL_TOP_TTL:
        return FRAKTAL_TOP_CACHE['data']

    # NVS scan'den top K hisseyi al
    try:
        scan = scan_all(limit=700, force=False)
    except Exception as e:
        return {"top_k": top_k, "min_nvs": min_nvs,
                "sonuclar": [], "hata": f"NVS taramada hata: {str(e)[:100]}"}

    rows = sorted(
        [r for r in scan.get('sonuclar', [])
         if (r.get('nvs') or 0) >= min_nvs],
        key=lambda x: x.get('nvs') or 0, reverse=True
    )[:top_k]

    if not rows:
        return {"top_k": top_k, "min_nvs": min_nvs,
                "sonuclar": [], "uyari": "NVS filtresinden hiçbir hisse geçmedi"}

    t0 = time.time()
    results: List[Dict] = []
    failed: List[str] = []  # Hata alan hisseler (raporlama)

    def worker(nvs_row):
        sym = nvs_row.get('sembol')
        if not sym:
            return None
        try:
            fr = _compute_fraktal_for(sym)
            merged = dict(nvs_row)
            merged['fraktal_skor'] = fr.get('fraktal_skor')
            merged['fraktal_karar'] = fr.get('karar')
            merged['fraktal_karar_renk'] = fr.get('karar_renk')
            merged['fraktal_gecen'] = fr.get('gecen_kosul')
            merged['fraktal_degerler'] = fr.get('degerler')
            merged['fraktal_kosullar'] = fr.get('kosullar')
            merged['fraktal_hata'] = fr.get('hata')
            return merged
        except Exception as e:
            return {'_failed': True, 'sembol': sym, '_error': str(e)[:80]}

    # Düşürülmüş worker sayısı + per-task timeout
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(worker, r): r for r in rows}
        for fut in as_completed(futures, timeout=120):
            try:
                r = fut.result(timeout=20)  # Her hisse max 20 saniye
                if r is None:
                    continue
                if r.get('_failed'):
                    failed.append(r.get('sembol', '?'))
                    continue
                results.append(r)
            except Exception as e:
                # Worker timeout veya kritik hata — atla, devam et
                src = futures[fut]
                failed.append(src.get('sembol', '?'))
                continue

    # Fraktal skoruna göre sırala
    def _sort_key(x):
        fs = x.get('fraktal_skor')
        return fs if fs is not None else -1
    results.sort(key=_sort_key, reverse=True)

    gercek_al = [r for r in results if (r.get('fraktal_skor') or 0) >= 85]
    bekle = [r for r in results if 65 <= (r.get('fraktal_skor') or 0) < 85]
    gecersiz = [r for r in results if (r.get('fraktal_skor') or 0) < 65]
    payload = {
        "top_k": top_k, "min_nvs": min_nvs,
        "sure_ms": int((time.time() - t0) * 1000),
        "islenen": len(results),
        "basarisiz": len(failed),
        "basarisiz_listesi": failed if failed else None,
        "dagilim": {"gercek_al": len(gercek_al), "bekle": len(bekle),
                    "gecersiz": len(gecersiz)},
        "sonuclar": results
    }
    payload = _json_safe(payload)
    FRAKTAL_TOP_CACHE = {'t': time.time(), 'key': cache_key, 'data': payload}
    return payload


# ═══════════════════════════════════════════════════════════════════
# LAB
# ───────────────────────────────────────────────────────────────────
# v2.5 DEĞİŞİKLİK: Bar limitleri 2000→500 minimum, 5000 maksimum
# Sebep: MANAS gibi 1177 barlık BIST hisseleri DNA üretebilsin
# Maksimum: 5000+ bar gereksiz, hesabı yavaşlatıyor
# ═══════════════════════════════════════════════════════════════════
@app.get("/lab/{symbol}")
def lab_endpoint(symbol: str, force: bool = Query(False)):
    symbol = symbol.upper().replace('.IS', '').strip()
    if not symbol.isalnum() or len(symbol) > 8:
        raise HTTPException(400, "Geçersiz sembol formatı")

    if not force:
        cached = load_dna(symbol)
        if cached is not None:
            return cached

    df = fetch_ohlc(symbol, period="10y")
    if df is None or len(df) < 500:
        df = fetch_ohlc(symbol, period="max")
        if df is None:
            return {'sembol': symbol, 'status': 'FAIL',
                    'reason': 'yfinance veri çekemedi (tüm suffix denemeleri başarısız)'}
        if len(df) < 500:
            return {'sembol': symbol, 'status': 'FAIL',
                    'reason': f'Yetersiz geçmiş: {len(df)} bar, en az 500 gerekli'}

    # Maksimum 5000 bar — daha fazlası gereksiz, hesabı yavaşlatır
    if len(df) > 5000:
        df = df.tail(5000).copy()

    try:
        dna = build_dna(df, symbol=symbol)
    except Exception as e:
        return {'sembol': symbol, 'status': 'FAIL',
                'reason': f'build_dna hatası: {str(e)[:150]}'}

    dna = _json_safe(dna)
    dna['_bar_count'] = len(df)

    if dna.get('status') in ('OK', 'ZAYIF', 'GÜÇLÜ'):
        save_dna(symbol, dna, ttl_days=7)

    return dna


@app.get("/lab_test/{symbol}")
def lab_test_endpoint(symbol: str):
    symbol = symbol.upper().replace('.IS', '').strip()
    dna = load_dna(symbol)

    if dna is None:
        return {'sembol': symbol, 'status': 'NOT_CACHED',
                'mesaj': 'Önce /lab/{symbol} çağır, DNA üretsin'}

    if dna.get('status') not in ('OK', 'GÜÇLÜ'):
        return {
            'sembol': symbol,
            'status': dna.get('status'),
            'mesaj': dna.get('reason'),
            'yas_saat': round(
                (time.time() - dna.get('_stored_at', time.time())) / 3600, 1
            )
        }

    chosen = dna.get('chosen') or {}
    mode = dna.get('mode')
    quality = dna.get('quality')

    if mode == 'TEKLİ':
        indikatör_str = f"{chosen.get('name')}({chosen.get('params')})"
    else:
        members = chosen.get('members', [])
        indikatör_str = ' + '.join(
            f"{m['name']}({m['params']})" for m in members
        )

    return {
        'sembol': symbol,
        'status': 'OK',
        'mode': mode,
        'level': dna.get('level'),
        'quality': quality,
        'strateji': indikatör_str,
        'train_kalite': chosen.get('train', {}).get('quality'),
        'test_kalite': chosen.get('test', {}).get('quality'),
        'test_sinyal_sayisi': chosen.get('test', {}).get('n_signals'),
        'test_basari_orani': chosen.get('test', {}).get('success_rate'),
        'test_ort_kazanc': chosen.get('test', {}).get('avg_max_gain'),
        'test_ort_kayip': chosen.get('test', {}).get('avg_max_drawdown'),
        'yas_saat': round(
            (time.time() - dna.get('_stored_at', time.time())) / 3600, 1
        ),
        'bar_count': dna.get('_bar_count'),
        'build_time_sec': dna.get('build_time_sec')
    }


@app.get("/lab_list")
def lab_list_endpoint(
    status: Optional[str] = Query(None,
        pattern="^(OK|GÜÇLÜ|ZAYIF|FAIL)?$"),
    min_quality: Optional[float] = Query(None, ge=0, le=100)
):
    all_dna = list_all_dna()
    if status:
        all_dna = [d for d in all_dna if d.get('status') == status]
    if min_quality is not None:
        all_dna = [d for d in all_dna
                   if (d.get('quality') or 0) >= min_quality]
    return {
        'toplam': len(all_dna),
        'filtre': {'status': status, 'min_quality': min_quality},
        'dna_kartlari': all_dna
    }


@app.get("/lab_storage")
def lab_storage_endpoint():
    return storage_info()


@app.delete("/lab/{symbol}")
def lab_delete_endpoint(symbol: str):
    symbol = symbol.upper().replace('.IS', '').strip()
    success = delete_dna(symbol)
    return {'sembol': symbol, 'silindi': success}


# ═══════════════════════════════════════════════════════════════════
# AŞAMA 3.3 — GÜNLÜK SİNYAL ÜRETİCİSİ
# ───────────────────────────────────────────────────────────────────
# DNA'sı olan hisseleri tarayıp BUGÜN hangi hisseler kendi DNA'sına
# göre GÜÇLÜ AL veriyor — onu listeler.
# ═══════════════════════════════════════════════════════════════════
def _check_dna_signal_today(symbol: str, dna: Dict) -> Dict:
    """
    Bir hisse için DNA'sının BUGÜN sinyal verip vermediğini kontrol et.
    """
    chosen = dna.get('chosen') or {}
    if not chosen:
        return {'symbol': symbol, 'has_signal': False,
                'reason': 'Seçilmiş strateji yok'}

    # Son 30 günlük veri çek (sinyal kontrolü için yeterli)
    df = fetch_ohlc(symbol, period="6mo")
    if df is None or len(df) < 30:
        return {'symbol': symbol, 'has_signal': False,
                'reason': 'Güncel veri çekilemedi'}

    try:
        # DNA'daki indikatör(ler)den sinyal serisi üret
        signals_combined = None
        members = chosen.get('members') if 'members' in chosen else [chosen]

        for member in members:
            ind_name = member.get('name')
            params = member.get('params') or {}
            if ind_name not in SIGNAL_REGISTRY:
                continue

            func, _ = SIGNAL_REGISTRY[ind_name]
            sig = func(df, **params)

            if not isinstance(sig, pd.Series):
                continue
            sig_bool = sig.fillna(False).astype(bool)

            if signals_combined is None:
                signals_combined = sig_bool
            else:
                # İkili/üçlü: tüm üyelerin son 3 bar içinde sinyal vermesi
                ext = sig_bool.rolling(window=4, min_periods=1).max().astype(bool)
                ext_existing = signals_combined.rolling(
                    window=4, min_periods=1).max().astype(bool)
                signals_combined = ext_existing & ext

        if signals_combined is None or signals_combined.sum() == 0:
            return {'symbol': symbol, 'has_signal': False,
                    'reason': 'Henüz sinyal yok'}

        # Son sinyalin kaç bar önce verildiğini bul
        signal_indices = signals_combined.values.nonzero()[0] if hasattr(
            signals_combined.values, 'nonzero') else \
            [i for i, v in enumerate(signals_combined.values) if v]

        if len(signal_indices) == 0:
            return {'symbol': symbol, 'has_signal': False,
                    'reason': 'Henüz sinyal yok'}

        last_signal_idx = signal_indices[-1]
        bars_since_signal = len(signals_combined) - 1 - last_signal_idx

        # Son 5 bar içinde sinyal varsa "TAZE"
        is_fresh = bars_since_signal <= 5

        close = df['close'].astype(float)
        last_close = float(close.iloc[-1])
        signal_close = float(close.iloc[last_signal_idx]) if last_signal_idx < len(close) else last_close
        change_since_signal = ((last_close - signal_close) / signal_close * 100) \
            if signal_close > 0 else 0

        return {
            'symbol': symbol,
            'has_signal': bool(is_fresh),
            'is_fresh': bool(is_fresh),
            'bars_since_signal': int(bars_since_signal),
            'signal_close': round(signal_close, 2),
            'last_close': round(last_close, 2),
            'change_since_signal_pct': round(change_since_signal, 2),
            'dna_quality': dna.get('quality'),
            'dna_status': dna.get('status'),
            'dna_mode': dna.get('mode'),
            'strategy': ' + '.join(m.get('name', '?') for m in members)
        }
    except Exception as e:
        return {'symbol': symbol, 'has_signal': False,
                'reason': f'Hata: {str(e)[:80]}'}


@app.get("/lab_today")
def lab_today_endpoint(
    fresh_only: bool = Query(True, description="Sadece son 5 günde sinyal verenler"),
    min_quality: float = Query(50.0, ge=0, le=100,
                                description="Minimum DNA kalitesi"),
    force: bool = Query(False)
):
    """
    DNA'sı olan hisseleri tarayıp BUGÜN hangi hisseler kendi DNA'sına
    göre GÜÇLÜ AL veriyor.
    """
    global LAB_TODAY_CACHE
    cache_key = f"{fresh_only}_{min_quality}"
    if not force and LAB_TODAY_CACHE and \
       LAB_TODAY_CACHE.get('key') == cache_key and \
       (time.time() - LAB_TODAY_CACHE['t']) < LAB_TODAY_TTL:
        return LAB_TODAY_CACHE['data']

    t0 = time.time()
    all_dna = list_all_dna()

    # Min kalite filtresi
    candidates = [d for d in all_dna
                  if (d.get('quality') or 0) >= min_quality
                  and d.get('status') in ('OK', 'GÜÇLÜ')]

    if not candidates:
        return {
            'fresh_only': fresh_only,
            'min_quality': min_quality,
            'sonuclar': [],
            'mesaj': f'DNA kartlarında kalite>={min_quality} olan hisse yok'
        }

    results = []
    failed = []

    def worker(dna_summary):
        sym = dna_summary.get('symbol')
        if not sym:
            return None
        # Tam DNA'yı disk'ten oku
        full_dna = load_dna(sym)
        if full_dna is None:
            return None
        return _check_dna_signal_today(sym, full_dna)

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(worker, d): d for d in candidates}
        for fut in as_completed(futures, timeout=180):
            try:
                r = fut.result(timeout=30)
                if r is None:
                    continue
                if fresh_only and not r.get('is_fresh'):
                    continue
                if r.get('has_signal') or (not fresh_only and r.get('bars_since_signal') is not None):
                    results.append(r)
            except Exception as e:
                src = futures[fut]
                failed.append(src.get('symbol', '?'))
                continue

    # Sıralama: önce fresh sinyaller, sonra kaliteye göre
    results.sort(key=lambda x: (
        -1 if x.get('is_fresh') else 1,
        x.get('bars_since_signal') or 999,
        -(x.get('dna_quality') or 0)
    ))

    payload = {
        'taranan': len(candidates),
        'sinyal_veren': len(results),
        'basarisiz': len(failed),
        'sure_ms': int((time.time() - t0) * 1000),
        'fresh_only': fresh_only,
        'min_quality': min_quality,
        'sonuclar': results
    }
    payload = _json_safe(payload)
    LAB_TODAY_CACHE = {'t': time.time(), 'key': cache_key, 'data': payload}
    return payload


# ═══════════════════════════════════════════════════════════════════
# v2.5 YENİ — MOMENTUM ENDPOINT (Kapı 4 için backend)
# ───────────────────────────────────────────────────────────────────
# Amaç: Son 3-5-10 bar GERÇEK getirisini ve yön sayımını döndürmek.
# Frontend'deki 4. Kapı bunu kullanacak; "estimateMomentum"
# tahmininin yerini alacak. Böylece "son 3 bar düşüşte ama AL
# diyor" sorunu kökten çözülür.
#
# Risk skoru anlamı:
#   3 → AL kesinlikle BLOKE (son barlar net düşüş)
#   2 → BEKLE (zayıf düşüş, kısa vade negatif)
#   1 → YATAY (kararsız)
#   0 → AL güvenli (kısa vade pozitif)
#  -1 → AL tercihli (güçlü yukarı momentum)
# ═══════════════════════════════════════════════════════════════════
@app.get("/momentum/{symbol}")
def momentum_endpoint(symbol: str, force: bool = Query(False)):
    """
    Son N bar getiri + yön sayımı + ATR%.
    Kapı 4 (kısa vadeli momentum filtresi) tarafından kullanılır.

    Dönen alanlar:
      r3_pct, r5_pct, r10_pct: son 3/5/10 bar % getiri
      son3_yukari/asagi: son 3 barın kaçı yukarı/aşağı kapanmış
      son5_yukari/asagi: son 5 barın kaçı yukarı/aşağı kapanmış
      atr_pct: 14 günlük günlük % değişim std (volatilite)
      egim_pct: son 5 bar lineer regresyon eğimi (% / gün)
      yorum: AŞAĞI_GÜÇLÜ | AŞAĞI_ZAYIF | YATAY | YUKARI_ZAYIF | YUKARI_GÜÇLÜ
      risk_skoru: 3, 2, 1, 0, -1
    """
    symbol = symbol.upper().replace('.IS', '').strip()
    if not symbol.isalnum() or len(symbol) > 8:
        raise HTTPException(400, "Geçersiz sembol formatı")

    # Cache kontrol
    if not force and symbol in MOMENTUM_CACHE:
        entry = MOMENTUM_CACHE[symbol]
        if (time.time() - entry['t']) < MOMENTUM_TTL:
            return entry['data']

    df = fetch_ohlc(symbol, period="3mo")
    if df is None or len(df) < 11:
        result = {
            "sembol": symbol,
            "yeterli_veri": False,
            "hata": "Yeterli geçmiş veri yok (en az 11 bar gerekli)",
            "yorum": "VERI_YOK",
            "risk_skoru": 1
        }
        MOMENTUM_CACHE[symbol] = {'t': time.time(), 'data': result}
        return result

    try:
        closes = df['close'].tail(20).tolist()
        if len(closes) < 11:
            return {
                "sembol": symbol, "yeterli_veri": False,
                "hata": "Az veri", "yorum": "VERI_YOK", "risk_skoru": 1
            }

        # Getiri hesapları (yüzdesel)
        def _pct(now, then):
            if then is None or then <= 0:
                return 0.0
            return (now / then - 1) * 100

        r3 = _pct(closes[-1], closes[-4])
        r5 = _pct(closes[-1], closes[-6])
        r10 = _pct(closes[-1], closes[-11])

        # Bar bar yön (son 3 bar): kapanış[i] vs kapanış[i-1]
        son3_yukari = sum(1 for i in range(1, 4) if closes[-i] > closes[-i - 1])
        son3_asagi = sum(1 for i in range(1, 4) if closes[-i] < closes[-i - 1])

        # Son 5 bar yön
        son5_yukari = sum(1 for i in range(1, 6) if closes[-i] > closes[-i - 1])
        son5_asagi = sum(1 for i in range(1, 6) if closes[-i] < closes[-i - 1])

        # Volatilite: günlük % değişimin 14 günlük std'i
        pct_changes = df['close'].pct_change().dropna().tail(14)
        atr_pct = float(pct_changes.std() * 100) if len(pct_changes) > 0 else 0.0

        # Eğim: son 5 günün lineer regresyon slope'u (% cinsinden)
        slope_pct = 0.0
        if len(closes) >= 5:
            n = 5
            xs = list(range(n))
            ys = closes[-n:]
            x_mean = sum(xs) / n
            y_mean = sum(ys) / n
            num = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
            den = sum((xs[i] - x_mean) ** 2 for i in range(n))
            slope = num / den if den > 0 else 0.0
            slope_pct = (slope / y_mean * 100) if y_mean > 0 else 0.0

        # ─── KARAR MATRİSİ ───────────────────────────────────
        if son3_asagi >= 2 and r3 < -2:
            yorum = "AŞAĞI_GÜÇLÜ"
            risk = 3
        elif r3 < 0 and r5 < 0:
            yorum = "AŞAĞI_ZAYIF"
            risk = 2
        elif son3_yukari >= 2 and r3 > 3:
            yorum = "YUKARI_GÜÇLÜ"
            risk = -1
        elif r3 > 0 and r5 > 0:
            yorum = "YUKARI_ZAYIF"
            risk = 0
        else:
            yorum = "YATAY"
            risk = 1

        result = {
            "sembol": symbol,
            "yeterli_veri": True,
            "fiyat": round(float(closes[-1]), 4),
            "r3_pct": round(r3, 2),
            "r5_pct": round(r5, 2),
            "r10_pct": round(r10, 2),
            "son3_yukari": son3_yukari,
            "son3_asagi": son3_asagi,
            "son5_yukari": son5_yukari,
            "son5_asagi": son5_asagi,
            "atr_pct": round(atr_pct, 2),
            "egim_pct": round(slope_pct, 3),
            "yorum": yorum,
            "risk_skoru": risk,
            "_cached_at": int(time.time())
        }

        result = _json_safe(result)
        MOMENTUM_CACHE[symbol] = {'t': time.time(), 'data': result}
        return result

    except Exception as e:
        result = {
            "sembol": symbol,
            "yeterli_veri": False,
            "hata": f"Hesaplama hatası: {str(e)[:120]}",
            "yorum": "HATA",
            "risk_skoru": 1
        }
        return result


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
def backtest_all_endpoint(limit: int = Query(50, ge=5, le=200),
                          min_quality: int = Query(0, ge=0, le=100),
                          force: bool = Query(False)):
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
        "tarananlar": len(syms), "basarili": len(results),
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
    return HTMLResponse("<h1>fkahin-index.html bulunamadi</h1>", status_code=404)


# ═══════════════════════════════════════════════════════════
# TEST ENDPOINT'LERİ
# ═══════════════════════════════════════════════════════════
@app.get("/tv_test/{symbol}")
def tv_test(symbol: str):
    symbol = symbol.upper().replace('.IS', '').strip()
    return _json_safe(fetch_all_timeframes(symbol))


@app.get("/nvs_test")
def nvs_test():
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
