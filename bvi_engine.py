"""
═══════════════════════════════════════════════════════════════
bvi_engine.py — KIRILIM DOĞRULAMA İNDEKSİ (Breakout Verification Index) v1.0
───────────────────────────────────────────────────────────────
SORUN: Haftalık Süpertrend>EMA kesişimi veren hisselerden hangisi BUGÜN
tavan/agresif yükseliş yapar, hangisi yatay/tuzak kalır?

KÖK BULGU (BAKAB tavan vs KNFRT cılız, aynı an):
  KNFRT'nin KALİTESİ daha YÜKSEK (LAB DNA 67.5>56.4, Fraktal eğim
  +6.72%>+3.58%, LSMA fark +46.2%>+8.7%) AMA yine de kaybetti.
  Çünkü kalite TOPLAMSAL değil; HACİM ve MOMENTUM birer KAPI (çarpan).
  KNFRT: hacim 0.93× (kapı~0.21) + r3 −3.26% (kapı~0.07) → kalite çarpılıp sıfırlandı.

MODEL — ÇARPIMSAL (gated), toplamsal DEĞİL:
  BVI = TemelKalite × HacimKapısı × MomentumKapısı × (1 − UzamaCezası)

  • TemelKalite : Güven (BKM/NVS) + Fraktal eğimi  → potansiyel
  • HacimKapısı : V = son5g/son20g hacim; lojistik (merkez 1.2)
  • MomentumKapısı: r3 = son 3 bar getirisi; lojistik (merkez +1%)
  • UzamaCezası : LSMA25/LSMA200 sapması aşırıysa (mean-reversion riski)

Tek bir kapı ~0 ise BVI çöker (kalite ne olursa olsun). KNFRT'yi bu açıklar.

ÇIKTI: 0–100 BVI + kapı kırılımı + karar.
  ≥55 🚀 KIRILIM DOĞRULANDI · 30–55 ⚠️ ŞÜPHELİ · <30 ❌ TUZAK/YATAY

ENDPOINTLER:
  /bvi/{symbol}                      → HTML panel
  /bvi/{symbol}?bkm=100&nvs=78       → sistemin gerçek BKM/NVS'siyle (kesin)
  /bvi/{symbol}?fmt=json
  /bvi/compare?symbols=BAKAB,KNFRT[&bkm=..&nvs=..]

NOT: BKM/NVS verilmezse trend-dizilim vekiliyle tahmin edilir. Kesin sonuç
için KARAR ekranındaki BKM/NVS değerlerini parametre olarak geç.

KURULUM: alpha_tab_integration.install_alpha_tab() içinden register edilir.
GERİ ALMA: bu dosyayı sil + alpha_tab_integration eski halini yükle.
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
import json
import math

try:
    import numpy as np
except Exception:
    np = None
try:
    import pandas as pd
except Exception:
    pd = None
try:
    import yfinance as yf
except Exception:
    yf = None

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse


# ── KONFİG ──────────────────────────────────────────────────────
VOL_FAST = 5       # hızlı hacim penceresi (gün)
VOL_SLOW = 20      # yavaş hacim penceresi (gün)
MOM_BARS = 3       # r3 momentum (son 3 bar)
SLOPE_BARS = 10    # Fraktal eğim penceresi (gün)
LSMA_FAST = 25     # Fraktal kısa LSMA
LSMA_SLOW = 200    # Fraktal uzun LSMA
PERIOD = "2y"      # LSMA200 için yeterli günlük geçmiş

# Kapı parametreleri (kalibre edilebilir)
VGATE_CENTER = 1.2;  VGATE_K = 5.0     # hacim kapısı lojistik
MGATE_CENTER = 1.0;  MGATE_K = 0.6     # momentum kapısı lojistik (r3 %)
EXT_LO = 15.0; EXT_HI = 50.0; EXT_MAX = 0.5   # LSMA sapma cezası


def _self_port():
    return str(os.environ.get("PORT", "10000"))


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _lin(x, x0, x1, y0=0.0, y1=100.0):
    if x1 == x0:
        return y0
    t = (x - x0) / (x1 - x0)
    return _clamp(y0 + t * (y1 - y0), min(y0, y1), max(y0, y1))


def _logistic(x, center, k):
    try:
        return 1.0 / (1.0 + math.exp(-k * (x - center)))
    except OverflowError:
        return 0.0 if x < center else 1.0


def _flatten(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _fetch_daily(symbol):
    if yf is None:
        return None
    try:
        df = yf.download(symbol + ".IS", period=PERIOD, interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        df = _flatten(df).dropna(subset=["Close"])
        return df if len(df) >= 40 else None
    except Exception:
        return None


def _lsma_value(close, length, offset=0):
    """Lineer regresyon hareketli ortalama (LSMA) — pencere sonundaki uç değer."""
    end = len(close) - offset
    if end < length:
        return None
    seg = close.iloc[end - length:end].values.astype(float)
    x = np.arange(length)
    a, b = np.polyfit(x, seg, 1)       # eğim a, kesişim b
    return a * (length - 1) + b        # son noktadaki regresyon değeri


# ════════════════════════════════════════════════════════════════
# ANA HESAP
# ════════════════════════════════════════════════════════════════
def score_bvi(symbol, bkm=None, nvs=None):
    symbol = symbol.upper().strip()
    if yf is None or pd is None or np is None:
        return {"symbol": symbol, "hata": "yfinance/pandas/numpy yok"}
    df = _fetch_daily(symbol)
    if df is None:
        return {"symbol": symbol, "hata": "günlük veri yok / yetersiz"}

    close = pd.to_numeric(df["Close"], errors="coerce")
    volume = pd.to_numeric(df["Volume"], errors="coerce") if "Volume" in df.columns \
        else pd.Series([0] * len(df))

    # ── DEĞİŞKENLER ────────────────────────────────────────────
    # V: hacim çarpanı (son5g / son20g)
    v_fast = float(volume.iloc[-VOL_FAST:].mean())
    v_slow = float(volume.iloc[-VOL_SLOW:].mean())
    V = v_fast / v_slow if v_slow > 0 else 0.0

    # M: kısa vade momentum (r3 = son 3 bar getirisi %)
    if len(close) > MOM_BARS:
        M = (float(close.iloc[-1]) / float(close.iloc[-1 - MOM_BARS]) - 1.0) * 100.0
    else:
        M = 0.0

    # S: Fraktal eğimi (LSMA25'in son 10g % değişimi)
    lsma25_now = _lsma_value(close, LSMA_FAST, 0)
    lsma25_prev = _lsma_value(close, LSMA_FAST, SLOPE_BARS)
    if lsma25_now and lsma25_prev and lsma25_prev != 0:
        S = (lsma25_now / lsma25_prev - 1.0) * 100.0
    else:
        S = 0.0

    # Sapma: LSMA25 vs LSMA200 (% fark) → aşırı uzama
    lsma200_now = _lsma_value(close, LSMA_SLOW, 0)
    if lsma25_now and lsma200_now and lsma200_now != 0:
        divergence = (lsma25_now / lsma200_now - 1.0) * 100.0
    else:
        divergence = 0.0

    # ── GÜVEN (C) ──────────────────────────────────────────────
    if bkm is not None and nvs is not None:
        C = 0.55 * float(bkm) + 0.45 * float(nvs)
        c_kaynak = "sistem (BKM=%s, NVS=%s)" % (bkm, nvs)
    else:
        # Vekil: trend dizilimi (EMA20>50>200) + son eğim
        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1] if len(close) >= 200 else ema50
        c_now = float(close.iloc[-1])
        stack = (c_now > ema20) + (ema20 > ema50) + (ema50 > ema200)
        C = _clamp(40 + stack * 18 + _lin(S, 0, 8, 0, 6), 0, 100)
        c_kaynak = "vekil (trend dizilimi) — kesin için ?bkm=&nvs= geç"

    # ── KAPILAR ─────────────────────────────────────────────────
    Vgate = _logistic(V, VGATE_CENTER, VGATE_K)
    Mgate = _logistic(M, MGATE_CENTER, MGATE_K)
    ExtPen = _clamp((divergence - EXT_LO) / (EXT_HI - EXT_LO) * EXT_MAX, 0, EXT_MAX)

    Sscore = _lin(S, 0, 8)
    base_quality = _clamp(0.65 * C + 0.35 * Sscore, 0, 100)

    BVI = _clamp(base_quality * Vgate * Mgate * (1.0 - ExtPen), 0, 100)

    if BVI >= 55:
        karar = "🚀 KIRILIM DOĞRULANDI — tavan/agresif aday"; renk = "#22c55e"
    elif BVI >= 30:
        karar = "⚠️ ŞÜPHELİ — zayıf onay, küçük/izle"; renk = "#e8b84b"
    else:
        karar = "❌ TUZAK / YATAY — PAS"; renk = "#ef4444"

    return {
        "symbol": symbol,
        "bvi": round(BVI, 1),
        "karar": karar,
        "renk": renk,
        "fiyat": round(float(close.iloc[-1]), 2),
        "degiskenler": {
            "hacim_carpani_V": round(V, 2),
            "momentum_r3_%": round(M, 2),
            "fraktal_egim_S_%": round(S, 2),
            "lsma_sapma_%": round(divergence, 1),
            "guven_C": round(C, 1),
        },
        "kapilar": {
            "TemelKalite": round(base_quality, 1),
            "HacimKapisi": round(Vgate, 3),
            "MomentumKapisi": round(Mgate, 3),
            "UzamaCezasi": round(ExtPen, 3),
        },
        "guven_kaynak": c_kaynak,
        "not": "BVI = TemelKalite × HacimKapısı × MomentumKapısı × (1−UzamaCezası). Tek kapı ~0 ise BVI çöker. Olasılıksal; garanti değil.",
    }


# ════════════════════════════════════════════════════════════════
# HTML
# ════════════════════════════════════════════════════════════════
def _bar(x, color):
    w = _clamp(x, 0, 100)
    return ("<div style='background:#0b0e18;border-radius:4px;height:8px;overflow:hidden'>"
            "<div style='width:%.0f%%;height:8px;background:%s'></div></div>") % (w, color)


def _render_html(d):
    if d.get("hata"):
        return ("<html><body style='background:#0a0d14;color:#e7eefc;font-family:monospace;padding:20px'>"
                "<h2>%s</h2><p style='color:#ef4444'>Hata: %s</p>"
                "<p style='color:#4b5e78'>Örnek: /bvi/BAKAB?bkm=100&nvs=78</p></body></html>") \
            % (d.get("symbol", "?"), d["hata"])
    g = d["degiskenler"]; k = d["kapilar"]
    def gate_row(ad, val, txt):
        col = "#22c55e" if val >= 0.7 else "#e8b84b" if val >= 0.35 else "#ef4444"
        return ("<div style='margin:8px 0'><div style='display:flex;justify-content:space-between;font-size:12px'>"
                "<span style='color:#c0cfe0'>%s</span><span style='color:%s;font-weight:700'>×%.2f</span></div>%s"
                "<div style='font-size:10px;color:#4b5e78;margin-top:2px'>%s</div></div>") % (
            ad, col, val, _bar(val * 100, col), txt)
    gates = (gate_row("🔊 Hacim Kapısı", k["HacimKapisi"], "V = %.2f× (son5g/son20g)" % g["hacim_carpani_V"]) +
             gate_row("⚡ Momentum Kapısı", k["MomentumKapisi"], "r3 = %%%.2f (son 3 bar)" % g["momentum_r3_%"]))
    extcol = "#ef4444" if k["UzamaCezasi"] >= 0.25 else "#4b5e78"
    return ("""<html><head><meta name=viewport content='width=device-width,initial-scale=1'>
<title>BVI · %s</title></head>
<body style='background:#0a0d14;color:#e7eefc;font-family:monospace;padding:16px;max-width:680px;margin:auto'>
<div style='display:flex;justify-content:space-between;align-items:center'>
<h2 style='margin:0'>%s</h2><span style='color:#4b5e78'>₺%s</span></div>
<div style='text-align:center;margin:14px 0;padding:16px;border:2px solid %s;border-radius:12px'>
<div style='font-size:11px;color:#4b5e78;letter-spacing:2px'>KIRILIM DOĞRULAMA İNDEKSİ (BVI)</div>
<div style='font-size:54px;font-weight:800;color:%s;line-height:1'>%s</div>
<div style='font-size:15px;font-weight:700;color:%s'>%s</div></div>
<div style='font-size:11px;color:#7a9ab8;margin-bottom:4px'>ÇARPIMSAL KAPILAR (biri ~0 ise BVI çöker)</div>
<div style='text-align:center;font-size:13px;color:#9aa7bd;margin:6px 0'>
TemelKalite <b style='color:#e7eefc'>%.0f</b> × Hacim <b style='color:#e7eefc'>%.2f</b> × Momentum <b style='color:#e7eefc'>%.2f</b> × (1−Uzama <b style='color:%s'>%.2f</b>) = <b style='color:%s'>%s</b></div>
%s
<div style='margin:8px 0;font-size:11px;color:%s'>Uzama cezası: LSMA sapma %%%s → ×%.2f</div>
<div style='margin-top:12px;font-size:10px;color:#4b5e78'>Fraktal eğim S=%%%s · Güven C=%s · kaynak: %s</div>
<div style='margin-top:8px;font-size:10px;color:#4b5e78'>%s</div>
</body></html>""") % (d["symbol"], d["symbol"], d["fiyat"], d["renk"], d["renk"],
                       d["bvi"], d["renk"], d["karar"],
                       k["TemelKalite"], k["HacimKapisi"], k["MomentumKapisi"],
                       extcol, k["UzamaCezasi"], d["renk"], d["bvi"], gates,
                       extcol, g["lsma_sapma_%"], (1 - k["UzamaCezasi"]),
                       g["fraktal_egim_S_%"], g["guven_C"], d["guven_kaynak"], d["not"])


def _render_compare(items):
    head = ("<tr><th style='text-align:left;padding:6px'>Hisse</th><th style='padding:6px'>BVI</th>"
            "<th style='padding:6px'>Kalite</th><th style='padding:6px'>Hacim×</th>"
            "<th style='padding:6px'>r3%</th><th style='padding:6px'>HacKapı</th>"
            "<th style='padding:6px'>MomKapı</th><th style='text-align:left;padding:6px'>Karar</th></tr>")
    body = ""
    for d in items:
        if d.get("hata"):
            body += "<tr><td style='padding:6px'>%s</td><td colspan=7 style='color:#ef4444;padding:6px'>%s</td></tr>" % (d.get("symbol"), d["hata"]); continue
        g = d["degiskenler"]; k = d["kapilar"]
        def cc(v, hi=62, mid=40):
            return "#22c55e" if v >= hi else "#e8b84b" if v >= mid else "#ef4444"
        body += ("<tr><td style='padding:6px;font-weight:700'>%s</td>"
                 "<td style='text-align:center;padding:6px;color:%s;font-weight:800;font-size:16px'>%s</td>"
                 "<td style='text-align:center;padding:6px'>%.0f</td>"
                 "<td style='text-align:center;padding:6px;color:%s'>%.2f</td>"
                 "<td style='text-align:center;padding:6px;color:%s'>%.1f</td>"
                 "<td style='text-align:center;padding:6px'>%.2f</td>"
                 "<td style='text-align:center;padding:6px'>%.2f</td>"
                 "<td style='padding:6px;color:%s;font-size:11px'>%s</td></tr>") % (
            d["symbol"], d["renk"], d["bvi"], k["TemelKalite"],
            cc(100 if g["hacim_carpani_V"] >= 1.5 else 0), g["hacim_carpani_V"],
            cc(100 if g["momentum_r3_%"] >= 1 else 0), g["momentum_r3_%"],
            k["HacimKapisi"], k["MomentumKapisi"], d["renk"], d["karar"])
    return ("""<html><head><meta name=viewport content='width=device-width,initial-scale=1'>
<title>BVI Karşılaştırma</title></head>
<body style='background:#0a0d14;color:#e7eefc;font-family:monospace;padding:14px'>
<h2>🚀 BVI Karşılaştırma</h2>
<div style='overflow-x:auto'><table style='border-collapse:collapse;font-size:12px;min-width:600px'>%s%s</table></div>
<p style='color:#4b5e78;font-size:11px;margin-top:12px'>BVI = Kalite × HacimKapısı × MomentumKapısı × (1−Uzama). Bir kapı ~0 → BVI çöker. Kesin BKM/NVS için ?bkm=&nvs= geç.</p>
</body></html>""") % (head, body)


# ════════════════════════════════════════════════════════════════
# ROUTER
# ════════════════════════════════════════════════════════════════
bvi_router = APIRouter(prefix="/bvi", tags=["bvi"])


@bvi_router.get("/compare", response_class=HTMLResponse)
def compare(symbols: str = "BAKAB,KNFRT", fmt: str = "html", bkm: float = None, nvs: float = None):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:10]
    items = [score_bvi(s, bkm=bkm, nvs=nvs) for s in syms]
    if fmt == "json":
        return JSONResponse(items)
    return HTMLResponse(_render_compare(items))


@bvi_router.get("/{symbol}", response_class=HTMLResponse)
def get_bvi(symbol: str, fmt: str = "html", bkm: float = None, nvs: float = None):
    d = score_bvi(symbol, bkm=bkm, nvs=nvs)
    if fmt == "json":
        return JSONResponse(d)
    return HTMLResponse(_render_html(d))


_installed = {"on": False}


def install_bvi(app) -> None:
    if _installed["on"]:
        return
    _installed["on"] = True
    app.include_router(bvi_router)


if __name__ == "__main__":
    import sys
    s = sys.argv[1] if len(sys.argv) > 1 else "BAKAB"
    print(json.dumps(score_bvi(s), ensure_ascii=False, indent=2))
