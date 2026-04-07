# 🏇 At Yarışı Analiz — URİS v3.5

## Railway'e Deploy (5 Dakika)

### 1. Bu dosyaları Replit'e yükle
Tüm klasörü Replit'teki horse-race-analyst projesine kopyala.

### 2. Railway'de yeni proje aç
- railway.app → New Project → Deploy from GitHub
- VEYA: GitHub'a push et → Railway bağla

### 3. Environment Variables (Railway Dashboard)
```
PORT=3000
PROXY_URL=           (opsiyonel, TJK IP engeli için)
NODE_ENV=production
```

### 4. Deploy et
Railway otomatik build eder (Dockerfile kullanarak).

---

## Kullanım

### A) Otomatik (Railway'den TJK çekme dener)
```
GET /api/scrape
```

### B) Bookmarklet (En güvenilir)
1. `YOUR_URL/bookmarklet` sayfasına git
2. Oradaki kodu Via Browser'a bookmark olarak kaydet
3. mobil.tjk.org'da yarış sayfasını aç
4. Bookmark'a tıkla → veri otomatik analiz edilir

### C) Manuel API
```
POST /api/analyze
{
  "race": {
    "no": 1,
    "track": "İzmir",
    "horses": [
      {
        "no": 1,
        "name": "AT ADI",
        "jockeyName": "JOKEY ADI",
        "weight": 56,
        "son6Y": "1-2-3-1-5-2",
        "agf": 3.5,
        "ds": false
      }
    ]
  }
}
```

---

## Sistem — URİS v3.5

12 Katman | Max 116p | Trinity Çıktısı

| Katman | Konu | Max |
|--------|------|-----|
| 1 | Son 6Y form | 25p |
| 2 | AGF/HP piyasa | 15p |
| 3 | Jokey kalitesi | 12p |
| 4 | Antrenör | 8p |
| 5 | Kilo | 8p |
| 6 | KGS tazelik | 8p |
| 7 | İdman | 8p |
| 8 | DS bayrağı | 5p |
| 9-12 | Mesafe/pist/sahip/yaş | 11p |
| Bonus | Kombinasyon | +16p |
| **TOPLAM** | | **116p** |

**Eşikler:**
- ≥80 → 👑 SOVEREIGN (Kesin Aday)
- 70-79 → ⚔️ BREAKER (2-3. Aday)
- 60-69 → 👻 GHOST (Sürpriz adayı)
- <60 → İZLE

---

## Proxy Kurulumu (TJK IP engeli için)

Eğer Railway IP'si de engellenirse:
1. webshare.io → Ücretsiz 10 proxy al
2. Railway env: `PROXY_URL=http://user:pass@proxy:port`
3. Redeploy
