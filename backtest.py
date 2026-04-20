"""
Fraktal Kahin · Backtest Motoru v1
v1.0 sinyallerinin geçmiş 2 yıldaki gerçek performansını ölçer.
"""

import numpy as np
import pandas as pd
from typing import Dict, List
from indicators import analyze_symbol


def backtest_symbol(df: pd.DataFrame, symbol: str,
                    horizons: List[int] = [21, 42, 63],
                    min_signal_score: float = 0.50,
                    warmup: int = 100) -> Dict:
    """
    Tek bir hisse için walk-forward backtest.
    
    df: en az 250 bar günlük OHLCV
    horizons: kaç gün sonra ölçeceğiz (21=1ay, 42=2ay, 63=3ay)
    min_signal_score: bu skorun üstündeki sinyalleri al
    warmup: ilk N barı atla (göstergelerin oturması için)
    """
    if df is None or len(df) < warmup + max(horizons) + 30:
        return {
            "sembol": symbol,
            "hata": f"Yetersiz veri: {len(df) if df is not None else 0} bar",
            "yeterli_veri": False
        }

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    
    signals = []  # her sinyali kaydet
    
    # Walk-forward: her gün için, o güne kadarki veriyle sinyal üret
    end_idx = len(df) - max(horizons) - 1
    
    for i in range(warmup, end_idx, 5):  # her 5 günde bir tara (hız için)
        window = df.iloc[:i+1].copy()
        try:
            result = analyze_symbol(window, symbol)
        except Exception:
            continue
        
        sig = result.get('sinyal', 'NOTR')
        score = result.get('guc', 0.0)
        yön = result.get('yön', 'NOTR')
        
        # Sadece güçlü sinyalleri kaydet
        if sig in ('VERI_YOK', 'VERI_YETERSIZ', 'HATA', 'NOTR'):
            continue
        if score < min_signal_score:
            continue
        
        entry_price = float(df['close'].iloc[i])
        entry_date = str(df.index[i])
        
        # Her horizon için gelecek fiyata bak
        future_returns = {}
        for h in horizons:
            if i + h < len(df):
                future_price = float(df['close'].iloc[i + h])
                ret = (future_price - entry_price) / entry_price * 100
                future_returns[f"{h}g"] = round(ret, 2)
        
        signals.append({
            "tarih": entry_date,
            "sinyal": sig,
            "yön": yön,
            "skor": round(score, 3),
            "giris_fiyat": round(entry_price, 2),
            "getiri": future_returns
        })
    
    if not signals:
        return {
            "sembol": symbol,
            "toplam_sinyal": 0,
            "not": "Backtest periyodunda hiç güçlü sinyal üretilmedi",
            "yeterli_veri": True
        }
    
    # AGREGAT METRİKLER
    metrics = {}
    for h in horizons:
        key = f"{h}g"
        returns = [s['getiri'].get(key) for s in signals if s['getiri'].get(key) is not None]
        if not returns:
            continue
        returns = np.array(returns)
        
        # AL sinyalleri için
        al_returns = np.array([
            s['getiri'].get(key) for s in signals 
            if s['yön'] == 'DIP' and s['getiri'].get(key) is not None
        ])
        # SAT sinyalleri için (negatif yön = doğru)
        sat_returns = np.array([
            -s['getiri'].get(key) for s in signals 
            if s['yön'] == 'TEPE' and s['getiri'].get(key) is not None
        ])
        
        all_directional = np.concatenate([al_returns, sat_returns]) if len(al_returns) + len(sat_returns) > 0 else np.array([])
        
        if len(all_directional) == 0:
            continue
        
        wins_5pct = np.sum(all_directional > 5.0)
        wins_15pct = np.sum(all_directional > 15.0)
        losses_neg5 = np.sum(all_directional < -5.0)
        
        # Max drawdown (kümülatif)
        cumulative = np.cumsum(all_directional)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = cumulative - running_max
        max_dd = float(drawdown.min()) if len(drawdown) > 0 else 0
        
        # Annualized return (basitleştirilmiş)
        avg_return_per_signal = float(all_directional.mean())
        signals_per_year = len(all_directional) * (252 / (end_idx - warmup))
        annual_return = avg_return_per_signal * signals_per_year if signals_per_year > 0 else 0
        
        calmar = abs(annual_return / max_dd) if max_dd < -0.1 else 0
        
        metrics[key] = {
            "toplam_sinyal": int(len(all_directional)),
            "ortalama_getiri": round(float(all_directional.mean()), 2),
            "median_getiri": round(float(np.median(all_directional)), 2),
            "win_rate": round(float(np.sum(all_directional > 0) / len(all_directional) * 100), 1),
            "precision_5pct": round(float(wins_5pct / len(all_directional) * 100), 1),
            "precision_15pct": round(float(wins_15pct / len(all_directional) * 100), 1),
            "loss_rate_neg5": round(float(losses_neg5 / len(all_directional) * 100), 1),
            "best_signal": round(float(all_directional.max()), 2),
            "worst_signal": round(float(all_directional.min()), 2),
            "max_drawdown": round(max_dd, 2),
            "calmar": round(calmar, 2)
        }
    
    # Genel kalite skoru (0-100)
    primary = metrics.get('63g', {})
    quality = 0
    if primary.get('precision_5pct', 0) >= 60:
        quality += 30
    elif primary.get('precision_5pct', 0) >= 50:
        quality += 20
    elif primary.get('precision_5pct', 0) >= 40:
        quality += 10
    
    if primary.get('precision_15pct', 0) >= 30:
        quality += 25
    elif primary.get('precision_15pct', 0) >= 20:
        quality += 15
    
    if primary.get('calmar', 0) >= 1.0:
        quality += 25
    elif primary.get('calmar', 0) >= 0.5:
        quality += 15
    
    if primary.get('toplam_sinyal', 0) >= 10:
        quality += 20
    elif primary.get('toplam_sinyal', 0) >= 5:
        quality += 10
    
    # Güvenilirlik etiketi
    if quality >= 70:
        guvenilirlik = "YUKSEK"
    elif quality >= 50:
        guvenilirlik = "ORTA"
    elif quality >= 30:
        guvenilirlik = "DUSUK"
    else:
        guvenilirlik = "GUVENILMEZ"
    
    return {
        "sembol": symbol,
        "test_periyodu_bar": int(end_idx - warmup),
        "toplam_sinyal": len(signals),
        "metrikler": metrics,
        "kalite_skoru": int(quality),
        "guvenilirlik": guvenilirlik,
        "son_5_sinyal": signals[-5:] if len(signals) >= 5 else signals,
        "yeterli_veri": True
    }
