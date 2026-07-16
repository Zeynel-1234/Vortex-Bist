# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
KAP SONDAJ — Vortex İz Motoru fizibilite ucu (tek atımlık)
═══════════════════════════════════════════════════════════════════
Amaç : Tam tarama motorunu (kap_iz) yazmadan önce iki kritik soruyu
       10 dakikada cevaplamak:
         1) KAP güvenlik duvarı Render'ın IP'sinden istek kabul
            ediyor mu? (WAF testi)
         2) Tarihsel derinlik ne kadar? (2012/2016/2020/2024/güncel
            pencerelerinden veri dönüyor mu?)

Kullanım: GET /kapsondaj
Çıktı  : pencere pencere → HTTP kodu, kayıt sayısı, "Pay Alım Satım
         Bildirimi" sayısı, "Geri Alım" sayısı, 2 örnek kayıt.

Hiçbir şey kaydetmez, hiçbir panele dokunmaz — saf teşhis cihazı.
Nezaket: istekler arası 0.7 sn, oturum ısınması (bildirim-sorgu GET),
gerekli Referer/User-Agent başlıkları (KAP keşif notlarına uygun).
═══════════════════════════════════════════════════════════════════
"""

import time

try:
    import requests
except Exception:
    requests = None

KAP = "https://www.kap.org.tr"
UA = "Mozilla/5.0 (Linux; Android 13) VortexIz/0.1 (arastirma)"

# sondaj pencereleri: derinlik merdiveni + güncel kontrol
PENCERELER = [
    ("2012-03-05", "2012-03-11"),
    ("2016-03-07", "2016-03-13"),
    ("2020-03-02", "2020-03-08"),
    ("2024-03-04", "2024-03-10"),
    ("2026-07-06", "2026-07-12"),
]


def _pencere_sorgula(ses, f, t):
    r = ses.post(
        KAP + "/tr/api/disclosure/members/byCriteria",
        json={"fromDate": f, "toDate": t,
              "mkkMemberOidList": [], "subjectList": []},
        headers={"Referer": KAP + "/tr/bildirim-sorgu",
                 "User-Agent": UA,
                 "Content-Type": "application/json"},
        timeout=30)
    kod = r.status_code
    if kod != 200:
        return {"pencere": f + " → " + t, "http": kod,
                "not": (r.text or "")[:120]}
    try:
        veri = r.json()
    except Exception:
        return {"pencere": f + " → " + t, "http": kod,
                "not": "JSON degil: " + (r.text or "")[:120]}
    if not isinstance(veri, list):
        return {"pencere": f + " → " + t, "http": kod,
                "not": "beklenmeyen govde"}
    pas = [d for d in veri
           if "Pay Alım Satım" in (d.get("subject") or "")]
    geri = [d for d in veri
            if "Geri Alım" in (d.get("subject") or "")
            or "Geri Alım" in (d.get("summary") or "")]
    ornekler = [{"t": d.get("publishDate"),
                 "hisse": d.get("relatedStocks") or d.get("stockCodes"),
                 "konu": (d.get("subject") or "")[:40]}
                for d in (pas[:2] or veri[:2])]
    return {"pencere": f + " → " + t, "http": kod,
            "toplam": len(veri), "tavan_2000": len(veri) >= 2000,
            "pay_alim_satim": len(pas), "geri_alim": len(geri),
            "ornek": ornekler}


def install_kap_sondaj(app) -> None:
    @app.get("/kapsondaj")
    def kap_sondaj():
        if requests is None:
            return {"hata": "requests yok"}
        ses = requests.Session()
        rapor = {"sondaj": []}
        # oturum ısınması: WAF çerezleri için
        try:
            r0 = ses.get(KAP + "/tr/bildirim-sorgu",
                         headers={"User-Agent": UA}, timeout=30)
            rapor["isinma_http"] = r0.status_code
        except Exception as e:
            rapor["isinma_http"] = "HATA: " + repr(e)[:100]
        for f, t in PENCERELER:
            try:
                rapor["sondaj"].append(_pencere_sorgula(ses, f, t))
            except Exception as e:
                rapor["sondaj"].append(
                    {"pencere": f + " → " + t,
                     "hata": repr(e)[:140]})
            time.sleep(0.7)
        # okuma anahtarı
        rapor["yorum"] = ("http=200 + toplam>0 olan en eski pencere = "
                          "tarihsel derinlik siniri. Tum pencereler "
                          "hata/403/timeout ise WAF Render IP'sini "
                          "engelliyor demektir → ScraperAPI yoluna "
                          "geceriz.")
        return rapor

    print("[kap_sondaj] kuruldu: GET /kapsondaj")
