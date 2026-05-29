"""
═══════════════════════════════════════════════════════════════
vmom_router.py — V-MOM Backtest Render Endpoint v1.1
───────────────────────────────────────────────────────────────
v1.0 → v1.1 düzeltmeleri:
  ✓ Deadlock düzeltildi (_RUNNING durumu yanlış yerde set ediliyordu)
  ✓ Universe limiti kaldırıldı (200 → tüm 630 hisse)
  ✓ yfinance 100'lük gruplara bölündü (timeout/rate-limit dayanıklılığı)
  ✓ Bayat kilit (>15 dk eski) otomatik temizleniyor
  ✓ /vmom/reset endpoint'i eklendi (zorla sıfırla)

KULLANIM:
  1) GET /vmom/start    → arka planda başlat
  2) GET /vmom/status   → ilerleme
  3) GET /vmom/summary  → bitince özet
  4) GET /vmom/reset    → sıkışırsa zorla sıfırla
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
import json
import time
import math
import threading
import warnings
import traceback
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats
from fastapi import APIRouter, BackgroundTasks, HTTPException

try:
    import yfinance as yf
    _HAS_YF = True
except Exception:
    _HAS_YF = False


# ── KONFİG ───────────────────────────────────────────────────────
START_DATE = "2021-06-01"
BACKTEST_START = "2022-06-01"
BACKTEST_END = "2026-05-01"
TOP_N = 20
ROUND_TRIP_COST = 0.003
N_TRIALS = 4

CHUNK_SIZE = 100              # yfinance'a aynı anda gönderilecek max hisse
STALE_LOCK_MIN = 15           # Bu kadar dk hareket yoksa kilit bayat sayılır

STATUS_PATH = "/tmp/vmom_status.json"
RESULT_PATH = "/tmp/vmom_result.json"

_RUN_LOCK = threading.Lock()
_RUNNING = {"active": False}


# ── Yardımcılar ─────────────────────────────────────────────────
def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _write_status(stage: str, progress: int, detail: str = "", error: str = ""):
    try:
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "active": _RUNNING["active"],
                "stage": stage,
                "progress": progress,
                "detail": detail,
                "error": error,
                "updated_at": _now_iso(),
            }, f, ensure_ascii=False)
    except Exception:
        pass

def _read_status():
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _is_stale_lock():
    """Kilit aktif ama uzun süredir hareket yoksa bayattır."""
    if not _RUNNING["active"]:
        return False
    s = _read_status()
    if not s or not s.get("updated_at"):
        return True
    try:
        t = datetime.fromisoformat(s["updated_at"].replace("Z", "+00:00"))
        age_sec = (datetime.now(timezone.utc) - t).total_seconds()
        return age_sec > STALE_LOCK_MIN * 60
    except Exception:
        return True

def _clean(o):
    if isinstance(o, dict): return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_clean(v) for v in o]
    if isinstance(o, np.bool_): return bool(o)
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.floating):
        f = float(o)
        return None if (f != f or f in (float("inf"), float("-inf"))) else f
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    return o


# ── Universe (tüm 630 hisse) ────────────────────────────────────
_DEFAULT = [
    "AKBNK","AKSEN","ALARK","ARCLK","ASELS","BIMAS","BRSAN","CCOLA",
    "DOAS","EKGYO","ENJSA","ENKAI","EREGL","FROTO","GARAN","HALKB",
    "ISCTR","KCHOL","KOZAA","KOZAL","KRDMD","MGROS","ODAS","PETKM",
    "PGSUS","SAHOL","SASA","SISE","TAVHL","TCELL","THYAO","TKFEN",
    "TOASO","TTKOM","TUPRS","ULKER","VAKBN","VESTL","YKBNK","ZOREN"
]

def _load_universe():
    try:
        from symbols import BIST_SYMBOLS
        u = list(BIST_SYMBOLS)
        if u:
            return u   # LİMİT YOK — tüm 630 hisse
    except Exception:
        pass
    return _DEFAULT


# ── yfinance gruplu indirme ─────────────────────────────────────
def _fetch_in_chunks(tickers, start, end):
    """Tickers'ı CHUNK_SIZE'lik gruplara böler, paralel indirir."""
    all_close = {}
    n_total = len(tickers)
    n_chunks = (n_total + CHUNK_SIZE - 1) // CHUNK_SIZE

    for i in range(0, n_total, CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        chunk_no = i // CHUNK_SIZE + 1
        prog = 10 + int(30 * chunk_no / n_chunks)
        _write_status("fetching", prog,
                      f"yfinance grup {chunk_no}/{n_chunks} "
                      f"({len(chunk)} hisse, toplam: {len(all_close)})")
        try:
            df = yf.download(chunk, start=start, end=end, progress=False,
                             auto_adjust=True, group_by="ticker", threads=True,
                             timeout=120)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                for t in chunk:
                    try:
                        if (t, "Close") in df.columns:
                            s = df[t]["Close"]
                            if s.count() >= 252:
                                all_close[t] = s
                    except Exception:
                        continue
            else:
                # Tek ticker geldi
                if "Close" in df.columns and len(chunk) == 1:
                    s = df["Close"]
                    if s.count() >= 252:
                        all_close[chunk[0]] = s
        except Exception as e:
            print(f"[vmom] chunk {chunk_no} hata: {str(e)[:120]}")
            continue

    if not all_close:
        return pd.DataFrame()

    close = pd.DataFrame(all_close)
    close = close.sort_index()
    return close


# ── Sinyaller + portföy + backtest (önceki sürümle aynı) ────────
def _compute_signals(close_df, asof_idx):
    if asof_idx < 252:
        return None
    prices = close_df.iloc[: asof_idx + 1]
    p1m = prices.iloc[-22]; p12m = prices.iloc[-252]
    mom_12_1 = np.log(p1m / p12m)
    rets = np.log(prices / prices.shift(1)).dropna()
    vol_60d = rets.tail(60).std() * math.sqrt(252)
    with np.errstate(divide="ignore", invalid="ignore"):
        vmom = mom_12_1 / vol_60d
        vmom = vmom.replace([np.inf, -np.inf], np.nan)
    high_52w = prices.tail(252).max()
    current = prices.iloc[-1]
    high_prox = current / high_52w
    ema200 = prices.ewm(span=200, adjust=False).mean().iloc[-1]
    trend_ok = current > ema200
    return pd.DataFrame({
        "mom_12_1": mom_12_1, "vol_60d": vol_60d, "vmom": vmom,
        "high_prox": high_prox, "trend_ok": trend_ok, "price": current
    })

def _select(sig, variant, top_n):
    v = sig.dropna(subset=["mom_12_1"])
    if variant == "1_pure_mom":
        r = v.sort_values("mom_12_1", ascending=False)
    elif variant == "2_vmom":
        v = v.dropna(subset=["vmom"])
        r = v.sort_values("vmom", ascending=False)
    elif variant == "3_vmom_trend":
        v = v.dropna(subset=["vmom"])
        v = v[v["trend_ok"] == True]
        r = v.sort_values("vmom", ascending=False)
    elif variant == "4_vmom_full":
        v = v.dropna(subset=["vmom", "high_prox"])
        v = v[(v["trend_ok"] == True) & (v["high_prox"] >= 0.80)]
        r = v.sort_values("vmom", ascending=False)
    else:
        r = v.sort_values("mom_12_1", ascending=False)
    return r.head(top_n).index.tolist() if len(r) else []

def _dsr(sr, n_trials, n_obs, skew=0.0, kurt=3.0):
    if n_obs < 12: return 0.0
    emc = 0.5772156649
    nt = max(n_trials, 2)
    e_max = ((1 - emc) * stats.norm.ppf(1 - 1.0 / nt) +
             emc * stats.norm.ppf(1 - 1.0 / (nt * math.e)))
    var = (1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (n_obs - 1)
    if var <= 0: return 0.0
    return float(stats.norm.cdf((sr - e_max) / math.sqrt(var)))

def _run_one(close_df, variant):
    months = pd.date_range(BACKTEST_START, BACKTEST_END, freq="ME")
    rebal = []
    for m in months:
        mask = close_df.index <= m
        if mask.any():
            idx = int(mask.sum() - 1)
            if idx >= 252:
                rebal.append(idx)
    if len(rebal) < 6: return None

    mo_rets = []; holds = []
    for i in range(len(rebal) - 1):
        idx_now, idx_next = rebal[i], rebal[i + 1]
        sig = _compute_signals(close_df, idx_now)
        if sig is None: continue
        picks = _select(sig, variant, TOP_N)
        if not picks:
            mo_rets.append((close_df.index[idx_next], 0.0))
            holds.append((close_df.index[idx_now], []))
            continue
        pb = close_df.iloc[idx_now][picks]
        ps = close_df.iloc[idx_next][picks]
        valid = (~pb.isna()) & (~ps.isna()) & (pb > 0)
        if valid.sum() == 0: continue
        sr = (ps[valid] / pb[valid] - 1)
        mr = float(sr.mean()) - ROUND_TRIP_COST
        mo_rets.append((close_df.index[idx_next], mr))
        holds.append((close_df.index[idx_now], picks))

    if len(mo_rets) < 6: return None
    rets = pd.Series({d: r for d, r in mo_rets}).sort_index()
    n = len(rets); mu = float(rets.mean()); sd = float(rets.std())
    annual_ret = (1 + mu) ** 12 - 1
    annual_vol = sd * math.sqrt(12)
    sharpe = (mu / sd) * math.sqrt(12) if sd > 1e-9 else 0.0
    down = rets[rets < 0]
    sortino = (mu / down.std()) * math.sqrt(12) if len(down) > 1 and down.std() > 0 else 0.0
    eq = (1 + rets).cumprod()
    mdd = float((eq / eq.cummax() - 1).min())
    win = float((rets > 0).mean())
    return {
        "variant": variant, "n_months": n,
        "cagr": annual_ret, "annual_vol": annual_vol,
        "sharpe": sharpe, "sortino": sortino,
        "max_drawdown": mdd, "win_rate": win,
        "deflated_sharpe": _dsr(sharpe, N_TRIALS, n),
        "total_return": float(eq.iloc[-1] - 1),
        "last_picks": holds[-1][1] if holds else [],
    }


# ── Ana arka plan görevi ────────────────────────────────────────
def _run_backtest_task():
    # NOT: _RUNNING["active"] = True burada set ediliyor, /start'ta DEĞİL
    _RUNNING["active"] = True
    t0 = time.time()
    try:
        _write_status("starting", 2, "Başlatılıyor")
        if not _HAS_YF:
            raise RuntimeError("yfinance kurulu değil")

        universe = _load_universe()
        _write_status("universe", 5, f"Universe: {len(universe)} hisse yüklendi")

        tickers = [s.replace(".IS", "") + ".IS" for s in universe]
        close = _fetch_in_chunks(tickers, START_DATE, BACKTEST_END)
        if close.empty or close.shape[1] < 30:
            raise RuntimeError(f"Yetersiz hisse verisi: {close.shape[1]} < 30")
        # .IS suffix temizle
        close.columns = [c.replace(".IS", "") for c in close.columns]
        _write_status("fetched", 42,
                      f"{close.shape[1]}/{len(universe)} hisse, {len(close)} gün")

        # Benchmark
        _write_status("benchmark", 45, "XU100 benchmark")
        bench_obj = None
        try:
            bench = yf.download("XU100.IS", start=BACKTEST_START, end=BACKTEST_END,
                                progress=False, auto_adjust=True, timeout=60)["Close"]
            if isinstance(bench, pd.DataFrame):
                bench = bench.iloc[:, 0]
            bench_m = bench.resample("ME").last().pct_change().dropna()
            if len(bench_m) >= 6:
                b_cagr = (1 + bench_m.mean()) ** 12 - 1
                b_sd = bench_m.std()
                b_sharpe = (bench_m.mean() / b_sd) * math.sqrt(12) if b_sd > 0 else 0
                b_eq = (1 + bench_m).cumprod()
                b_mdd = float((b_eq / b_eq.cummax() - 1).min())
                bench_obj = {"cagr": float(b_cagr), "sharpe": float(b_sharpe),
                             "max_drawdown": b_mdd, "n_months": len(bench_m)}
        except Exception as e:
            print(f"[vmom] benchmark err: {str(e)[:120]}")

        # Varyantlar
        variants = ["1_pure_mom", "2_vmom", "3_vmom_trend", "4_vmom_full"]
        labels = {
            "1_pure_mom":   "Saf 12-1 Momentum (referans)",
            "2_vmom":       "+ Vol-ölçekleme (Barroso)",
            "3_vmom_trend": "+ Trend filtresi (EMA200)",
            "4_vmom_full":  "+ 52-hafta zirvesi yakın",
        }
        results = []
        for i, v in enumerate(variants):
            prog = 50 + int(45 * (i + 1) / len(variants))
            _write_status("backtest", prog, f"Test: {labels[v]}")
            try:
                r = _run_one(close, v)
            except Exception as e:
                print(f"[vmom] {v} err: {e}")
                r = None
            if r:
                r["label"] = labels[v]
                results.append(r)

        if not results:
            raise RuntimeError("Hiçbir varyant tamamlanamadı")

        best = max(results, key=lambda x: x["sharpe"])
        if best["deflated_sharpe"] >= 0.95:
            verdict = "ANLAMLI_EDGE"
            vt = "İstatistiksel olarak anlamlı edge var (DSR ≥ 0.95). Canlıya bağlanabilir."
        elif best["deflated_sharpe"] >= 0.80:
            verdict = "ZAYIF_EDGE"
            vt = "Zayıf edge (0.80 ≤ DSR < 0.95). Parametreleri ayarlamak gerekir."
        else:
            verdict = "EDGE_YOK"
            vt = "İstatistiksel edge yok (DSR < 0.80). Canlıya bağlanmamalı."

        payload = _clean({
            "config": {"start": BACKTEST_START, "end": BACKTEST_END,
                       "top_n": TOP_N, "cost": ROUND_TRIP_COST,
                       "universe_requested": len(universe),
                       "universe_used": int(close.shape[1])},
            "benchmark": bench_obj,
            "best_variant": best["variant"],
            "best_label": best["label"],
            "verdict": verdict,
            "verdict_text": vt,
            "results": results,
            "duration_sec": int(time.time() - t0),
            "completed_at": _now_iso(),
        })
        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        _write_status("completed", 100,
                      f"BİTTİ! En iyi: {best['variant']} · "
                      f"CAGR={best['cagr']*100:+.1f}% · Sharpe={best['sharpe']:.2f} · "
                      f"DSR={best['deflated_sharpe']:.2f}")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        _write_status("error", -1, "", err)
    finally:
        _RUNNING["active"] = False


# ── Router ──────────────────────────────────────────────────────
vmom_router = APIRouter(prefix="/vmom", tags=["vmom-backtest"])


@vmom_router.get("/start")
def vmom_start(background: BackgroundTasks):
    # Bayat kilidi otomatik temizle (>15 dk hareket yoksa)
    if _RUNNING["active"] and _is_stale_lock():
        _RUNNING["active"] = False
        _write_status("reset", 0, "Bayat kilit temizlendi")

    if _RUNNING["active"]:
        return {"status": "already_running",
                "message": "Backtest zaten çalışıyor. /vmom/status ile izle.",
                "hint": "Eğer sıkıştıysa /vmom/reset çağır."}

    # NOT: _RUNNING["active"] burada SET ETME — _run_backtest_task içinde edilecek
    _write_status("queued", 1, "Sıraya alındı")
    background.add_task(_run_backtest_task)
    return {"status": "started",
            "message": "Backtest arka planda başladı. 5-15 dakika sürer (630 hisse).",
            "next": "/vmom/status (ilerleme), /vmom/summary (sonuç)"}


@vmom_router.get("/status")
def vmom_status():
    s = _read_status()
    if s is None:
        return {"active": _RUNNING["active"], "stage": "none",
                "message": "Henüz başlatılmadı. /vmom/start çağır."}
    s["result_ready"] = os.path.exists(RESULT_PATH)
    s["actual_running"] = bool(_RUNNING["active"])
    s["is_stale"] = _is_stale_lock()
    return s


@vmom_router.get("/result")
def vmom_result():
    if not os.path.exists(RESULT_PATH):
        raise HTTPException(404,
            "Sonuç henüz yok. /vmom/start çağır, /vmom/status ile bekle.")
    try:
        with open(RESULT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(500, f"Sonuç okunamadı: {e}")


@vmom_router.get("/summary")
def vmom_summary():
    if not os.path.exists(RESULT_PATH):
        raise HTTPException(404, "Sonuç yok. /vmom/start çağır.")
    with open(RESULT_PATH, "r", encoding="utf-8") as f:
        r = json.load(f)
    L = []
    L.append("V-MOM BACKTEST · " + r.get("completed_at", ""))
    L.append("=" * 64)
    cfg = r.get("config", {})
    L.append(f"Dönem: {cfg.get('start')} → {cfg.get('end')}")
    L.append(f"Universe: {cfg.get('universe_used')}/{cfg.get('universe_requested')} hisse · Top {cfg.get('top_n')}")
    L.append("")
    bench = r.get("benchmark")
    if bench:
        L.append(f"XU100 BENCHMARK: CAGR={bench['cagr']*100:+.1f}% · "
                 f"Sharpe={bench['sharpe']:.2f} · MDD={bench['max_drawdown']*100:.1f}%")
        L.append("")
    L.append(f"{'Varyant':<14} {'CAGR':>8} {'Sharpe':>8} {'MDD':>8} {'DSR':>6} {'Win':>6}")
    L.append("-" * 64)
    for v in r.get("results", []):
        L.append(
            f"{v['variant']:<14} "
            f"{v['cagr']*100:+7.1f}% "
            f"{v['sharpe']:7.2f}  "
            f"{v['max_drawdown']*100:7.1f}% "
            f"{v['deflated_sharpe']:5.2f} "
            f"{v['win_rate']*100:5.0f}%"
        )
    L.append("")
    L.append(f"EN İYİ: {r.get('best_variant')} ({r.get('best_label','')})")
    L.append(f"KARAR: {r.get('verdict')} — {r.get('verdict_text','')}")
    L.append(f"Süre: {r.get('duration_sec','?')} sn")
    return {"summary_text": "\n".join(L), "raw": r}


@vmom_router.get("/reset")
def vmom_reset():
    """Sıkışırsa zorla sıfırla."""
    _RUNNING["active"] = False
    try:
        if os.path.exists(STATUS_PATH):
            os.remove(STATUS_PATH)
    except Exception:
        pass
    return {"status": "reset",
            "message": "Kilit sıfırlandı. Şimdi /vmom/start çağırabilirsin."}
