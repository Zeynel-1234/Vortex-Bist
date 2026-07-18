# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
KAP İZ · VORTEX İZ MOTORU — Aşama 1 (varlık/yoğunluk testi)
═══════════════════════════════════════════════════════════════════
Amaç : KAP'tan tüm tarih boyunca (2010→bugün) "Pay Alım Satım
       Bildirimi" (içeriden işlem) ve "Geri Alım" izlerini toplayıp
       dna_scan havuzundaki 10.000 olayla eşleştirmek ve şu soruyu
       cevaplamak:

       "A trendlerinin T0'ından önceki 60/21 günde içeriden işlem
        bildirimi olma sıklığı, B zıplamalarından anlamlı derecede
        yüksek mi?"

ÖN-KAYIT (mühürlü):
  · pencere_uzun = 60 takvim günü (T0-60 … T0-1)
  · pencere_kisa = 21 takvim günü (T0-21 … T0-1)
  · konu süzgeçleri: subject "Pay Alım Satım" içerir → PAS;
    subject/summary "Geri Alım" içerir → GERI
  · çağ sınırı: 2018-01-01 (istikrar sınavı)
  · Aşama 1 yön ayrımı YAPMAZ (alış/satış) — o Aşama 2'dir ve ancak
    Aşama 1 sinyal verirse detay sayfalarına inilir.

Akış (tanıdık kalıp):
  GET /kapiz/start        → 2010'dan bugüne 5 günlük pencere kuyruğu
  GET /kapiz/run?batch=20 → sıradaki pencereleri sorgular; 2000
                            tavanına çarpan pencereyi İKİYE BÖLÜP
                            kuyruğa geri koyar; izleri Gist'e yazar
  GET /kapiz/status       → ilerleme
  GET /kapiz/ozet         → havuz eşleştirmesi: A vs B oran/lift/AUC
                            + çift-çağ istikrarı
  GET /kapiz/retry        → hatalı pencereleri kuyruğa geri koyar

Kalıcılık: KAPIZ_GIST_ID + GITHUB_TOKEN (kırpılmış-gist okuyucu dahil)
Nezaket : istek arası 0.7 sn, oturum ısınması, Referer/UA başlıkları.
Bu modül saf laboratuvardır — hiçbir sinyal/karar ekranına dokunmaz.
═══════════════════════════════════════════════════════════════════
"""

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Dict, List

import numpy as np

try:
    import requests
except Exception:
    requests = None

KAP = "https://www.kap.org.tr"
UA = "Mozilla/5.0 (Linux; Android 13) VortexIz/1.0 (arastirma)"

KAPIZ_GIST_ID = (os.environ.get("KAPIZ_GIST_ID") or "").strip()
GITHUB_TOKEN = (os.environ.get("GITHUB_TOKEN") or "").strip()
GIST_DOSYA = "kapiz_state.json"

ONKAYIT = {
    "baslangic": "2010-01-01",
    "pencere_gun": 5,
    "pencere_uzun": 60,
    "pencere_kisa": 21,
    "cag_siniri": "2018-01-01",
    "surum": "kap_iz_v1.0",
}

_STATE: Dict = {"kuruldu": False}
_SES = None


# ─── Gist (kırpılma-dayanıklı) ──────────────────────────────────
def _hd():
    return {"Authorization": "token " + GITHUB_TOKEN,
            "Accept": "application/vnd.github+json"} if GITHUB_TOKEN else None


def _gist_load() -> bool:
    global _STATE
    hd = _hd()
    if not (hd and KAPIZ_GIST_ID and requests):
        return False
    try:
        r = requests.get("https://api.github.com/gists/" + KAPIZ_GIST_ID,
                         headers=hd, timeout=90)
        if r.status_code == 200:
            f = r.json().get("files", {}).get(GIST_DOSYA)
            if f:
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
    global KAPIZ_GIST_ID
    hd = _hd()
    if not (hd and requests):
        return {"gist": "yok (GITHUB_TOKEN eksik) — bellek-içi mod"}
    icerik = {"files": {GIST_DOSYA: {
        "content": json.dumps(_STATE, ensure_ascii=False)}}}
    try:
        if KAPIZ_GIST_ID:
            r = requests.patch(
                "https://api.github.com/gists/" + KAPIZ_GIST_ID,
                headers=hd, json=icerik, timeout=60)
            if 200 <= r.status_code < 300:
                return {"gist": "guncellendi", "gist_id": KAPIZ_GIST_ID}
            return {"gist": "PATCH hatasi kod=" + str(r.status_code)}
        icerik["description"] = "Vortex-BIST KAP Iz havuzu"
        icerik["public"] = False
        r = requests.post("https://api.github.com/gists",
                          headers=hd, json=icerik, timeout=60)
        if r.status_code in (200, 201):
            KAPIZ_GIST_ID = r.json().get("id", "")
            return {"gist": "OLUSTURULDU — Render'a KAPIZ_GIST_ID "
                            "olarak ekle!", "gist_id": KAPIZ_GIST_ID}
    except Exception as e:
        return {"gist": "hata: " + repr(e)[:100]}
    return {"gist": "yazilamadi"}


def _durum_hazirla():
    if not _STATE.get("kuruldu"):
        if not _gist_load():
            _STATE.update({"kuruldu": True, "bekleyen": [], "hatali": [],
                           "tamam": 0, "pas": {}, "geri": {},
                           "onkayit": ONKAYIT, "baslangic_ts": None})


# ─── KAP sorgusu ────────────────────────────────────────────────
def _oturum():
    global _SES
    if _SES is None and requests is not None:
        _SES = requests.Session()
        try:
            _SES.get(KAP + "/tr/bildirim-sorgu",
                     headers={"User-Agent": UA}, timeout=30)
        except Exception:
            pass
    return _SES


_KOD_RE = re.compile(r"^[A-Z0-9]{3,6}$")


def _hisse_ayikla(kayit) -> List[str]:
    ham = (kayit.get("relatedStocks") or kayit.get("stockCodes") or "")
    out = []
    for p in str(ham).split(","):
        p = p.strip().upper()
        if _KOD_RE.match(p) and p not in out:
            out.append(p)
    return out


def _pencere_isle(f: str, t: str) -> Dict:
    ses = _oturum()
    r = ses.post(KAP + "/tr/api/disclosure/members/byCriteria",
                 json={"fromDate": f, "toDate": t,
                       "mkkMemberOidList": [], "subjectList": []},
                 headers={"Referer": KAP + "/tr/bildirim-sorgu",
                          "User-Agent": UA,
                          "Content-Type": "application/json"},
                 timeout=40)
    if r.status_code != 200:
        return {"hata": "http " + str(r.status_code)}
    veri = r.json()
    if not isinstance(veri, list):
        return {"hata": "beklenmeyen govde"}
    if len(veri) >= 2000 and f != t:
        return {"bol": True}          # tavana çarptı → pencereyi böl
    pas_n = geri_n = 0
    for d in veri:
        konu = d.get("subject") or ""
        ozet = d.get("summary") or ""
        pd_ = d.get("publishDate") or ""
        try:
            gun = datetime.strptime(pd_.split(" ")[0], "%d.%m.%Y").date()
        except Exception:
            continue
        g = str(gun)
        if "Pay Alım Satım" in konu:
            for h in _hisse_ayikla(d):
                lst = _STATE["pas"].setdefault(h, [])
                if g not in lst:
                    lst.append(g)
                    pas_n += 1
        if "Geri Alım" in konu or "Geri Alım" in ozet:
            for h in _hisse_ayikla(d):
                lst = _STATE["geri"].setdefault(h, [])
                if g not in lst:
                    lst.append(g)
                    geri_n += 1
    return {"pas": pas_n, "geri": geri_n, "toplam": len(veri)}


# ─── FastAPI ────────────────────────────────────────────────────
def install_kap_iz(app) -> None:
    from fastapi import Query

    @app.get("/kapiz/start")
    def kapiz_start():
        _durum_hazirla()
        pencereler = []
        gun = date.fromisoformat(ONKAYIT["baslangic"])
        bugun = date.today()
        adim = timedelta(days=ONKAYIT["pencere_gun"] - 1)
        while gun <= bugun:
            son = min(gun + adim, bugun)
            pencereler.append([str(gun), str(son)])
            gun = son + timedelta(days=1)
        _STATE.update({"kuruldu": True, "bekleyen": pencereler,
                       "hatali": [], "tamam": 0, "pas": {}, "geri": {},
                       "onkayit": ONKAYIT,
                       "baslangic_ts": time.strftime("%Y-%m-%d %H:%M")})
        g = _gist_save()
        return {"durum": "basladi", "pencere": len(pencereler), **g}

    @app.get("/kapiz/run")
    def kapiz_run(batch: int = Query(20, ge=1, le=60)):
        _durum_hazirla()
        bek = _STATE.get("bekleyen", [])
        if not bek:
            return {"durum": "bitti-veya-baslatilmadi",
                    "ipucu": "/kapiz/start ile baslat",
                    "tamam": _STATE.get("tamam", 0)}
        islenen = 0
        bolunen = 0
        hatali = 0
        adim = 0
        while adim < batch and bek:
            adim += 1
            f, t = bek.pop(0)
            try:
                r = _pencere_isle(f, t)
            except Exception as e:
                r = {"hata": repr(e)[:80]}
            if r.get("bol"):
                # pencereyi ikiye böl, kuyruğun BAŞINA koy
                fd = date.fromisoformat(f)
                td = date.fromisoformat(t)
                orta = fd + (td - fd) / 2
                bek.insert(0, [str(orta + timedelta(days=1)), t])
                bek.insert(0, [f, str(orta)])
                bolunen += 1
            elif "hata" in r:
                _STATE["hatali"].append([f, t])
                hatali += 1
            else:
                _STATE["tamam"] = _STATE.get("tamam", 0) + 1
                islenen += 1
            time.sleep(0.7)
        g = _gist_save()
        pas_toplam = sum(len(v) for v in _STATE["pas"].values())
        return {"islenen": islenen, "bolunen": bolunen,
                "hatali": hatali, "kalan": len(bek),
                "tamam": _STATE["tamam"],
                "pas_iz": pas_toplam,
                "geri_iz": sum(len(v) for v in _STATE["geri"].values()),
                **g}

    @app.get("/kapiz/status")
    def kapiz_status():
        _durum_hazirla()
        return {"kalan": len(_STATE.get("bekleyen", [])),
                "tamam": _STATE.get("tamam", 0),
                "hatali": len(_STATE.get("hatali", [])),
                "pas_iz": sum(len(v) for v in _STATE.get("pas", {}).values()),
                "geri_iz": sum(len(v) for v in _STATE.get("geri", {}).values()),
                "hisse_pas": len(_STATE.get("pas", {})),
                "surum": ONKAYIT["surum"]}

    @app.get("/kapiz/retry")
    def kapiz_retry():
        _durum_hazirla()
        h = _STATE.get("hatali", [])
        _STATE["bekleyen"] = h + _STATE.get("bekleyen", [])
        _STATE["hatali"] = []
        g = _gist_save()
        return {"kuyruga_geri": len(h), **g}

    @app.get("/kapiz/ozet")
    def kapiz_ozet():
        _durum_hazirla()
        if not _STATE.get("pas"):
            return {"hata": "iz havuzu bos — once /kapiz/start ve run"}
        # dna_scan olay havuzunu al (bellek → gist)
        olaylar = None
        try:
            import dna_scan as _ds
            _ds._durum_hazirla()
            olaylar = _ds._STATE.get("olaylar")
        except Exception:
            pass
        if not olaylar:
            return {"hata": "dna_scan havuzu okunamadi",
                    "ipucu": "/dnascan/status'u bir kez ac, sonra tekrar dene"}

        pas = {h: set(v) for h, v in _STATE["pas"].items()}
        geri = {h: set(v) for h, v in _STATE["geri"].items()}
        u, k = ONKAYIT["pencere_uzun"], ONKAYIT["pencere_kisa"]

        def _say(izler, t0d, gun):
            n = 0
            for j in range(1, gun + 1):
                if str(t0d - timedelta(days=j)) in izler:
                    n += 1
            return n

        kayit = []
        for o in olaylar:
            try:
                t0d = date.fromisoformat(o["t0"])
            except Exception:
                continue
            s = o["s"]
            kayit.append({
                "sf": o["sf"], "t0": o["t0"],
                "pas60": _say(pas.get(s, set()), t0d, u),
                "pas21": _say(pas.get(s, set()), t0d, k),
                "geri60": _say(geri.get(s, set()), t0d, u),
            })

        A = [x for x in kayit if x["sf"] == "A"]
        B = [x for x in kayit if x["sf"] == "B"]
        if len(A) < 100 or len(B) < 100:
            return {"hata": "eslesme az", "a": len(A), "b": len(B)}

        def _auc(av, bv):
            import pandas as pd
            hepsi = np.concatenate([av, bv])
            sira = pd.Series(hepsi).rank().values
            uu = sira[:len(av)].sum() - len(av) * (len(av) + 1) / 2.0
            return round(float(uu / (len(av) * len(bv))), 3)

        def _blok(alan, grup_a, grup_b):
            av = np.array([x[alan] for x in grup_a], float)
            bv = np.array([x[alan] for x in grup_b], float)
            oa = float((av > 0).mean())
            ob = float((bv > 0).mean())
            return {"A_oran": round(oa, 4), "B_oran": round(ob, 4),
                    "lift": round(oa / ob, 2) if ob > 0 else None,
                    "A_ort_adet": round(float(av.mean()), 3),
                    "B_ort_adet": round(float(bv.mean()), 3),
                    "auc": _auc(av, bv)}

        def _z(alan, ga, gb):
            """iki-oran z testi: fark şansla mı?"""
            a1 = sum(1 for x in ga if x[alan] > 0)
            b1 = sum(1 for x in gb if x[alan] > 0)
            n1, n2 = len(ga), len(gb)
            if min(n1, n2) < 30 or (a1 + b1) == 0:
                return None
            p1, p2 = a1 / n1, b1 / n2
            p = (a1 + b1) / (n1 + n2)
            se = (p * (1 - p) * (1 / n1 + 1 / n2)) ** 0.5
            return round((p1 - p2) / se, 2) if se > 0 else None

        cs = ONKAYIT["cag_siniri"]
        Ae = [x for x in A if x["t0"] < cs]
        Be = [x for x in B if x["t0"] < cs]
        Ay = [x for x in A if x["t0"] >= cs]
        By = [x for x in B if x["t0"] >= cs]

        out = {"surum": ONKAYIT["surum"] + "+ozet1.1",
               "a_olay": len(A), "b_olay": len(B),
               "pas60": _blok("pas60", A, B),
               "pas21": _blok("pas21", A, B),
               "geri60": _blok("geri60", A, B)}
        out["geri60"]["z"] = _z("geri60", A, B)
        if len(Ae) >= 50 and len(Be) >= 50:
            out["pas60_2010_17"] = _blok("pas60", Ae, Be)
            ge = _blok("geri60", Ae, Be)
            ge["z"] = _z("geri60", Ae, Be)
            out["geri60_2010_17"] = ge
        if len(Ay) >= 50 and len(By) >= 50:
            out["pas60_2018_26"] = _blok("pas60", Ay, By)
            gy = _blok("geri60", Ay, By)
            gy["z"] = _z("geri60", Ay, By)
            out["geri60_2018_26"] = gy
        out["okuma"] = ("lift>1.3 ve iki cagda ayni yon → iz gercek. "
                        "lift~1.0 → iceriden islem VARLIGI ayirmiyor; "
                        "Asama 2'de YON (alis/satis) ayrimina gecilir.")
        return out

    print("[kap_iz] kuruldu: /kapiz/start · /kapiz/run · /kapiz/status "
          "· /kapiz/ozet · /kapiz/retry")
