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

app = FastAPI(title="Fraktal Kahin", version="1.1.0")

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
        "servis": "Fraktal Kahin v1.1",
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
            "/momentum/{symbol}",
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
BACKTEST_TTL = 86400   # 24 saat (backtest sonuçları yavaş değişir)


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
NVS_TTL = 300   # 5 dakika cache


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
    """Her ara hesabı adım adım göster + timeframe doğrulaması."""
    symbol = symbol.upper().strip()
    tv = fetch_all_timeframes(symbol)
    d_raw = tv.get('d') or {}
    w_raw = tv.get('w') or {}
    m_raw = tv.get('m') or {}
    if d_raw.get('_error'):
        return {"hata": d_raw['_error']}
    # ÖNEMLİ KONTROL: Günlük change BIST için %10'u geçemez
    change = d_raw.get('change')
    timeframe_suspicious = False
    if change is not None and abs(change) > 10.1:
        timeframe_suspicious = True
    return _json_safe({
        "sembol": symbol,
        "TIMEFRAME_KONTROL": {
            "change_value": change,
            "beklenen": "BIST için günlük maksimum ±%10",
            "suspicious": timeframe_suspicious,
            "uyari": "Change %10'u geciyorsa veri günlük DEĞİL!" if timeframe_suspicious else "OK"
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
# v1.1 YENİ — MOMENTUM ENDPOINT (Kapı 4 için backend)
# ───────────────────────────────────────────────────────────
# Amaç: Son 3-5-10 bar GERÇEK getirisini ve yön sayımını döndürmek.
# Frontend'deki 4. Kapı bunu kullanacak; "estimateMomentum"
# tahmininin yerini alacak. Böylece "son 3 bar düşüşte ama AL
# diyor" sorunu kökten çözülür.
# Cache: 10 dakika (gün içinde yeterli; aşırı yfinance çağrısını engeller)
# ═══════════════════════════════════════════════════════════

MOMENTUM_CACHE: Dict[str, Dict] = {}
MOMENTUM_TTL = 600   # 10 dakika


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
      risk_skoru: 3 (al-bloke), 2 (bekle), 1 (yatay), 0 (al-güvenli), -1 (al-tercih)
    """
    symbol = symbol.upper().replace('.IS', '').strip()
    if not symbol.isalnum() or len(symbol) > 8:
        raise HTTPException(400, "Geçersiz sembol formatı")

    # Cache
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
        # risk_skoru:
        #   3 → AL kesinlikle BLOKE (son barlar net düşüş)
        #   2 → BEKLE (zayıf düşüş, kısa vade negatif)
        #   1 → YATAY (kararsız)
        #   0 → AL güvenli (kısa vade pozitif)
        #  -1 → AL tercihli (güçlü yukarı momentum)
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
