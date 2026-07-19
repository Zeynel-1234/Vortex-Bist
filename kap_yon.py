# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
KAP YÖN · VORTEX İZ MOTORU — Aşama 2b (içeriden işlem YÖNÜ)
═══════════════════════════════════════════════════════════════════
Amaç : DKB sınıfı "Pay Alım Satım Bildirimi"lerinden (yönetici/ilişkili
       kişi formları — fon gürültüsü ODA kaynağında elenir) havuz
       olaylarının pencereleriyle kesişenlerin YÖNÜNÜ (Alış/Satış)
       çıkarmak ve şu soruyu cevaplamak:

       "T0-öncesi 60 günde içeriden NET ALIŞ olan olayların gerçek
        trend (A) olma oranı, olmayanlardan anlamlı derecede yüksek mi?"

Veri kapıları (sondaj-3 ile CANLI DOĞRULANDI):
  · Liste : POST /tr/api/disclosure/members/byCriteria (DKB süzme istemcide)
  · Detay : GET /tr/api/notification/export/excel/{id} (3-4KB, hızlı)
            GET /tr/api/BildirimPdf/{id} (yedek; pypdf ile metin)
  Kodlama: utf-8 / windows-1254 / iso-8859-9 sırayla denenir.

ÖN-KAYIT: pencere 60/21 takvim günü · çağ sınırı 2018-01-01 ·
  yön kuralı: metindeki "Alış" sayısı > "Satış" sayısı → ALIŞ;
  tersi → SATIŞ; eşit/sıfır → BELİRSİZ (teste girmez).

Akış:
  GET /kapyon/ornek?id=…  → tek bildirimde kaynakların okunabilirliği
  GET /kapyon/start       → tarama kuyruğu (5 günlük pencereler)
  GET /kapyon/run?batch=… → FAZ 1 tarama: pencere→eşleşen DKB kimlikleri
                            FAZ 2 detay: kimlik→yön (otomatik geçiş)
  GET /kapyon/status · /kapyon/ozet · /kapyon/retry
Kalıcılık: KAPYON_GIST_ID + GITHUB_TOKEN (kırpılma-dayanıklı).
Gereksinim: requirements.txt'e "pypdf" satırı eklenmelidir (PDF yedeği).
Saf laboratuvar — sinyal/karar ekranlarına dokunmaz.
═══════════════════════════════════════════════════════════════════
"""

import io
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Dict, List

try:
    import requests
except Exception:
    requests = None
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

KAP = "https://www.kap.org.tr"
UA = "Mozilla/5.0 (Linux; Android 13) VortexIz/2b (arastirma)"

KAPYON_GIST_ID = (os.environ.get("KAPYON_GIST_ID") or "").strip()
GITHUB_TOKEN = (os.environ.get("GITHUB_TOKEN") or "").strip()
GIST_DOSYA = "kapyon_state.json"

ONKAYIT = {"baslangic": "2010-01-01", "pencere_gun": 5,
           "pencere_uzun": 60, "pencere_kisa": 21,
           "cag_siniri": "2018-01-01", "surum": "kap_yon_v1.0"}

_STATE: Dict = {"kuruldu": False}
_SES = None


# ─── Gist (kırpılma-dayanıklı) ──────────────────────────────────
def _hd_git():
    return {"Authorization": "token " + GITHUB_TOKEN,
            "Accept": "application/vnd.github+json"} if GITHUB_TOKEN else None


def _gist_load() -> bool:
    global _STATE
    hd = _hd_git()
    if not (hd and KAPYON_GIST_ID and requests):
        return False
    try:
        r = requests.get("https://api.github.com/gists/" + KAPYON_GIST_ID,
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
    global KAPYON_GIST_ID
    hd = _hd_git()
    if not (hd and requests):
        return {"gist": "yok (GITHUB_TOKEN eksik)"}
    icerik = {"files": {GIST_DOSYA: {
        "content": json.dumps(_STATE, ensure_ascii=False)}}}
    try:
        if KAPYON_GIST_ID:
            r = requests.patch("https://api.github.com/gists/" + KAPYON_GIST_ID,
                               headers=hd, json=icerik, timeout=60)
            if 200 <= r.status_code < 300:
                return {"gist": "guncellendi", "gist_id": KAPYON_GIST_ID}
            return {"gist": "PATCH hatasi " + str(r.status_code)}
        icerik["description"] = "Vortex-BIST KAP Yon havuzu"
        icerik["public"] = False
        r = requests.post("https://api.github.com/gists",
                          headers=hd, json=icerik, timeout=60)
        if r.status_code in (200, 201):
            KAPYON_GIST_ID = r.json().get("id", "")
            return {"gist": "OLUSTURULDU — Render'a KAPYON_GIST_ID ekle!",
                    "gist_id": KAPYON_GIST_ID}
    except Exception as e:
        return {"gist": "hata: " + repr(e)[:90]}
    return {"gist": "yazilamadi"}


def _durum_hazirla():
    if not _STATE.get("kuruldu"):
        if not _gist_load():
            _STATE.update({"kuruldu": True, "faz": "tarama",
                           "bekleyen": [], "detay_kuyruk": [],
                           "hatali": [], "tamam": 0, "detay_tamam": 0,
                           "yonler": [], "pencere_haritasi": {},
                           "onkayit": ONKAYIT, "baslangic_ts": None})


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


# ─── yön çıkarımı ───────────────────────────────────────────────
def _coz(icerik: bytes) -> str:
    for kod in ("utf-8", "windows-1254", "iso-8859-9"):
        try:
            m = icerik.decode(kod)
            if "Alı" in m or "Satı" in m or "<" in m:
                return m
        except Exception:
            continue
    return icerik.decode("utf-8", "ignore")


def _yon_say(metin: str) -> Dict:
    a = len(re.findall(r"Alış", metin))
    s = len(re.findall(r"Satış", metin))
    return {"alis": a, "satis": s,
            "yon": "ALIS" if a > s else ("SATIS" if s > a else "BELIRSIZ")}


def _detay_yon(bid: str) -> Dict:
    """Excel dene → yön yoksa PDF dene. {yon, kaynak} döndürür."""
    ses = _oturum()
    hg = {"User-Agent": UA, "Referer": KAP + "/tr/Bildirim/" + str(bid)}
    try:
        r = ses.get(KAP + "/tr/api/notification/export/excel/" + str(bid),
                    headers=hg, timeout=40)
        if r.status_code == 200 and r.content:
            y = _yon_say(_coz(r.content))
            if y["yon"] != "BELIRSIZ":
                y["kaynak"] = "excel"
                return y
    except Exception:
        pass
    if PdfReader is not None:
        try:
            r = ses.get(KAP + "/tr/api/BildirimPdf/" + str(bid),
                        headers=hg, timeout=60)
            if r.status_code == 200 and (r.content or b"")[:4] == b"%PDF":
                metin = ""
                pdf = PdfReader(io.BytesIO(r.content))
                for sf in pdf.pages[:6]:
                    metin += sf.extract_text() or ""
                y = _yon_say(metin)
                y["kaynak"] = "pdf"
                return y
        except Exception:
            pass
    return {"yon": "BELIRSIZ", "kaynak": "yok", "alis": 0, "satis": 0}


_KOD_RE = re.compile(r"^[A-Z0-9]{3,6}$")


def _hisseler(kayit) -> List[str]:
    ham = (kayit.get("relatedStocks") or kayit.get("stockCodes") or "")
    out = []
    for p in str(ham).split(","):
        p = p.strip().upper()
        if _KOD_RE.match(p) and p not in out:
            out.append(p)
    return out


def _pencere_haritasi_kur() -> Dict[str, List]:
    """dna_scan havuzundan: hisse → [(pencere_bas, t0), ...]"""
    try:
        import dna_scan as _ds
        _ds._durum_hazirla()
        olaylar = _ds._STATE.get("olaylar") or []
    except Exception:
        olaylar = []
    hari: Dict[str, List] = {}
    u = ONKAYIT["pencere_uzun"]
    for o in olaylar:
        try:
            t0 = date.fromisoformat(o["t0"])
        except Exception:
            continue
        hari.setdefault(o["s"], []).append(
            [str(t0 - timedelta(days=u)), o["t0"]])
    return hari


def _faz1_pencere(f: str, t: str) -> Dict:
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
        return {"hata": "govde"}
    if len(veri) >= 2000 and f != t:
        return {"bol": True}
    hari = _STATE.get("pencere_haritasi", {})
    yeni = 0
    for d in veri:
        if "Pay Alım Satım" not in (d.get("subject") or ""):
            continue
        if str(d.get("disclosureClass")) != "DKB":
            continue  # fon/kurum gürültüsü (ODA) kaynağında elenir
        try:
            gun = str(datetime.strptime(
                (d.get("publishDate") or "").split(" ")[0],
                "%d.%m.%Y").date())
        except Exception:
            continue
        bid = d.get("disclosureIndex")
        if not bid:
            continue
        eslesti = False
        for h in _hisseler(d):
            for (bas, t0) in hari.get(h, []):
                if bas <= gun < t0:      # pencere içi (T0 hariç)
                    _STATE["detay_kuyruk"].append(
                        {"id": str(bid), "h": h, "g": gun})
                    yeni += 1
                    eslesti = True
                    break
            if eslesti:
                break
    return {"yeni": yeni}


# ─── FastAPI ────────────────────────────────────────────────────
def install_kap_yon(app) -> None:
    from fastapi import Query

    @app.get("/kapyon/ornek")
    def kapyon_ornek(id: str = Query("1633516")):
        """Tek bildirimde kaynakların okunabilirlik raporu (teşhis)."""
        ses = _oturum()
        hg = {"User-Agent": UA, "Referer": KAP + "/tr/Bildirim/" + id}
        rapor = {"id": id, "pypdf": PdfReader is not None}
        try:
            r = ses.get(KAP + "/tr/api/notification/export/excel/" + id,
                        headers=hg, timeout=40)
            m = _coz(r.content or b"")
            rapor["excel"] = {"http": r.status_code,
                              "boyut": len(r.content or b""),
                              **_yon_say(m), "parca": m[:250]}
        except Exception as e:
            rapor["excel"] = {"hata": repr(e)[:90]}
        time.sleep(0.7)
        try:
            r = ses.get(KAP + "/tr/api/BildirimPdf/" + id,
                        headers=hg, timeout=60)
            p = {"http": r.status_code,
                 "boyut": len(r.content or b""),
                 "pdf_mi": (r.content or b"")[:4] == b"%PDF"}
            if p["pdf_mi"] and PdfReader is not None:
                pdf = PdfReader(io.BytesIO(r.content))
                metin = ""
                for sf in pdf.pages[:6]:
                    metin += sf.extract_text() or ""
                p.update(_yon_say(metin))
                p["parca"] = metin[:250]
            rapor["pdf"] = p
        except Exception as e:
            rapor["pdf"] = {"hata": repr(e)[:90]}
        rapor["karar"] = _detay_yon(id)
        return rapor

    @app.get("/kapyon/start")
    def kapyon_start():
        _durum_hazirla()
        hari = _pencere_haritasi_kur()
        if not hari:
            return {"hata": "dna_scan havuzu okunamadi",
                    "ipucu": "once /dnascan/status ac"}
        pencereler = []
        gun = date.fromisoformat(ONKAYIT["baslangic"])
        bugun = date.today()
        adim = timedelta(days=ONKAYIT["pencere_gun"] - 1)
        while gun <= bugun:
            son = min(gun + adim, bugun)
            pencereler.append([str(gun), str(son)])
            gun = son + timedelta(days=1)
        _STATE.update({"kuruldu": True, "faz": "tarama",
                       "bekleyen": pencereler, "detay_kuyruk": [],
                       "hatali": [], "tamam": 0, "detay_tamam": 0,
                       "yonler": [], "pencere_haritasi": hari,
                       "onkayit": ONKAYIT,
                       "baslangic_ts": time.strftime("%Y-%m-%d %H:%M")})
        g = _gist_save()
        return {"durum": "basladi", "pencere": len(pencereler),
                "izlenen_hisse": len(hari), **g}

    @app.get("/kapyon/run")
    def kapyon_run(batch: int = Query(15, ge=1, le=50)):
        _durum_hazirla()
        faz = _STATE.get("faz", "tarama")
        if faz == "tarama":
            bek = _STATE.get("bekleyen", [])
            if not bek:
                _STATE["faz"] = "detay"
                g = _gist_save()
                return {"durum": "FAZ 2'ye gecildi (detay)",
                        "detay_kuyruk": len(_STATE["detay_kuyruk"]), **g}
            islenen = bolunen = hatali = 0
            adim = 0
            while adim < batch and bek:
                adim += 1
                f, t = bek.pop(0)
                try:
                    r = _faz1_pencere(f, t)
                except Exception as e:
                    r = {"hata": repr(e)[:70]}
                if r.get("bol"):
                    fd, td = date.fromisoformat(f), date.fromisoformat(t)
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
            return {"faz": "tarama", "islenen": islenen,
                    "bolunen": bolunen, "hatali": hatali,
                    "kalan": len(bek),
                    "detay_kuyruk": len(_STATE["detay_kuyruk"]), **g}
        # ── FAZ 2 — detay/yön ──
        kuyruk = _STATE.get("detay_kuyruk", [])
        if not kuyruk:
            return {"durum": "bitti",
                    "yon_kaydi": len(_STATE.get("yonler", []))}
        islenen = 0
        adim = 0
        while adim < batch and kuyruk:
            adim += 1
            k = kuyruk.pop(0)
            y = _detay_yon(k["id"])
            _STATE["yonler"].append({"h": k["h"], "g": k["g"],
                                     "yon": y["yon"],
                                     "kaynak": y.get("kaynak")})
            _STATE["detay_tamam"] = _STATE.get("detay_tamam", 0) + 1
            islenen += 1
            time.sleep(0.8)
        g = _gist_save()
        alis = sum(1 for y in _STATE["yonler"] if y["yon"] == "ALIS")
        return {"faz": "detay", "islenen": islenen,
                "kalan": len(kuyruk),
                "yon_kaydi": len(_STATE["yonler"]),
                "alis": alis, **g}

    @app.get("/kapyon/status")
    def kapyon_status():
        _durum_hazirla()
        yn = _STATE.get("yonler", [])
        return {"faz": _STATE.get("faz"),
                "tarama_kalan": len(_STATE.get("bekleyen", [])),
                "tarama_tamam": _STATE.get("tamam", 0),
                "detay_kuyruk": len(_STATE.get("detay_kuyruk", [])),
                "detay_tamam": _STATE.get("detay_tamam", 0),
                "hatali": len(_STATE.get("hatali", [])),
                "alis": sum(1 for y in yn if y["yon"] == "ALIS"),
                "satis": sum(1 for y in yn if y["yon"] == "SATIS"),
                "belirsiz": sum(1 for y in yn if y["yon"] == "BELIRSIZ"),
                "surum": ONKAYIT["surum"]}

    @app.get("/kapyon/retry")
    def kapyon_retry():
        _durum_hazirla()
        h = _STATE.get("hatali", [])
        _STATE["bekleyen"] = h + _STATE.get("bekleyen", [])
        _STATE["hatali"] = []
        if h:
            _STATE["faz"] = "tarama"
        g = _gist_save()
        return {"kuyruga_geri": len(h), **g}

    @app.get("/kapyon/ozet")
    def kapyon_ozet():
        _durum_hazirla()
        yn = _STATE.get("yonler", [])
        if len(yn) < 50:
            return {"hata": "yon kaydi az", "kayit": len(yn)}
        try:
            import dna_scan as _ds
            _ds._durum_hazirla()
            olaylar = _ds._STATE.get("olaylar") or []
        except Exception:
            olaylar = []
        if not olaylar:
            return {"hata": "dna_scan havuzu okunamadi",
                    "ipucu": "once /dnascan/status ac"}
        alis, satis = {}, {}
        for y in yn:
            if y["yon"] == "ALIS":
                alis.setdefault(y["h"], set()).add(y["g"])
            elif y["yon"] == "SATIS":
                satis.setdefault(y["h"], set()).add(y["g"])
        u, kk = ONKAYIT["pencere_uzun"], ONKAYIT["pencere_kisa"]

        def _say(izler, t0d, gun):
            return sum(1 for j in range(1, gun + 1)
                       if str(t0d - timedelta(days=j)) in izler)

        kayit = []
        for o in olaylar:
            try:
                t0d = date.fromisoformat(o["t0"])
            except Exception:
                continue
            s = o["s"]
            a60 = _say(alis.get(s, set()), t0d, u)
            s60 = _say(satis.get(s, set()), t0d, u)
            kayit.append({"sf": o["sf"], "t0": o["t0"],
                          "alis60": a60,
                          "alis21": _say(alis.get(s, set()), t0d, kk),
                          "net60": 1 if a60 > s60 else 0})
        A = [x for x in kayit if x["sf"] == "A"]
        B = [x for x in kayit if x["sf"] == "B"]
        if len(A) < 100 or len(B) < 100:
            return {"hata": "eslesme az", "a": len(A), "b": len(B)}

        def _blok(alan, ga, gb):
            na = sum(1 for x in ga if x[alan] > 0)
            nb = sum(1 for x in gb if x[alan] > 0)
            pa, pb = na / len(ga), nb / len(gb)
            p = (na + nb) / (len(ga) + len(gb))
            se = (p * (1 - p) * (1 / len(ga) + 1 / len(gb))) ** 0.5 \
                if 0 < p < 1 else 0
            return {"A_oran": round(pa, 4), "B_oran": round(pb, 4),
                    "lift": round(pa / pb, 2) if pb > 0 else None,
                    "z": round((pa - pb) / se, 2) if se > 0 else None}

        cs = ONKAYIT["cag_siniri"]
        Ae = [x for x in A if x["t0"] < cs]
        Be = [x for x in B if x["t0"] < cs]
        Ay = [x for x in A if x["t0"] >= cs]
        By = [x for x in B if x["t0"] >= cs]
        out = {"surum": ONKAYIT["surum"], "a_olay": len(A),
               "b_olay": len(B), "yon_kaydi": len(yn),
               "alis60": _blok("alis60", A, B),
               "alis21": _blok("alis21", A, B),
               "net_alis60": _blok("net60", A, B)}
        if len(Ae) >= 50 and len(Be) >= 50:
            out["alis60_2010_17"] = _blok("alis60", Ae, Be)
        if len(Ay) >= 50 and len(By) >= 50:
            out["alis60_2018_26"] = _blok("alis60", Ay, By)
        out["okuma"] = ("alis60 lift>1.3 + iki cagda ayni yon → ikinci iz "
                        "dogrulandi. Geri alim bayragiyla birlikte Iz "
                        "Skoru'nun cekirdegi kurulur.")
        return out

    print("[kap_yon] kuruldu: /kapyon/ornek · /kapyon/start · /kapyon/run "
          "· /kapyon/status · /kapyon/ozet · /kapyon/retry")
