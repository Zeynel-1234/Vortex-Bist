# Fraktal Kâhin · BIST Analiz Motoru

Hibrit mimari: **Python FastAPI backend (Railway)** + **HTML Dashboard (Android Via Browser)**

Her BIST hissesi için fraktal parmak izi (DNA) + çok faktörlü dip/tepe tespiti üretir. Saf matematik, metafor yok.

---

## Mimari

```
┌─────────────────────────────┐       ┌──────────────────────┐
│  Frontend (index.html)      │       │  Railway Backend     │
│  · Android Via Browser      │ ───▶  │  · FastAPI           │
│  · Tek HTML dosya           │       │  · yfinance          │
│  · HTTPS XHR ile API çağrır │       │  · In-memory cache   │
└─────────────────────────────┘       └──────────────────────┘
                                                  │
                                                  ▼
                                         ┌────────────────┐
                                         │ Yahoo Finance  │
                                         │ (günlük OHLC)  │
                                         └────────────────┘
```

---

## Gerçek Matematik (Metafor Yok)

Her hisse için Python backend şunları hesaplar:

| Metrik | Ne yapar | Matematik |
|--------|----------|-----------|
| **Hurst Exponent** | Fraktal bellek katsayısı | E[(X_t+τ − X_t)²] ~ τ^(2H) |
| **R/S Analizi** | Trend kalıcılığı | log(R/S) = H·log(n) + c |
| **Dominant Cycle (FFT)** | Hisseye özgü döngü uzunluğu | FFT power spectrum peak detection |
| **Volatilite Rejimi** | Düşük/normal/yüksek/aşırı | 20g std / 100g std (annualized) |
| **ATR Kanalları** | Volatilite sınırları | mid ± mult × ATR(14) |
| **FYI** | Fraktal Yorgunluk İndeksi | (Close − 20g low) / (ATR × √20) |
| **LRK** | Likidite Rezonans Katsayısı | (Hurst × log(Volume)) / Vol |
| **Hisse DNA** | Deterministik parmak izi | SHA256(H + Cycle + Rejim + R/S) |

### Dip/Tepe Tespiti (ELMAS)

Her sinyal **7 gerçek faktörün** ağırlıklı toplamı:
- RSI aşırı satım + dönüş (Wilder smoothing)
- FYI bölgesi
- ATR kanal konumu
- Hacim climax + bar içi toparlanma
- Hurst mean-reverting + LRK
- Volatilite rejimi düzeltmesi

**Sinyal eşikleri:**
- `GUCLU_AL` (ELMAS): ≥ 0.70
- `AL`: 0.50 – 0.70
- `ZAYIF_AL`: 0.30 – 0.50
- `NOTR`: < 0.30

---

## Deployment · Railway

### 1) Backend'i Railway'e Deploy Et

GitHub'a `fkahin/backend/` klasörünü push et:

```bash
cd fkahin/backend
git init
git add .
git commit -m "Fraktal Kahin v1.0"
git remote add origin https://github.com/<user>/fkahin-backend.git
git push -u origin main
```

Railway'de yeni proje:
1. **Deploy from GitHub repo** → `fkahin-backend`
2. Railway Dockerfile'ı otomatik algılar
3. Build bitince generated domain oluşur: `https://fkahin-backend-production-xxxx.up.railway.app`
4. Test: `curl https://<domain>/` → `{"servis":"Fraktal Kahin v1.0",...}`

### 2) Frontend'i Kullan

`index.html`'i Android telefonuna indir ve Via Browser ile aç.
Üstteki input kutusuna Railway URL'ini yapıştır, **KAYDET** bas.

Frontend localStorage'a URL'i kaydeder, bir sonraki açılışta otomatik bağlanır.

---

## Endpoints

| Endpoint | Ne döner |
|----------|----------|
| `GET /` | Health + endpoint listesi |
| `GET /analyze/{sym}` | Tek hisse tam analiz (~3-8 sn ilk çağrıda, cache sonrası <100ms) |
| `GET /scan` | Tüm BIST tarama + sinyal dağılımı (~3-5 dk ilk, sonra cache) |
| `GET /dips` | En güçlü dip adayları |
| `GET /peaks` | Tepe uyarıları |
| `GET /symbols` | Desteklenen semboller |

Cache TTL: 15 dk (tek hisse), 30 dk (tarama).

---

## Örnek API Yanıtı

```json
{
  "sembol": "THYAO",
  "sinyal": "GUCLU_AL",
  "guc": 0.73,
  "yön": "DIP",
  "fiyat": 280.5,
  "gunluk_degisim": -1.8,
  "dna_kodu": "FKDNA-7A3B-9C12-45",
  "bilimsel_gerekce": {
    "hurst": 0.612,
    "rs_analiz": 0.587,
    "dominant_cycle": 28,
    "volatilite_rejimi": {
      "rejim": "NORMAL",
      "current_vol": 32.5,
      "baseline_vol": 28.1,
      "ratio": 1.16
    },
    "fyi": 0.34,
    "lrk": 2.45,
    "atr_kanal": {
      "alt": 265.2,
      "orta": 282.0,
      "ust": 298.8,
      "konum": 0.12
    },
    "destek_uzaklik_yuzde": 5.3
  },
  "tetiklenen_faktorler": [
    "RSI dönüşü: 32 > 29",
    "FYI derin dip: 0.34",
    "ATR alt band sınırı (0.12)",
    "Mean-reverting + likidite (H=0.61, LRK=2.45)"
  ],
  "beklenen_vade": "14-56 iş günü",
  "yaratici_not": "Güçlü trend + derin çekilme · ATR alt band + dip = nadir fırsat"
}
```

---

## Dosya Yapısı

```
fkahin/
├── backend/
│   ├── main.py             # FastAPI uygulaması
│   ├── indicators.py       # Tüm matematik (Hurst, FFT, FYI, LRK, dip/tepe)
│   ├── symbols.py          # 400+ BIST sembolü (genişletilebilir)
│   ├── requirements.txt    # Pinned dependencies
│   ├── Dockerfile          # Railway deploy
│   ├── railway.json        # Railway config
│   └── .gitignore
└── frontend/
    └── index.html          # Via Browser uyumlu tek dosya
```

---

## Performans Notları

- **İlk tarama** (630 hisse, cache boş): 3-5 dakika. yfinance HTTP request'ler 8 paralel thread ile yapılır.
- **Sonraki taramalar** (cache dolu): < 5 saniye.
- **Tek hisse ilk çağrı**: 3-8 saniye (yfinance + matematik).
- **Tek hisse cache**: < 100ms.
- **Cache strategy**: In-memory, TTL bazlı. Railway restart'ta temizlenir (sorun değil — 15 dk sonra zaten güncellenir).

## Genişletme Önerileri

- Sembol listesini tam 630'a tamamlama (Borsa Istanbul aylık listeyi yayınlar)
- Multi-timeframe ekle: 1H/4H veriler (yfinance `interval="1h"` destekler)
- Historical backtesting: CPCV ile 5 yıllık geriye dönük test
- WebSocket ile canlı fiyat + sinyal push
- Telegram botu entegrasyonu (güçlü sinyal → otomatik bildirim)
