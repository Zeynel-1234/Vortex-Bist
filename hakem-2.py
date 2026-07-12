"""
═══════════════════════════════════════════════════════════════════════════
HAKEM · Kural Doğrulama Tezgâhı — "önce kanıt, sonra kod"
───────────────────────────────────────────────────────────────────────────
SABİT KABUL EŞİKLERİ (koşudan ÖNCE kilitlendi; sonradan OYNANMAZ):
  E1 · TEST sinyal sayısı  ≥ 30
  E2 · TEST lift           ≥ 1.5   (isabet / koşulsuz taban)
  E3 · TEST medyan max GÖRELİ getiri (63 bar) ≥ +%15
  E4 · TEST sinyal-sonrası medyan max düşüş   ≤ %12
Dördü birden geçen kural ONAYLI; aksi hâlde panele giremez.
Ölçüm: XU100'e GÖRELİ · ufuk 63 işlem günü (~3 ay) · zaman-bazlı %70/30.
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import json
import threading
import statistics
import datetime as dt
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

import makro_trend_lab as MT
import dip_dna as DD

HORIZON = 63
SPLIT = 0.7
ESIK = {"min_test_sinyal": 30, "min_lift": 1.5,
        "min_medyan_getiri": 0.15, "max_medyan_dusus": 0.12}

BASKET = ["LUKSK", "PRKAB", "PSDTC", "THYAO", "ASELS", "SISE", "EREGL",
          "FROTO", "TOASO", "KRDMD", "PGSUS", "HEKTS", "KCHOL", "GARAN",
          "TUPRS", "BIMAS", "SAHOL", "MGROS", "AKSA", "VESTL"]

_state = {"updated": None, "sonuc": None}
_run = {"on": False, "progress": 0, "total": 0, "err": None}


# ── YARGILANAN KURALLAR (günlük df → bool Series, nedensel) ─────────────
def _rule_makro(df: pd.DataFrame) -> pd.Series:
    """Aylık makro SINYAL'i günlük eksene taşır (ay içinde ilk gün işaretli)."""
    s = MT.compute_signals(MT.to_monthly(df))
    out = pd.Series(False, index=pd.to_datetime(df.index))
    if s is None:
        return out
    for ts in s.index[s["SINYAL"].values]:
        m = (out.index.to_period("M") == pd.Period(ts, "M"))
        if m.any():
            out.iloc[int(np.argmax(m))] = True     # ayın ilk günü
    return out

def _rule_dipdna(df: pd.DataFrame) -> pd.Series:
    dna = DD.build_dna(df)
    idx = pd.to_datetime(df.index)
    out = pd.Series(False, index=idx)
    if not dna or dna.get("env") is None or dna["episodes"] < DD.MIN_EPISODES:
        return out
    F = dna["F"]; last = -10**9
    for i in range(260, len(F)):
        ok, _ = DD._match_row(F, dna["env"], i)
        hz = F["hacim_z"].iloc[i]
        if ok >= 6 and np.isfinite(hz) and hz >= 1.0 and i - last >= 15:
            last = i; out.iloc[i] = True
    return out

def _rule_kesisim(df: pd.DataFrame) -> pd.Series:
    """Aylık ST(50,1)×EMA20(high) taze kesişim (KSŞ mantığı), günlük eksende."""
    dm = MT.to_monthly(df)
    out = pd.Series(False, index=pd.to_datetime(df.index))
    if dm is None or len(dm) < 55:
        return out
    c = pd.to_numeric(dm["Close"], errors="coerce")
    h = pd.to_numeric(dm["High"], errors="coerce")
    l = pd.to_numeric(dm["Low"], errors="coerce")
    _, d = MT.supertrend(h, l, c, period=50, mult=1.0)
    ema = h.ewm(span=20, adjust=False).mean()
    cond = (d == 1) & (c > ema)
    fresh = cond & ~cond.shift(1).fillna(False)
    for ts in dm.index[fresh.values]:
        m = (out.index.to_period("M") == pd.Period(ts, "M"))
        if m.any():
            out.iloc[int(np.argmax(m))] = True
    return out

RULES: Dict[str, Callable] = {"MAKRO_SINYAL": _rule_makro,
                              "DIP_DNA": _rule_dipdna,
                              "KESISIM_AYLIK": _rule_kesisim}


def _judge(fetch_ohlc, symbols: List[str]) -> Dict:
    # XU100 (göreli ölçüm)
    xu = None
    for tk in ("XU100", "XU100.IS"):
        try:
            xdf = MT._norm_cols(fetch_ohlc(tk, period="max"))
            if xdf is not None and len(xdf) > 300:
                xu = pd.to_numeric(xdf["Close"], errors="coerce")
                xu.index = pd.to_datetime(xdf.index); break
        except Exception:
            pass
    agg = {r: {"tr_s": 0, "tr_h": 0, "te_s": 0, "te_h": 0,
               "te_g": [], "te_d": [], "bz_a": 0, "bz_h": 0} for r in RULES}
    import gc
    for k, sym in enumerate(symbols):
        _run["progress"] = k + 1
        try:
            df = MT._norm_cols(fetch_ohlc(sym, period="max"))
            if df is None or len(df) < 400:
                continue
            df.index = pd.to_datetime(df.index)
            c = pd.to_numeric(df["Close"], errors="coerce")
            base = c
            if xu is not None:
                x = xu.reindex(c.index, method="ffill")
                base = c / x.replace(0, np.nan)
            b = base.values; n = len(b); cut = int(n * SPLIT)
            fmax = np.full(n, np.nan); fmin = np.full(n, np.nan)
            for i in range(n - 1):
                j = min(i + HORIZON, n - 1)
                w = b[i + 1:j + 1]; w = w[np.isfinite(w)]
                if len(w) and np.isfinite(b[i]) and b[i] > 0:
                    fmax[i] = w.max() / b[i] - 1.0
                    fmin[i] = w.min() / b[i] - 1.0
            valid = ~np.isnan(fmax)
            for rname, fn in RULES.items():
                try:
                    sig = fn(df).values
                except Exception:
                    continue
                a = agg[rname]
                for i in range(n - HORIZON):
                    if not valid[i]:
                        continue
                    hit = fmax[i] >= ESIK["min_medyan_getiri"] * 2  # taban: +%30 göreli
                    if i >= cut:
                        a["bz_a"] += 1; a["bz_h"] += int(hit)
                    if sig[i]:
                        if i < cut:
                            a["tr_s"] += 1; a["tr_h"] += int(hit)
                        else:
                            a["te_s"] += 1; a["te_h"] += int(hit)
                            a["te_g"].append(float(fmax[i]))
                            a["te_d"].append(float(-fmin[i]))
            del df; gc.collect()
        except Exception:
            pass
    out = {}
    for rname, a in agg.items():
        te_p = a["te_h"] / a["te_s"] if a["te_s"] else None
        bz_p = a["bz_h"] / a["bz_a"] if a["bz_a"] else None
        lift = (te_p / bz_p) if (te_p is not None and bz_p) else None
        mg = statistics.median(a["te_g"]) if a["te_g"] else None
        md = statistics.median(a["te_d"]) if a["te_d"] else None
        k1 = a["te_s"] >= ESIK["min_test_sinyal"]
        k2 = (lift or 0) >= ESIK["min_lift"]
        k3 = (mg or -9) >= ESIK["min_medyan_getiri"]
        k4 = (md if md is not None else 9) <= ESIK["max_medyan_dusus"]
        out[rname] = {
            "train": {"sinyal": a["tr_s"], "isabet30": a["tr_h"]},
            "test": {"sinyal": a["te_s"], "isabet30": a["te_h"],
                     "precision": round(te_p, 3) if te_p is not None else None,
                     "taban": round(bz_p, 3) if bz_p is not None else None,
                     "lift": round(lift, 2) if lift else None,
                     "medyan_max_getiri": round(mg, 3) if mg is not None else None,
                     "medyan_max_dusus": round(md, 3) if md is not None else None},
            "esikler": {"E1_sinyal>=30": k1, "E2_lift>=1.5": k2,
                        "E3_getiri>=%15": k3, "E4_dusus<=%12": k4},
            "KARAR": "ONAYLI ✅" if (k1 and k2 and k3 and k4) else "RED ❌",
        }
    return {"olcum": "XU100'e göreli · 63 bar ufuk · hedef +%30 · split %70/30",
            "esikler": ESIK, "hisse_sayisi": len(symbols), "kurallar": out}


def install_hakem(app, fetch_ohlc: Callable) -> None:
    from fastapi import Query

    @app.get("/hakem/status")
    def hakem_status():
        return {"running": _run["on"], "progress": _run["progress"],
                "total": _run["total"], "updated": _state["updated"],
                "sonuc": _state["sonuc"], "err": _run["err"]}

    @app.get("/hakem/run")
    def hakem_run(symbols: str = Query("")):
        if _run["on"]:
            return {"status": "zaten çalışıyor — /hakem/status"}
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if not syms:
            try:
                syms = MT._universe_symbols() or BASKET   # TAM EVREN duruşması
            except Exception:
                syms = BASKET
        _run.update({"on": True, "progress": 0, "total": len(syms), "err": None})

        def _go():
            try:
                _state["sonuc"] = _judge(fetch_ohlc, syms)
                _state["updated"] = dt.datetime.now().isoformat(timespec="seconds")
            except Exception as e:
                import traceback
                print("[hakem] HATA:\n" + traceback.format_exc())
                _run["err"] = str(e)[:200]
            finally:
                _run["on"] = False
        threading.Thread(target=_go, daemon=True).start()
        return {"status": "başladı", "hisse": len(syms),
                "not": "~5-10 dk · /hakem/status ile izle"}
