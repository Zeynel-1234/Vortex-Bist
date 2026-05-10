"""
═══════════════════════════════════════════════════════════════════════════
URİS SAT v2.0 — main.py ENDPOINT KODLARI
───────────────────────────────────────────────────────────────────────────
Bu dosya main.py'nin SONUNA kopyalanacak hazır endpoint'leri içerir.
Mevcut endpoint'lere DOKUNULMAZ — sadece /sell_v2_ prefix'iyle yeni 4 route eklenir.
═══════════════════════════════════════════════════════════════════════════
"""

# ╔═══════════════════════════════════════════════════════════════════════╗
# ║ AŞAĞIDAKİ TÜM KODU MAIN.PY'NİN SONUNA YAPIŞTIR                     ║
# ╚═══════════════════════════════════════════════════════════════════════╝

# ── v2 CACHE (mevcut cache'lerle çakışmaz) ───────────────────────────────
SELL_V2_TODAY_CACHE = None
SELL_V2_TODAY_TTL = 1800  # 30 dakika


# ── ENDPOINT 1: Tek hisse için v2 SAT DNA üret ──────────────────────────
@app.get("/sell_v2/{symbol}")
def sell_v2_endpoint(symbol: str, force: bool = Query(False)):
    """
    v2 SAT DNA üretir veya cache'den döner.
    v2 farkı: Pre-peak divergence + climax bar detection.
    Hedef: TAM TEPE BAR'INDA veya 1-3 bar ÖNCE sinyal vermek.
    """
    symbol = symbol.upper().replace('.IS', '').strip()
    if not symbol.isalnum() or len(symbol) > 8:
        raise HTTPException(400, "Geçersiz sembol formatı")

    if not force:
        cached = load_sell_v2_dna(symbol)
        if cached is not None:
            return cached

    df = fetch_ohlc(symbol, period="10y")
    if df is None or len(df) < 500:
        df = fetch_ohlc(symbol, period="max")
        if df is None:
            return {'sembol': symbol, 'status': 'FAIL',
                    'reason': 'yfinance veri çekemedi'}
        if len(df) < 500:
            return {'sembol': symbol, 'status': 'FAIL',
                    'reason': f'Yetersiz geçmiş: {len(df)} bar, en az 500 gerekli'}

    if len(df) > 5000:
        df = df.tail(5000).copy()

    try:
        dna = build_sell_v2_dna(df, symbol=symbol)
    except Exception as e:
        return {'sembol': symbol, 'status': 'FAIL',
                'reason': f'build_sell_v2_dna hatası: {str(e)[:150]}'}

    dna = _json_safe(dna)
    dna['_bar_count'] = len(df)

    if dna.get('status') in ('OK', 'ZAYIF'):
        save_sell_v2_dna(symbol, dna, ttl_days=7)

    return dna


# ── ENDPOINT 2: v2 sinyal listesi (BUGÜN) ───────────────────────────────
@app.get("/sell_v2_today/{symbol}")
def sell_v2_today_endpoint(symbol: str, lookback_days: int = Query(15, ge=5, le=60)):
    """
    Bir hisse için son N gündeki v2 sinyallerini listeler.
    Her sinyal için strength (1=ZAYIF, 3=GUCLU, 4=KESIN) ve detay.
    """
    symbol = symbol.upper().replace('.IS', '').strip()
    df = fetch_ohlc(symbol, period="2y")
    if df is None or len(df) < 100:
        return {'sembol': symbol, 'hata': 'Yetersiz veri'}

    sigs = detect_v2_sell_signals(df)
    
    # Son lookback_days bar
    n = min(lookback_days, len(df))
    recent_sigs = sigs.tail(n)
    recent_close = df['close'].tail(n)
    recent_dates = df.index[-n:]
    
    signals_list = []
    for i, (date, row) in enumerate(zip(recent_dates, recent_sigs.itertuples())):
        if row.signal_strength >= 1:
            strength_label = {1: 'ZAYIF', 3: 'GUCLU', 4: 'KESIN'}.get(row.signal_strength, 'NOTR')
            signals_list.append({
                'tarih': str(date.date()),
                'fiyat': float(recent_close.iloc[i]),
                'guc': int(row.signal_strength),
                'guc_label': strength_label,
                'pre_peak_count': int(row.pre_peak_count),
                'climax_count': int(row.climax_count)
            })
    
    return {
        'sembol': symbol,
        'lookback_days': lookback_days,
        'sinyal_sayisi': len(signals_list),
        'sinyaller': signals_list,
        'son_fiyat': float(df['close'].iloc[-1]),
        'son_tarih': str(df.index[-1].date())
    }


# ── ENDPOINT 3: Tüm v2 DNA'ları listele ─────────────────────────────────
@app.get("/sell_v2_list")
def sell_v2_list_endpoint(min_quality: float = Query(0.0, ge=0, le=100)):
    summaries = list_sell_v2_dna()
    if min_quality > 0:
        summaries = [s for s in summaries if (s.get('quality') or 0) >= min_quality]
    return {
        'side': 'SELL_V2',
        'toplam': len(summaries),
        'min_quality': min_quality,
        'kayitlar': summaries
    }


# ── ENDPOINT 4: Storage durumu ──────────────────────────────────────────
@app.get("/sell_v2_storage")
def sell_v2_storage_endpoint():
    return sell_v2_storage_info()


# ── ENDPOINT 5: BUGÜN GUCLU sinyal veren tüm hisseler (toplu tara) ──────
@app.get("/sell_v2_scan_today")
def sell_v2_scan_today_endpoint(
    min_strength: int = Query(3, ge=1, le=4,
                               description="3=GUCLU, 4=KESIN"),
    lookback_days: int = Query(3, ge=1, le=7,
                                description="Son N günde sinyal verenler"),
    max_symbols: int = Query(50, ge=10, le=200),
    force: bool = Query(False)
):
    """
    Tüm BIST sembollerini tarayıp BUGÜN (son N günde) GUCLU/KESIN
    v2 SAT sinyali veren hisseleri listeler.
    """
    global SELL_V2_TODAY_CACHE
    cache_key = f"{min_strength}_{lookback_days}_{max_symbols}"
    if not force and SELL_V2_TODAY_CACHE and \
       SELL_V2_TODAY_CACHE.get('key') == cache_key and \
       (time.time() - SELL_V2_TODAY_CACHE['t']) < SELL_V2_TODAY_TTL:
        return SELL_V2_TODAY_CACHE['data']

    t0 = time.time()
    symbols = get_all()[:max_symbols]
    results = []
    failed = []

    def worker(sym):
        try:
            df = fetch_ohlc(sym, period="2y")
            if df is None or len(df) < 100:
                return None
            sigs = detect_v2_sell_signals(df)
            recent = sigs.tail(lookback_days)
            
            # Son N bar içinde min_strength'i geçen sinyal var mı?
            triggers = recent[recent['signal_strength'] >= min_strength]
            if len(triggers) == 0:
                return None
            
            last_trigger = triggers.iloc[-1]
            last_idx = triggers.index[-1]
            bars_ago = len(df) - 1 - df.index.get_loc(last_idx)
            
            return {
                'sembol': sym,
                'son_fiyat': float(df['close'].iloc[-1]),
                'sinyal_fiyat': float(df['close'].loc[last_idx]),
                'sinyal_tarih': str(last_idx.date()),
                'bars_ago': int(bars_ago),
                'guc': int(last_trigger['signal_strength']),
                'pre_peak': int(last_trigger['pre_peak_count']),
                'climax': int(last_trigger['climax_count'])
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(worker, s): s for s in symbols}
        for fut in as_completed(futures, timeout=300):
            try:
                r = fut.result(timeout=15)
                if r is not None:
                    results.append(r)
                else:
                    failed.append(futures[fut])
            except Exception:
                failed.append(futures[fut])

    # Strength + bars_ago'ya göre sırala (en taze sinyal önce)
    results.sort(key=lambda x: (-x['guc'], x['bars_ago']))

    payload = {
        'side': 'SELL_V2',
        'taranan': len(symbols),
        'sinyal_veren': len(results),
        'min_strength': min_strength,
        'lookback_days': lookback_days,
        'sure_ms': int((time.time() - t0) * 1000),
        'sonuclar': results
    }
    payload = _json_safe(payload)
    SELL_V2_TODAY_CACHE = {'t': time.time(), 'key': cache_key, 'data': payload}
    return payload
