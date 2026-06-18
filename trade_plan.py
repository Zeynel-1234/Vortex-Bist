"""
═══════════════════════════════════════════════════════════════
trade_plan.py — Faz 3: ATR İŞLEM PLANI  v1.0
───────────────────────────────────────────────────────────────
BİLİMSEL TEMEL:
  • Volatilite/ATR-bazlı stop + risk-bazlı pozisyon boyutu
    (volatility targeting / ATR dynamic stops literatürü). Gerçek
    hesapta kârı; kazananı bırakıp kaybedeni SABİT küçük riskle
    kesmek ve doğru boyutlandırmak yapar — giriş sinyali değil.
  • R-katları: hedefler riskin (1R) katları olarak konur; R:R
    bilinir, beklenen değer hesaplanabilir.
  • Rejim duyarlı boyut: kötü rejimde (RISK_OFF/NÖTR) pozisyon
    küçültülür (rejim çarpanı). Trend/sakin rejimde tam boyut.

NE YAPAR (stateless — durum tutmaz, kalıcılıktan bağımsız):
  Bir hisse için yfinance'ten günlük ATR(14) + fiyat çeker, şunu üretir:
    giriş, ATR-stop, stop mesafesi %, hedefler (1R/2R/3R), her hedefin
    R:R'si, ve "X% risk + Y sermaye" için önerilen lot/maliyet.
  İstenirse /ogren/regime'i okuyup boyutu rejime göre ölçekler.

ENDPOINT:
  /plan/{symbol}?risk=1&capital=100000&atr_mult=1.5&targets=3&use_regime=true

KURULUM (main.py'a 2 satır):
    from trade_plan import install_trade_plan
    install_trade_plan(app)
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
import json
import math

import numpy as np
import pandas as pd

try:
    import requests
except Exception:
    requests = None
try:
    import yfinance as yf
except Exception:
    yf = None

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


BASE_URL    = os.environ.get("OGREN_BASE_URL", "").rstrip("/")
ATR_LEN     = 14
DEF_RISK    = 1.0          # hesabın % kaçı riske atılır (işlem başına)
DEF_CAPITAL = 100_000.0    # TL
DEF_ATR_MULT = 1.5         # stop = giriş - atr_mult*ATR
DEF_TARGETS = 3            # kaç R-katı hedef
REGIME_MULT = {"RISK_ON": 1.0, "NOTR": 0.55, "RISK_OFF": 0.15}


def _self_base():
    if BASE_URL:
        return BASE_URL
    return "http://127.0.0.1:" + str(os.environ.get("PORT", "10000"))


def _get_json(url, timeout=60):
    try:
        if requests is not None:
            r = requests.get(url, timeout=timeout)
            return r.json() if 200 <= r.status_code < 300 else None
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "plan/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _wilder_atr(high, low, close, length=ATR_LEN):
    pc = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - pc).abs(), (low - pc).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False).mean()


def build_plan(entry, atr, *, risk_pct=DEF_RISK, capital=DEF_CAPITAL,
               atr_mult=DEF_ATR_MULT, n_targets=DEF_TARGETS,
               regime=None) -> dict:
    """Saf hesap (test edilebilir). Giriş + ATR'den tam işlem planı üretir."""
    if entry is None or entry <= 0 or atr is None or atr <= 0:
        return {"hata": "geçersiz giriş/ATR"}
    n_targets = max(1, min(int(n_targets), 5))

    stop = entry - atr_mult * atr
    if stop <= 0:
        return {"hata": "stop sıfır/negatif (ATR fiyata göre çok büyük)"}
    risk_per_share = entry - stop                      # 1R (TL/lot)
    stop_dist_pct = risk_per_share / entry * 100.0

    # Risk-bazlı boyut: hesabın risk_pct kadarını 1R'ye böl
    risk_amount = capital * (risk_pct / 100.0)
    raw_shares = risk_amount / risk_per_share if risk_per_share > 0 else 0

    # Rejim çarpanı (kötü rejimde küçült)
    mult = 1.0
    if regime:
        mult = REGIME_MULT.get(regime, 0.55)
    shares = math.floor(raw_shares * mult)

    # Sermaye sınırı: pozisyon değeri sermayeyi aşamaz
    capped = False
    if shares * entry > capital:
        shares = math.floor(capital / entry)
        capped = True
    shares = max(0, shares)

    position_value = shares * entry
    actual_risk = shares * risk_per_share
    actual_risk_pct = (actual_risk / capital * 100.0) if capital > 0 else 0

    targets = []
    for k in range(1, n_targets + 1):
        tprice = entry + k * risk_per_share            # k-R hedefi
        gain = shares * k * risk_per_share
        targets.append({
            "R": k,
            "fiyat": round(tprice, 2),
            "kazanc_TL": round(gain, 0),
            "getiri_pct": round((tprice / entry - 1) * 100, 2),
            "risk_reward": float(k),                   # R:R = k:1
        })

    return {
        "giris": round(entry, 2),
        "stop": round(stop, 2),
        "stop_mesafe_pct": round(stop_dist_pct, 2),
        "atr": round(atr, 4),
        "atr_mult": atr_mult,
        "1R_TL_lot": round(risk_per_share, 4),
        "rejim": regime,
        "rejim_carpani": mult,
        "risk_pct_hedef": risk_pct,
        "sermaye": capital,
        "onerilen_lot": shares,
        "pozisyon_degeri_TL": round(position_value, 0),
        "gercek_risk_TL": round(actual_risk, 0),
        "gercek_risk_pct": round(actual_risk_pct, 2),
        "sermaye_siniri_devrede": capped,
        "hedefler": targets,
        "not": "Stop = giris - %.1f×ATR. Lot = (sermaye×risk%%)/1R, rejimle ölçekli, sermayeyle sınırlı." % atr_mult,
    }


def plan_for_symbol(symbol, **kw) -> dict:
    """yfinance'ten günlük veri çekip ATR(14)+fiyat ile plan üretir."""
    symbol = symbol.upper().strip()
    if yf is None:
        return {"symbol": symbol, "hata": "yfinance yok"}
    try:
        df = yf.download(symbol + ".IS", period="4mo", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return {"symbol": symbol, "hata": "veri yok"}
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = pd.to_numeric(df["Close"], errors="coerce")
        high = pd.to_numeric(df["High"], errors="coerce")
        low = pd.to_numeric(df["Low"], errors="coerce")
        atr = _wilder_atr(high, low, close, ATR_LEN)
        entry = float(close.iloc[-1])
        atr_now = float(atr.iloc[-1])
        plan = build_plan(entry, atr_now, **kw)
        plan["symbol"] = symbol
        plan["atr_pct"] = round(atr_now / entry * 100, 2) if entry > 0 else None
        return plan
    except Exception as e:
        return {"symbol": symbol, "hata": str(e)[:120]}


# ════════════════════════════════════════════════════════════════
plan_router = APIRouter(prefix="/plan", tags=["trade-plan"])


@plan_router.get("/{symbol}")
def get_plan(symbol: str, risk: float = DEF_RISK, capital: float = DEF_CAPITAL,
             atr_mult: float = DEF_ATR_MULT, targets: int = DEF_TARGETS,
             use_regime: bool = True):
    regime = None
    if use_regime:
        r = _get_json(_self_base() + "/ogren/regime") or {}
        regime = r.get("regime")
    return plan_for_symbol(symbol, risk_pct=risk, capital=capital,
                           atr_mult=atr_mult, n_targets=targets, regime=regime)


def install_trade_plan(app) -> None:
    app.include_router(plan_router)
