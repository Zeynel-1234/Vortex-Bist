# -*- coding: utf-8 -*-
"""
KAP YÖN SONDAJI v2 — detay API kapısı ve sınıf haritası keşfi
  1) PAS kayıtlarının disclosureClass/Type dağılımı (yönetici formu hangi sınıfta?)
  2) Süzgeç testi: byCriteria + veriden öğrenilen sınıf değeri
  3) Bir disclosureIndex için 6 aday detay kapısı: durum/tür/ilk baytlar/yön metni
Kullanım: GET /kapyonsondaj2 — saf teşhis, hiçbir şey kaydetmez.
"""
import time
try:
    import requests
except Exception:
    requests = None

KAP = "https://www.kap.org.tr"
UA = "Mozilla/5.0 (Linux; Android 13) VortexIz/2.1 (arastirma)"


def install_kap_yon_sondaj2(app) -> None:
    @app.get("/kapyonsondaj2")
    def kap_yon_sondaj2():
        if requests is None:
            return {"hata": "requests yok"}
        ses = requests.Session()
        try:
            ses.get(KAP + "/tr/bildirim-sorgu",
                    headers={"User-Agent": UA}, timeout=30)
        except Exception:
            pass
        hd = {"Referer": KAP + "/tr/bildirim-sorgu",
              "User-Agent": UA, "Content-Type": "application/json"}
        rapor = {}
        try:
            r = ses.post(KAP + "/tr/api/disclosure/members/byCriteria",
                         json={"fromDate": "2026-07-09", "toDate": "2026-07-15",
                               "mkkMemberOidList": [], "subjectList": []},
                         headers=hd, timeout=40)
            veri = r.json() if r.status_code == 200 else []
        except Exception as e:
            return {"hata": "liste: " + repr(e)[:100]}
        pas = [d for d in veri if "Pay Alım Satım" in (d.get("subject") or "")]
        sinif = {}
        tur = {}
        tek_hisseli = None
        for d in pas:
            c = str(d.get("disclosureClass"))
            t = str(d.get("disclosureType"))
            sinif[c] = sinif.get(c, 0) + 1
            tur[t] = tur.get(t, 0) + 1
            his = str(d.get("relatedStocks") or "")
            if tek_hisseli is None and "," not in his and his.strip():
                tek_hisseli = d
        rapor["pas_sayisi"] = len(pas)
        rapor["sinif_dagilimi"] = sinif
        rapor["tur_dagilimi"] = tur
        hedef = tek_hisseli or (pas[0] if pas else None)
        if not hedef:
            return rapor
        bid = str(hedef.get("disclosureIndex"))
        rapor["hedef"] = {"id": bid,
                          "hisse": str(hedef.get("relatedStocks"))[:20],
                          "sinif": str(hedef.get("disclosureClass")),
                          "baslik": str(hedef.get("kapTitle"))[:40]}
        time.sleep(0.7)

        # süzgeç: veriden öğrenilen en yaygın sınıf
        if sinif:
            en = max(sinif, key=sinif.get)
            try:
                r2 = ses.post(KAP + "/tr/api/disclosure/members/byCriteria",
                              json={"fromDate": "2026-07-09",
                                    "toDate": "2026-07-15",
                                    "disclosureClass": en,
                                    "mkkMemberOidList": [], "subjectList": []},
                              headers=hd, timeout=40)
                n2 = len(r2.json()) if r2.status_code == 200 else -1
                rapor["suzgec_" + en] = {"http": r2.status_code, "sayi": n2}
            except Exception as e:
                rapor["suzgec_" + en] = {"hata": repr(e)[:80]}
        time.sleep(0.7)

        # aday detay kapıları
        adaylar = [
            "/tr/api/disclosure/detail/" + bid,
            "/tr/api/disclosure/" + bid,
            "/api/disclosure/detail/" + bid,
            "/tr/api/disclosures/" + bid,
            "/tr/BildirimPdf/" + bid,
            "/tr/api/file/download/" + bid,
        ]
        sonuc = []
        for yol in adaylar:
            kayit = {"yol": yol}
            try:
                rr = ses.get(KAP + yol,
                             headers={"User-Agent": UA,
                                      "Referer": KAP + "/tr/Bildirim/" + bid},
                             timeout=40)
                kayit["http"] = rr.status_code
                kayit["tur"] = rr.headers.get("Content-Type", "?")[:40]
                kayit["boyut"] = len(rr.content or b"")
                kayit["ilk"] = repr((rr.content or b"")[:12])
                if rr.status_code == 200 and kayit["boyut"] < 2_000_000:
                    try:
                        metin = rr.content.decode("utf-8", "ignore")
                        for a in ("Alış", "Satış", "İşlemin Niteliği",
                                  "islemNiteligi", "transactionNature"):
                            if a in metin:
                                kayit.setdefault("yon_izleri", []).append(a)
                    except Exception:
                        pass
            except Exception as e:
                kayit["hata"] = repr(e)[:80]
            sonuc.append(kayit)
            time.sleep(0.7)
        rapor["detay_kapilari"] = sonuc
        rapor["yorum"] = ("http=200 + yon_izleri dolu olan kapi = motorun "
                          "kapisi. %PDF ilk baytli 200 varsa PDF yolu. "
                          "sinif_dagiliminda ODA disi sinif = yonetici "
                          "formu adayi.")
        return rapor

    print("[kap_yon_sondaj2] kuruldu: GET /kapyonsondaj2")
