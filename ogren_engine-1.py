"""
═══════════════════════════════════════════════════════════════
ogren_engine.py — ÖĞREN: Otonom Öğrenme & Rejim Motoru  v1.0
───────────────────────────────────────────────────────────────
Var olan signal_tracker'ı (snapshot + ileri-değerlendirme) bir
"BEYİN" ile sarmalar ve sistemi KENDİ KENDİNE çalışan, kendi
sonuçlarından ÖĞRENEN dürüst bir otomasyona dönüştürür.

BİLİMSEL TEMEL (literatür sentezi):
  • Kesitsel momentum / göreceli güç (Jegadeesh-Titman 1993,
    Rouwenhorst 1998 gelişen piyasalar, Asness-Moskowitz-Pedersen
    2013): geçmişin göreli kazananı gelecekte de kazanır; etki
    ilk 4-8 haftada en güçlü → kısa/orta vade.
  • Rejim filtresi: momentum/trend stratejileri SAKİN + YÜKSELEN
    piyasada kazanır, volatilite sıçrayınca çöker → düşen/çalkantılı
    rejimde alım sinyalleri kısılır.
  • Çoklu-test/aşırı-uyum (Bailey & López de Prado 2014 "Deflated
    Sharpe"; Harvey et al. t>3 eşiği): küçük örneklemli "iyi görünen"
    sinyale GÜVENME. Bu yüzden ağırlıklar shrinkage ile, yeterli
    ileriye-dönük (out-of-sample) kanıt biriktikçe güçlenir.

NE YAPAR (/ogren/cron her tetiklendiğinde, GÜNDE 1 KEZ):
  1) PİYASA REJİMİ hesaplar (XU100 trend + volatilite) → RISK_ON /
     NÖTR / RISK_OFF.  (Kapı 0 — her şeyin önünde.)
  2) Mevcut signal_tracker'ı çalıştırır (snapshot + ileri-değerlendirme).
  3) Tracker'ın KÜMÜLATİF ileri-isabet sonuçlarından her sinyale
     ADAPTİF AĞIRLIK öğrenir (shrinkage; az kanıt = az ağırlık).
  4) Hepsini GitHub Gist'e KALICI yazar (Render restart'ında kaybolmaz).

OTOMASYON (sıfır insan müdahalesi):
  cron-job.org zaten Render'ı uyutmamak için 10 dk'da bir ping atıyor.
  O ping'i (veya ikinci bir job'u) /ogren/cron adresine yönlendir.
  Endpoint idempotent: ağır işi her gün YALNIZCA BİR KEZ yapar.

KARAR KATMANI İÇİN:
  /ogren/score/{symbol} → o hissenin AKTİF sinyalleri × öğrenilmiş
  ağırlıklar × rejim çarpanı = tek bir "öğrenilmiş güven" skoru.
  Nihai Karar kutusu bunu Kapı olarak tüketebilir.

KURULUM (main.py'a 2 satır):
    from ogren_engine import ogren_router, install_ogren
    install_ogren(app)            # router + arka plan kanca
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
import json
import math
import time
import datetime as dt
import threading
import urllib.request
import urllib.parse

import numpy as np
import pandas as pd

try:
    import requests  # yfinance bağımlılığı; genelde mevcut
except Exception:
    requests = None

try:
    import yfinance as yf
except Exception:
    yf = None

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse


# ════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════
BASE_URL       = os.environ.get("OGREN_BASE_URL", "").rstrip("/")  # boşsa localhost:$PORT
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "").strip()
OGREN_GIST_ID  = os.environ.get("OGREN_GIST_ID", "").strip()
GIST_FILENAME  = "ogren_state.json"
TMP_PATH       = "/tmp/ogren_state.json"

XU100_TICKERS  = ["XU100.IS", "^XU100", "XU100"]   # sırayla denenir
REGIME_EMA_W   = 20      # haftalık EMA (≈100 günlük) — trend
REGIME_ATR_LEN = 14
REGIME_VOL_AVG = 100     # ATR%'nin uzun-dönem ortalaması (gün)

SHRINK_K       = 20      # ağırlık güveni için: trust = n/(n+K). ~20 gözlem = yarı-güven
MIN_OBS_TRUST  = 8       # bu sayının altında sinyale ~0 ağırlık (Deflated-Sharpe ruhu)

REGIME_MULT    = {"RISK_ON": 1.0, "NOTR": 0.55, "RISK_OFF": 0.15}

_lock = threading.Lock()
_state_cache = None      # bellek-içi son durum (Gist/tmp ayna)


# ════════════════════════════════════════════════════════════════
# YARDIMCI: HTTP
# ════════════════════════════════════════════════════════════════
def _self_base():
    if BASE_URL:
        return BASE_URL
    port = os.environ.get("PORT", "10000")
    return "http://127.0.0.1:" + str(port)


def _get_json(url, timeout=120):
    """Basit GET → JSON. requests varsa onu, yoksa urllib kullan."""
    try:
        if requests is not None:
            r = requests.get(url, timeout=timeout)
            if r.status_code >= 200 and r.status_code < 300:
                return r.json()
            return None
        req = urllib.request.Request(url, headers={"User-Agent": "ogren/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════
# KALICI DEPOLAMA — GitHub Gist (yedek: /tmp)
# ════════════════════════════════════════════════════════════════
def _empty_state():
    return {
        "version": "ogren-1.0",
        "last_run_date": None,
        "regime": None,
        "regime_history": [],     # [{date, regime, ...}]
        "weights": {},            # {signal: {weight, n, hit_rate, excess, trust}}
        "weights_updated": None,
        "notes": [],
    }


def _gist_headers():
    return {
        "Authorization": "token " + GITHUB_TOKEN,
        "Accept": "application/vnd.github+json",
        "User-Agent": "ogren-engine",
    }


def _gist_create(state):
    """Token var ama gist yoksa otomatik oluştur; yeni gist id'yi döndür."""
    if not (requests and GITHUB_TOKEN):
        return None
    try:
        payload = {
            "description": "Vortex-BIST ÖĞREN otonom durum (otomatik)",
            "public": False,
            "files": {GIST_FILENAME: {"content": json.dumps(state, ensure_ascii=False)}},
        }
        r = requests.post("https://api.github.com/gists",
                          headers=_gist_headers(), json=payload, timeout=30)
        if r.status_code in (200, 201):
            return r.json().get("id")
    except Exception:
        pass
    return None


def load_state():
    global _state_cache, OGREN_GIST_ID
    if _state_cache is not None:
        return _state_cache
    # 1) Gist
    if requests and GITHUB_TOKEN and OGREN_GIST_ID:
        try:
            r = requests.get("https://api.github.com/gists/" + OGREN_GIST_ID,
                             headers=_gist_headers(), timeout=30)
            if r.status_code == 200:
                files = r.json().get("files", {})
                if GIST_FILENAME in files:
                    content = files[GIST_FILENAME].get("content", "")
                    if content:
                        _state_cache = json.loads(content)
                        return _state_cache
        except Exception:
            pass
    # 2) /tmp
    try:
        if os.path.exists(TMP_PATH):
            with open(TMP_PATH, "r", encoding="utf-8") as f:
                _state_cache = json.load(f)
                return _state_cache
    except Exception:
        pass
    _state_cache = _empty_state()
    return _state_cache


def save_state(state):
    global _state_cache, OGREN_GIST_ID
    _state_cache = state
    # /tmp her zaman (hızlı yedek)
    try:
        with open(TMP_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass
    # Gist (kalıcı)
    if requests and GITHUB_TOKEN:
        if not OGREN_GIST_ID:
            new_id = _gist_create(state)
            if new_id:
                OGREN_GIST_ID = new_id
                state.setdefault("notes", []).append(
                    "Gist otomatik oluşturuldu: " + new_id +
                    " — bunu OGREN_GIST_ID env'ine ekle.")
            return
        try:
            payload = {"files": {GIST_FILENAME: {"content": json.dumps(state, ensure_ascii=False)}}}
            requests.patch("https://api.github.com/gists/" + OGREN_GIST_ID,
                           headers=_gist_headers(), json=payload, timeout=30)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════
# 1) PİYASA REJİMİ  (Kapı 0)
# ════════════════════════════════════════════════════════════════
def _wilder_atr(high, low, close, length):
    pc = close.shift(1)
    tr = pd.concat([(high - low).abs(),
                    (high - pc).abs(),
                    (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False).mean()


def compute_regime_from_df(df: pd.DataFrame) -> dict:
    """Günlük XU100 OHLC'den rejim sınıfı üretir.
    Trend: close > 100g EMA (≈20 haftalık).  Vol: ATR% < 100g ortalaması.
    RISK_ON = trend yukarı & sakin · RISK_OFF = trend aşağı & çalkantılı · NÖTR = diğer.
    """
    if df is None or len(df) < REGIME_VOL_AVG + 5:
        return {"regime": "NOTR", "reason": "yetersiz veri",
                "trend_up": None, "calm": None}
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    high = pd.to_numeric(df["High"], errors="coerce").reindex(close.index)
    low = pd.to_numeric(df["Low"], errors="coerce").reindex(close.index)

    ema_len = REGIME_EMA_W * 5  # haftalık→günlük yaklaşık
    ema = close.ewm(span=ema_len, adjust=False).mean()
    trend_up = bool(close.iloc[-1] > ema.iloc[-1])

    atr = _wilder_atr(high, low, close, REGIME_ATR_LEN)
    atr_pct = (atr / close).dropna()
    atr_now = float(atr_pct.iloc[-1])
    atr_avg = float(atr_pct.tail(REGIME_VOL_AVG).mean())
    calm = bool(atr_now < atr_avg)

    # eğim (momentum teyidi): close > 20g önce
    slope_up = bool(close.iloc[-1] > close.iloc[-min(len(close) - 1, 20)])

    if trend_up and calm:
        regime = "RISK_ON"
    elif (not trend_up) and (not calm):
        regime = "RISK_OFF"
    elif not trend_up:
        regime = "RISK_OFF" if not slope_up else "NOTR"
    else:
        regime = "NOTR"

    return {
        "regime": regime,
        "trend_up": trend_up,
        "calm": calm,
        "slope_up": slope_up,
        "close": round(float(close.iloc[-1]), 2),
        "ema": round(float(ema.iloc[-1]), 2),
        "atr_pct": round(atr_now * 100, 3),
        "atr_pct_avg": round(atr_avg * 100, 3),
        "multiplier": REGIME_MULT.get(regime, 0.5),
    }


def fetch_regime() -> dict:
    """XU100'ü yfinance'ten çek, rejimi hesapla. Hata olursa NÖTR."""
    if yf is None:
        return {"regime": "NOTR", "reason": "yfinance yok"}
    for tk in XU100_TICKERS:
        try:
            df = yf.download(tk, period="2y", interval="1d",
                             progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                r = compute_regime_from_df(df)
                r["ticker"] = tk
                r["asof"] = dt.date.today().isoformat()
                return r
        except Exception:
            continue
    return {"regime": "NOTR", "reason": "XU100 çekilemedi",
            "asof": dt.date.today().isoformat()}


# ════════════════════════════════════════════════════════════════
# 2) ADAPTİF AĞIRLIK ÖĞRENME  (dürüst, shrinkage)
# ════════════════════════════════════════════════════════════════
def _wilson_lower(hits, n, z=1.96):
    """Wilson skor alt sınırı — küçük örneklemde isabet oranını ihtiyatlı tahmin eder."""
    if n <= 0:
        return 0.0
    p = hits / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def _extract_signal_stats(tracker_data: dict):
    """signal_tracker /tracker/data çıktısını ESNEK okur ve
    (base_rate, {key: {n, hits, hit_rate, label, lift}}) döndürür.

    Gerçek tracker yapısı:
      {"metrics": {"baseline": float,
                   "signals": [{"key","picks","hits","hit_rate","lift",...}, ...],
                   "combos":  [{"key","picks","hits","hit_rate","lift",...}, ...]},
       ...}
    Eski/alternatif yapı da desteklenir:
      {"signals": {ad: {"n"/"picks","hits","hit_rate"}}, "base_rate": float}
    """
    if not tracker_data:
        return 0.0, {}
    metrics = tracker_data.get("metrics", tracker_data) or {}
    base = metrics.get("baseline", metrics.get("base_rate",
            tracker_data.get("base_rate", 0.0)))
    try:
        base = float(base or 0.0)
    except Exception:
        base = 0.0

    out = {}

    def _ingest(item, fallback_key=None):
        if not isinstance(item, dict):
            return
        key = item.get("key") or fallback_key
        if not key:
            return
        n = item.get("picks", item.get("n", 0))
        try:
            n = int(n or 0)
        except Exception:
            n = 0
        hits = item.get("hits", 0)
        try:
            hits = int(hits or 0)
        except Exception:
            hits = 0
        hr = item.get("hit_rate")
        if hits == 0 and hr and n > 0:
            hits = int(round(float(hr) * n))
        out[key] = {"n": n, "hits": hits,
                    "hit_rate": (float(hr) if hr is not None else None),
                    "label": item.get("label", key),
                    "lift": item.get("lift")}

    sigs = metrics.get("signals")
    combos = metrics.get("combos")
    if isinstance(sigs, list):
        for it in sigs:
            _ingest(it)
    elif isinstance(sigs, dict):
        for k, v in sigs.items():
            _ingest(v, k)
    if isinstance(combos, list):
        for it in combos:
            _ingest(it)
    elif isinstance(combos, dict):
        for k, v in combos.items():
            _ingest(v, k)

    return base, out


def compute_weights(tracker_data: dict) -> dict:
    """Tracker'ın kümülatif sinyal istatistiklerinden adaptif ağırlık üretir.

    Ağırlık mantığı (Deflated-Sharpe ruhu):
      excess = wilson_lower(hits,n) - base_rate        # şansa göre fazladan isabet
      trust  = n / (n + K)                              # küçük örneklem = düşük güven
      weight = max(0, excess) * trust                   # kanıt yoksa ~0
    Ağırlıklar 0..1'e normalize edilir. Hem tekil sinyaller hem kombinasyonlar.
    """
    base, sigs = _extract_signal_stats(tracker_data)
    if not sigs:
        return {"weights": {}, "base_rate": None,
                "note": "tracker verisi yok / yapı tanınmadı — /tracker/run birikmeli"}

    if not base:
        tot_h = sum(s["hits"] for s in sigs.values())
        tot_n = sum(s["n"] for s in sigs.values())
        base = (tot_h / tot_n) if tot_n > 0 else 0.0

    raw = {}
    detail = {}
    for name, s in sigs.items():
        n = s["n"]; hits = s["hits"]
        wl = _wilson_lower(hits, n)
        excess = wl - base
        trust = n / (n + SHRINK_K) if n > 0 else 0.0
        if n < MIN_OBS_TRUST:
            trust *= 0.25  # çok az kanıt: ekstra cezalandır
        w = max(0.0, excess) * trust
        raw[name] = w
        detail[name] = {
            "n": n, "hits": hits,
            "hit_rate": round(hits / n, 4) if n > 0 else None,
            "wilson_lower": round(wl, 4),
            "excess_vs_base": round(excess, 4),
            "trust": round(trust, 4),
            "weight_raw": round(w, 6),
        }

    total = sum(raw.values())
    for name in detail:
        detail[name]["weight"] = round(raw[name] / total, 4) if total > 0 else 0.0

    return {
        "weights": detail,
        "base_rate": round(base, 4),
        "updated": dt.datetime.now().isoformat(timespec="seconds"),
        "method": "wilson_lower - base, shrunk by n/(n+%d), floor at %d obs" % (SHRINK_K, MIN_OBS_TRUST),
    }


# ════════════════════════════════════════════════════════════════
# 3) BİLEŞİK SKOR  (karar katmanı için)
# ════════════════════════════════════════════════════════════════
def composite_score(active_signals, weights_detail, regime) -> dict:
    """active_signals: o hissede AKTİF olan sinyal adları listesi.
    weights_detail: compute_weights()['weights'].
    regime: 'RISK_ON' / 'NOTR' / 'RISK_OFF'.
    """
    base_conf = 0.0
    contrib = {}
    for sig in active_signals:
        w = (weights_detail.get(sig, {}) or {}).get("weight", 0.0)
        base_conf += w
        contrib[sig] = w
    mult = REGIME_MULT.get(regime, 0.5)
    final = base_conf * mult
    return {
        "active_signals": active_signals,
        "raw_confidence": round(base_conf, 4),
        "regime": regime,
        "regime_multiplier": mult,
        "final_score": round(final, 4),
        "contributions": contrib,
    }


# ════════════════════════════════════════════════════════════════
# 4) CANLI SİNYAL OKUMA (kendi API'lerinden)
# ════════════════════════════════════════════════════════════════
def _active_signals_for_symbol(sym, scan_row, crossover_syms):
    """Bir hissenin AKTİF sinyalleri — tracker anahtarlarıyla AYNI isimlerle
    (nvs, bkm, gs, gunluk, kesisim) + qualified kombinasyonlar (nvs+kesisim,
    min2, min3, hepsi-5 …). Böylece compute_weights ağırlıkları eşleşir.

    NOT: üyelik eşikleri yaklaşıktır (tracker top-20 mantığını birebir
    bilmiyoruz); skor Nihai Karar'a bağlanmadan önce (Faz 4) kalibre edilecek.
    """
    base = []
    if scan_row:
        lbl = (scan_row.get("nvs_label") or "").upper()
        if "AL" in lbl:
            base.append("nvs")
        if (scan_row.get("bkm") or 0) >= 70:
            base.append("bkm")
        if (scan_row.get("guven_skoru") or 0) >= 45:
            base.append("gs")
        if (scan_row.get("gunluk_degisim") or 0) > 0:
            base.append("gunluk")
    if sym in crossover_syms:
        base.append("kesisim")

    active = list(base)
    s = set(base)
    # qualified kombinasyonlar (tracker key formatına uygun)
    pairs = ["nvs+bkm", "nvs+kesisim", "nvs+gunluk", "gunluk+kesisim", "nvs+bkm+gs"]
    for combo in pairs:
        parts = combo.split("+")
        if all(p in s for p in parts):
            active.append(combo)
    if len(s) >= 5:
        active.append("hepsi-5")
    if len(s) >= 3:
        active.append("min3")
    if len(s) >= 2:
        active.append("min2")
    return active


# ════════════════════════════════════════════════════════════════
# OTONOM ÇALIŞMA DÖNGÜSÜ
# ════════════════════════════════════════════════════════════════
def _today_str():
    return dt.date.today().isoformat()


def _is_trading_day():
    # BIST hafta içi (Pzt-Cum). Resmi tatil takvimi yok; hafta sonu elenir.
    return dt.date.today().weekday() < 5


def run_daily_cycle(force=False) -> dict:
    """Günlük otonom döngü — idempotent. Ağır iş (tracker) tetiklenir."""
    with _lock:
        state = load_state()
        today = _today_str()
        already = (state.get("last_run_date") == today)
        if already and not force:
            return {"ran": False, "reason": "bugün zaten çalıştı",
                    "last_run_date": today, "regime": state.get("regime")}

        # 1) REJİM
        regime = fetch_regime()
        state["regime"] = regime
        hist = state.get("regime_history", [])
        hist.append({"date": today, "regime": regime.get("regime"),
                     "atr_pct": regime.get("atr_pct")})
        state["regime_history"] = hist[-180:]   # ~6 ay

        # 2) TRACKER (snapshot + ileri-değerlendirme) — kendi API'sinden tetikle
        base = _self_base()
        tracker_started = False
        try:
            _get_json(base + "/tracker/run", timeout=30)  # arka planda başlar
            tracker_started = True
        except Exception:
            pass

        state["last_run_date"] = today
        save_state(state)

    # 3) Ağırlıkları güncelle — tracker'ın bitmesini bekleyip ayrı yap
    def _post_update():
        time.sleep(15)  # tracker'ın snapshot+eval'i için kısa bekleme
        try:
            data = _get_json(_self_base() + "/tracker/data", timeout=120)
            if data:
                w = compute_weights(data)
                with _lock:
                    st = load_state()
                    st["weights"] = w.get("weights", {})
                    st["base_rate"] = w.get("base_rate")
                    st["weights_updated"] = w.get("updated")
                    save_state(st)
        except Exception:
            pass

    threading.Thread(target=_post_update, daemon=True).start()

    return {"ran": True, "date": _today_str(),
            "regime": regime, "tracker_started": tracker_started}


# ════════════════════════════════════════════════════════════════
# ROUTER
# ════════════════════════════════════════════════════════════════
ogren_router = APIRouter(prefix="/ogren", tags=["ogren-otonom"])


@ogren_router.get("/cron")
def cron(background: BackgroundTasks):
    """cron-job.org bunu 10 dk'da bir çağırır; ağır iş günde 1 kez yapılır."""
    state = load_state()
    if state.get("last_run_date") == _today_str():
        return {"status": "skip", "reason": "bugün işlendi",
                "regime": (state.get("regime") or {}).get("regime"),
                "last_run_date": state.get("last_run_date")}
    if not _is_trading_day():
        return {"status": "skip", "reason": "hafta sonu"}
    background.add_task(run_daily_cycle, False)
    return {"status": "started", "date": _today_str()}


@ogren_router.get("/run")
def run_now(background: BackgroundTasks):
    """Manuel zorla çalıştır (test/ilk kurulum)."""
    background.add_task(run_daily_cycle, True)
    return {"status": "started (force)", "date": _today_str()}


@ogren_router.get("/regime")
def get_regime(refresh: bool = False):
    state = load_state()
    if refresh or not state.get("regime"):
        r = fetch_regime()
        with _lock:
            st = load_state(); st["regime"] = r; save_state(st)
        return r
    return state.get("regime")


@ogren_router.get("/weights")
def get_weights():
    state = load_state()
    return {"weights": state.get("weights", {}),
            "base_rate": state.get("base_rate"),
            "updated": state.get("weights_updated")}


@ogren_router.get("/status")
def status():
    state = load_state()
    reg = state.get("regime") or {}
    w = state.get("weights", {})
    top = sorted(w.items(), key=lambda kv: kv[1].get("weight", 0), reverse=True)
    return {
        "last_run_date": state.get("last_run_date"),
        "regime": reg.get("regime"),
        "regime_detail": reg,
        "base_rate": state.get("base_rate"),
        "weights_updated": state.get("weights_updated"),
        "top_signals": [{"signal": k, "weight": v.get("weight"),
                         "hit_rate": v.get("hit_rate"), "n": v.get("n")}
                        for k, v in top[:10]],
        "gist": bool(GITHUB_TOKEN),
        "notes": state.get("notes", [])[-5:],
    }


@ogren_router.get("/score/{symbol}")
def score_symbol(symbol: str):
    """Bir hissenin öğrenilmiş bileşik güven skoru (Nihai Karar için)."""
    symbol = symbol.upper().strip()
    state = load_state()
    weights = state.get("weights", {})
    regime = (state.get("regime") or {}).get("regime", "NOTR")
    base = _self_base()

    scan = _get_json(base + "/scan?limit=700", timeout=120) or {}
    rows = scan.get("results") or scan.get("data") or scan if isinstance(scan, list) else scan.get("results", [])
    if isinstance(scan, dict) and not rows:
        rows = scan.get("rows", []) or scan.get("results", [])
    row = None
    for r in (rows or []):
        if (r.get("sembol") or r.get("symbol") or "").upper() == symbol:
            row = r; break

    xo = _get_json(base + "/crossover/api/scan", timeout=120) or {}
    xs = set()
    for r in (xo.get("results") or []):
        xs.add((r.get("symbol") or "").upper())

    active = _active_signals_for_symbol(symbol, row, xs)
    return composite_score(active, weights, regime)


@ogren_router.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    state = load_state()
    reg = state.get("regime") or {}
    regime = reg.get("regime", "—")
    color = {"RISK_ON": "#7ed321", "NOTR": "#f5c542", "RISK_OFF": "#ff5a5a"}.get(regime, "#888")
    w = state.get("weights", {})
    rows = sorted(w.items(), key=lambda kv: kv[1].get("weight", 0), reverse=True)
    trows = ""
    for k, v in rows:
        bar = int(round((v.get("weight", 0) or 0) * 100))
        trows += (
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td><div style='background:#1a2a1a;border-radius:4px;height:14px;width:120px'>"
            "<div style='background:#7ed321;height:14px;border-radius:4px;width:%d%%'></div></div> %.3f</td></tr>"
            % (k, v.get("n", "—"),
               ("%.1f%%" % (v.get("hit_rate", 0) * 100)) if v.get("hit_rate") is not None else "—",
               ("%.3f" % v.get("excess_vs_base", 0)) if v.get("excess_vs_base") is not None else "—",
               bar, v.get("weight", 0)))
    html = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>ÖĞREN</title><style>
body{background:#050505;color:#ddd;font:14px system-ui,sans-serif;margin:0;padding:16px}
h1{color:#7ed321;font-size:18px}.card{background:#0a0a0a;border:1px solid #1f1f1f;border-radius:10px;padding:14px;margin:10px 0}
.reg{font:700 22px system-ui;color:%s}table{width:100%%;border-collapse:collapse;font-size:13px}
td,th{padding:6px 8px;border-bottom:1px solid #161616;text-align:left}th{color:#7ed321}
.muted{color:#777;font-size:12px}.btn{display:inline-block;background:#1a2a1a;color:#7ed321;border:1px solid #7ed321;
padding:8px 14px;border-radius:8px;text-decoration:none;margin-right:8px}
</style></head><body>
<h1>🧠 ÖĞREN · Otonom Öğrenme & Rejim Motoru</h1>
<div class=card><div class=muted>PİYASA REJİMİ (Kapı 0)</div>
<div class=reg>%s</div>
<div class=muted>XU100 %s · close %s / EMA %s · ATR%% %s (ort %s) · çarpan %s</div>
<div class=muted>son çalışma: %s · ağırlık güncelleme: %s</div></div>
<div class=card><div class=muted>ÖĞRENİLMİŞ SİNYAL AĞIRLIKLARI (ileriye-dönük isabete göre, shrinkage)</div>
<table><tr><th>Sinyal</th><th>n</th><th>İsabet</th><th>Fazla(base)</th><th>Ağırlık</th></tr>%s</table>
<div class=muted>base oran: %s · yöntem: Wilson alt sınır − base, n/(n+%d) ile küçültme</div></div>
<div class=card>
<a class=btn href='/ogren/run'>▶ ŞİMDİ ÇALIŞTIR</a>
<a class=btn href='/ogren/status'>DURUM (JSON)</a>
<a class=btn href='/ogren/regime?refresh=true'>REJİMİ YENİLE</a>
<div class=muted style='margin-top:10px'>Otomasyon: cron-job.org → <b>%s/ogren/cron</b> (10 dk'da bir; günde 1 kez işler)</div>
</div></body></html>""" % (
        color, regime,
        ("yukarı" if reg.get("trend_up") else "aşağı") + ("/sakin" if reg.get("calm") else "/çalkantılı"),
        reg.get("close", "—"), reg.get("ema", "—"), reg.get("atr_pct", "—"),
        reg.get("atr_pct_avg", "—"), reg.get("multiplier", "—"),
        state.get("last_run_date", "—"), state.get("weights_updated", "—"),
        trows or "<tr><td colspan=5 class=muted>Henüz veri yok — /tracker/run birikince dolacak</td></tr>",
        state.get("base_rate", "—"), SHRINK_K, _self_base())
    return HTMLResponse(html)


# ════════════════════════════════════════════════════════════════
def install_ogren(app) -> None:
    """main.py'a: from ogren_engine import install_ogren; install_ogren(app)"""
    app.include_router(ogren_router)
