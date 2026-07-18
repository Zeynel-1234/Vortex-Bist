# -*- coding: utf-8 -*-
"""
KAP YÖN SONDAJI v3 — API kapısını sayfanın kendi kodundan sökme
  1) /tr/Bildirim/{id} HTML → __NEXT_DATA__/buildId var mı, HTML içinde
     gecen /tr/api/ yollari neler?
  2) buildId varsa Next veri yolu denenir: /_next/data/{buildId}/...json
  3) En buyuk 3 script parcasi indirilir → icinden api yollari regex ile
     sokulur (disclosure gecenler one alinir)
  4) Bulunan aday yollar (ham + sonuna id eklenmis) tek tek yoklanir;
     200 + yon izi ("Alış/Satış/islemNiteligi") donen kapi raporlanir.
Kullanım: GET /kapyonsondaj3 — saf teşhis.
"""
import re
import time
try:
    import requests
except Exception:
    requests = None

KAP = "https://www.kap.org.tr"
UA = "Mozilla/5.0 (Linux; Android 13) VortexIz/3.0 (arastirma)"
BID = "1633516"   # MANAS DKB bildirimi (2. sondajdan)


def install_kap_yon_sondaj3(app) -> None:
    @app.get("/kapyonsondaj3")
    def kap_yon_sondaj3():
        if requests is None:
            return {"hata": "requests yok"}
        ses = requests.Session()
        try:
            ses.get(KAP + "/tr/bildirim-sorgu",
                    headers={"User-Agent": UA}, timeout=30)
        except Exception:
            pass
        hg = {"User-Agent": UA, "Referer": KAP + "/tr/bildirim-sorgu"}
        rapor = {"id": BID}

        # 1) sayfa
        try:
            r = ses.get(KAP + "/tr/Bildirim/" + BID, headers=hg, timeout=40)
            gov = r.text or ""
        except Exception as e:
            return {"hata": "sayfa: " + repr(e)[:100]}
        rapor["sayfa_http"] = r.status_code
        rapor["next_data_var"] = "__NEXT_DATA__" in gov
        mb = re.search(r'"buildId"\s*:\s*"([^"]+)"', gov)
        rapor["buildId"] = mb.group(1) if mb else None
        html_api = sorted(set(re.findall(r'/tr/api/[A-Za-z0-9/_.-]+', gov)))
        rapor["html_api_yollari"] = html_api[:15]
        parcalar = sorted(set(re.findall(
            r'/_next/static/[A-Za-z0-9/._-]+\.js', gov)))
        rapor["parca_sayisi"] = len(parcalar)
        time.sleep(0.7)

        # 2) Next veri yolu
        if rapor["buildId"]:
            yol = "/_next/data/" + rapor["buildId"] + "/tr/Bildirim/" + BID + ".json"
            try:
                rn = ses.get(KAP + yol, headers=hg, timeout=40)
                kayit = {"yol": yol, "http": rn.status_code,
                         "tur": rn.headers.get("Content-Type", "?")[:40],
                         "boyut": len(rn.content or b"")}
                m = (rn.text or "")[:200000]
                izler = [a for a in ("Alış", "Satış", "islemNiteligi",
                                     "İşlemin Niteliği") if a in m]
                if izler:
                    kayit["yon_izleri"] = izler
                rapor["next_data_denemesi"] = kayit
            except Exception as e:
                rapor["next_data_denemesi"] = {"hata": repr(e)[:100]}
            time.sleep(0.7)

        # 3) script parçalarından api sökümü
        adaylar = set(html_api)
        okunan = 0
        for p in parcalar:
            if okunan >= 3:
                break
            try:
                rj = ses.get(KAP + p, headers=hg, timeout=40)
                if rj.status_code == 200:
                    okunan += 1
                    js = rj.text or ""
                    for y in re.findall(r'["\'`](/tr/api/[A-Za-z0-9/_.${}-]+)', js):
                        adaylar.add(y)
                    for y in re.findall(r'["\'`](api/[A-Za-z0-9/_.${}-]{4,})', js):
                        adaylar.add("/tr/" + y)
            except Exception:
                pass
            time.sleep(0.7)
        rapor["js_okunan_parca"] = okunan
        onemli = sorted(a for a in adaylar if "disclosure" in a.lower()
                        or "bildirim" in a.lower() or "notification" in a.lower())
        diger = sorted(a for a in adaylar if a not in onemli)
        rapor["aday_disclosure"] = onemli[:15]
        rapor["aday_diger"] = diger[:15]

        # 4) adayları yokla (en fazla 6 deneme)
        yoklanan = []
        deneme = 0
        for a in onemli:
            if deneme >= 6:
                break
            temiz = a.replace("${", "").replace("}", "")
            for u in ([temiz] if temiz.rstrip("/").endswith(BID)
                      else [temiz.rstrip("/") + "/" + BID]):
                if deneme >= 6:
                    break
                deneme += 1
                k = {"yol": u}
                try:
                    ry = ses.get(KAP + u, headers=hg, timeout=30)
                    k["http"] = ry.status_code
                    k["tur"] = ry.headers.get("Content-Type", "?")[:40]
                    k["boyut"] = len(ry.content or b"")
                    m = (ry.text or "")[:300000]
                    izler = [x for x in ("Alış", "Satış", "islemNiteligi",
                                         "İşlemin Niteliği") if x in m]
                    if izler:
                        k["yon_izleri"] = izler
                        k["ornek"] = m[:180]
                except Exception as e:
                    k["hata"] = repr(e)[:90]
                yoklanan.append(k)
                time.sleep(0.8)
        rapor["yoklama"] = yoklanan
        rapor["yorum"] = ("yon_izleri dolu 200 kapi = motor kapisi. Hicbiri "
                          "acilmadiysa aday listelerini gonder — bir sonraki "
                          "tur o listeden hedefli kurulur.")
        return rapor

    print("[kap_yon_sondaj3] kuruldu: GET /kapyonsondaj3")
