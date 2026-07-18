# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
KAP YÖN SONDAJI — Aşama 2b fizibilite ucu (tek atımlık)
═══════════════════════════════════════════════════════════════════
Amaç : İçeriden işlem bildirimlerinde YÖN (Alış/Satış) bilgisinin
       tam olarak nerede durduğunu, motoru yazmadan önce keşfetmek.

Cevaplanan sorular:
  1) Liste kaydında hangi alanlar var? (id alanının gerçek adı)
  2) byCriteria "disclosureClass" süzgecini kabul ediyor mu?
     (ederse yeniden tarama 6-7 kat kısalır)
  3) Bildirim detay sayfasında (HTML) "Alış/Satış/İşlemin Niteliği"
     metni geçiyor mu, yoksa bilgi ekteki dosyada mı?
  4) Ek dosyanın gerçek türü ne? (ilk baytlar: %PDF mi, başka mı)

Kullanım: GET /kapyonsondaj   — hiçbir şey kaydetmez, saf teşhis.
═══════════════════════════════════════════════════════════════════
"""

import re
import time

try:
    import requests
except Exception:
    requests = None

KAP = "https://www.kap.org.tr"
UA = "Mozilla/5.0 (Linux; Android 13) VortexIz/2.0 (arastirma)"


def install_kap_yon_sondaj(app) -> None:
    @app.get("/kapyonsondaj")
    def kap_yon_sondaj():
        if requests is None:
            return {"hata": "requests yok"}
        ses = requests.Session()
        rapor = {}
        try:
            ses.get(KAP + "/tr/bildirim-sorgu",
                    headers={"User-Agent": UA}, timeout=30)
        except Exception:
            pass
        hd = {"Referer": KAP + "/tr/bildirim-sorgu",
              "User-Agent": UA, "Content-Type": "application/json"}

        # ── 1) Son 7 günün PAS kayıtları + şema keşfi ──────────
        try:
            r = ses.post(KAP + "/tr/api/disclosure/members/byCriteria",
                         json={"fromDate": "2026-07-09",
                               "toDate": "2026-07-15",
                               "mkkMemberOidList": [], "subjectList": []},
                         headers=hd, timeout=40)
            veri = r.json() if r.status_code == 200 else []
        except Exception as e:
            return {"hata": "liste sorgusu: " + repr(e)[:120]}
        pas = [d for d in veri
               if "Pay Alım Satım" in (d.get("subject") or "")]
        rapor["liste_toplam"] = len(veri)
        rapor["pas_sayisi"] = len(pas)
        if pas:
            rapor["pas_kayit_alanlari"] = sorted(pas[0].keys())
            rapor["ornek_pas"] = {k: str(pas[0].get(k))[:60]
                                  for k in list(pas[0].keys())[:12]}
        time.sleep(0.7)

        # ── 2) disclosureClass süzgeci deneniyor ───────────────
        try:
            r2 = ses.post(KAP + "/tr/api/disclosure/members/byCriteria",
                          json={"fromDate": "2026-07-09",
                                "toDate": "2026-07-15",
                                "disclosureClass": "DKB",
                                "mkkMemberOidList": [], "subjectList": []},
                          headers=hd, timeout=40)
            if r2.status_code == 200:
                v2 = r2.json()
                konular = {}
                for d in (v2 if isinstance(v2, list) else [])[:200]:
                    kk = (d.get("subject") or "?")[:30]
                    konular[kk] = konular.get(kk, 0) + 1
                rapor["dkb_suzgec"] = {"http": 200, "sayi": len(v2),
                                       "konular": konular}
            else:
                rapor["dkb_suzgec"] = {"http": r2.status_code}
        except Exception as e:
            rapor["dkb_suzgec"] = {"hata": repr(e)[:100]}
        time.sleep(0.7)

        # ── 3-4) İlk 2 PAS bildiriminin detayı + ekleri ────────
        detaylar = []
        for d in pas[:2]:
            bid = (d.get("disclosureIndex") or d.get("id")
                   or d.get("disclosureId") or "")
            det = {"id": str(bid),
                   "hisse": str(d.get("relatedStocks"))[:30]}
            if not bid:
                det["not"] = "id alani bulunamadi"
                detaylar.append(det)
                continue
            try:
                rd = ses.get(KAP + "/tr/Bildirim/" + str(bid),
                             headers={"User-Agent": UA,
                                      "Referer": KAP + "/tr/bildirim-sorgu"},
                             timeout=40)
                det["html_http"] = rd.status_code
                gov = rd.text or ""
                det["html_uzunluk"] = len(gov)
                for anahtar in ("Alış", "Satış", "İşlemin Niteliği",
                                "Alım Satım", "Sermaye Piyasası Aracı"):
                    det["icerir_" + anahtar[:10]] = anahtar in gov
                ekler = re.findall(r'["\'](/[^"\']*?(?:file|File|ek|attachment)[^"\']*?)["\']',
                                   gov)[:5]
                det["ek_adaylari"] = ekler
                if ekler:
                    time.sleep(0.7)
                    re_ = ses.get(KAP + ekler[0],
                                  headers={"User-Agent": UA,
                                           "Referer": KAP + "/tr/Bildirim/" + str(bid)},
                                  timeout=40)
                    det["ek_http"] = re_.status_code
                    det["ek_tur"] = re_.headers.get("Content-Type", "?")[:50]
                    det["ek_ilk_baytlar"] = repr(re_.content[:12])
                    det["ek_boyut"] = len(re_.content)
            except Exception as e:
                det["hata"] = repr(e)[:120]
            detaylar.append(det)
            time.sleep(0.7)
        rapor["detaylar"] = detaylar
        rapor["yorum"] = ("icerir_Alış/Satış true ise yön HTML'de → motor "
                          "kolay. Degilse ek_ilk_baytlar %PDF ise PDF "
                          "okuyucu eklenir. dkb_suzgec sayisi kucuk ve "
                          "konular PAS agirlikliysa hizli tarama yolu acik.")
        return rapor

    print("[kap_yon_sondaj] kuruldu: GET /kapyonsondaj")
