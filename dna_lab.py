# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
DNA LAB · ADIM 1 — RALLİ ETİKETLEYİCİ (Triple-Barrier)
═══════════════════════════════════════════════════════════════════
Amaç : Bir hissenin tarihindeki TÜM gerçek %30+ yükseliş olaylarını
       bilimsel kurallarla bulmak ve her ralli için tek bir T0
       (dip günü) işaretlemek. Bu, Hisse DNA Motoru'nun anatomi
       masasıdır — parmak izi çıkarımı (Adım 3) bu etiketler
       üzerine kurulacaktır.

Yöntem: Lopez de Prado Triple-Barrier etiketleme
  · Üst bariyer  : +%30 (hedef)      — High ile ölçülür
  · Alt bariyer  : -%12 (stop)       — Low ile ölçülür
  · Zaman bariyeri: 60 işlem günü
  Bir günden ileriye bakıldığında ÜST bariyere ALT bariyerden
  ÖNCE çarpılıyorsa o gün "pozitif" adaydır. Aynı gün her iki
  bariyer de kesilirse muhafazakâr davranılır → NEGATİF sayılır
  (gerçekte stop yemiş olabilirdik).

Tekil T0 kuralı:
  Ardışık/örtüşen pozitif günler AYNI rallinin parçasıdır.
  Pencereleri zincirleme örtüşen pozitif günler tek olaya
  indirgenir; olayın T0'ı = grubun EN DÜŞÜK kapanışlı günü (dip).
  Böylece aynı ralli 5 kez sayılıp istatistik şişmez.

Veri hijyeni:
  · 2010 öncesi veri kırpılır (farklı mikro yapı).
  · Olay penceresinde tek günde |%45|'ten büyük kapanış sıçraması
    varsa olay "veri_suphesi" bayrağı alır (bedelli/düzeltme
    artefaktı olabilir) ve temiz sayıma girmez.

ÖN-KAYIT (data snooping kilidi):
  Aşağıdaki ONKAYIT sabitleri bu sistemin mühürlü parametreleridir.
  Test sonuçları görüldükten sonra değiştirilmesi protokol ihlalidir.
  Her cevapta aynen geri yankılanır ki hangi parametreyle üretildiği
  kayıt altında olsun.

Kurulum (main.py — tamamen EKLEMELİ, 5 satır):
  try:
      from dna_lab import install_dna_lab
      install_dna_lab(app, fetch_ohlc)   # /dnalab/{symbol}
  except Exception as _e:
      print("[main] dna_lab yuklenemedi:", repr(_e))

Bellek: hisse başına talep üzerine çalışır; global durum tutmaz.
        512MB Render free tier için güvenlidir.
═══════════════════════════════════════════════════════════════════
"""

from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

# ═══ ÖN-KAYIT · MÜHÜRLÜ PARAMETRELER ═══════════════════════════
ONKAYIT = {
    "hedef_getiri": 0.30,     # üst bariyer: +%30
    "stop_dusus": 0.12,       # alt bariyer: -%12
    "ufuk_gun": 60,           # zaman bariyeri: 60 işlem günü
    "veri_baslangic": "2010-01-01",
    "anomali_esik": 0.45,     # tek gün |getiri| > %45 → veri şüphesi
    "min_veri_gun": 300,      # bundan az bar varsa analiz yapılmaz
    "zirve_penceresi": 252,
    "min_gecmis_gun": 60,     # T0 öncesi en az 60 bar tarihçe yoksa → kenar olayı
    "kalicilik_kontrol": [30, 90, 120],  # vuruştan 30-90-120 gün sonra HEPSİNDE...
    "kalicilik_min": 0.20,    # ...girişin +%20 üstünde olmalı (Sınıf A)
    "sma_uzun": 200,          # uzun vadeli yapı referansı
    "sma_ustu_ardisik": 10,   # SMA200 üstünde en az 10 ardışık kapanış (Sınıf A)   # 52 hafta ~ 252 işlem günü
    "surum": "dna_lab_v2.2",
}


# ═══ ÇEKİRDEK: SAF ETİKETLEME FONKSİYONU (test edilebilir) ═════
def etiketle(df: pd.DataFrame,
             hedef: float = None,
             dus: float = None,
             ufuk: int = None) -> Dict:
    """
    OHLC DataFrame alır (kolonlar: Open/High/Low/Close, DatetimeIndex),
    ralli olay listesi + özet istatistik döndürür. FastAPI'den bağımsız
    saf fonksiyondur; sentetik veriyle birim testi yapılabilir.
    """
    hedef = ONKAYIT["hedef_getiri"] if hedef is None else float(hedef)
    dus = ONKAYIT["stop_dusus"] if dus is None else float(dus)
    ufuk = ONKAYIT["ufuk_gun"] if ufuk is None else int(ufuk)

    # ── veri hazırlığı ────────────────────────────────────────
    d = df.copy()
    # kolon normalizasyonu: fetch_ohlc küçük harf döndürür ('close'),
    # ham yfinance ise 'Close' — ikisini de kabul et.
    esle = {}
    for c in d.columns:
        cl = str(c).strip().lower()
        if cl in ("close", "high", "low", "open", "volume"):
            esle[c] = cl.capitalize()
    d = d.rename(columns=esle)
    try:
        d = d[d.index >= pd.Timestamp(ONKAYIT["veri_baslangic"])]
    except Exception:
        pass
    for kol in ("Close", "High", "Low"):
        if kol not in d.columns:
            return {"hata": "eksik kolon: " + kol}
        d[kol] = pd.to_numeric(d[kol], errors="coerce")
    d = d.dropna(subset=["Close", "High", "Low"])
    n = len(d)
    if n < ONKAYIT["min_veri_gun"]:
        return {"hata": "yetersiz veri", "bar_sayisi": int(n)}

    c = d["Close"].values.astype(float)
    h = d["High"].values.astype(float)
    l = d["Low"].values.astype(float)
    tarih = d.index

    # günlük kapanış getirisi (anomali bekçisi için)
    gunluk = np.zeros(n)
    gunluk[1:] = c[1:] / c[:-1] - 1.0

    # uzun vadeli yapı referansı: SMA200 (Sınıf A/B ayrımı için)
    sma_n = ONKAYIT["sma_uzun"]
    sma = pd.Series(c).rolling(sma_n, min_periods=sma_n).mean().values

    # ── 1) triple-barrier taraması: pozitif gün adayları ──────
    # pozitif gün = ileriye bakıldığında üst bariyer alt bariyerden
    # önce vuruluyor. (i, j_vurus) çiftleri toplanır.
    pozitifler: List[tuple] = []
    for i in range(n - 5):
        ust = c[i] * (1.0 + hedef)
        alt = c[i] * (1.0 - dus)
        son = min(n, i + ufuk + 1)
        tur = None
        j_vurus = -1
        for j in range(i + 1, son):
            alt_kesildi = l[j] <= alt
            ust_kesildi = h[j] >= ust
            if alt_kesildi:
                # aynı gün ikisi de kesilse bile muhafazakâr: ALT önce
                tur = "ALT"
                j_vurus = j
                break
            if ust_kesildi:
                tur = "UST"
                j_vurus = j
                break
        if tur == "UST":
            pozitifler.append((i, j_vurus))

    # ── 2) örtüşen pozitifleri TEK olaya indirge ──────────────
    gruplar: List[List[tuple]] = []
    aktif: List[tuple] = []
    for (i, j) in pozitifler:
        if not aktif:
            aktif = [(i, j)]
        elif i <= aktif[-1][1]:          # pencere zinciri örtüşüyor
            aktif.append((i, j))
        else:
            gruplar.append(aktif)
            aktif = [(i, j)]
    if aktif:
        gruplar.append(aktif)

    # ── 3) her grup için T0 = en düşük kapanışlı gün ──────────
    olaylar: List[Dict] = []
    zp = ONKAYIT["zirve_penceresi"]
    esik = ONKAYIT["anomali_esik"]
    for grup in gruplar:
        baslar = [g[0] for g in grup]
        t0 = min(baslar, key=lambda ix: c[ix])
        # T0'a ait vuruş noktasını bul (grup içinden)
        j_hit = dict(grup)[t0]

        pencere_c = c[t0:min(n, t0 + ufuk + 1)]
        pencere_h = h[t0:min(n, t0 + ufuk + 1)]
        pencere_l = l[t0 + 1:j_hit + 1] if j_hit > t0 else l[t0:t0 + 1]

        max_getiri = float(pencere_h.max() / c[t0] - 1.0)
        yol_dd = max(0.0, float(1.0 - pencere_l.min() / c[t0])) if len(pencere_l) else 0.0

        # dip derinliği: T0 kapanışının önceki 52h zirvesine uzaklığı
        z_bas = max(0, t0 - zp)
        onceki_zirve = float(c[z_bas:t0 + 1].max())
        dip_derinligi = float(1.0 - c[t0] / onceki_zirve) if onceki_zirve > 0 else 0.0
        # düşüşün yaşı: zirveden T0'a geçen gün
        zirve_ix = z_bas + int(np.argmax(c[z_bas:t0 + 1]))
        dusus_yasi = int(t0 - zirve_ix)

        # anomali bekçisi: olay yolunda tek günlük dev sıçrama var mı
        yol = gunluk[max(1, t0):j_hit + 1]
        suphe = bool(len(yol) and np.max(np.abs(yol)) > esik)

        # kenar bekçisi: T0 öncesi yeterli tarihçe yoksa (halka arz
        # dönemi vb.) parmak izi çıkarılamaz → temiz sayıma girmez
        kenar = bool(t0 < ONKAYIT["min_gecmis_gun"])

        # ── SINIF A/B: GERÇEK TREND mi, ZIPLAMA mı? ──────────
        # A şartı 1 (kalıcılık): vuruştan kalicilik_gun sonra kapanış
        #   hâlâ t0*(1+kalicilik_min) üstünde → kazanç geri verilmemiş
        # A şartı 2 (yapı): [t0 .. vuruş+kalicilik_gun] aralığında
        #   SMA200 üstünde en az sma_ustu_ardisik ARDIŞIK kapanış
        kontrol = ONKAYIT["kalicilik_kontrol"]
        j_son = j_hit + max(kontrol)
        if j_son >= n or (sma_n - 1) > j_hit:
            sinif = "BELIRSIZ"   # sınamak için veri henüz yok/yetersiz
        else:
            # süreklilik: TÜM kontrol noktalarında +%20 üstü kalmalı;
            # tek noktada çöküp sonra "kurtarılma" artık A sayılmaz
            esik_f = c[t0] * (1.0 + ONKAYIT["kalicilik_min"])
            kalici = all(c[j_hit + k] >= esik_f for k in kontrol)
            seri = 0
            en_uzun = 0
            for k in range(t0, j_son + 1):
                if not np.isnan(sma[k]) and c[k] > sma[k]:
                    seri += 1
                    en_uzun = max(en_uzun, seri)
                else:
                    seri = 0
            yapi = bool(en_uzun >= ONKAYIT["sma_ustu_ardisik"])
            sinif = "A_TREND" if (kalici and yapi) else "B_ZIPLAMA"

        olaylar.append({
            "t0_tarih": str(tarih[t0].date()),
            "t0_fiyat": round(float(c[t0]), 4),
            "vurus_tarih": str(tarih[j_hit].date()),
            "gun_sayisi": int(j_hit - t0),
            "max_getiri_pct": round(max_getiri * 100, 1),
            "yol_dd_pct": round(yol_dd * 100, 1),
            "dip_derinligi_pct": round(dip_derinligi * 100, 1),
            "dusus_yasi_gun": dusus_yasi,
            "veri_suphesi": suphe,
            "kenar_olayi": kenar,
            "sinif": sinif,
        })

    # ── 4) özet istatistik ────────────────────────────────────
    temiz = [o for o in olaylar if not o["veri_suphesi"] and not o["kenar_olayi"]]
    sinif_a = [o for o in temiz if o["sinif"] == "A_TREND"]
    yil = max(0.5, (tarih[-1] - tarih[0]).days / 365.25)

    def _med(anahtar):
        v = [o[anahtar] for o in sinif_a]   # medyanlar = DNA tabanı (Sınıf A)
        return round(float(np.median(v)), 1) if v else None

    ozet = {
        "toplam_ralli": len(olaylar),
        "temiz_ralli": len(temiz),
        "supheli_ralli": sum(1 for o in olaylar if o["veri_suphesi"]),
        "kenar_ralli": sum(1 for o in olaylar if o["kenar_olayi"]),
        "sinif_a_trend": len(sinif_a),
        "sinif_b_ziplama": sum(1 for o in temiz if o["sinif"] == "B_ZIPLAMA"),
        "sinif_belirsiz": sum(1 for o in temiz if o["sinif"] == "BELIRSIZ"),
        "yil_basina_ralli": round(len(temiz) / yil, 2),
        "yil_basina_a_trend": round(len(sinif_a) / yil, 2),
        "medyan_gun": _med("gun_sayisi"),
        "medyan_max_getiri_pct": _med("max_getiri_pct"),
        "medyan_yol_dd_pct": _med("yol_dd_pct"),
        "medyan_dip_derinligi_pct": _med("dip_derinligi_pct"),
        "medyan_dusus_yasi_gun": _med("dusus_yasi_gun"),
        "son_a_trend_t0": sinif_a[-1]["t0_tarih"] if sinif_a else None,
        "son_ralli_t0": temiz[-1]["t0_tarih"] if temiz else None,
        "veri_araligi": [str(tarih[0].date()), str(tarih[-1].date())],
        "bar_sayisi": int(n),
    }

    return {"onkayit": ONKAYIT, "ozet": ozet, "ralliler": olaylar}


# ═══ FASTAPI KURULUMU ══════════════════════════════════════════
def install_dna_lab(app, fetch_ohlc: Callable) -> None:
    from fastapi import Query

    @app.get("/dnalab/{symbol}")
    def dna_lab_endpoint(symbol: str,
                         hedef: float = Query(ONKAYIT["hedef_getiri"], ge=0.10, le=1.00),
                         dus: float = Query(ONKAYIT["stop_dusus"], ge=0.05, le=0.30),
                         ufuk: int = Query(ONKAYIT["ufuk_gun"], ge=20, le=180)):
        """
        Hissenin tüm tarihindeki %hedef+ ralli olaylarını etiketler.
        Varsayılanlar ÖN-KAYIT parametreleridir; farklı değer verilirse
        cevap 'onkayit_disi': true bayrağı taşır (keşif modu — resmi
        DNA istatistiğine GİRMEZ).
        """
        sym = symbol.upper().replace(".IS", "").strip()
        try:
            df = fetch_ohlc(sym, period="max")
        except Exception:
            df = None
        if df is None or len(df) < ONKAYIT["min_veri_gun"]:
            return {"sembol": sym, "hata": "yetersiz veri (period=max)"}

        out = etiketle(df, hedef=hedef, dus=dus, ufuk=ufuk)
        out["sembol"] = sym
        out["onkayit_disi"] = not (
            abs(hedef - ONKAYIT["hedef_getiri"]) < 1e-9 and
            abs(dus - ONKAYIT["stop_dusus"]) < 1e-9 and
            ufuk == ONKAYIT["ufuk_gun"]
        )
        return out

    print("[dna_lab] kuruldu: GET /dnalab/{symbol}  ·", ONKAYIT["surum"])
