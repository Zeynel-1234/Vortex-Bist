"""
═══════════════════════════════════════════════════════════════
vmom_router.py — V-MOM Backtest Render Endpoint v1.0
───────────────────────────────────────────────────────────────
Backtest'i Render'da arka planda çalıştırır. Replit'e gerek yok.

KULLANIM (sırayla):
  1) GET /vmom/start    → arka planda başlat (anında dön)
  2) GET /vmom/status   → her dakika kontrol et (ilerleme)
  3) GET /vmom/result   → bitince sonuçları al

KURULUM (main.py'a 2 satır):
    from vmom_router import vmom_router
    app.include_router(vmom_router)
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
from datetime import datetime

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

STATUS_PATH = "/tmp/vmom_status.json"
RESULT_PATH = "/tmp/vmom_result.json"

_RUN_LOCK = threading.Lock()
_RUNNING = {"active": False}


# ── Status yardımcıları ─────────────────────────────────────────
def _write_status(stage: str, progress: int, detail: str = "", error: str = ""):
    try:
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "active": _RUNNING["active"],
                "stage": stage,
                "progress": progress,
                "detail": detail,
                "error": error,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }, f, ensure_ascii=False)
    except Exception:
        pass


def _read_status():
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        f = float(o)
        return None if (f != f or f in (float("inf"), float("-inf"))) else f
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    return o


# ── Universe ─────────────────────────────────────────────────────
def _load_universe():
    try:
        from symbols import BIST_SYMBOLS
        u = list(BIST_SYMBOLS)
        # Çok büyükse ilk 200'le sınırla (yfinance toplu indirme limiti)
        return u[:200]
    except Exception:
        return ["AKBNK","AKSEN","ALARK","ARCLK","ASELS","BIMAS","BRSAN","CCOLA",
                "DOAS","EKGYO","ENJSA","ENKAI","EREGL","FROTO","GARAN","HALKB",
                "ISCTR","KCHOL","KOZAA","KOZAL","KRDMD","MGROS","ODAS","PETKM",
                "PGSUS","SAHOL","SASA","SISE","TAVHL","TCELL","THYAO","TKFEN",
                "TOASO","TTKOM","TUPRS","ULKER","VAKBN","VESTL","YKBNK","ZOREN"]


# ── Sinyal hesaplama ────────────────────────────────────────────
def _compute_signals(close_df, asof_idx):
    if asof_idx < 252:
        return None
    prices = close_df.iloc[: asof_idx + 1]
    p1m = prices.iloc[-22]
    p12m = prices.iloc[-252]
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


def _select_portfolio(sig, variant, top_n):
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
    if len(r) == 0:
        return []
    return r.head(top_n).index.tolist()


def _deflated_sharpe(sr, n_trials, n_obs, skew=0.0, kurt=3.0):
    if n_obs < 12:
        return 0.0
    emc = 0.5772156649
    nt = max(n_trials, 2)
    e_max = ((1 - emc) * stats.norm.ppf(1 - 1.0 / nt) +
             emc * stats.norm.ppf(1 - 1.0 / (nt * math.e)))
    var = (1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (n_obs - 1)
    if var <= 0:
        return 0.0
    return float(stats.norm.cdf((sr - e_max) / math.sqrt(var)))


def _run_one(close_df, variant):
    months = pd.date_range(BACKTEST_START, BACKTEST_END, freq="ME")
    rebal_idxs = []
    for m in months:
        mask = close_df.index <= m
        if mask.any():
            idx = int(mask.sum() - 1)
            if idx >= 252:
                rebal_idxs.append(idx)
    if len(rebal_idxs) < 6:
        return None
    monthly_rets = []
    holdings = []
    for i in range(len(rebal_idxs) - 1):
        idx_now = rebal_idxs[i]
        idx_next = rebal_idxs[i + 1]
        sig = _compute_signals(close_df, idx_now)
        if sig is None:
            continue
        picks = _select_portfolio(sig, variant, TOP_N)
        if not picks:
            monthly_rets.append((close_df.index[idx_next], 0.0))
            holdings.append((close_df.index[idx_now], []))
            continue
        p_buy = close_df.iloc[idx_now][picks]
        p_sell = close_df.iloc[idx_next][picks]
        valid = (~p_buy.isna()) & (~p_sell.isna()) & (p_buy > 0)
        if valid.sum() == 0:
            continue
        stock_rets = (p_sell[valid] / p_buy[valid] - 1)
        month_ret = float(stock_rets.mean()) - ROUND_TRIP_COST
        monthly_rets.append((close_df.index[idx_next], month_ret))
        holdings.append((close_df.index[idx_now], picks))
    if len(monthly_rets) < 6:
        return None
    rets = pd.Series({d: r for d, r in monthly_rets}).sort_index()
    n_months = len(rets)
    mu_m = float(rets.mean())
    sd_m = float(rets.std())
    annual_ret = (1 + mu_m) ** 12 - 1
    annual_vol = sd_m * math.sqrt(12)
    sharpe = (mu_m / sd_m) * math.sqrt(12) if sd_m > 1e-9 else 0.0
    down = rets[rets < 0]
    sortino = (mu_m / down.std()) * math.sqrt(12) if len(down) > 1 and down.std() > 0 else 0.0
    equity = (1 + rets).cumprod()
    mdd = float((equity / equity.cummax() - 1).min())
    win_rate = float((rets > 0).mean())
    dsr = _deflated_sharpe(sharpe, N_TRIALS, n_months)
    return {
        "variant": variant, "n_months": n_months,
        "cagr": annual_ret, "annual_vol": annual_vol,
        "sharpe": sharpe, "sortino": sortino,
        "max_drawdown": mdd, "win_rate": win_rate,
        "deflated_sharpe": dsr,
        "total_return": float(equity.iloc[-1] - 1),
        "last_picks": holdings[-1][1] if holdings else [],
    }


# ── Ana backtest akışı ──────────────────────────────────────────
def _run_backtest_task():
    if _RUNNING["active"]:
        return
    _RUNNING["active"] = True
    t0 = time.time()
    try:
        _write_status("starting", 0, "Backtest başlatılıyor")
        if not _HAS_YF:
            raise RuntimeError("yfinance yüklü değil")

        # 1) Universe
        _write_status("universe", 5, "Universe yükleniyor")
        universe = _load_universe()

        # 2) Veri çek
        _write_status("fetching", 10, f"yfinance: {len(universe)} hisse indiriliyor")
        tickers = [s.replace(".IS", "") + ".IS" for s in universe]
        df = yf.download(tickers, start=START_DATE, end=BACKTEST_END,
                         progress=False, auto_adjust=True,
                         group_by="ticker", threads=True)
        if isinstance(df.columns, pd.MultiIndex):
            close = pd.DataFrame({
                t: (df[t]["Close"] if (t, "Close") in df.columns else pd.Series(dtype=float))
                for t in tickers
            })
        else:
            close = pd.DataFrame({tickers[0]: df["Close"]}) if "Close" in df.columns else pd.DataFrame()
        close = close.dropna(axis=1, how="all")
        valid = close.columns[close.count() >= 252]
        close = close[valid].copy()
        close.columns = [c.replace(".IS", "") for c in close.columns]
        if close.shape[1] < 30:
            raise RuntimeError(f"Yetersiz hisse: {close.shape[1]} < 30")
        _write_status("fetched", 40,
                      f"{close.shape[1]} hisse, {len(close)} gün")

        # 3) Benchmark
        _write_status("benchmark", 45, "XU100 indiriliyor")
        bench_obj = None
        try:
            bench = yf.download("XU100.IS", start=BACKTEST_START, end=BACKTEST_END,
                                progress=False, auto_adjust=True)["Close"]
            if isinstance(bench, pd.DataFrame):
                bench = bench.iloc[:, 0]
            bench_m = bench.resample("ME").last().pct_change().dropna()
            if len(bench_m) >= 6:
                b_cagr = (1 + bench_m.mean()) ** 12 - 1
                b_sharpe = (bench_m.mean() / bench_m.std()) * math.sqrt(12) if bench_m.std() > 0 else 0
                b_eq = (1 + bench_m).cumprod()
                b_mdd = float((b_eq / b_eq.cummax() - 1).min())
                bench_obj = {"cagr": float(b_cagr), "sharpe": float(b_sharpe),
                             "max_drawdown": b_mdd, "n_months": len(bench_m)}
        except Exception as e:
            print(f"[vmom] benchmark err: {e}")

        # 4) Varyantları çalıştır
        variants = ["1_pure_mom", "2_vmom", "3_vmom_trend", "4_vmom_full"]
        labels = {
            "1_pure_mom":   "Saf 12-1 Momentum (referans)",
            "2_vmom":       "+ Vol-ölçekleme (Barroso)",
            "3_vmom_trend": "+ Trend filtresi (EMA200)",
            "4_vmom_full":  "+ 52-hafta zirvesi yakın",
        }
        results = []
        for i, v in enumerate(variants):
            prog = 50 + int(40 * (i + 1) / len(variants))
            _write_status("backtest", prog, f"Test ediliyor: {labels[v]}")
            try:
                r = _run_one(close, v)
            except Exception as e:
                print(f"[vmom] {v} err: {e}")
                r = None
            if r is not None:
                r["label"] = labels[v]
                results.append(r)

        if not results:
            raise RuntimeError("Hiçbir varyant tamamlanamadı")

        best = max(results, key=lambda x: x["sharpe"])
        if best["deflated_sharpe"] >= 0.95:
            verdict = "ANLAMLI_EDGE"
            verdict_text = "İstatistiksel olarak anlamlı edge var (DSR ≥ 0.95). Canlıya bağlanabilir."
        elif best["deflated_sharpe"] >= 0.80:
            verdict = "ZAYIF_EDGE"
            verdict_text = "Zayıf edge (0.80 ≤ DSR < 0.95). Parametreleri ayarlamak gerekir."
        else:
            verdict = "EDGE_YOK"
            verdict_text = "İstatistiksel edge yok (DSR < 0.80). Canlıya bağlanmamalı."

        payload = {
            "config": {"start": BACKTEST_START, "end": BACKTEST_END,
                       "top_n": TOP_N, "cost": ROUND_TRIP_COST,
                       "universe_size": int(close.shape[1])},
            "benchmark": bench_obj,
            "best_variant": best["variant"],
            "best_label": best["label"],
            "verdict": verdict,
            "verdict_text": verdict_text,
            "results": results,
            "duration_sec": int(time.time() - t0),
            "completed_at": datetime.utcnow().isoformat() + "Z",
        }
        payload = _clean(payload)
        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        _write_status("completed", 100,
                      f"Bitti! En iyi: {best['variant']} · "
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
    """Backtest'i arka planda başlat."""
    if _RUNNING["active"]:
        return {"status": "already_running",
                "message": "Backtest zaten çalışıyor. /vmom/status ile izle."}
    with _RUN_LOCK:
        _RUNNING["active"] = True
    _write_status("queued", 1, "Sıraya alındı")
    background.add_task(_run_backtest_task)
    return {"status": "started",
            "message": "Backtest arka planda başladı. 5-10 dakika sürer.",
            "next": "/vmom/status (ilerleme) ve /vmom/result (sonuç)"}


@vmom_router.get("/status")
def vmom_status():
    """Backtest ilerleme durumu."""
    s = _read_status()
    if s is None:
        return {"active": _RUNNING["active"], "stage": "none",
                "message": "Henüz başlatılmadı. /vmom/start çağır."}
    has_result = os.path.exists(RESULT_PATH)
    s["result_ready"] = has_result
    return s


@vmom_router.get("/result")
def vmom_result():
    """Bitmiş backtest sonucu."""
    if not os.path.exists(RESULT_PATH):
        raise HTTPException(404,
            "Sonuç henüz yok. /vmom/start ile başlat, /vmom/status ile bekle.")
    try:
        with open(RESULT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(500, f"Sonuç okunamadı: {e}")


@vmom_router.get("/summary")
def vmom_summary():
    """İnsan-okur özet (tablo)."""
    if not os.path.exists(RESULT_PATH):
        raise HTTPException(404, "Sonuç yok. /vmom/start çağır.")
    with open(RESULT_PATH, "r", encoding="utf-8") as f:
        r = json.load(f)
    lines = []
    lines.append("V-MOM BACKTEST · " + r.get("completed_at", ""))
    lines.append("=" * 60)
    cfg = r.get("config", {})
    lines.append(f"Dönem: {cfg.get('start')} → {cfg.get('end')}")
    lines.append(f"Universe: {cfg.get('universe_size')} hisse · Top {cfg.get('top_n')}")
    lines.append("")
    bench = r.get("benchmark")
    if bench:
        lines.append(f"XU100 BENCHMARK: CAGR={bench['cagr']*100:+.1f}% · "
                     f"Sharpe={bench['sharpe']:.2f} · MDD={bench['max_drawdown']*100:.1f}%")
        lines.append("")
    lines.append(f"{'Varyant':<14} {'CAGR':>8} {'Sharpe':>8} {'MDD':>8} {'DSR':>6} {'Win':>6}")
    lines.append("-" * 60)
    for v in r.get("results", []):
        lines.append(
            f"{v['variant']:<14} "
            f"{v['cagr']*100:+7.1f}% "
            f"{v['sharpe']:7.2f}  "
            f"{v['max_drawdown']*100:7.1f}% "
            f"{v['deflated_sharpe']:5.2f} "
            f"{v['win_rate']*100:5.0f}%"
        )
    lines.append("")
    lines.append(f"EN İYİ: {r.get('best_variant')} ({r.get('best_label','')})")
    lines.append(f"KARAR: {r.get('verdict')} — {r.get('verdict_text','')}")
    return {"summary_text": "\n".join(lines), "raw": r}
