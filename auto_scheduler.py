"""
═══════════════════════════════════════════════════════════════
auto_scheduler.py — OTONOM GÜNLÜK ZAMANLAYICI v1.0
───────────────────────────────────────────────────────────────
AMAÇ: Sistemi her İŞ GÜNÜ saat 18:30'da (Türkiye saati, BIST kapandıktan
sonra) KENDİ KENDİNE çalıştırmak. İnsan tıklaması / müdahalesi GEREKMEZ.

Bir iş günü 18:30'dan SONRA (uygulama uyanık olan ilk anda) şunları yapar:
  1) /scan?force=true        → 600+ hissenin taze NVS/BKM/GS taraması
  2) ÖĞREN günlük döngüsü     → piyasa rejimi + signal_tracker (snapshot +
                                önceki günü değerlendirme) + ileriye-dönük
                                isabete göre ADAPTİF AĞIRLIK öğrenme
  3) /rs/refresh             → göreceli güç + likidite (KARAR için)
  4) Tracker bitince ağırlıkları SON KEZ kesin veriyle yeniden hesaplar
     ve GitHub Gist'e KALICI yazar.

Böylece KARAR motoru her sabah taze, öğrenilmiş ağırlıklarla hazır olur.
Kanıt biriktikçe (her gün 1 değerlendirme) sistem otomatik akıllanır.

İDEMPOTENT: Aynı gün ikinci kez tetiklense bile ağır iş bir kez yapılır
(ÖĞREN durumundaki last_run_date kontrolü). Tekrar tetikleme zararsızdır.

KURULUM: alpha_tab_integration.install_alpha_tab() içinde otomatik başlar;
main.py'ya dokunmaya GEREK YOKTUR. (İstenirse main.py'ya da eklenebilir:
    from auto_scheduler import start_scheduler
    start_scheduler()
)

GERİ ALMA: Bu dosyayı sil + alpha_tab_integration.py'nin eski halini yükle.

ÖNEMLİ (Render ücretsiz katman): Uygulama 15 dk hareketsiz kalınca uyur.
İçerideki zamanlayıcı yalnızca uygulama UYANIKSA tetiklenir. cron-job.org
keep-alive ping'iniz uygulamayı 7/24 uyanık tuttuğu için 18:30'da çalışır.
Ek güvence için cron-job.org'da GÜNLÜK 18:35'te /ogren/cron'a bir job daha
kurabilirsiniz (idempotent — çift çalışmaz).

AYAR (opsiyonel ortam değişkenleri):
    AUTO_RUN_HOUR   (varsayılan 18)   — tetik saati (TR)
    AUTO_RUN_MIN    (varsayılan 30)   — tetik dakikası
    AUTO_RUN_OFF=1                    — zamanlayıcıyı tamamen kapatır
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
import json
import time
import threading
import datetime as dt
import urllib.request

# ── KONFİG ──────────────────────────────────────────────────────
TR_OFFSET_HOURS = 3            # Türkiye = UTC+3 (2016'dan beri sabit, DST yok)
RUN_HOUR = int(os.environ.get("AUTO_RUN_HOUR", "18"))
RUN_MIN = int(os.environ.get("AUTO_RUN_MIN", "30"))
CHECK_EVERY_SEC = 60          # döngü her dakikada bir kontrol eder
TRACKER_MAX_WAIT_SEC = 600    # tracker'ın bitmesini en fazla 10 dk bekle

_started = False
_inflight = False
_lock = threading.Lock()


# ── YARDIMCI ────────────────────────────────────────────────────
def _now_tr() -> dt.datetime:
    """Türkiye yerel saati (UTC+3)."""
    return dt.datetime.utcnow() + dt.timedelta(hours=TR_OFFSET_HOURS)


def _today_tr_str() -> str:
    return _now_tr().date().isoformat()


def _is_weekday() -> bool:
    return _now_tr().weekday() < 5    # Pzt=0 ... Cum=4


def _past_trigger_time() -> bool:
    """TR saati bugünkü tetik anını (varsayılan 18:30) geçti mi?"""
    now = _now_tr()
    if now.hour > RUN_HOUR:
        return True
    if now.hour == RUN_HOUR and now.minute >= RUN_MIN:
        return True
    return False


def _self_base() -> str:
    base = os.environ.get("OGREN_BASE_URL", "").rstrip("/")
    if base:
        return base
    return "http://127.0.0.1:" + str(os.environ.get("PORT", "10000"))


def _get(url: str, timeout: int = 120):
    """Basit GET → JSON (urllib; harici bağımlılık yok). Hata olursa None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "auto-sched/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw)
            except Exception:
                return {"_raw": raw[:200]}
    except Exception as e:
        print("[auto_scheduler] GET hata:", url.split("?")[0], "·", str(e)[:120])
        return None


def _already_ran_today() -> bool:
    """ÖĞREN durumundaki last_run_date bugüne eşitse, ağır iş yapıldı demektir."""
    try:
        import ogren_engine as og
        st = og.load_state()
        return (st or {}).get("last_run_date") == _today_tr_str()
    except Exception:
        return False


# ── ANA GÜNLÜK İŞ ───────────────────────────────────────────────
def _daily_run():
    """Tam otonom günlük döngü. Arka planda, tek seferde çalışır."""
    global _inflight
    base = _self_base()
    t0 = time.time()
    print("[auto_scheduler] ▶ GÜNLÜK OTONOM DÖNGÜ başladı ·", _now_tr().isoformat())

    try:
        # 1) Taze NVS taraması (senkron; bitince döner)
        print("[auto_scheduler] 1/4 · /scan?force=true")
        _get(base + "/scan?force=true&limit=900", timeout=300)

        # 2) ÖĞREN günlük döngüsü: rejim + tracker tetikle + (ön) ağırlık
        print("[auto_scheduler] 2/4 · ÖĞREN run_daily_cycle()")
        try:
            import ogren_engine as og
            og.run_daily_cycle(force=False)
        except Exception as e:
            print("[auto_scheduler] ÖĞREN doğrudan çağrı hatası, HTTP'ye düşülüyor:",
                  str(e)[:120])
            _get(base + "/ogren/run", timeout=60)

        # 3) Göreceli güç + likidite (KARAR için) — arka planda başlar
        print("[auto_scheduler] 3/4 · /rs/refresh")
        _get(base + "/rs/refresh", timeout=60)

        # 4) Tracker'ın gerçekten BİTMESİNİ bekle, sonra ağırlıkları
        #    KESİN (taze) veriyle son kez hesapla → kalıcı kaydet.
        print("[auto_scheduler] 4/4 · tracker tamamlanması bekleniyor...")
        waited = 0
        completed = False
        while waited < TRACKER_MAX_WAIT_SEC:
            time.sleep(15)
            waited += 15
            s = _get(base + "/tracker/status", timeout=30) or {}
            stage = s.get("stage")
            if stage == "completed":
                completed = True
                break
            if stage == "error":
                print("[auto_scheduler] tracker hata bildirdi:", str(s.get("error"))[:120])
                break

        # Tracker tamam → ağırlıkları taze kümülatif veriyle yeniden öğren
        try:
            import ogren_engine as og
            data = _get(base + "/tracker/data", timeout=120)
            if data:
                w = og.compute_weights(data)
                st = og.load_state()
                st["weights"] = w.get("weights", {})
                st["base_rate"] = w.get("base_rate")
                st["weights_updated"] = w.get("updated")
                st["last_run_date"] = _today_tr_str()
                og.save_state(st)
                nw = len(w.get("weights", {}) or {})
                print("[auto_scheduler] ağırlıklar güncellendi · sinyal sayısı:", nw,
                      "· base:", w.get("base_rate"))
        except Exception as e:
            print("[auto_scheduler] ağırlık güncelleme hatası:", str(e)[:120])

        dur = int(time.time() - t0)
        print("[auto_scheduler] ✓ DÖNGÜ BİTTİ · tracker_tamam=%s · %ds" % (completed, dur))

    except Exception as e:
        import traceback
        traceback.print_exc()
        print("[auto_scheduler] ✗ döngü hatası:", str(e)[:160])
    finally:
        with _lock:
            _inflight = False


# ── ZAMANLAYICI DÖNGÜSÜ ─────────────────────────────────────────
def _loop():
    global _inflight
    print("[auto_scheduler] aktif · tetik: her iş günü %02d:%02d (TR) ·" % (RUN_HOUR, RUN_MIN),
          "ilk kontrol birazdan")
    # Başlangıçta uygulamanın tam ayağa kalkması için kısa bekleme
    time.sleep(45)
    while True:
        try:
            if _is_weekday() and _past_trigger_time() and not _already_ran_today():
                with _lock:
                    start_it = not _inflight
                    if start_it:
                        _inflight = True
                if start_it:
                    threading.Thread(target=_daily_run, daemon=True).start()
        except Exception as e:
            print("[auto_scheduler] döngü kontrol hatası:", str(e)[:120])
        time.sleep(CHECK_EVERY_SEC)


def start_scheduler():
    """Zamanlayıcı daemon thread'ini TEK SEFER başlatır (çift çağrıya güvenli)."""
    global _started
    if os.environ.get("AUTO_RUN_OFF", "").strip() in ("1", "true", "True", "yes"):
        print("[auto_scheduler] AUTO_RUN_OFF=1 → zamanlayıcı kapalı")
        return
    with _lock:
        if _started:
            return
        _started = True
    th = threading.Thread(target=_loop, daemon=True)
    th.start()
    print("[auto_scheduler] zamanlayıcı thread başlatıldı")


# Doğrudan import edilip elle de tetiklenebilir (test için):
#   python -c "import auto_scheduler as a; a._daily_run()"
if __name__ == "__main__":
    _daily_run()
