"""
═══════════════════════════════════════════════════════════════
patlama_engine.py — PATLAMA (HAREKET BÜYÜKLÜĞÜ) SKORU  v1.0
───────────────────────────────────────────────────────────────
SORUN: Supertrend>EMA "kesişimi" iki hissede de aynı şekilde oluşur,
ama biri TAVAN yapar (CELHA), diğeri cılız kalır (GSDDE). Kesişim
sadece KIVILCIM'dır; büyüklüğü taşımaz. Büyüklüğü "YAKIT" belirler.

BİLİMSEL TEMEL (hepsi haftalık OHLCV'den ölçülebilir):
  1) SIKIŞMA (squeeze)      — Bollinger BandWidth'in 52H yüzdelik dibi.
        Volatilite daralması = depolanmış enerji (TTM Squeeze fikri).
  2) HACİM (RVOL)           — kırılım haftası hacmi / 20H ort. hacim.
        Patlamalar gerçek katılımla (hacim) gelir.
  3) AÇIK GÖK (clear sky)   — kapanış / son 52H en yüksek. Yeni zirve =
        üstte satıcı yok = vakum (tavan). Direnç altı = tavan/tepe baskısı.
  4) KAPANIŞ GÜCÜ (CLV)     — mumun nereye kapandığı. Zirveye yakın =
        talep; uzun üst fitil = dağıtım/reddedilme.
  5) GÖRECELİ GÜÇ (RS)      — XU100'e göre fazla getiri (lider mi takipçi mi).
  6) TABAN SIKILIĞI (VCP)   — kırılımdan önce dar/uzun taban = yay gerilmiş.
  7) UZAMA CEZASI (EXT)     — kesişimde EMA'dan ATR cinsinden ne kadar uzak;
        çoktan uçmuşsa kovalama riski (negatif katkı).

ÇIKTI: 0–100 PATLAMA skoru + her bileşenin şeffaf katkısı + karar.
  ≥75 🚀 TAVAN ADAYI · 60-74 GÜÇLÜ · 45-59 ORTA · <45 ZAYIF

DÜRÜST SINIR: Bu skor tavanı GARANTİ etmez; beklenen-büyüklüğü
OLASILIKSAL sıralar. Ağırlıklar (W_*) makul varsayılanlardır ve senin
BIST verinden (tracker/LAB) kalibre edilmelidir.

ENDPOINTLER:
  /patlama/{symbol}                 → HTML panel (mobilde aç, gör)
  /patlama/{symbol}?fmt=json        → ham JSON
  /patlama/compare?symbols=CELHA,GSDDE  → yan yana karşılaştırma (doğrulama için)

KURULUM: alpha_tab_integration.install_alpha_tab() içinden otomatik
register edilir (main.py'ya dokunmaya gerek yok). Alternatif (main.py):
    from patlama_engine import install_patlama
    install_patlama(app)

GERİ ALMA: bu dosyayı sil + alpha_tab_integration.py eski halini yükle.
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
import json

try:
    import numpy as np
except Exception:
    np = None
try:
    import pandas as pd
except Exception:
    pd = None
try:
    import requests
except Exception:
    requests = None
try:
    import yfinance as yf
except Exception:
    yf = None

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse


# ════════════════════════════════════════════════════════════════
# KONFİG — AĞIRLIKLAR (kalibre edilebilir; toplam pozitif kısım = 1.0)
# v1.1: SANEL(tavan) vs ESCOM(cılız) dersi → "Verim (ER)" chop filtresi eklendi.
# ════════════════════════════════════════════════════════════════
W_CS    = 0.24   # Açık gök / yeni zirve (en güçlü yapısal ayraç)
W_ER    = 0.20   # Verim / trend temizliği (chop filtresi — ESCOM dersi)
W_SQ    = 0.14   # Sıkışma (depolanmış enerji)
W_RS    = 0.14   # Göreceli güç (liderlik)
W_RVOL  = 0.12   # Hacim patlaması (katılım)
W_CLV   = 0.08   # Kapanış gücü (talep vs dağıtım)
W_BASE  = 0.08   # Taban sıkılığı (VCP)
W_EXT   = 0.18   # Uzama CEZASI (çıkarılır)

BB_LEN      = 20      # Bollinger / SMA penceresi (hafta)
VOL_LEN     = 20      # hacim ortalaması (hafta)
SQ_WINDOW   = 52      # BandWidth yüzdelik penceresi (hafta)
HIGH_WINDOW = 52      # açık gök penceresi (hafta)
ATR_LEN     = 14      # haftalık ATR
EMA_LEN     = 20      # haftalık EMA (uzama referansı)
ER_LEN      = 20      # Kaufman verim oranı penceresi (hafta)
PERIOD      = "5y"    # haftalık veri için yeterli geçmiş

XU100_TICKERS = ["XU100.IS", "^XU100", "XU100"]

BASE_URL = os.environ.get("OGREN_BASE_URL", "").rstrip("/")


# ════════════════════════════════════════════════════════════════
# YARDIMCILAR
# ════════════════════════════════════════════════════════════════
def _self_base():
    if BASE_URL:
        return BASE_URL
    return "http://127.0.0.1:" + str(os.environ.get("PORT", "10000"))


def _get_json(url, timeout=30):
    try:
        if requests is not None:
            r = requests.get(url, timeout=timeout)
            return r.json() if 200 <= r.status_code < 300 else None
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "patlama/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _lin(x, x0, x1, y0=0.0, y1=100.0):
    """x'i [x0,x1] aralığından [y0,y1]'e doğrusal eşler, sınırlanır."""
    if x1 == x0:
        return y0
    t = (x - x0) / (x1 - x0)
    return _clamp(y0 + t * (y1 - y0), min(y0, y1), max(y0, y1))


def _wilder_atr(high, low, close, length=ATR_LEN):
    pc = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - pc).abs(), (low - pc).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False).mean()


def _flatten(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _fetch_weekly(symbol):
    """Hisse için haftalık OHLCV (auto_adjust)."""
    if yf is None:
        return None
    try:
        df = yf.download(symbol + ".IS", period=PERIOD, interval="1wk",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        df = _flatten(df)
        df = df.dropna(subset=["Close"])
        return df if len(df) >= 8 else None
    except Exception:
        return None


def _fetch_xu100_weekly():
    if yf is None:
        return None
    for tk in XU100_TICKERS:
        try:
            df = yf.download(tk, period=PERIOD, interval="1wk",
                             progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                df = _flatten(df)
                return pd.to_numeric(df["Close"], errors="coerce").dropna()
        except Exception:
            continue
    return None


# ════════════════════════════════════════════════════════════════
# BİLEŞEN HESAPLARI — her biri (skor 0-100, ham değer, açıklama)
# ════════════════════════════════════════════════════════════════
def _comp_efficiency(close):
    """Kaufman Verim Oranı (ER): temiz trend mi, chop mu? (ESCOM dersi)"""
    try:
        c = pd.to_numeric(close, errors="coerce").dropna()
        n = min(ER_LEN, len(c) - 1)
        if n < 6:
            return 50.0, None, "yetersiz veri"
        seg = c.iloc[-(n + 1):]
        direction = abs(float(seg.iloc[-1]) - float(seg.iloc[0]))
        vol = float(seg.diff().abs().sum())
        er = direction / vol if vol > 0 else 0.0
        score = _lin(er, 0.15, 0.55)            # 0.15→0 (chop), 0.55→100 (temiz trend)
        tag = "temiz/güçlü trend" if er > 0.40 else \
              ("orta trend" if er > 0.25 else "CHOP / yatay — kesişim ALDATICI")
        return score, round(er, 2), tag + " (verim %.2f)" % er
    except Exception as e:
        return 50.0, None, "hata:" + str(e)[:40]


def _comp_squeeze(close):
    """Bollinger BandWidth'in son 52H içindeki yüzdelik konumu (dip=sıkışık)."""
    try:
        sma = close.rolling(BB_LEN).mean()
        std = close.rolling(BB_LEN).std()
        bbw = (4.0 * std / sma)                      # (üst-alt)/orta = 4σ/sma
        bbw = bbw.dropna()
        if len(bbw) < 10:
            return 50.0, None, "yetersiz veri"
        cur = float(bbw.iloc[-1])
        win = bbw.iloc[-SQ_WINDOW:] if len(bbw) >= SQ_WINDOW else bbw
        arr = [float(v) for v in win.values if v == v]
        below = sum(1 for v in arr if v < cur)
        pct = below / (len(arr) - 1) if len(arr) > 1 else 0.5
        score = _clamp(100.0 * (1.0 - pct), 0, 100)   # düşük yüzdelik = yüksek skor
        return score, round(cur, 4), "BandWidth %d.dilim (dip=sıkışık)" % int(pct * 100)
    except Exception as e:
        return 50.0, None, "hata:" + str(e)[:40]


def _comp_rvol(volume):
    try:
        v = pd.to_numeric(volume, errors="coerce").dropna()
        if len(v) < VOL_LEN + 1 or v.iloc[-VOL_LEN:].mean() <= 0:
            return 50.0, None, "yetersiz hacim"
        avg = float(v.iloc[-VOL_LEN - 1:-1].mean())   # son hariç 20H ort
        cur = float(v.iloc[-1])
        rvol = cur / avg if avg > 0 else 0
        score = _lin(rvol, 0.7, 2.5)                   # 0.7×→0, 2.5×→100
        return score, round(rvol, 2), "%.2f× ortalama hacim" % rvol
    except Exception as e:
        return 50.0, None, "hata:" + str(e)[:40]


def _comp_clear_sky(high, close):
    try:
        h = pd.to_numeric(high, errors="coerce").dropna()
        c = float(close.iloc[-1])
        if len(h) < 6:
            return 50.0, None, "yetersiz veri"
        prior = h.iloc[-(HIGH_WINDOW + 1):-1] if len(h) > HIGH_WINDOW else h.iloc[:-1]
        h52 = float(prior.max()) if len(prior) else c
        if h52 <= 0:
            return 50.0, None, "geçersiz"
        cs = c / h52
        if cs >= 1.0:
            return 100.0, round(cs, 3), "YENİ ZİRVE — üstte satıcı yok (vakum)"
        score = _lin(cs, 0.65, 1.0, 0, 95)             # zirvenin altı → ceza
        return score, round(cs, 3), "52H zirvenin %%%d'i (üstte direnç var)" % int(cs * 100)
    except Exception as e:
        return 50.0, None, "hata:" + str(e)[:40]


def _comp_clv(high, low, close):
    """Son 2 haftanın kapanış-konumu (zirveye yakın=talep, dipte=satış)."""
    try:
        def clv1(i):
            hi = float(high.iloc[i]); lo = float(low.iloc[i]); cl = float(close.iloc[i])
            rng = hi - lo
            if rng <= 0:
                return 0.0
            return (2.0 * cl - hi - lo) / rng           # [-1, +1]
        last = clv1(-1)
        prev = clv1(-2) if len(close) >= 2 else last
        clv = 0.65 * last + 0.35 * prev
        score = _clamp(50.0 * (clv + 1.0), 0, 100)      # +1→100, 0→50, -1→0
        tag = "zirveye yakın kapanış (talep)" if clv > 0.3 else \
              ("dip/üst-fitil (dağıtım)" if clv < -0.2 else "nötr kapanış")
        return score, round(clv, 2), tag
    except Exception as e:
        return 50.0, None, "hata:" + str(e)[:40]


def _comp_rs(close, xu):
    """XU100'e göre 13H/26H fazla getiri → 0-100. (Tek hisse için vekil eşleme.)"""
    try:
        if xu is None or len(xu) < 14 or len(close) < 14:
            return 50.0, None, "XU100/veri yok"
        def rel(n):
            if len(close) <= n or len(xu) <= n:
                return None
            sr = float(close.iloc[-1]) / float(close.iloc[-1 - n]) - 1.0
            xr = float(xu.iloc[-1]) / float(xu.iloc[-1 - n]) - 1.0
            return sr - xr
        r13 = rel(13)
        r26 = rel(26)
        parts = [(r13, 0.6), (r26, 0.4)]
        num = 0.0; wsum = 0.0
        for val, w in parts:
            if val is not None:
                num += w * val; wsum += w
        if wsum == 0:
            return 50.0, None, "yetersiz"
        relblend = num / wsum
        score = _lin(relblend, -0.30, 0.50, 0, 100)     # endeksin -%30 altı→0, +%50 üstü→100
        score = _clamp(50.0 + (score - 50.0), 0, 100)
        tag = "endeksin ÖNÜNDE (lider)" if relblend > 0.05 else \
              ("endeksin GERİSİNDE (takipçi)" if relblend < -0.05 else "endeksle paralel")
        return score, round(relblend * 100, 1), tag + " (fazla getiri %%%.1f)" % (relblend * 100)
    except Exception as e:
        return 50.0, None, "hata:" + str(e)[:40]


def _comp_base(high, low, close):
    """Kırılımdan ÖNCEKİ pencerede taban darlığı (dar=enerji)."""
    try:
        if len(close) < 16:
            return 50.0, None, "yetersiz veri"
        h = pd.to_numeric(high, errors="coerce")
        l = pd.to_numeric(low, errors="coerce")
        c = pd.to_numeric(close, errors="coerce")
        seg_h = h.iloc[-13:-3]; seg_l = l.iloc[-13:-3]; seg_c = c.iloc[-13:-3]
        mc = float(seg_c.mean())
        if mc <= 0:
            return 50.0, None, "geçersiz"
        tightness = (float(seg_h.max()) - float(seg_l.min())) / mc
        score = _lin(tightness, 0.50, 0.10)             # %50 geniş→0, %10 dar→100
        tag = "dar/uzun taban (yay gerilmiş)" if tightness < 0.20 else \
              ("orta taban" if tightness < 0.35 else "dağınık/geniş taban")
        return score, round(tightness * 100, 1), tag + " (taban genişliği %%%.0f)" % (tightness * 100)
    except Exception as e:
        return 50.0, None, "hata:" + str(e)[:40]


def _comp_ext(high, low, close):
    """EMA20'den ATR cinsinden uzaklık → KOVALAMA cezası (yüksek=kötü)."""
    try:
        ema = close.ewm(span=EMA_LEN, adjust=False).mean()
        atr = _wilder_atr(high, low, close, ATR_LEN)
        a = float(atr.iloc[-1]); e = float(ema.iloc[-1]); c = float(close.iloc[-1])
        if a <= 0:
            return 0.0, None, "ATR yok"
        ext = (c - e) / a
        penalty = _lin(ext, 1.0, 4.0)                   # ≤1 ATR→0 ceza, ≥4 ATR→100 ceza
        tag = "EMA'ya yakın (taze)" if ext < 1.0 else \
              ("makul uzaklık" if ext < 2.5 else "ÇOK UZAMIŞ (kovalama riski)")
        return penalty, round(ext, 2), tag + " (EMA'dan %.1f ATR)" % ext
    except Exception as e:
        return 0.0, None, "hata:" + str(e)[:40]


def _liquidity(close, volume):
    """Ortalama haftalık TL hacmi (likidite/float vekili) — bilgi amaçlı."""
    try:
        c = pd.to_numeric(close, errors="coerce")
        v = pd.to_numeric(volume, errors="coerce")
        tl = (c * v).iloc[-VOL_LEN:].mean()
        return round(float(tl), 0) if tl == tl else None
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════
# ANA SKORLAYICI
# ════════════════════════════════════════════════════════════════
def score_symbol(symbol, asof_back=0):
    symbol = symbol.upper().strip()
    if yf is None or pd is None:
        return {"symbol": symbol, "hata": "yfinance/pandas yok"}
    df = _fetch_weekly(symbol)
    if df is None:
        return {"symbol": symbol, "hata": "haftalık veri yok / yetersiz"}

    # Geçmişe sarma (doğrulama): son asof_back haftayı at, o tarihteki gibi skorla
    asof_back = int(asof_back or 0)
    if asof_back > 0 and len(df) - asof_back >= 8:
        df = df.iloc[:len(df) - asof_back]

    close = pd.to_numeric(df["Close"], errors="coerce")
    high = pd.to_numeric(df["High"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    volume = df["Volume"] if "Volume" in df.columns else pd.Series([0] * len(df), index=df.index)
    xu = _fetch_xu100_weekly()
    if xu is not None and asof_back > 0 and len(xu) - asof_back >= 8:
        xu = xu.iloc[:len(xu) - asof_back]

    cs_s, cs_v, cs_t = _comp_clear_sky(high, close)
    er_s, er_v, er_t = _comp_efficiency(close)
    sq_s, sq_v, sq_t = _comp_squeeze(close)
    rs_s, rs_v, rs_t = _comp_rs(close, xu)
    rv_s, rv_v, rv_t = _comp_rvol(volume)
    cl_s, cl_v, cl_t = _comp_clv(high, low, close)
    ba_s, ba_v, ba_t = _comp_base(high, low, close)
    ex_s, ex_v, ex_t = _comp_ext(high, low, close)

    positive = (W_CS * cs_s + W_ER * er_s + W_SQ * sq_s + W_RS * rs_s +
                W_RVOL * rv_s + W_CLV * cl_s + W_BASE * ba_s)
    patlama = _clamp(positive - W_EXT * ex_s, 0, 100)

    if patlama >= 75:
        verdict = "🚀 TAVAN ADAYI"; vcolor = "#22c55e"
    elif patlama >= 60:
        verdict = "GÜÇLÜ"; vcolor = "#86efac"
    elif patlama >= 45:
        verdict = "ORTA"; vcolor = "#e8b84b"
    else:
        verdict = "ZAYIF / KAÇIN"; vcolor = "#ef4444"

    comps = [
        {"ad": "Açık Gök (yeni zirve)", "skor": round(cs_s, 1), "agirlik": W_CS,
         "katki": round(W_CS * cs_s, 1), "deger": cs_v, "aciklama": cs_t},
        {"ad": "Verim (ER) / chop filtresi", "skor": round(er_s, 1), "agirlik": W_ER,
         "katki": round(W_ER * er_s, 1), "deger": er_v, "aciklama": er_t},
        {"ad": "Sıkışma (squeeze)", "skor": round(sq_s, 1), "agirlik": W_SQ,
         "katki": round(W_SQ * sq_s, 1), "deger": sq_v, "aciklama": sq_t},
        {"ad": "Göreceli Güç (RS)", "skor": round(rs_s, 1), "agirlik": W_RS,
         "katki": round(W_RS * rs_s, 1), "deger": rs_v, "aciklama": rs_t},
        {"ad": "Hacim (RVOL)", "skor": round(rv_s, 1), "agirlik": W_RVOL,
         "katki": round(W_RVOL * rv_s, 1), "deger": rv_v, "aciklama": rv_t},
        {"ad": "Kapanış Gücü (CLV)", "skor": round(cl_s, 1), "agirlik": W_CLV,
         "katki": round(W_CLV * cl_s, 1), "deger": cl_v, "aciklama": cl_t},
        {"ad": "Taban Sıkılığı (VCP)", "skor": round(ba_s, 1), "agirlik": W_BASE,
         "katki": round(W_BASE * ba_s, 1), "deger": ba_v, "aciklama": ba_t},
        {"ad": "Uzama CEZASI (EXT)", "skor": round(ex_s, 1), "agirlik": -W_EXT,
         "katki": round(-W_EXT * ex_s, 1), "deger": ex_v, "aciklama": ex_t},
    ]

    return {
        "symbol": symbol,
        "patlama": round(patlama, 1),
        "karar": verdict,
        "renk": vcolor,
        "fiyat": round(float(close.iloc[-1]), 2),
        "asof_back": asof_back,
        "bilesenler": comps,
        "likidite_TL_haftalik": _liquidity(close, volume),
        "veri_hafta": len(df),
        "not": "Kesişim verildiğinde hareketin BÜYÜK olma potansiyeli. Olasılıksal sıralama; garanti değil. Ağırlıklar kalibre edilmeli.",
    }


# ════════════════════════════════════════════════════════════════
# HTML PANEL
# ════════════════════════════════════════════════════════════════
def _bar(score, color="#00d4ff"):
    w = _clamp(score, 0, 100)
    return ("<div style='background:#0b0e18;border-radius:4px;height:8px;overflow:hidden'>"
            "<div style='width:%.0f%%;height:8px;background:%s'></div></div>") % (w, color)


def _render_html(d):
    if d.get("hata"):
        return ("<html><body style='background:#0a0d14;color:#e7eefc;font-family:monospace;padding:20px'>"
                "<h2>%s</h2><p style='color:#ef4444'>Hata: %s</p>"
                "<p style='color:#4b5e78'>Örnek: /patlama/CELHA · /patlama/compare?symbols=CELHA,GSDDE</p>"
                "</body></html>") % (d.get("symbol", "?"), d["hata"])
    rows = ""
    for c in d["bilesenler"]:
        sc = c["skor"]
        col = "#22c55e" if sc >= 65 else "#e8b84b" if sc >= 45 else "#ef4444"
        if c["agirlik"] < 0:  # ceza satırı
            col = "#ef4444" if sc >= 40 else "#4b5e78"
        rows += ("<div style='margin:10px 0'>"
                 "<div style='display:flex;justify-content:space-between;font-size:12px'>"
                 "<span style='color:#c0cfe0'>%s</span>"
                 "<span style='color:%s;font-weight:700'>%.0f → %+.1f p</span></div>"
                 "%s"
                 "<div style='font-size:10px;color:#4b5e78;margin-top:2px'>%s · değer: %s · ağırlık: %s</div>"
                 "</div>") % (c["ad"], col, c["skor"], c["katki"], _bar(c["skor"], col),
                              c["aciklama"], str(c["deger"]), c["agirlik"])
    liq = d.get("likidite_TL_haftalik")
    liq_s = "{:,.0f} TL/hafta".format(liq) if liq else "—"
    return ("""<html><head><meta name=viewport content='width=device-width,initial-scale=1'>
<title>PATLAMA · %s</title></head>
<body style='background:#0a0d14;color:#e7eefc;font-family:monospace;padding:16px;max-width:680px;margin:auto'>
<div style='display:flex;justify-content:space-between;align-items:center'>
<h2 style='margin:0'>%s</h2><span style='color:#4b5e78'>₺%s</span></div>
<div style='text-align:center;margin:18px 0;padding:18px;border:2px solid %s;border-radius:12px'>
<div style='font-size:11px;color:#4b5e78;letter-spacing:2px'>🚀 PATLAMA SKORU</div>
<div style='font-size:56px;font-weight:800;color:%s;line-height:1'>%s</div>
<div style='font-size:18px;font-weight:700;color:%s'>%s</div></div>
<div style='font-size:11px;color:#7a9ab8;margin-bottom:6px'>BİLEŞENLER (kesişim verildiğinde büyük hareket potansiyeli)</div>
%s
<div style='margin-top:14px;font-size:10px;color:#4b5e78'>Likidite: %s · veri: %s hafta</div>
<div style='margin-top:8px;font-size:10px;color:#4b5e78'>%s</div>
<div style='margin-top:14px;font-size:11px'>
<a style='color:#00d4ff' href='/patlama/compare?symbols=CELHA,GSDDE'>↔ CELHA vs GSDDE karşılaştır</a></div>
</body></html>""") % (d["symbol"], d["symbol"], d["fiyat"], d["renk"], d["renk"],
                       d["patlama"], d["renk"], d["karar"], rows, liq_s, d["veri_hafta"], d["not"])


def _render_compare(items):
    head = ("<tr><th style='text-align:left;padding:6px'>Hisse</th>"
            "<th style='padding:6px'>PATLAMA</th><th style='padding:6px'>Karar</th>"
            "<th style='padding:6px'>AçıkGök</th><th style='padding:6px'>Verim</th>"
            "<th style='padding:6px'>Sıkışma</th>"
            "<th style='padding:6px'>RS</th><th style='padding:6px'>RVOL</th>"
            "<th style='padding:6px'>CLV</th><th style='padding:6px'>Taban</th>"
            "<th style='padding:6px'>Uzama</th></tr>")
    body = ""
    for d in items:
        if d.get("hata"):
            body += "<tr><td style='padding:6px'>%s</td><td colspan=10 style='color:#ef4444;padding:6px'>%s</td></tr>" % (d.get("symbol"), d["hata"])
            continue
        m = {c["ad"].split(" ")[0]: c["skor"] for c in d["bilesenler"]}
        cells = [m.get("Açık", 0), m.get("Verim", 0), m.get("Sıkışma", 0), m.get("Göreceli", 0),
                 m.get("Hacim", 0), m.get("Kapanış", 0), m.get("Taban", 0), m.get("Uzama", 0)]
        tds = "".join("<td style='text-align:center;padding:6px;color:%s'>%.0f</td>" %
                      ("#22c55e" if v >= 65 else "#e8b84b" if v >= 45 else "#ef4444", v) for v in cells)
        body += ("<tr><td style='padding:6px;font-weight:700'>%s</td>"
                 "<td style='text-align:center;padding:6px;color:%s;font-weight:800;font-size:16px'>%s</td>"
                 "<td style='text-align:center;padding:6px;color:%s'>%s</td>%s</tr>") % (
            d["symbol"], d["renk"], d["patlama"], d["renk"], d["karar"], tds)
    return ("""<html><head><meta name=viewport content='width=device-width,initial-scale=1'>
<title>PATLAMA Karşılaştırma</title></head>
<body style='background:#0a0d14;color:#e7eefc;font-family:monospace;padding:14px'>
<h2>🚀 PATLAMA Karşılaştırma</h2>
<div style='overflow-x:auto'><table style='border-collapse:collapse;font-size:12px;min-width:560px'>
%s%s</table></div>
<p style='color:#4b5e78;font-size:11px;margin-top:12px'>Yüksek skor = kesişim verildiğinde büyük hareket olasılığı yüksek. Olasılıksal; garanti değil.</p>
</body></html>""") % (head, body)


# ════════════════════════════════════════════════════════════════
# ROUTER
# ════════════════════════════════════════════════════════════════
patlama_router = APIRouter(prefix="/patlama", tags=["patlama"])


@patlama_router.get("/compare", response_class=HTMLResponse)
def compare(symbols: str = "CELHA,GSDDE", fmt: str = "html", gecmis: int = 0):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:10]
    items = [score_symbol(s, asof_back=gecmis) for s in syms]
    if fmt == "json":
        return JSONResponse(items)
    return HTMLResponse(_render_compare(items))


@patlama_router.get("/{symbol}", response_class=HTMLResponse)
def get_patlama(symbol: str, fmt: str = "html", gecmis: int = 0):
    d = score_symbol(symbol, asof_back=gecmis)
    if fmt == "json":
        return JSONResponse(d)
    return HTMLResponse(_render_html(d))


_installed = {"on": False}


def install_patlama(app) -> None:
    if _installed["on"]:
        return
    _installed["on"] = True
    app.include_router(patlama_router)


if __name__ == "__main__":
    import sys
    s = sys.argv[1] if len(sys.argv) > 1 else "CELHA"
    print(json.dumps(score_symbol(s), ensure_ascii=False, indent=2))
