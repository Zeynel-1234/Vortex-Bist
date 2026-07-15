# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
DNA SCAN · ADIM 3a — EVREN TARAYICISI
═══════════════════════════════════════════════════════════════════
Amaç : dna_lab v2.3 etiketleyicisini TÜM BIST evreninde (~630 hisse)
       parti parti koşturmak ve temiz A_TREND / B_ZIPLAMA olaylarını
       tek bir havuzda (Gist) biriktirmek. Bu havuz, parmak izi
       motorunun (Adım 3b) öğrenme kümesidir.

Çalışma şekli (512MB RAM dostu):
  1) GET /dnascan/start          → evren listesini kurar, durumu sıfırlar
  2) GET /dnascan/run?batch=15   → sıradaki N hisseyi işler, Gist'e yazar
     (cron-job.org bu adresi 10-15 dk arayla çağırırsa tarama
      kendiliğinden biter; elle de çağrılabilir)
  3) GET /dnascan/status         → ilerleme
  4) GET /dnascan/ozet           → havuz istatistikleri (A/B sayıları,
                                   medyanlar, en çok A üreten hisseler)
  5) GET /dnascan/retry          → hatalı hisseleri kuyruğa geri koyar

Kalıcılık: DNASCAN_GIST_ID + GITHUB_TOKEN ortam değişkenleri.
  DNASCAN_GIST_ID yoksa ilk kayıtta otomatik Gist oluşturulur ve
  cevapta kimliği döner → Render ortam değişkenine eklenmelidir,
  yoksa yeniden başlatmada ilerleme kaybolur (bellek-içi devam eder).

Bellek: hisse başına tek seferde bir DataFrame; işlenince bırakılır.
Olay kayıtları kompakt tutulur (yalnız temiz A/B; şüpheli, kenar ve
BELIRSIZ havuza girmez — öğrenme kümesi saf kalır).
═══════════════════════════════════════════════════════════════════
"""

import json
import os
import time
from typing import Callable, Dict, List

try:
    import requests
except Exception:
    requests = None

from dna_lab import etiketle, ONKAYIT

BASE_URL = (os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
DNASCAN_GIST_ID = (os.environ.get("DNASCAN_GIST_ID") or "").strip()
GITHUB_TOKEN = (os.environ.get("GITHUB_TOKEN") or "").strip()
GIST_DOSYA = "dnascan_state.json"

# bellek-içi durum (Gist yoksa da çalışsın; Gist varsa aynadır)
_STATE: Dict = {"kuruldu": False}


# ─── yardımcılar ────────────────────────────────────────────────
def _self_base():
    if BASE_URL:
        return BASE_URL
    return "http://127.0.0.1:" + str(os.environ.get("PORT", "10000"))


def _get_json(url, timeout=120):
    try:
        if requests is not None:
            r = requests.get(url, timeout=timeout)
            return r.json() if 200 <= r.status_code < 300 else None
    except Exception:
        pass
    return None


def _universe_symbols() -> List[str]:
    data = _get_json(_self_base() + "/scan?limit=900", timeout=120) or {}
    rows = data.get("sonuclar") or data.get("results") or data.get("rows") or []
    syms = []
    for r in rows:
        s = (r.get("sembol") or r.get("symbol") or "").upper().strip()
        if s and s not in syms:
            syms.append(s)
    return syms


def _gist_headers():
    return {"Authorization": "token " + GITHUB_TOKEN,
            "Accept": "application/vnd.github+json"} if GITHUB_TOKEN else None


def _gist_load() -> bool:
    """Gist'ten durumu belleğe çeker. Başarıysa True.
    1MB üstü dosyalar API cevabında KIRPILIR (truncated) — o durumda
    içerik raw_url'den tam olarak indirilir."""
    global _STATE
    hd = _gist_headers()
    if not (hd and DNASCAN_GIST_ID and requests):
        return False
    try:
        r = requests.get("https://api.github.com/gists/" + DNASCAN_GIST_ID,
                         headers=hd, timeout=90)
        if r.status_code == 200:
            files = r.json().get("files", {})
            if GIST_DOSYA in files:
                f = files[GIST_DOSYA]
                if f.get("truncated") and f.get("raw_url"):
                    rr = requests.get(f["raw_url"], headers=hd, timeout=120)
                    _STATE = json.loads(rr.text)
                else:
                    _STATE = json.loads(f["content"])
                return True
    except Exception:
        pass
    return False


def _gist_save() -> Dict:
    """Durumu Gist'e yazar. Gist yoksa oluşturur ve kimliği döndürür."""
    global DNASCAN_GIST_ID
    hd = _gist_headers()
    if not (hd and requests):
        return {"gist": "yok (GITHUB_TOKEN eksik) — bellek-içi mod"}
    icerik = {"files": {GIST_DOSYA: {"content": json.dumps(_STATE, ensure_ascii=False)}}}
    try:
        if DNASCAN_GIST_ID:
            requests.patch("https://api.github.com/gists/" + DNASCAN_GIST_ID,
                           headers=hd, json=icerik, timeout=30)
            return {"gist": "guncellendi", "gist_id": DNASCAN_GIST_ID}
        icerik["description"] = "Vortex-BIST DNA Scan havuzu"
        icerik["public"] = False
        r = requests.post("https://api.github.com/gists",
                          headers=hd, json=icerik, timeout=30)
        if r.status_code in (200, 201):
            DNASCAN_GIST_ID = r.json().get("id", "")
            return {"gist": "OLUSTURULDU — bunu Render'a DNASCAN_GIST_ID "
                            "olarak ekle!", "gist_id": DNASCAN_GIST_ID}
    except Exception as e:
        return {"gist": "hata: " + repr(e)}
    return {"gist": "yazilamadi"}


def _durum_hazirla():
    """Gist'ten yükle; yoksa bellek-içi başlangıç."""
    if not _STATE.get("kuruldu"):
        if not _gist_load():
            _STATE.update({"kuruldu": True, "bekleyen": [], "hatali": [],
                           "tamam": 0, "olaylar": [], "hisse_ozet": {},
                           "onkayit": ONKAYIT, "baslangic": None})


def _tek_hisse(sym: str, fetch_ohlc: Callable) -> Dict:
    """Bir hisseyi etiketler; kompakt olay listesi döndürür."""
    df = None
    try:
        df = fetch_ohlc(sym, period="max")
    except Exception:
        pass
    if df is None or len(df) < ONKAYIT["min_veri_gun"]:
        return {"hata": "veri"}
    out = etiketle(df)
    del df
    if "hata" in out:
        return {"hata": out["hata"]}
    olaylar = []
    for o in out["ralliler"]:
        if o["veri_suphesi"] or o["kenar_olayi"] or o["sinif"] == "BELIRSIZ":
            continue  # havuz saf kalır
        olaylar.append({
            "s": sym, "t0": o["t0_tarih"], "vt": o["vurus_tarih"],
            "g": o["gun_sayisi"], "mg": o["max_getiri_pct"],
            "dd": o["yol_dd_pct"], "derin": o["dip_derinligi_pct"],
            "yas": o["dusus_yasi_gun"], "sf": o["sinif"][0],  # "A" / "B"
        })
    oz = out["ozet"]
    return {"olaylar": olaylar,
            "ozet": {"a": oz["sinif_a_trend"], "b": oz["sinif_b_ziplama"],
                     "bar": oz["bar_sayisi"]}}


# ─── FastAPI kurulumu ───────────────────────────────────────────
def install_dna_scan(app, fetch_ohlc: Callable) -> None:
    from fastapi import Query

    @app.get("/dnascan/start")
    def dnascan_start():
        _durum_hazirla()
        syms = _universe_symbols()
        if len(syms) < 50:
            return {"hata": "evren alinamadi (/scan cevabi zayif)",
                    "bulunan": len(syms)}
        _STATE.update({"kuruldu": True, "bekleyen": syms, "hatali": [],
                       "tamam": 0, "olaylar": [], "hisse_ozet": {},
                       "onkayit": ONKAYIT,
                       "baslangic": time.strftime("%Y-%m-%d %H:%M")})
        g = _gist_save()
        return {"durum": "basladi", "evren": len(syms), **g}

    @app.get("/dnascan/run")
    def dnascan_run(batch: int = Query(15, ge=1, le=40)):
        _durum_hazirla()
        bek = _STATE.get("bekleyen", [])
        if not bek:
            return {"durum": "bitti-veya-baslatilmadi",
                    "ipucu": "/dnascan/start ile baslat",
                    "tamam": _STATE.get("tamam", 0)}
        islenen, hatali = [], []
        for _ in range(min(batch, len(bek))):
            sym = bek.pop(0)
            r = _tek_hisse(sym, fetch_ohlc)
            if "hata" in r:
                hatali.append(sym)
                _STATE["hatali"].append(sym)
            else:
                _STATE["olaylar"].extend(r["olaylar"])
                _STATE["hisse_ozet"][sym] = r["ozet"]
                _STATE["tamam"] = _STATE.get("tamam", 0) + 1
                islenen.append(sym)
            time.sleep(0.4)  # yfinance nezaketi
        g = _gist_save()
        return {"islenen": islenen, "hatali_bu_parti": hatali,
                "kalan": len(bek), "tamam": _STATE["tamam"],
                "havuz_olay": len(_STATE["olaylar"]), **g}

    @app.get("/dnascan/status")
    def dnascan_status():
        _durum_hazirla()
        ol = _STATE.get("olaylar", [])
        return {"kalan": len(_STATE.get("bekleyen", [])),
                "tamam": _STATE.get("tamam", 0),
                "hatali": len(_STATE.get("hatali", [])),
                "havuz_olay": len(ol),
                "a_trend": sum(1 for o in ol if o["sf"] == "A"),
                "b_ziplama": sum(1 for o in ol if o["sf"] == "B"),
                "baslangic": _STATE.get("baslangic"),
                "surum": ONKAYIT["surum"]}

    @app.get("/dnascan/retry")
    def dnascan_retry():
        _durum_hazirla()
        h = _STATE.get("hatali", [])
        _STATE["bekleyen"] = _STATE.get("bekleyen", []) + h
        _STATE["hatali"] = []
        g = _gist_save()
        return {"kuyruga_geri": len(h), **g}

    @app.get("/dnascan/ozet")
    def dnascan_ozet():
        _durum_hazirla()
        ol = _STATE.get("olaylar", [])
        if not ol:
            return {"hata": "havuz bos — once /dnascan/start ve /dnascan/run"}
        import numpy as np
        A = [o for o in ol if o["sf"] == "A"]
        B = [o for o in ol if o["sf"] == "B"]

        def med(evs, k):
            v = [e[k] for e in evs]
            return round(float(np.median(v)), 1) if v else None

        sayac = {}
        for e in A:
            sayac[e["s"]] = sayac.get(e["s"], 0) + 1
        en_cok_a = sorted(sayac.items(), key=lambda kv: -kv[1])[:15]

        return {"surum": ONKAYIT["surum"],
                "taranan_hisse": _STATE.get("tamam", 0),
                "a_trend": len(A), "b_ziplama": len(B),
                "A_profili": {"medyan_gun": med(A, "g"),
                              "medyan_max_getiri_pct": med(A, "mg"),
                              "medyan_dip_derinligi_pct": med(A, "derin"),
                              "medyan_dusus_yasi_gun": med(A, "yas")},
                "B_profili": {"medyan_gun": med(B, "g"),
                              "medyan_max_getiri_pct": med(B, "mg"),
                              "medyan_dip_derinligi_pct": med(B, "derin"),
                              "medyan_dusus_yasi_gun": med(B, "yas")},
                "en_cok_a_ureten": en_cok_a}

    print("[dna_scan] kuruldu: /dnascan/start · /dnascan/run · "
          "/dnascan/status · /dnascan/ozet · /dnascan/retry")
