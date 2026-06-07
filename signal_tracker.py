"""
═══════════════════════════════════════════════════════════════
signal_tracker.py — SİNYAL DOĞRULAMA TAKİPÇİSİ v1.0
───────────────────────────────────────────────────────────────
Bilimsel, kümülatif, ileriye-dönük sinyal doğrulama sistemi.

NE YAPAR (tek /tracker/run çağrısında, arka planda):
  1) Her sinyalin (NVS/BKM/GS/Günlük/Kesişim) top-20'sini snapshot alır
  2) Kesişim setlerini hesaplar (NVS∩BKM, NVS∩Kesişim, hepsi-∩, ≥3, ≥2)
  3) Önceki snapshot'ı bugünün fiyatlarıyla eşler → %5+ hareket = isabet
  4) Hit rate / lift / kapsama metriklerini KÜMÜLATİF günceller
  5) HER HİSSE İÇİN en başarılı sinyali tespit eder (per-stock)

DEPOLAMA (kalıcılık):
  - GitHub Gist (kalıcı)  — GITHUB_TOKEN + TRACKER_GIST_ID env varsa
  - /tmp (yedek)          — env yoksa; uygulama uyanık kaldıkça durur

GÖRÜNTÜLEME:
  /tracker/dashboard      — panel (▶ İŞLE butonu + tüm tablolar)
  /tracker/run            — arka planda işle
  /tracker/status         — ilerleme
  /tracker/data           — ham JSON

KURULUM (main.py'a 2 satır):
    from signal_tracker import tracker_router
    app.include_router(tracker_router)
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
import json
import time
import base64
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone, date

import numpy as np
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from tv_scanner import fetch_tv_bulk
from nvs import analyze_nvs


# ── KONFİG ───────────────────────────────────────────────────────
SIGNALS = ["nvs", "bkm", "gs", "gunluk", "kesisim"]
SIGNAL_LABELS = {"nvs": "NVS", "bkm": "BKM", "gs": "GS",
                 "gunluk": "Günlük", "kesisim": "Kesişim"}
TOP_N = 20
HIT_THRESHOLD = 0.05          # %5+ ertesi gün hareketi = isabet
MIN_STOCK_PICKS = 3           # per-stock anlamlılık için min gözlem

# Takip edilen kombinasyonlar (hepsi: ilgili sinyallerin top-20'sinde ortak)
COMBO_DEFS = {
    "nvs+bkm":      ["nvs", "bkm"],
    "nvs+kesisim":  ["nvs", "kesisim"],
    "nvs+gunluk":   ["nvs", "gunluk"],
    "gunluk+kesisim": ["gunluk", "kesisim"],
    "nvs+bkm+gs":   ["nvs", "bkm", "gs"],
    "hepsi-5":      ["nvs", "bkm", "gs", "gunluk", "kesisim"],
}
COMBO_LABELS = {
    "nvs+bkm": "NVS ∩ BKM", "nvs+kesisim": "NVS ∩ Kesişim",
    "nvs+gunluk": "NVS ∩ Günlük", "gunluk+kesisim": "Günlük ∩ Kesişim",
    "nvs+bkm+gs": "NVS ∩ BKM ∩ GS", "hepsi-5": "Hepsi-5 (∩)",
    "min3": "≥3 sinyal", "min2": "≥2 sinyal",
}

STATUS_PATH = "/tmp/tracker_status.json"
TMP_DATA_PATH = "/tmp/tracker_data.json"
GIST_ID_PATH = "/tmp/tracker_gist_id.txt"
GIST_FILENAME = "vortex_tracker.json"

_RUN_LOCK = threading.Lock()
_RUNNING = {"active": False}


# ── Genel yardımcılar ───────────────────────────────────────────
def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _today():
    return date.today().isoformat()

def _clean(o):
    if isinstance(o, dict): return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_clean(v) for v in o]
    if isinstance(o, np.bool_): return bool(o)
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.floating):
        f = float(o); return None if (f != f or f in (float("inf"), float("-inf"))) else f
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    return o

def _write_status(stage, progress, detail="", error=""):
    try:
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump({"active": _RUNNING["active"], "stage": stage,
                       "progress": progress, "detail": detail, "error": error,
                       "updated_at": _now_iso()}, f, ensure_ascii=False)
    except Exception:
        pass

def _read_status():
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── DEPOLAMA KATMANI (Gist + /tmp) ──────────────────────────────
def _gh_token():
    return os.environ.get("GITHUB_TOKEN", "").strip()

def _gist_id():
    gid = os.environ.get("TRACKER_GIST_ID", "").strip()
    if gid:
        return gid
    try:
        with open(GIST_ID_PATH, "r") as f:
            return f.read().strip()
    except Exception:
        return ""

def _gist_api(method, url, payload=None):
    token = _gh_token()
    if not token:
        raise RuntimeError("no token")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "token " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "vortex-tracker")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _gist_create():
    """Yeni gist oluştur, id'sini /tmp'e kaydet."""
    payload = {"description": "Vortex-BIST Signal Tracker", "public": False,
               "files": {GIST_FILENAME: {"content": "{}"}}}
    r = _gist_api("POST", "https://api.github.com/gists", payload)
    gid = r.get("id", "")
    if gid:
        try:
            with open(GIST_ID_PATH, "w") as f:
                f.write(gid)
        except Exception:
            pass
    return gid

def storage_mode():
    if _gh_token():
        return "gist" if _gist_id() else "gist-new"
    return "tmp"

def load_data():
    """Kümülatif veriyi yükle. Gist varsa oradan, yoksa /tmp."""
    if _gh_token():
        try:
            gid = _gist_id()
            if not gid:
                gid = _gist_create()
            if gid:
                r = _gist_api("GET", "https://api.github.com/gists/" + gid)
                files = r.get("files", {})
                fobj = files.get(GIST_FILENAME)
                if fobj and fobj.get("content"):
                    return json.loads(fobj["content"])
                return _empty_data()
        except Exception as e:
            print("[tracker] gist load err:", str(e)[:120])
    # /tmp fallback
    try:
        with open(TMP_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _empty_data()

def save_data(data):
    data = _clean(data)
    # /tmp her zaman yaz (yedek)
    try:
        with open(TMP_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass
    # Gist (kalıcı)
    if _gh_token():
        try:
            gid = _gist_id() or _gist_create()
            if gid:
                payload = {"files": {GIST_FILENAME: {
                    "content": json.dumps(data, ensure_ascii=False)}}}
                _gist_api("PATCH", "https://api.github.com/gists/" + gid, payload)
        except Exception as e:
            print("[tracker] gist save err:", str(e)[:120])

def _empty_data():
    return {
        "created_at": _now_iso(),
        "snapshots": {},          # date -> {ts, prices{}, signals{sig:[syms]}}
        "cumulative": {
            "days_evaluated": 0,
            "universe_picks": 0, "universe_hits": 0,
            "signals": {s: {"picks": 0, "hits": 0} for s in SIGNALS},
            "combos": {c: {"picks": 0, "hits": 0}
                       for c in list(COMBO_DEFS.keys()) + ["min3", "min2"]},
            "per_stock": {},      # sym -> {sig: {p,h}}
        },
        "last_eval_date": None,
        "eval_log": [],           # son birkaç değerlendirme özeti
    }


# ── VERİ ÇEKME ──────────────────────────────────────────────────
def _build_nvs_inputs(d_raw, w_raw, m_raw):
    d = {'rec': d_raw.get('rec'), 'rsi': d_raw.get('rsi'), 'stoch': d_raw.get('stoch'),
         'macd': d_raw.get('macd'), 'ema20': d_raw.get('ema20'), 'ema50': d_raw.get('ema50'),
         'ema200': d_raw.get('ema200'), 'vol': d_raw.get('vol'),
         'vol_avg': d_raw.get('vol_avg'), 'adx': d_raw.get('adx')}
    w = {'rec': w_raw.get('rec'), 'rsi': w_raw.get('rsi'), 'stoch': w_raw.get('stoch'),
         'macd': w_raw.get('macd'), 'ema20': w_raw.get('ema20'), 'ema50': w_raw.get('ema50')}
    m = {'rec': m_raw.get('rec'), 'rsi': m_raw.get('rsi'), 'stoch': m_raw.get('stoch'),
         'macd': m_raw.get('macd'), 'ema20': m_raw.get('ema20'), 'ema50': m_raw.get('ema50')}
    return d, w, m

def _fetch_scores():
    """Tüm hisseler için nvs/bkm/gs/gunluk + fiyat. {sym: {...}}"""
    bulk = fetch_tv_bulk(limit=700)
    if not bulk or (bulk and '_error' in bulk[0]):
        raise RuntimeError("TV bulk veri gelmedi")
    out = {}
    for row in bulk:
        sym = (row.get('symbol') or '').strip().upper()
        if not sym:
            continue
        d_raw = row.get('d') or {}
        if d_raw.get('_error'):
            continue
        if d_raw.get('rsi') is None and d_raw.get('rec') is None:
            continue
        d, w, m = _build_nvs_inputs(d_raw, row.get('w') or {}, row.get('m') or {})
        try:
            r = analyze_nvs(sym, d, w, m)
        except Exception:
            continue
        price = d_raw.get('_close') or d_raw.get('close')
        if not price or price <= 0:
            continue
        out[sym] = {
            "nvs": r.get("nvs"), "bkm": r.get("bkm"),
            "gs": r.get("guven_skoru"), "gunluk": r.get("gunluk"),
            "price": float(price), "change": d_raw.get('change'),
        }
    return out

def _fetch_kesisim_set():
    """Crossover cache'inden kesisim top sembolleri (taze YENİ öncelikli)."""
    try:
        import crossover_scanner as cs
    except Exception:
        return [], "modül yok"
    # Cache bayatsa tazele (bugün değilse)
    try:
        cache = cs._cache
        lu = cache.get("last_updated")
        stale = True
        if lu:
            stale = (lu[:10] != _today())
        if stale and not cache.get("scanning"):
            try:
                cs.run_full_scan()   # bloklar (~2-3 dk) ama arka plandayız
            except Exception as e:
                print("[tracker] crossover scan err:", str(e)[:120])
        data = cs._cache.get("data") or []
    except Exception:
        data = []
    # data zaten YENİ→ORTA→YÜKSEK + pct sıralı; ilk TOP_N sembol
    syms = []
    for r in data:
        s = (r.get("symbol") or "").strip().upper()
        if s:
            syms.append(s)
    return syms[:TOP_N], "ok"


# ── SİNYAL SETLERİ ──────────────────────────────────────────────
def _build_signal_sets(scores, kesisim_syms):
    """Her sinyal için top-20 sembol listesi."""
    sets = {}
    for sig in ["nvs", "bkm", "gs", "gunluk"]:
        ranked = sorted(
            [(s, v.get(sig)) for s, v in scores.items() if v.get(sig) is not None],
            key=lambda x: x[1], reverse=True)
        sets[sig] = [s for s, _ in ranked[:TOP_N]]
    sets["kesisim"] = list(kesisim_syms)
    return sets

def _membership_count(sets):
    """Her sembol kaç sinyalin top-20'sinde? {sym: count}"""
    cnt = {}
    for sig in SIGNALS:
        for s in sets.get(sig, []):
            cnt[s] = cnt.get(s, 0) + 1
    return cnt

def _combo_picks(sets):
    """Her kombinasyon için sembol listesi."""
    out = {}
    for cname, sigs in COMBO_DEFS.items():
        common = None
        for sig in sigs:
            ss = set(sets.get(sig, []))
            common = ss if common is None else (common & ss)
        out[cname] = sorted(common) if common else []
    cnt = _membership_count(sets)
    out["min3"] = sorted([s for s, c in cnt.items() if c >= 3])
    out["min2"] = sorted([s for s, c in cnt.items() if c >= 2])
    return out


# ── DEĞERLENDİRME ───────────────────────────────────────────────
def _evaluate_prev(data, today_scores, today_str):
    """Önceki (değerlendirilmemiş) snapshot'ı bugünün fiyatlarıyla eşle."""
    snaps = data.get("snapshots", {})
    # Bugünden önceki, henüz değerlendirilmemiş en güncel snapshot
    prev_dates = sorted([d for d in snaps.keys() if d < today_str], reverse=True)
    target = None
    for d in prev_dates:
        if not snaps[d].get("evaluated"):
            target = d
            break
    if target is None:
        return None
    snap = snaps[target]
    prev_prices = snap.get("prices", {})
    prev_signals = snap.get("signals", {})
    prev_combos = snap.get("combos", {})

    # Bugünkü fiyatlar
    cur_prices = {s: v["price"] for s, v in today_scores.items()}

    def ret(sym):
        p0 = prev_prices.get(sym); p1 = cur_prices.get(sym)
        if not p0 or not p1 or p0 <= 0:
            return None
        return p1 / p0 - 1.0

    cum = data["cumulative"]

    # Universe baseline
    uni_picks = 0; uni_hits = 0
    for sym in prev_prices.keys():
        r = ret(sym)
        if r is None:
            continue
        uni_picks += 1
        if r >= HIT_THRESHOLD:
            uni_hits += 1
    cum["universe_picks"] += uni_picks
    cum["universe_hits"] += uni_hits

    # Sinyal başına
    sig_results = {}
    for sig in SIGNALS:
        picks = prev_signals.get(sig, [])
        h = 0; p = 0
        for sym in picks:
            r = ret(sym)
            if r is None:
                continue
            p += 1
            hit = r >= HIT_THRESHOLD
            if hit:
                h += 1
            # per-stock
            ps = cum["per_stock"].setdefault(sym, {})
            rec = ps.setdefault(sig, {"p": 0, "h": 0})
            rec["p"] += 1
            if hit:
                rec["h"] += 1
        cum["signals"][sig]["picks"] += p
        cum["signals"][sig]["hits"] += h
        sig_results[sig] = {"picks": p, "hits": h}

    # Kombo başına
    combo_results = {}
    for cname in list(COMBO_DEFS.keys()) + ["min3", "min2"]:
        picks = prev_combos.get(cname, [])
        h = 0; p = 0
        for sym in picks:
            r = ret(sym)
            if r is None:
                continue
            p += 1
            if r >= HIT_THRESHOLD:
                h += 1
        cum["combos"][cname]["picks"] += p
        cum["combos"][cname]["hits"] += h
        combo_results[cname] = {"picks": p, "hits": h}

    cum["days_evaluated"] += 1
    snaps[target]["evaluated"] = True
    data["last_eval_date"] = today_str

    gap = (date.fromisoformat(today_str) - date.fromisoformat(target)).days
    log = {"snapshot": target, "evaluated_on": today_str, "gap_days": gap,
           "universe": {"picks": uni_picks, "hits": uni_hits},
           "signals": sig_results, "combos": combo_results}
    data.setdefault("eval_log", []).insert(0, log)
    data["eval_log"] = data["eval_log"][:30]
    return log


# ── ANA İŞLEM ───────────────────────────────────────────────────
def _run_task():
    _RUNNING["active"] = True
    t0 = time.time()
    try:
        _write_status("starting", 3, "Başlatılıyor")
        data = load_data()

        _write_status("fetching", 15, "NVS/BKM/GS/Günlük çekiliyor (TV)")
        scores = _fetch_scores()
        if len(scores) < 30:
            raise RuntimeError("Yetersiz hisse: " + str(len(scores)))

        _write_status("crossover", 35, "Kesişim taraması (gerekirse ~2-3dk)")
        kesisim_syms, kmsg = _fetch_kesisim_set()

        _write_status("building", 70, "Sinyal setleri + kombinasyonlar")
        sets = _build_signal_sets(scores, kesisim_syms)
        combos = _combo_picks(sets)

        today_str = _today()

        # Bugünün snapshot'ını kaydet (fiyatlar dahil)
        prices = {s: v["price"] for s, v in scores.items()}
        data["snapshots"][today_str] = {
            "ts": _now_iso(),
            "prices": prices,
            "signals": sets,
            "combos": combos,
            "evaluated": False,
            "kesisim_status": kmsg,
        }
        # Snapshot tarihçesini 45 günle sınırla (boyut)
        all_dates = sorted(data["snapshots"].keys())
        for d in all_dates[:-45]:
            data["snapshots"].pop(d, None)

        _write_status("evaluating", 85, "Önceki snapshot değerlendiriliyor")
        ev = _evaluate_prev(data, scores, today_str)

        _write_status("saving", 95, "Kaydediliyor (" + storage_mode() + ")")
        save_data(data)

        msg = "Snapshot alındı (" + str(len(scores)) + " hisse). "
        if ev:
            msg += ("Değerlendirildi: " + ev["snapshot"] +
                    " (evren isabet: " + str(ev["universe"]["hits"]) +
                    "/" + str(ev["universe"]["picks"]) + ")")
        else:
            msg += "İlk gün — yarın ilk değerlendirme yapılır."
        _write_status("completed", 100, msg)
    except Exception as e:
        import traceback; traceback.print_exc()
        _write_status("error", -1, "", str(type(e).__name__) + ": " + str(e))
    finally:
        _RUNNING["active"] = False


# ── METRİK HESABI (dashboard için) ──────────────────────────────
def _compute_metrics(data):
    cum = data["cumulative"]
    up = cum["universe_picks"]; uh = cum["universe_hits"]
    baseline = (uh / up) if up > 0 else 0.0

    def metrics(picks, hits):
        hr = (hits / picks) if picks > 0 else 0.0
        lift = (hr / baseline) if baseline > 0 else 0.0
        cov = (hits / uh) if uh > 0 else 0.0
        return {"picks": picks, "hits": hits, "hit_rate": hr,
                "lift": lift, "coverage": cov}

    sig_rows = []
    for s in SIGNALS:
        d = cum["signals"][s]
        m = metrics(d["picks"], d["hits"]); m["key"] = s
        m["label"] = SIGNAL_LABELS[s]; sig_rows.append(m)
    sig_rows.sort(key=lambda x: x["hit_rate"], reverse=True)

    combo_rows = []
    for c in list(COMBO_DEFS.keys()) + ["min3", "min2"]:
        d = cum["combos"][c]
        m = metrics(d["picks"], d["hits"]); m["key"] = c
        m["label"] = COMBO_LABELS.get(c, c); combo_rows.append(m)
    combo_rows.sort(key=lambda x: x["hit_rate"], reverse=True)

    # Per-stock: en iyi sinyali ve hit rate'i
    stock_rows = []
    for sym, sigs in cum["per_stock"].items():
        best_sig = None; best_hr = -1; best_p = 0; total_p = 0; total_h = 0
        for sig, rec in sigs.items():
            p = rec["p"]; h = rec["h"]; total_p += p; total_h += h
            if p >= MIN_STOCK_PICKS:
                hr = h / p
                if hr > best_hr or (hr == best_hr and p > best_p):
                    best_hr = hr; best_sig = sig; best_p = p
        if best_sig is not None:
            stock_rows.append({
                "sym": sym, "best_signal": SIGNAL_LABELS.get(best_sig, best_sig),
                "best_hit_rate": best_hr, "best_picks": best_p,
                "total_picks": total_p, "total_hits": total_h,
            })
    stock_rows.sort(key=lambda x: (x["best_hit_rate"], x["best_picks"]), reverse=True)

    return {"baseline": baseline, "signals": sig_rows, "combos": combo_rows,
            "stocks": stock_rows[:40], "days_evaluated": cum["days_evaluated"],
            "universe_picks": up, "universe_hits": uh}

def _today_high_conviction(data):
    """Bugünkü en yüksek-güven seti (hepsi-5 ∩, yoksa min3)."""
    today = data.get("snapshots", {}).get(_today())
    if not today:
        return [], "yok"
    combos = today.get("combos", {})
    if combos.get("hepsi-5"):
        return combos["hepsi-5"], "Hepsi-5 (∩)"
    if combos.get("min3"):
        return combos["min3"], "≥3 sinyal"
    if combos.get("min2"):
        return combos["min2"], "≥2 sinyal"
    return [], "yok"


# ── ROUTER ──────────────────────────────────────────────────────
tracker_router = APIRouter(prefix="/tracker", tags=["signal-tracker"])

@tracker_router.get("/run")
def tracker_run(background: BackgroundTasks):
    if _RUNNING["active"]:
        s = _read_status()
        if s and s.get("updated_at"):
            try:
                t = datetime.fromisoformat(s["updated_at"].replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - t).total_seconds() > 20 * 60:
                    _RUNNING["active"] = False
            except Exception:
                pass
    if _RUNNING["active"]:
        return {"status": "already_running", "message": "Zaten çalışıyor. /tracker/status"}
    _write_status("queued", 1, "Sıraya alındı")
    background.add_task(_run_task)
    return {"status": "started", "message": "İşlem başladı (~1-4 dk, kesişim taze değilse uzar)."}

@tracker_router.get("/status")
def tracker_status():
    s = _read_status()
    if s is None:
        return {"stage": "none", "message": "Henüz çalıştırılmadı. /tracker/run"}
    s["storage"] = storage_mode()
    return s

@tracker_router.get("/data")
def tracker_data():
    data = load_data()
    return JSONResponse(_clean({"metrics": _compute_metrics(data),
                                "today_picks": _today_high_conviction(data),
                                "last_eval_date": data.get("last_eval_date"),
                                "storage": storage_mode(),
                                "eval_log": data.get("eval_log", [])[:7]}))

@tracker_router.get("/reset")
def tracker_reset():
    _RUNNING["active"] = False
    save_data(_empty_data())
    try:
        if os.path.exists(STATUS_PATH):
            os.remove(STATUS_PATH)
    except Exception:
        pass
    return {"status": "reset", "message": "Tüm takip verisi sıfırlandı."}

@tracker_router.get("/dashboard", response_class=HTMLResponse)
def tracker_dashboard():
    return _DASHBOARD_HTML


# ── DASHBOARD HTML (var-only, XHR, mobil) ───────────────────────
_DASHBOARD_HTML = r"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>📊 Sinyal Doğrulama · Vortex-BIST</title>
<style>
:root{--bg:#0a0a0a;--card:#121212;--bd:#1f1f1f;--green:#22c55e;--g2:#1a3a1a;
--yellow:#e8b84b;--red:#ef4444;--teal:#42d49c;--mut:#888;--txt:#e8e8e8;--dim:#aaa;--blue:#60a5fa}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--txt);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:10px 8px 40px}
h1{font-size:16px;margin:0 0 2px;color:var(--blue);font-weight:700}
h2{font-size:13px;margin:16px 0 6px;color:var(--teal);letter-spacing:.04em}
.sub{color:var(--mut);font-size:11px;margin-bottom:10px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:10px;margin-bottom:8px}
.btn{background:var(--g2);color:var(--green);border:1px solid #2a5a2a;border-radius:6px;
padding:11px 16px;font:600 14px/1 inherit;cursor:pointer;margin-right:6px;width:100%;margin-bottom:6px}
.btn:active{transform:translateY(1px)}
.btn-sec{background:#181818;color:var(--dim);border-color:var(--bd)}
.info{color:var(--mut);font-size:12px;margin-top:6px;min-height:14px}
.prog{height:5px;background:#181818;border-radius:3px;overflow:hidden;margin:8px 0;display:none}
.prog.on{display:block}.prog-fill{height:100%;background:var(--green);width:0%;transition:width .3s}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}
th{background:#161616;color:var(--dim);padding:6px 4px;text-align:right;font:600 10px/1.2 inherit;
text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid #2a2a2a}
th.l,td.l{text-align:left}
td{padding:7px 4px;border-bottom:1px solid #161616;text-align:right}
.lbl{color:var(--txt);font-weight:600}
.hr-hi{color:var(--green);font-weight:700}.hr-mid{color:var(--yellow)}.hr-lo{color:var(--mut)}
.pill{display:inline-block;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:700;
background:rgba(96,165,250,.14);color:var(--blue);border:1px solid rgba(96,165,250,.3)}
.big{font-size:22px;font-weight:700;color:var(--green)}
.muted{color:var(--mut);font-size:11px}
.empty{color:#555;text-align:center;padding:24px 8px;font-size:13px}
.tag{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:700;margin:2px 3px 2px 0}
.warn{background:#2a1505;color:var(--yellow);border:1px solid #4a3515;padding:8px;border-radius:6px;font-size:11px;margin-bottom:8px}
.foot{color:#444;font-size:10px;text-align:center;margin-top:16px}
</style></head><body>

<h1>📊 SİNYAL DOĞRULAMA</h1>
<div class="sub">Her sinyalin %5+ ertesi-gün hareketi tahmin gücü · kümülatif, bilimsel</div>

<div class="card">
  <button class="btn" id="btnRun">▶ BUGÜNÜ İŞLE</button>
  <button class="btn btn-sec" id="btnRefresh">↻ PANELİ YENİLE</button>
  <div class="prog" id="prog"><div class="prog-fill" id="pf"></div></div>
  <div class="info" id="info">Hazır.</div>
</div>

<div id="content"></div>

<div class="foot">Vortex-BIST · Signal Tracker v1.0 · %5+ eşik · top-20</div>

<script>
var pollT=null;
function $(id){return document.getElementById(id);}
function pct(x){if(x==null||isNaN(x))return '-';return (x*100).toFixed(0)+'%';}
function fx(x){if(x==null||isNaN(x))return '-';return Number(x).toFixed(2)+'×';}
function hrClass(hr,base){if(hr>=base*1.8)return 'hr-hi';if(hr>=base*1.2)return 'hr-mid';return 'hr-lo';}

function xhr(url, cb, err){
  var x=new XMLHttpRequest();x.open('GET',url,true);x.timeout=300000;
  x.onload=function(){if(x.status>=200&&x.status<300){try{cb(JSON.parse(x.responseText));}catch(e){if(err)err(e);}}else if(err)err(new Error('HTTP '+x.status));};
  x.onerror=function(){if(err)err(new Error('net'));};
  x.ontimeout=function(){if(err)err(new Error('timeout'));};
  x.send();
}

function runNow(){
  $('btnRun').disabled=true;$('prog').className='prog on';$('pf').style.width='5%';
  $('info').textContent='Başlatılıyor...';
  xhr('/tracker/run', function(r){
    if(r.status==='already_running'){$('info').textContent='Zaten çalışıyor, izleniyor...';}
    else{$('info').textContent='İşlem başladı, ilerleme izleniyor...';}
    poll();
  }, function(){$('info').textContent='✗ Başlatılamadı';$('btnRun').disabled=false;});
}

function poll(){
  if(pollT)clearTimeout(pollT);
  xhr('/tracker/status', function(s){
    var p=s.progress||0;
    if(p<0){$('info').innerHTML='<span style="color:#ef4444">✗ '+(s.error||'hata')+'</span>';
      $('btnRun').disabled=false;$('prog').className='prog';return;}
    $('pf').style.width=Math.max(5,p)+'%';
    $('info').textContent='['+(s.stage||'')+'] '+(s.detail||'')+' ('+p+'%)';
    if(s.stage==='completed'){$('btnRun').disabled=false;
      setTimeout(function(){$('prog').className='prog';},800);loadData();return;}
    pollT=setTimeout(poll,3000);
  }, function(){pollT=setTimeout(poll,4000);});
}

function loadData(){
  $('info').textContent='Panel yükleniyor...';
  xhr('/tracker/data', function(d){render(d);$('info').textContent='Güncel.';},
    function(){$('info').textContent='✗ Veri alınamadı';});
}

function render(d){
  var m=d.metrics, base=m.baseline, H='';
  // Depolama uyarısı
  if(d.storage==='tmp'){
    H+='<div class="warn">⚠ Geçici depolama (/tmp). Uygulama yeniden deploy olursa veri sıfırlanır. '+
       'Kalıcılık için GitHub Gist kur (panel altındaki nota bak).</div>';
  }
  // Özet
  H+='<div class="card"><div style="display:flex;gap:12px;flex-wrap:wrap">';
  H+='<div><div class="muted">Değerlendirilen gün</div><div class="big">'+m.days_evaluated+'</div></div>';
  H+='<div><div class="muted">Toplam gözlem</div><div class="big" style="color:#60a5fa">'+m.universe_picks+'</div></div>';
  H+='<div><div class="muted">Evren isabet (baz)</div><div class="big" style="color:#e8b84b">'+pct(base)+'</div></div>';
  H+='</div>';
  if(m.days_evaluated===0){
    H+='<div class="muted" style="margin-top:8px">Henüz değerlendirme yok. Bugün işle, yarın tekrar işle → ilk sonuç gelir. Anlamlı istatistik için ~10-14 gün.</div>';
  }
  H+='</div>';

  // Bugünkü yüksek-güven
  if(d.today_picks && d.today_picks[0] && d.today_picks[0].length){
    H+='<h2>⚡ BUGÜNKÜ YÜKSEK-GÜVEN ('+d.today_picks[1]+')</h2>';
    H+='<div class="card">';
    var ps=d.today_picks[0],i;
    for(i=0;i<ps.length;i++){H+='<span class="tag" style="background:rgba(34,197,94,.14);color:#22c55e;border:1px solid rgba(34,197,94,.3)">'+ps[i]+'</span>';}
    H+='<div class="muted" style="margin-top:6px">En çok sinyalin birleştiği hisseler — en yüksek olasılıklı bahisler (kanıt biriktikçe doğrula).</div></div>';
  }

  // Sinyal liderlik
  if(m.days_evaluated>0){
    H+='<h2>🎯 SİNYAL PERFORMANSI (tekil)</h2><div class="card"><table>';
    H+='<tr><th class="l">Sinyal</th><th>İsabet</th><th>Lift</th><th>Kapsama</th><th>Gözlem</th></tr>';
    var i,r;
    for(i=0;i<m.signals.length;i++){r=m.signals[i];
      H+='<tr><td class="l lbl">'+r.label+'</td>'+
        '<td class="'+hrClass(r.hit_rate,base)+'">'+pct(r.hit_rate)+'</td>'+
        '<td>'+fx(r.lift)+'</td><td>'+pct(r.coverage)+'</td><td class="muted">'+r.picks+'</td></tr>';
    }
    H+='</table></div>';

    // Kombo liderlik
    H+='<h2>🔗 KOMBİNASYON PERFORMANSI</h2><div class="card"><table>';
    H+='<tr><th class="l">Kombinasyon</th><th>İsabet</th><th>Lift</th><th>Kapsama</th><th>Gözlem</th></tr>';
    for(i=0;i<m.combos.length;i++){r=m.combos[i];
      H+='<tr><td class="l lbl">'+r.label+'</td>'+
        '<td class="'+hrClass(r.hit_rate,base)+'">'+pct(r.hit_rate)+'</td>'+
        '<td>'+fx(r.lift)+'</td><td>'+pct(r.coverage)+'</td><td class="muted">'+r.picks+'</td></tr>';
    }
    H+='</table><div class="muted" style="margin-top:6px">Lift = rastgeleye göre kaç kat iyi. 1.0× = şans. Yüksek lift + makul gözlem = gerçek edge.</div></div>';

    // Per-stock
    if(m.stocks && m.stocks.length){
      H+='<h2>🏆 HİSSE BAZINDA EN İYİ SİNYAL</h2><div class="card"><table>';
      H+='<tr><th class="l">Hisse</th><th class="l">En iyi sinyal</th><th>İsabet</th><th>Gözlem</th></tr>';
      for(i=0;i<m.stocks.length;i++){r=m.stocks[i];
        H+='<tr><td class="l lbl">'+r.sym+'</td><td class="l"><span class="pill">'+r.best_signal+'</span></td>'+
          '<td class="'+hrClass(r.best_hit_rate,base)+'">'+pct(r.best_hit_rate)+'</td>'+
          '<td class="muted">'+r.best_picks+'</td></tr>';
      }
      H+='</table><div class="muted" style="margin-top:6px">Her hissenin geçmişte en çok %5+ getirdiği sinyal. Min '+'3 gözlem.</div></div>';
    }
  }

  $('content').innerHTML=H;
}

$('btnRun').onclick=runNow;
$('btnRefresh').onclick=loadData;
loadData();
</script>
</body></html>
"""
