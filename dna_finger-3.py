# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
DNA FINGER · ADIM 3b — PARMAK İZİ MOTORU
═══════════════════════════════════════════════════════════════════
Amaç : dna_scan havuzundaki her olayın (A_TREND / B_ZIPLAMA) T0
       günündeki ÖN-KAYITLI 10 özelliğini ölçmek ve iki sınıfın
       dağılımlarını karşılaştırarak hangi özelliklerin gerçek
       trendi sahte zıplamadan AYIRDIĞINI sayısal olarak bulmak.
       DNA skoru bu tablodan doğacaktır.

Sızıntı yok: tüm özellikler T0 günü ve ÖNCESİYLE hesaplanır.
(Canlıda "bugün T0'a benziyor mu" sorusu sorulacağı için T0 günü
 kapanış verisi meşrudur; T0 sonrası tek bar bile kullanılmaz.)

ÖN-KAYITLI ÖZELLİK LİSTESİ (test sonrası değiştirilemez):
  1  hacim_kuruma  : ort(hacim son5) / ort(hacim son60)   — satıcı tükenmesi
  2  hacim_uyanis  : hacim[T0] / ort(hacim son20)          — ilk kıvılcım
  3  atr_daralma   : ATR10 / ATR60                          — volatilite sıkışması
  4  r5_pct        : 5 günlük getiri %                      — kısa momentum
  5  r20_pct       : 20 günlük getiri %                     — orta momentum
  6  dip_yakinlik  : kapanış / min(252g) - 1  (%)           — 52h dibe mesafe
  7  zirve_uzaklik : 1 - kapanış / max(252g)  (%)           — 52h zirveye mesafe
  8  sma200_sapma  : kapanış / SMA200 - 1  (%)              — uzun yapıya konum
  9  dusus_yasi    : 52h zirvesinden bu yana geçen gün      — düşüşün yaşı
  10 rsi14         : klasik RSI(14)                         — aşırı satım

Akış (dna_scan ile aynı kalıp):
  GET /dnafinger/start        → dna_scan Gist havuzunu okur, hisse
                                kuyruğunu kurar
  GET /dnafinger/run?batch=15 → sıradaki N hissenin olay özelliklerini
                                ölçer, Gist'e yazar
  GET /dnafinger/status       → ilerleme
  GET /dnafinger/ozet         → A vs B karşılaştırması + AUC ayrışma
  GET /dnafinger/retry        → hatalıları kuyruğa geri koyar

Kalıcılık: DNAFINGER_GIST_ID + GITHUB_TOKEN.
Havuz kaynağı: DNASCAN_GIST_ID (Adım 3a'nın çıktısı).
═══════════════════════════════════════════════════════════════════
"""

import json
import os
import time
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

try:
    import requests
except Exception:
    requests = None

DNAFINGER_GIST_ID = (os.environ.get("DNAFINGER_GIST_ID") or "").strip()
DNASCAN_GIST_ID = (os.environ.get("DNASCAN_GIST_ID") or "").strip()
GITHUB_TOKEN = (os.environ.get("GITHUB_TOKEN") or "").strip()
GIST_DOSYA = "dnafinger_state.json"
SCAN_DOSYA = "dnascan_state.json"

OZELLIKLER = ["hacim_kuruma", "hacim_uyanis", "atr_daralma", "r5_pct",
              "r20_pct", "dip_yakinlik", "zirve_uzaklik", "sma200_sapma",
              "dusus_yasi", "rsi14"]

# FAZ 2 — rejim (T0 günü piyasa durumu) + doğrulama (T0 sonrası ilk 5 gün;
# yalnız vuruşu 5 günden uzun olaylarda ölçülür, etiket +120. günde
# kesinleştiği için sızıntı yoktur — karar noktası T0+5'e taşınır)
OZELLIK_REJIM = ["xu_r20", "xu_r60", "xu_sma200_sapma"]
OZELLIK_DOGRULAMA = ["d5_getiri", "d5_hacim", "d5_yeni_yuksek",
                     "d3_getiri", "d5_max_getiri"]

# FAZ 3 — disiplinler-arası batarya (hepsi T0 ve öncesiyle; sızıntı yok)
OZELLIK_BATARYA = [
    "hacim_asimetri",   # 40g: yükseliş günleri hacmi / düşüş günleri hacmi (Wyckoff)
    "vwap120_oran",     # kapanış / 120g hacim-ağırlıklı ort. fiyat (maliyet tavanı)
    "kapitulasyon",     # son 20g'deki en büyük düşüş-günü hacmi / v60 (klimaks)
    "rel_guc60",        # 60g getiri - XU100 60g getirisi (artık güç)
    "ar1_60",           # getiri otokorelasyonu lag1, 60g (kritik yavaşlama)
    "varyans_egim",     # var(son20g) / var(40g önceki 20g) (titreme artışı)
    "perm_entropi",     # permütasyon entropisi n=3, 60g (düzenin doğuşu)
    "vr5_120",          # varyans oranı VR(5), 120g (ısrarcılık/Hurst vekili)
    "sma200_egim",      # SMA200'ün 20g değişimi % (yapısal yön)
    "yukselen_dip",     # son 60g dibi / önceki 60g dibi - 1 (%) (taban yapısı)
    "ay",               # T0 ayı 1-12 (mevsimsellik, keşifsel)
]
CAG_SINIRI = "2018-01-01"   # ön-kayıtlı çağ ayrımı (istikrar sınavı)

_STATE: Dict = {"kuruldu": False}
_REJIM = None  # XU100 rejim haritası (bellekte, run başında kurulur)


# ─── Gist yardımcıları ──────────────────────────────────────────
def _hd():
    return {"Authorization": "token " + GITHUB_TOKEN,
            "Accept": "application/vnd.github+json"} if GITHUB_TOKEN else None


def _gist_oku(gist_id, dosya):
    hd = _hd()
    if not (hd and gist_id and requests):
        return None
    try:
        r = requests.get("https://api.github.com/gists/" + gist_id,
                         headers=hd, timeout=90)
        if r.status_code == 200:
            files = r.json().get("files", {})
            if dosya in files:
                f = files[dosya]
                if f.get("truncated") and f.get("raw_url"):
                    rr = requests.get(f["raw_url"], timeout=120)
                    return json.loads(rr.text)
                return json.loads(f["content"])
    except Exception:
        pass
    return None


def _gist_load() -> bool:
    global _STATE
    d = _gist_oku(DNAFINGER_GIST_ID, GIST_DOSYA)
    if d:
        _STATE = d
        return True
    return False


def _gist_save() -> Dict:
    global DNAFINGER_GIST_ID
    hd = _hd()
    if not (hd and requests):
        return {"gist": "yok (GITHUB_TOKEN eksik) — bellek-içi mod"}
    icerik = {"files": {GIST_DOSYA: {"content": json.dumps(_STATE, ensure_ascii=False)}}}
    try:
        if DNAFINGER_GIST_ID:
            requests.patch("https://api.github.com/gists/" + DNAFINGER_GIST_ID,
                           headers=hd, json=icerik, timeout=60)
            return {"gist": "guncellendi", "gist_id": DNAFINGER_GIST_ID}
        icerik["description"] = "Vortex-BIST DNA Finger ozellik havuzu"
        icerik["public"] = False
        r = requests.post("https://api.github.com/gists",
                          headers=hd, json=icerik, timeout=60)
        if r.status_code in (200, 201):
            DNAFINGER_GIST_ID = r.json().get("id", "")
            return {"gist": "OLUSTURULDU — Render'a DNAFINGER_GIST_ID "
                            "olarak ekle!", "gist_id": DNAFINGER_GIST_ID}
    except Exception as e:
        return {"gist": "hata: " + repr(e)}
    return {"gist": "yazilamadi"}


def _durum_hazirla():
    if not _STATE.get("kuruldu"):
        if not _gist_load():
            _STATE.update({"kuruldu": True, "bekleyen": [], "hatali": [],
                           "tamam": 0, "kayitlar": [], "baslangic": None})


# ─── özellik hesabı ─────────────────────────────────────────────
def _rsi14(c: np.ndarray) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = pd.Series(up).ewm(alpha=1 / 14, min_periods=14).mean().values
    ad = pd.Series(dn).ewm(alpha=1 / 14, min_periods=14).mean().values
    rs = np.divide(au, ad, out=np.full_like(au, np.nan), where=ad > 0)
    return 100 - 100 / (1 + rs)


def _perm_entropi(x: np.ndarray) -> float:
    """Permütasyon entropisi (n=3), 0-1 normalize. Düşük = düzenli."""
    n = len(x)
    if n < 10:
        return np.nan
    say = {}
    for i in range(n - 2):
        p = tuple(np.argsort(x[i:i + 3]))
        say[p] = say.get(p, 0) + 1
    top = sum(say.values())
    ps = np.array([v / top for v in say.values()])
    return float(-(ps * np.log(ps)).sum() / np.log(6))


def _ar1(r: np.ndarray) -> float:
    r = r[np.isfinite(r)]
    if len(r) < 20:
        return np.nan
    a, b = r[:-1], r[1:]
    sa, sb = a.std(), b.std()
    if sa == 0 or sb == 0:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def _vr5(r: np.ndarray) -> float:
    """Varyans oranı: var(5g getiri)/(5*var(1g)). >1 ısrarcı, <1 dönen."""
    r = r[np.isfinite(r)]
    if len(r) < 40:
        return np.nan
    v1 = r.var()
    if v1 == 0:
        return np.nan
    r5 = np.array([r[i:i + 5].sum() for i in range(len(r) - 5)])
    return float(r5.var() / (5 * v1))


def ozellik_dizileri(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Tüm seri için özellik dizileri (her i günü, o güne KADARKİ veriyle)."""
    d = df.copy()
    esle = {}
    for col in d.columns:
        cl = str(col).strip().lower()
        if cl in ("close", "high", "low", "open", "volume"):
            esle[col] = cl.capitalize()
    d = d.rename(columns=esle)
    c = pd.to_numeric(d["Close"], errors="coerce").values.astype(float)
    h = pd.to_numeric(d["High"], errors="coerce").values.astype(float)
    l = pd.to_numeric(d["Low"], errors="coerce").values.astype(float)
    v = pd.to_numeric(d.get("Volume", pd.Series(np.nan, index=d.index)),
                      errors="coerce").values.astype(float)
    n = len(c)
    cs, hs, ls, vs = (pd.Series(c), pd.Series(h), pd.Series(l), pd.Series(v))

    v5 = vs.rolling(5).mean().values
    v20 = vs.rolling(20).mean().values
    v60 = vs.rolling(60).mean().values

    onceki_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - onceki_c), np.abs(l - onceki_c)))
    trs = pd.Series(tr)
    atr10 = trs.rolling(10).mean().values
    atr60 = trs.rolling(60).mean().values

    r5 = cs.pct_change(5).values * 100
    r20 = cs.pct_change(20).values * 100
    min252 = cs.rolling(252, min_periods=252).min().values
    max252 = cs.rolling(252, min_periods=252).max().values
    sma200 = cs.rolling(200, min_periods=200).mean().values

    # düşüş yaşı: son 252g zirvesinden bu yana gün
    yas = np.full(n, np.nan)
    for i in range(251, n):
        z = i - 251 + int(np.argmax(c[i - 251:i + 1]))
        yas[i] = i - z

    with np.errstate(divide="ignore", invalid="ignore"):
        diz = {
            "hacim_kuruma": v5 / v60,
            "hacim_uyanis": v / v20,
            "atr_daralma": atr10 / atr60,
            "r5_pct": r5,
            "r20_pct": r20,
            "dip_yakinlik": (c / min252 - 1) * 100,
            "zirve_uzaklik": (1 - c / max252) * 100,
            "sma200_sapma": (c / sma200 - 1) * 100,
            "dusus_yasi": yas,
            "rsi14": _rsi14(c),
        }
    # ── FAZ 3 dizileri (vektörel olanlar) ──
    getiri = np.full(n, np.nan)
    getiri[1:] = c[1:] / c[:-1] - 1.0
    tipik = (h + l + c) / 3.0
    pv = pd.Series(tipik * v)
    vwap120 = pv.rolling(120).sum().values / \
              pd.Series(v).rolling(120).sum().values
    min60 = cs.rolling(60, min_periods=60).min().values
    diz["vwap120_oran"] = c / vwap120
    diz["sma200_egim"] = np.full(n, np.nan)
    diz["sma200_egim"][20:] = (sma200[20:] / sma200[:-20] - 1) * 100
    diz["yukselen_dip"] = np.full(n, np.nan)
    diz["yukselen_dip"][60:] = (min60[60:] / min60[:-60] - 1) * 100

    tarih = [str(t.date()) for t in d.index]
    ham = {"c": c, "h": h, "l": l, "v": v, "v20": v20, "v60": v60,
           "getiri": getiri}
    return diz, tarih, ham


def batarya_olc(i: int, ham: Dict, rj: Dict) -> Dict[str, float]:
    """Pahalı FAZ 3 özelliklerini yalnız olay gününde hesaplar."""
    c, v, g = ham["c"], ham["v"], ham["getiri"]
    v60 = ham["v60"]
    out = {}
    if i >= 60:
        seg_g = g[i - 39:i + 1]
        seg_v = v[i - 39:i + 1]
        yuk = seg_v[seg_g > 0].sum()
        dus = seg_v[seg_g < 0].sum()
        out["hacim_asimetri"] = float(yuk / dus) if dus > 0 else np.nan
        dg = g[i - 19:i + 1]
        dv = v[i - 19:i + 1]
        neg = dv[dg < 0]
        out["kapitulasyon"] = float(neg.max() / v60[i]) \
            if len(neg) and np.isfinite(v60[i]) and v60[i] > 0 else np.nan
        out["ar1_60"] = _ar1(g[i - 59:i + 1])
        v_yeni = np.nanvar(g[i - 19:i + 1])
        v_eski = np.nanvar(g[i - 59:i - 39])
        out["varyans_egim"] = float(v_yeni / v_eski) if v_eski > 0 else np.nan
        out["perm_entropi"] = _perm_entropi(c[i - 59:i + 1])
    if i >= 120:
        out["vr5_120"] = _vr5(g[i - 119:i + 1])
    if rj and "xu_r60" in rj:
        r60_hisse = (c[i] / c[i - 60] - 1) * 100 if i >= 60 else np.nan
        out["rel_guc60"] = float(r60_hisse - rj["xu_r60"]) \
            if np.isfinite(r60_hisse) else np.nan
    return out


def rejim_haritasi(fetch_ohlc) -> Dict[str, Dict[str, float]]:
    """XU100 endeksinden T0 günü rejim özellikleri: tarih → değerler."""
    xu = None
    for tick in ("XU100", "^XU100"):
        try:
            xu = fetch_ohlc(tick, period="max")
        except Exception:
            xu = None
        if xu is not None and len(xu) > 300:
            break
    if xu is None or len(xu) < 300:
        return {}
    esle = {}
    for col in xu.columns:
        cl = str(col).strip().lower()
        if cl == "close":
            esle[col] = "Close"
    xu = xu.rename(columns=esle)
    c = pd.to_numeric(xu["Close"], errors="coerce")
    r20 = c.pct_change(20) * 100
    r60 = c.pct_change(60) * 100
    sma = c.rolling(200, min_periods=200).mean()
    sap = (c / sma - 1) * 100
    out = {}
    for i, t in enumerate(xu.index):
        a, b, s = r20.iloc[i], r60.iloc[i], sap.iloc[i]
        if np.isfinite(a) and np.isfinite(b) and np.isfinite(s):
            out[str(t.date())] = {"xu_r20": round(float(a), 3),
                                  "xu_r60": round(float(b), 3),
                                  "xu_sma200_sapma": round(float(s), 3)}
    return out


def _tek_hisse(sym: str, olaylar: List[Dict], fetch_ohlc: Callable,
               rejim: Dict = None) -> Dict:
    df = None
    try:
        df = fetch_ohlc(sym, period="max")
    except Exception:
        pass
    if df is None or len(df) < 300:
        return {"hata": "veri"}
    diz, tarih, ham = ozellik_dizileri(df)
    del df
    ix = {t: i for i, t in enumerate(tarih)}
    c, h, v, v20 = ham["c"], ham["h"], ham["v"], ham["v20"]
    n = len(c)
    kayitlar = []
    for o in olaylar:
        i = ix.get(o["t0"])
        if i is None:
            continue
        kay = {"s": sym, "t0": o["t0"], "sf": o["sf"],
               "mg": o.get("mg"), "g": o.get("g")}
        gecerli = True
        for k in OZELLIKLER:
            val = diz[k][i]
            if val is None or not np.isfinite(val):
                gecerli = False
                break
            kay[k] = round(float(val), 3)
        if not gecerli:
            continue
        # FAZ 2a — rejim (T0 günü XU100)
        rj = rejim.get(o["t0"]) if rejim else None
        if rj:
            kay.update(rj)
        # FAZ 3a — dizisel batarya özellikleri
        for kk in ("vwap120_oran", "sma200_egim", "yukselen_dip"):
            vv = diz[kk][i]
            if vv is not None and np.isfinite(vv):
                kay[kk] = round(float(vv), 4)
        # FAZ 3b — olay-anı batarya
        for kk, vv in batarya_olc(i, ham, rj).items():
            if vv is not None and np.isfinite(vv):
                kay[kk] = round(float(vv), 4)
        try:
            kay["ay"] = float(int(o["t0"][5:7]))
        except Exception:
            pass
        # FAZ 2b — doğrulama (T0+1..T0+5; yalnız vuruş > 5 gün ise)
        gs = o.get("g")
        if gs is not None and gs > 5 and i + 5 < n:
            seg_c = c[i + 1:i + 6]
            seg_h = h[i + 1:i + 6]
            seg_v = v[i + 1:i + 6]
            if np.isfinite(seg_c).all() and c[i] > 0 and \
               np.isfinite(v20[i]) and v20[i] > 0:
                onceki_zirve60 = float(np.nanmax(h[max(0, i - 60):i + 1]))
                kay["d3_getiri"] = round(float(c[i + 3] / c[i] - 1) * 100, 2)
                kay["d5_getiri"] = round(float(c[i + 5] / c[i] - 1) * 100, 2)
                kay["d5_max_getiri"] = round(float(seg_h.max() / c[i] - 1) * 100, 2)
                kay["d5_hacim"] = round(float(np.nanmean(seg_v) / v20[i]), 3)
                kay["d5_yeni_yuksek"] = 1.0 if float(seg_h.max()) > onceki_zirve60 else 0.0
        kayitlar.append(kay)
    return {"kayitlar": kayitlar}


def _auc(a_vals: List[float], b_vals: List[float]) -> float:
    """Mann-Whitney AUC: rastgele bir A'nın rastgele bir B'den büyük
    olma olasılığı. 0.5=ayrışma yok; 0.5'ten uzaklık = ayırt gücü."""
    a = np.asarray(a_vals)
    b = np.asarray(b_vals)
    hepsi = np.concatenate([a, b])
    sira = pd.Series(hepsi).rank().values
    ra = sira[:len(a)].sum()
    u = ra - len(a) * (len(a) + 1) / 2.0
    return round(float(u / (len(a) * len(b))), 3)


# ─── FastAPI kurulumu ───────────────────────────────────────────
def install_dna_finger(app, fetch_ohlc: Callable) -> None:
    from fastapi import Query

    @app.get("/dnafinger/start")
    def dnafinger_start():
        _durum_hazirla()
        # 1. yol: ayni surecteki dna_scan belleginden oku (en saglam)
        scan = None
        kaynak = "yok"
        try:
            import dna_scan as _ds
            _ds._durum_hazirla()
            if _ds._STATE.get("olaylar"):
                scan = _ds._STATE
                kaynak = "bellek(dna_scan)"
        except Exception:
            pass
        # 2. yol (yedek): Gist'ten oku
        if not scan:
            scan = _gist_oku(DNASCAN_GIST_ID, SCAN_DOSYA)
            kaynak = "gist"
        if not scan or not scan.get("olaylar"):
            return {"hata": "dna_scan havuzu okunamadi",
                    "ipucu": "once /dnascan/status ile havuzun durdugunu "
                             "dogrula; DNASCAN_GIST_ID dogru mu?"}
        gruplar: Dict[str, List[Dict]] = {}
        for o in scan["olaylar"]:
            gruplar.setdefault(o["s"], []).append(
                {"t0": o["t0"], "sf": o["sf"], "mg": o.get("mg")})
        _STATE.update({"kuruldu": True,
                       "bekleyen": sorted(gruplar.keys()),
                       "gruplar": gruplar, "hatali": [],
                       "tamam": 0, "kayitlar": [],
                       "baslangic": time.strftime("%Y-%m-%d %H:%M")})
        g = _gist_save()
        return {"durum": "basladi", "kaynak": kaynak,
                "hisse": len(gruplar),
                "olay": len(scan["olaylar"]), **g}

    @app.get("/dnafinger/run")
    def dnafinger_run(batch: int = Query(15, ge=1, le=40)):
        _durum_hazirla()
        bek = _STATE.get("bekleyen", [])
        if not bek:
            return {"durum": "bitti-veya-baslatilmadi",
                    "ipucu": "/dnafinger/start ile baslat",
                    "tamam": _STATE.get("tamam", 0)}
        global _REJIM
        if _REJIM is None:
            _REJIM = rejim_haritasi(fetch_ohlc)
        islenen, hatali = [], []
        for _ in range(min(batch, len(bek))):
            sym = bek.pop(0)
            r = _tek_hisse(sym, _STATE["gruplar"].get(sym, []), fetch_ohlc,
                           rejim=_REJIM)
            if "hata" in r:
                hatali.append(sym)
                _STATE["hatali"].append(sym)
            else:
                _STATE["kayitlar"].extend(r["kayitlar"])
                _STATE["tamam"] = _STATE.get("tamam", 0) + 1
                islenen.append(sym)
            time.sleep(0.4)
        g = _gist_save()
        return {"islenen": islenen, "hatali_bu_parti": hatali,
                "kalan": len(bek), "tamam": _STATE["tamam"],
                "olcum": len(_STATE["kayitlar"]), **g}

    @app.get("/dnafinger/status")
    def dnafinger_status():
        _durum_hazirla()
        kay = _STATE.get("kayitlar", [])
        return {"kalan": len(_STATE.get("bekleyen", [])),
                "tamam": _STATE.get("tamam", 0),
                "hatali": len(_STATE.get("hatali", [])),
                "olcum": len(kay),
                "a": sum(1 for k in kay if k["sf"] == "A"),
                "b": sum(1 for k in kay if k["sf"] == "B")}

    @app.get("/dnafinger/retry")
    def dnafinger_retry():
        _durum_hazirla()
        h = _STATE.get("hatali", [])
        _STATE["bekleyen"] = _STATE.get("bekleyen", []) + h
        _STATE["hatali"] = []
        g = _gist_save()
        return {"kuyruga_geri": len(h), **g}

    @app.get("/dnafinger/ozet")
    def dnafinger_ozet():
        _durum_hazirla()
        kay = _STATE.get("kayitlar", [])
        A = [k for k in kay if k["sf"] == "A"]
        B = [k for k in kay if k["sf"] == "B"]
        if len(A) < 30 or len(B) < 30:
            return {"hata": "yetersiz olcum", "a": len(A), "b": len(B)}
        tablo = []
        for oz in OZELLIKLER + OZELLIK_REJIM + OZELLIK_DOGRULAMA + OZELLIK_BATARYA:
            av = [k[oz] for k in A if oz in k]
            bv = [k[oz] for k in B if oz in k]
            if len(av) < 30 or len(bv) < 30:
                continue
            # çift-çağ istikrar: aynı özellik iki devirde de ayırıyor mu?
            a_es = [k[oz] for k in A if oz in k and k["t0"] < CAG_SINIRI]
            b_es = [k[oz] for k in B if oz in k and k["t0"] < CAG_SINIRI]
            a_ye = [k[oz] for k in A if oz in k and k["t0"] >= CAG_SINIRI]
            b_ye = [k[oz] for k in B if oz in k and k["t0"] >= CAG_SINIRI]
            auc_e = _auc(a_es, b_es) if len(a_es) >= 20 and len(b_es) >= 20 else None
            auc_y = _auc(a_ye, b_ye) if len(a_ye) >= 20 and len(b_ye) >= 20 else None
            istikrar = "?"
            if auc_e is not None and auc_y is not None:
                ayni_yon = (auc_e - 0.5) * (auc_y - 0.5) > 0
                guc = min(abs(auc_e - 0.5), abs(auc_y - 0.5)) >= 0.05
                istikrar = "EVET" if (ayni_yon and guc) else "HAYIR"
            auc = _auc(av, bv)
            tablo.append({"ozellik": oz,
                          "A_medyan": round(float(np.median(av)), 2),
                          "B_medyan": round(float(np.median(bv)), 2),
                          "auc": auc,
                          "auc_2010_17": auc_e, "auc_2018_26": auc_y,
                          "istikrar": istikrar, "n": len(av) + len(bv),
                          "ayirt_gucu": round(abs(auc - 0.5) * 2, 3)})
        tablo.sort(key=lambda x: -x["ayirt_gucu"])
        return {"a_olay": len(A), "b_olay": len(B),
                "aciklama": "auc 0.5=ayrisma yok · ayirt_gucu 0-1 "
                            "(0.2+ kayda deger, 0.4+ guclu)",
                "ozellik_tablosu": tablo}

    print("[dna_finger] kuruldu: /dnafinger/start · /dnafinger/run · "
          "/dnafinger/status · /dnafinger/ozet · /dnafinger/retry")
