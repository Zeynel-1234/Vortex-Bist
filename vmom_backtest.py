"""
═══════════════════════════════════════════════════════════════
vmom_backtest.py — V-MOM Stratejisi BIST Backtest v1.0
───────────────────────────────────────────────────────────────
Volatilite-ölçekli, 52-hafta-zirvesi-farkındalıklı, trend-filtreli momentum.

Akademik kaynaklar:
  - Jegadeesh-Titman (1993): 12-1 ay momentum standardı
  - Barroso & Santa-Clara (2015): vol-ölçekleme → Sharpe ~2×
  - Daniel & Moskowitz (2016): dinamik momentum
  - George & Hwang (2004): 52-hafta zirvesi yakınlığı
  - Bailey & López de Prado: Deflated Sharpe (çoklu test düzeltmesi)

ÇALIŞTIRMA (Replit shell):
    pip install yfinance pandas numpy scipy   # yoksa
    python vmom_backtest.py

ÇIKTI:
  - Konsola özet (4 varyant + benchmark)
  - vmom_backtest_results.json (detay)

SÜRE: ~5-10 dakika (yfinance 150 hisse indirir)
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import sys
import json
import time
import math
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

try:
    import numpy as np
    import pandas as pd
    import yfinance as yf
    from scipy import stats
except ImportError as e:
    print("✗ Eksik paket:", e)
    print("  Çalıştır: pip install yfinance pandas numpy scipy")
    sys.exit(1)


# ── KONFİG ───────────────────────────────────────────────────────
START_DATE = "2021-06-01"     # Veri başlangıcı (signal için 1y warmup gerek)
BACKTEST_START = "2022-06-01" # Backtest başlangıcı
BACKTEST_END = "2026-05-01"   # Backtest sonu
TOP_N = 20                    # Portföyde tutulacak hisse sayısı
ROUND_TRIP_COST = 0.003       # %0.3 alış-satış maliyeti (BIST gerçekçi)
N_TRIALS = 4                  # Test edilen varyant sayısı (Deflated SR için)

# Universe: BIST'te likit hisseler. symbols.py varsa oradan al,
# yoksa hardcoded top 100 likit.
DEFAULT_UNIVERSE = [
    "AKBNK","AKSEN","ALARK","ARCLK","ASELS","ASTOR","AYDEM","BIMAS","BIOEN",
    "BRSAN","CCOLA","CIMSA","DOAS","DOHOL","ECILC","EKGYO","ENJSA","ENKAI",
    "EREGL","EUREN","FROTO","GARAN","GUBRF","HALKB","HEKTS","ISCTR","ISGYO",
    "KAYSE","KCAER","KCHOL","KCAR","KOZAA","KOZAL","KORDS","KRDMD","KOZAA",
    "MAVI","MGROS","ODAS","OYAKC","OTKAR","PETKM","PGSUS","SAHOL","SASA",
    "SISE","SKBNK","SMRTG","SOKM","TAVHL","TCELL","THYAO","TKFEN","TKNSA",
    "TOASO","TSKB","TTKOM","TTRAK","TUKAS","TUPRS","ULKER","VAKBN","VESBE",
    "VESTL","YEOTK","YKBNK","YUNSA","ZOREN","AEFES","AGHOL","AGROT","AKCNS",
    "AKSA","ALKIM","ALTNY","ANSGR","ARDYZ","BERA","BFREN","BRISA","BUCIM",
    "CCOLA","CWENE","DEVA","DGKLB","DOAS","DOCO","EGEEN","EKOS","ENERY",
    "EREGL","FORMT","GESAN","GLYHO","GOZDE","GUBRF","GWIND","HALKB","HEKTS",
    "INVES","ISYAT","KAREL","KARSN","KCAER","KIMMR","KLMSN","KONTR","KOZAA"
]


def load_universe():
    try:
        from symbols import BIST_SYMBOLS
        return list(BIST_SYMBOLS)
    except Exception:
        return list(set(DEFAULT_UNIVERSE))


def fetch_universe_history(symbols, start, end):
    """yfinance ile toplu fiyat çek. .IS suffix ekler."""
    print(f"  → yfinance: {len(symbols)} hisse çekiliyor ({start} → {end})")
    tickers = [s.replace(".IS", "") + ".IS" for s in symbols]
    t0 = time.time()
    # Toplu indirme (paralel, daha hızlı)
    df = yf.download(tickers, start=start, end=end, progress=False,
                     auto_adjust=True, group_by="ticker", threads=True)
    # Sadece Close fiyatları
    if isinstance(df.columns, pd.MultiIndex):
        # MultiIndex: (ticker, OHLCV)
        close = pd.DataFrame({
            t: df[t]["Close"] if (t, "Close") in df.columns else pd.Series(dtype=float)
            for t in tickers
        })
    else:
        close = df[["Close"]].copy()
        close.columns = [tickers[0]]
    # Veri olmayan kolonları at
    close = close.dropna(axis=1, how="all")
    # Yeterli veri yok olanları at (1 yıldan az)
    valid = close.columns[close.count() >= 252]
    close = close[valid].copy()
    # .IS suffix'i isimden temizle (görsel için)
    close.columns = [c.replace(".IS", "") for c in close.columns]
    elapsed = time.time() - t0
    print(f"  ✓ {len(close.columns)}/{len(symbols)} hisse, {len(close)} gün, {elapsed:.1f}sn")
    return close


def compute_signals(close_df, asof_idx):
    """asof_idx (integer date index) itibarıyla tüm sinyalleri hesapla."""
    if asof_idx < 252:
        return None
    prices = close_df.iloc[: asof_idx + 1]
    # 12-1 ay log momentum (son ayı dışla)
    p1m = prices.iloc[-22]   # 1 ay önce
    p12m = prices.iloc[-252] # 12 ay önce
    mom_12_1 = np.log(p1m / p12m)
    # Realize volatilite (60 gün, yıllık)
    rets = np.log(prices / prices.shift(1)).dropna()
    vol_60d = rets.tail(60).std() * math.sqrt(252)
    # Vol-ölçekli momentum
    with np.errstate(divide="ignore", invalid="ignore"):
        vmom = mom_12_1 / vol_60d
        vmom = vmom.replace([np.inf, -np.inf], np.nan)
    # 52-hafta zirvesi yakınlığı (1.0 = zirvede)
    high_52w = prices.tail(252).max()
    current = prices.iloc[-1]
    high_prox = current / high_52w
    # Trend filtresi: fiyat > EMA200
    ema200 = prices.ewm(span=200, adjust=False).mean().iloc[-1]
    trend_ok = current > ema200
    sig = pd.DataFrame({
        "mom_12_1": mom_12_1, "vol_60d": vol_60d, "vmom": vmom,
        "high_prox": high_prox, "trend_ok": trend_ok, "price": current
    })
    return sig


def select_portfolio(signal, variant, top_n):
    """Varyanta göre top_n hisse seç."""
    valid = signal.dropna(subset=["mom_12_1"])
    if variant == "1_pure_mom":
        # Saf 12-1 momentum (referans)
        ranked = valid.sort_values("mom_12_1", ascending=False)
    elif variant == "2_vmom":
        # Vol-ölçekli momentum (Barroso edge)
        v = valid.dropna(subset=["vmom"])
        ranked = v.sort_values("vmom", ascending=False)
    elif variant == "3_vmom_trend":
        # Vol-ölçekli + trend filtresi (faber/antonacci)
        v = valid.dropna(subset=["vmom"])
        v = v[v["trend_ok"] == True]
        ranked = v.sort_values("vmom", ascending=False)
    elif variant == "4_vmom_full":
        # Vol-ölçekli + trend + 52-hafta zirvesi yakın (George-Hwang)
        v = valid.dropna(subset=["vmom", "high_prox"])
        v = v[(v["trend_ok"] == True) & (v["high_prox"] >= 0.80)]
        ranked = v.sort_values("vmom", ascending=False)
    else:
        ranked = valid.sort_values("mom_12_1", ascending=False)
    if len(ranked) == 0:
        return []
    return ranked.head(top_n).index.tolist()


def deflated_sharpe(sr, n_trials, n_obs, skew=0.0, kurt=3.0):
    """Bailey & López de Prado: çoklu test düzeltmesi."""
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


def run_backtest(close_df, variant, top_n=TOP_N):
    """Aylık rebalance, eşit ağırlık, long-only."""
    # Aylık rebalance noktaları (her ayın son işgününe yakın)
    months = pd.date_range(BACKTEST_START, BACKTEST_END, freq="ME")
    # Her ay için en yakın trading gününü bul
    rebal_idxs = []
    for m in months:
        # m tarihine eşit veya küçük en son trading gün
        mask = close_df.index <= m
        if mask.any():
            idx = mask.sum() - 1
            if idx >= 252:
                rebal_idxs.append(idx)
    if len(rebal_idxs) < 6:
        return None
    monthly_rets = []
    holdings_history = []
    for i in range(len(rebal_idxs) - 1):
        idx_now = rebal_idxs[i]
        idx_next = rebal_idxs[i + 1]
        sig = compute_signals(close_df, idx_now)
        if sig is None:
            continue
        picks = select_portfolio(sig, variant, top_n)
        if not picks:
            monthly_rets.append((close_df.index[idx_next], 0.0))
            holdings_history.append((close_df.index[idx_now], []))
            continue
        # Eşit ağırlık ay getirisi
        p_buy = close_df.iloc[idx_now][picks]
        p_sell = close_df.iloc[idx_next][picks]
        valid = (~p_buy.isna()) & (~p_sell.isna()) & (p_buy > 0)
        if valid.sum() == 0:
            continue
        stock_rets = (p_sell[valid] / p_buy[valid] - 1)
        month_ret = float(stock_rets.mean()) - ROUND_TRIP_COST
        monthly_rets.append((close_df.index[idx_next], month_ret))
        holdings_history.append((close_df.index[idx_now], picks))
    if len(monthly_rets) < 6:
        return None
    rets = pd.Series({d: r for d, r in monthly_rets}).sort_index()
    # İstatistikler
    n_months = len(rets)
    mu_m = float(rets.mean())
    sd_m = float(rets.std())
    annual_ret = (1 + mu_m) ** 12 - 1
    annual_vol = sd_m * math.sqrt(12)
    sharpe = (mu_m / sd_m) * math.sqrt(12) if sd_m > 1e-9 else 0.0
    sortino = 0.0
    down = rets[rets < 0]
    if len(down) > 1:
        sortino = (mu_m / down.std()) * math.sqrt(12)
    equity = (1 + rets).cumprod()
    mdd = float((equity / equity.cummax() - 1).min())
    win_rate = float((rets > 0).mean())
    dsr = deflated_sharpe(sharpe, N_TRIALS, n_months)
    return {
        "variant": variant, "n_months": n_months,
        "cagr": annual_ret, "annual_vol": annual_vol,
        "sharpe": sharpe, "sortino": sortino,
        "max_drawdown": mdd, "win_rate": win_rate,
        "deflated_sharpe": dsr,
        "total_return": float(equity.iloc[-1] - 1),
        "monthly_returns": [(str(d.date()), float(r)) for d, r in monthly_rets],
        "holdings": [(str(d.date()), p) for d, p in holdings_history],
    }


def fmt_pct(x): return f"{x*100:+.1f}%"
def fmt_x(x): return f"{x:.2f}"


def main():
    print("\n═══════════════════════════════════════════════════════")
    print("  V-MOM BIST BACKTEST v1.0")
    print("═══════════════════════════════════════════════════════")
    print(f"  Dönem: {BACKTEST_START} → {BACKTEST_END}")
    print(f"  Portföy: Top {TOP_N}, eşit ağırlık, aylık rebalance")
    print(f"  Maliyet: %{ROUND_TRIP_COST*100} round-trip")

    universe = load_universe()
    print(f"\n[1/3] Universe: {len(universe)} hisse")

    print("\n[2/3] Tarihsel veri çekiliyor...")
    try:
        close = fetch_universe_history(universe, START_DATE, BACKTEST_END)
    except Exception as e:
        print(f"✗ Veri çekme hatası: {e}")
        sys.exit(1)
    if close.shape[1] < 30:
        print(f"✗ Yetersiz hisse ({close.shape[1]} < 30). Universe büyüt.")
        sys.exit(1)

    # Benchmark XU100
    print("\n[3/3] Benchmark (XU100)...")
    try:
        bench = yf.download("XU100.IS", start=BACKTEST_START,
                            end=BACKTEST_END, progress=False, auto_adjust=True)["Close"]
        if isinstance(bench, pd.DataFrame):
            bench = bench.iloc[:, 0]
        bench_m = bench.resample("ME").last().pct_change().dropna()
        b_cagr = (1 + bench_m.mean()) ** 12 - 1
        b_sharpe = (bench_m.mean() / bench_m.std()) * math.sqrt(12) if bench_m.std() > 0 else 0
        b_eq = (1 + bench_m).cumprod()
        b_mdd = (b_eq / b_eq.cummax() - 1).min()
        print(f"  XU100: CAGR={fmt_pct(b_cagr)} Sharpe={fmt_x(b_sharpe)} MDD={fmt_pct(b_mdd)}")
        bench_obj = {"cagr": float(b_cagr), "sharpe": float(b_sharpe),
                     "max_drawdown": float(b_mdd), "n_months": len(bench_m)}
    except Exception as e:
        print(f"  ⚠ Benchmark alınamadı: {e}")
        bench_obj = None

    # Backtest varyantları
    print("\n═══ VARYANTLAR ═══")
    variants = ["1_pure_mom", "2_vmom", "3_vmom_trend", "4_vmom_full"]
    labels = {
        "1_pure_mom":   "Saf 12-1 Momentum (referans)",
        "2_vmom":       "+ Vol-ölçekleme (Barroso)",
        "3_vmom_trend": "+ Trend filtresi (EMA200)",
        "4_vmom_full":  "+ 52-hafta zirvesi yakın",
    }
    results = []
    for v in variants:
        print(f"\n→ {labels[v]}")
        try:
            r = run_backtest(close, v)
        except Exception as e:
            print(f"  ✗ Hata: {e}")
            continue
        if r is None:
            print("  ⚠ Yetersiz veri")
            continue
        print(f"  CAGR: {fmt_pct(r['cagr'])}  Sharpe: {fmt_x(r['sharpe'])}  "
              f"Sortino: {fmt_x(r['sortino'])}  MDD: {fmt_pct(r['max_drawdown'])}")
        print(f"  Win rate: {r['win_rate']*100:.0f}%  Deflated SR: {fmt_x(r['deflated_sharpe'])}  "
              f"({r['n_months']} ay)")
        if bench_obj:
            print(f"  vs XU100: CAGR alfa={fmt_pct(r['cagr']-bench_obj['cagr'])}, "
                  f"Sharpe Δ={fmt_x(r['sharpe']-bench_obj['sharpe'])}")
        results.append(r)

    # Karar
    print("\n═══ KARAR ═══")
    if not results:
        print("✗ Hiçbir varyant tamamlanamadı")
        sys.exit(1)
    best = max(results, key=lambda x: x["sharpe"])
    print(f"En iyi varyant: {best['variant']} ({labels[best['variant']]})")
    print(f"  CAGR: {fmt_pct(best['cagr'])}")
    print(f"  Sharpe: {fmt_x(best['sharpe'])}")
    print(f"  Deflated Sharpe: {fmt_x(best['deflated_sharpe'])}")
    print()
    if best["deflated_sharpe"] >= 0.95:
        print("✓ İSTATİSTİKSEL OLARAK ANLAMLI EDGE VAR (DSR ≥ 0.95)")
        print("  → Canlıya bağlamaya değer. Sonraki adım: live entegrasyon.")
    elif best["deflated_sharpe"] >= 0.80:
        print("⚠ ZAYIF EDGE (0.80 ≤ DSR < 0.95)")
        print("  → Parametreleri ayarla veya daha uzun dönemde tekrar test et.")
    else:
        print("✗ İSTATİSTİKSEL EDGE YOK (DSR < 0.80)")
        print("  → Bu konfigürasyonda canlıya bağlama. Yeniden tasarla.")
    # JSON kaydet
    out_path = "vmom_backtest_results.json"
    payload = {
        "config": {"start": BACKTEST_START, "end": BACKTEST_END,
                   "top_n": TOP_N, "cost": ROUND_TRIP_COST,
                   "universe_size": int(close.shape[1])},
        "benchmark": bench_obj,
        "best_variant": best["variant"],
        "results": [
            {k: v for k, v in r.items() if k not in ("monthly_returns", "holdings")}
            for r in results
        ],
        "best_holdings": best.get("holdings", [])[-3:],  # son 3 ay
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✓ Detay: {out_path}")
    print("  Bana bu dosyayı veya konsol özetini gönder, birlikte yorumlayalım.\n")


if __name__ == "__main__":
    main()
