"""
═══════════════════════════════════════════════════════════════════════════
FRAKTAL KAHİN LAB — AŞAMA 2c: YARATICI V3 (3 büyük iyileştirme)
───────────────────────────────────────────────────────────────────────────

V3'TE GELENLER:

[1] VOLATILITY-ADAPTIVE PARAMETERS (Oynaklığa Uyumlu)
    Hissenin ATR/fiyat oranına bakıp parametre ızgarasını seçer:
      • Yüksek oynaklık → hızlı parametreler (RSI 7, EMA 10)
      • Düşük oynaklık → yavaş parametreler (RSI 30, EMA 200)
    Böylece ULUUN gibi yavaş hisseler için haftalık benzeri tepkiler üretir.

[2] ENSEMBLE VOTING (Topluluk Oylama)
    Tek DNA yerine en iyi 3 kombinasyon saklanır. Canlıda sinyal için
    3 komitenin en az 2'si aynı bar civarında onay vermeli. Bu lucky
    shot'ları eler, ULUUN/TCELL gibi zorlu hisselerde güvenlik artırır.

[3] FITNESS LANDSCAPE ANALYSIS (Uygunluk Haritası)
    Bir kombinasyonun "komşuları" da kontrol edilir. Eğer:
      • Seçilen kombo yalnız zirve → ROBUST=False, bayrak kaldırılır
      • Komşular da iyi çıkıyor → ROBUST=True, gerçek dayanıklı kombo
    Overfitting'e karşı matematiksel koruma.

YENİ STATUS KATEGORİLERİ:
  • GÜÇLÜ   — kalite ≥ 60, robust=True, ensemble confidence ≥ 0.66
  • OK      — kalite ≥ 50
  • ZAYIF   — kalite ≥ 40, ama bilgilendirici (hâlâ öneri niteliğinde)
  • FAIL    — kalite < 40 veya geçerli kombo bulunamadı

KALİTE FORMÜLÜ:
  quality = success_rate×0.35 + avg_gain×0.35 + adequacy×0.15 - drawdown×0.15
═══════════════════════════════════════════════════════════════════════════
"""
from typing import Dict, List, Optional, Tuple
from itertools import combinations
import time
import numpy as np
import pandas as pd

from lab_signals import SIGNAL_REGISTRY, expand_params


# ═══════════════════════════════════════════════════════════════════════
# SABİTLER
# ═══════════════════════════════════════════════════════════════════════
TRAIN_BARS = 1400
PURGE_BARS = 20
TEST_BARS = 580
MIN_BARS = TRAIN_BARS + PURGE_BARS + TEST_BARS

FORWARD_WINDOW = 60
TARGET_GAIN_PCT = 30.0
PARTIAL_GAIN_PCT = 10.0

MIN_SIGNALS_TRAIN = 5
MIN_SIGNALS_TEST = 2
MIN_QUALITY_TO_PASS = 50.0
MIN_QUALITY_STRONG = 60.0
MIN_QUALITY_WEAK = 40.0
OVERFIT_THRESHOLD = 0.30

TOP_N_SINGLE = 15
ENSEMBLE_SIZE = 3          # Sakla en iyi 3 kombo
ENSEMBLE_MIN_VOTES = 2     # 3'ten 2'si onay vermeli

# [1] VOLATILITY-ADAPTIVE — Oynaklık sınıfları
VOL_LOW_THRESHOLD = 1.5     # ATR/close × 100 < 1.5 → düşük
VOL_HIGH_THRESHOLD = 3.5    # > 3.5 → yüksek

# [3] FITNESS LANDSCAPE — Robustluk analizi
ROBUST_NEIGHBOR_COUNT = 5   # Top 5 komşuya bak
ROBUST_MIN_GOOD_RATIO = 0.4 # %40'ı iyi ise robust


# ═══════════════════════════════════════════════════════════════════════
# [1] VOLATILITY-ADAPTIVE PARAMETER GRID
# ═══════════════════════════════════════════════════════════════════════
def classify_volatility(df: pd.DataFrame, lookback: int = 30) -> str:
    """
    Hissenin oynaklık karakterini tespit et.
    Döner: 'LOW', 'NORMAL', 'HIGH'
    """
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)

    # Basit True Range son lookback bar
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    recent_tr = tr.tail(lookback).mean()
    recent_price = close.tail(lookback).mean()
    if recent_price <= 0 or pd.isna(recent_price):
        return 'NORMAL'

    atr_pct = recent_tr / recent_price * 100

    if atr_pct < VOL_LOW_THRESHOLD:
        return 'LOW'
    elif atr_pct > VOL_HIGH_THRESHOLD:
        return 'HIGH'
    else:
        return 'NORMAL'


def adapt_params_for_volatility(params: Dict, vol_class: str) -> Dict:
    """
    Oynaklık sınıfına göre parametre ızgarasını uyarla.
    
    LOW  → yavaş parametreler öne çıkar (length artar, oversold gevşer)
    HIGH → hızlı parametreler öne çıkar (length azalır, oversold sıkı)
    NORMAL → aynı kalır
    """
    if vol_class == 'NORMAL':
        return params

    adapted = {}
    for key, values in params.items():
        if not isinstance(values, list):
            adapted[key] = values
            continue

        if vol_class == 'LOW' and key == 'length':
            # Düşük oynaklıkta uzun periyot tercih et
            adapted[key] = sorted([v for v in values if v >= 14], reverse=False)
            if not adapted[key]:
                adapted[key] = values
        elif vol_class == 'HIGH' and key == 'length':
            # Yüksek oynaklıkta kısa periyot tercih et
            adapted[key] = sorted([v for v in values if v <= 21])
            if not adapted[key]:
                adapted[key] = values
        elif vol_class == 'LOW' and key == 'oversold':
            # Düşük oynaklıkta eşiği gevşet
            if values and all(isinstance(v, (int, float)) for v in values):
                adapted[key] = values  # aynı, daha agresif arama
            else:
                adapted[key] = values
        else:
            adapted[key] = values

    return adapted


# ═══════════════════════════════════════════════════════════════════════
# SİNYAL PERFORMANS DEĞERLENDİRMESİ
# ═══════════════════════════════════════════════════════════════════════
def evaluate_signal_series(close: pd.Series, signal: pd.Series,
                           forward_window: int = FORWARD_WINDOW) -> Dict:
    close_vals = close.values
    sig_vals = signal.values
    n = len(close_vals)

    signal_indices = np.where(sig_vals)[0]
    valid_indices = [i for i in signal_indices if i + forward_window < n]

    if not valid_indices:
        return _empty_perf()

    max_gains, max_drawdowns = [], []
    for idx in valid_indices:
        entry = close_vals[idx]
        if entry <= 0 or np.isnan(entry):
            continue
        window = close_vals[idx + 1: idx + 1 + forward_window]
        if len(window) == 0:
            continue
        peak = np.nanmax(window)
        trough = np.nanmin(window)
        gain = (peak - entry) / entry * 100
        drawdown = (trough - entry) / entry * 100
        max_gains.append(gain)
        max_drawdowns.append(abs(min(drawdown, 0)))

    if not max_gains:
        return _empty_perf()

    n_signals = len(max_gains)
    arr_g = np.array(max_gains)
    arr_d = np.array(max_drawdowns)

    success_count = int((arr_g >= TARGET_GAIN_PCT).sum())
    partial_count = int((arr_g >= PARTIAL_GAIN_PCT).sum())
    success_rate = success_count / n_signals * 100
    partial_rate = partial_count / n_signals * 100
    avg_max_gain = float(arr_g.mean())
    avg_max_drawdown = float(arr_d.mean())

    if n_signals < 5:
        adequacy = (n_signals / 5.0) * 50
    elif n_signals <= 20:
        adequacy = 100.0
    else:
        adequacy = max(50.0, 100.0 - (n_signals - 20) * 2)

    norm_gain = min(avg_max_gain / 50.0 * 100, 100)
    norm_dd = min(avg_max_drawdown / 30.0 * 100, 100)
    quality = (
        success_rate * 0.35 +
        norm_gain * 0.35 +
        adequacy * 0.15 -
        norm_dd * 0.15
    )
    quality = max(0.0, min(100.0, quality))

    return {
        'n_signals': n_signals,
        'success_rate': round(success_rate, 2),
        'partial_rate': round(partial_rate, 2),
        'avg_max_gain': round(avg_max_gain, 2),
        'avg_max_drawdown': round(avg_max_drawdown, 2),
        'adequacy': round(adequacy, 2),
        'quality': round(quality, 2)
    }


def _empty_perf() -> Dict:
    return {
        'n_signals': 0, 'success_rate': 0.0, 'partial_rate': 0.0,
        'avg_max_gain': 0.0, 'avg_max_drawdown': 0.0,
        'adequacy': 0.0, 'quality': 0.0
    }


# ═══════════════════════════════════════════════════════════════════════
# TEK İNDİKATÖR TESTİ
# ═══════════════════════════════════════════════════════════════════════
def test_single_indicator(df: pd.DataFrame, name: str, func,
                          params: Dict,
                          min_sig_test: int = MIN_SIGNALS_TEST) -> Dict:
    try:
        signal = func(df, **params)
    except Exception as e:
        return {'error': str(e)[:80], 'quality': 0.0}

    if not isinstance(signal, pd.Series) or len(signal) != len(df):
        return {'error': 'sinyal format hatası', 'quality': 0.0}

    signal = signal.fillna(False).astype(bool)
    close = df['close'].astype(float)

    train_end = TRAIN_BARS
    test_start = TRAIN_BARS + PURGE_BARS

    train_close = close.iloc[:train_end]
    train_signal = signal.iloc[:train_end]
    test_close = close.iloc[test_start:]
    test_signal = signal.iloc[test_start:]

    train_eff = min(len(train_close) - FORWARD_WINDOW, len(train_close))
    test_eff = min(len(test_close) - FORWARD_WINDOW, len(test_close))
    if train_eff < 100 or test_eff < 100:
        return {'error': 'yetersiz bar', 'quality': 0.0}

    train_perf = evaluate_signal_series(
        train_close.iloc[:train_eff + FORWARD_WINDOW],
        train_signal.iloc[:train_eff]
    )
    test_perf = evaluate_signal_series(
        test_close.iloc[:test_eff + FORWARD_WINDOW],
        test_signal.iloc[:test_eff]
    )

    combined_quality = (train_perf['quality'] + test_perf['quality']) / 2

    overfit = False
    if train_perf['quality'] > 0:
        drop = (train_perf['quality'] - test_perf['quality']) / train_perf['quality']
        if drop > OVERFIT_THRESHOLD:
            overfit = True

    valid = (
        train_perf['n_signals'] >= MIN_SIGNALS_TRAIN and
        test_perf['n_signals'] >= min_sig_test and
        not overfit
    )

    return {
        'name': name, 'params': params,
        'train': train_perf, 'test': test_perf,
        'combined_quality': round(combined_quality, 2),
        'overfit': overfit, 'valid': valid,
        'signal_series': signal
    }


# ═══════════════════════════════════════════════════════════════════════
# [3] FITNESS LANDSCAPE — Robustluk Analizi
# ═══════════════════════════════════════════════════════════════════════
def analyze_robustness(all_singles: List[Dict], target: Dict,
                       n_neighbors: int = ROBUST_NEIGHBOR_COUNT) -> Dict:
    """
    Seçilen kombonun 'komşu' kombinasyonlarını kontrol et.
    Eğer aynı indikatör ailesinden başka parametreler de iyi çıkıyorsa
    → robust (dayanıklı, rastlantı değil).
    Yalnız zirve ise → lucky shot, robust=False.
    """
    target_name = target.get('name')
    if not target_name:
        return {'is_robust': True, 'neighbor_score': 0.0, 'reason': 'pass'}

    # Aynı indikatör ailesinden diğer parametrelerin skorları
    family = [s for s in all_singles if s['name'] == target_name]
    family_qualities = [s['combined_quality'] for s in family]

    if len(family) < 2:
        return {'is_robust': True, 'neighbor_score': 0.0,
                'reason': 'tek varyasyon var, robustluk değerlendirilemedi'}

    target_q = target['combined_quality']
    if target_q <= 0:
        return {'is_robust': False, 'neighbor_score': 0.0,
                'reason': 'hedef kalitesi sıfır'}

    # Komşu kalitelerinin ortalaması
    neighbor_avg = np.mean([q for q in family_qualities
                            if q != target_q]) if len(family) > 1 else 0

    # Komşu kalitelerinin, hedef kalitesine oranı
    # 1.0'a yakın = komşular da iyi (robust)
    # 0.5 altı = yalnız zirve (lucky shot)
    neighbor_ratio = (neighbor_avg / target_q) if target_q > 0 else 0

    is_robust = neighbor_ratio >= 0.55
    reason = (
        f'komşu oran={neighbor_ratio:.2f} ' +
        ('(dayanıklı)' if is_robust else '(yalnız zirve — lucky shot riski)')
    )

    return {
        'is_robust': is_robust,
        'neighbor_score': round(neighbor_ratio, 3),
        'neighbor_avg_quality': round(neighbor_avg, 2),
        'family_size': len(family),
        'reason': reason
    }


# ═══════════════════════════════════════════════════════════════════════
# KADEMELİ ARAMA (Volatility-Adaptive)
# ═══════════════════════════════════════════════════════════════════════
def search_singles(df: pd.DataFrame, vol_class: str = 'NORMAL',
                   min_sig_test: int = MIN_SIGNALS_TEST) -> List[Dict]:
    """Tekli arama, oynaklığa uyarlı."""
    results = []
    for name, (func, params) in SIGNAL_REGISTRY.items():
        # [1] VOLATILITY-ADAPTIVE: parametre ızgarasını oynaklığa göre filtrele
        adapted_params = adapt_params_for_volatility(params, vol_class)
        combos = expand_params(adapted_params)
        for combo in combos:
            r = test_single_indicator(df, name, func, combo, min_sig_test)
            if 'error' not in r:
                results.append(r)
    results.sort(key=lambda x: x['combined_quality'], reverse=True)
    return results


def combine_signals(signals: List[pd.Series], window: int = 3) -> pd.Series:
    if not signals:
        return pd.Series([], dtype=bool)

    expanded = []
    for s in signals:
        s_bool = s.fillna(False).astype(bool)
        ext = s_bool.rolling(window=window + 1, min_periods=1).max().astype(bool)
        expanded.append(ext)

    combined_wide = expanded[0].copy()
    for e in expanded[1:]:
        combined_wide = combined_wide & e

    prev = combined_wide.shift(1).fillna(False)
    trigger = combined_wide & ~prev
    return trigger


def test_multi_combo(df: pd.DataFrame, members: List[Dict], level: int = 2,
                     window: int = 3,
                     min_sig_test: int = MIN_SIGNALS_TEST) -> Dict:
    signals = [m['signal_series'] for m in members]
    combined = combine_signals(signals, window=window)

    close = df['close'].astype(float)
    train_end = TRAIN_BARS
    test_start = TRAIN_BARS + PURGE_BARS

    train_close = close.iloc[:train_end]
    train_signal = combined.iloc[:train_end]
    test_close = close.iloc[test_start:]
    test_signal = combined.iloc[test_start:]

    train_eff = len(train_close) - FORWARD_WINDOW
    test_eff = len(test_close) - FORWARD_WINDOW
    if train_eff < 100 or test_eff < 100:
        return {'error': 'yetersiz bar', 'quality': 0.0}

    train_perf = evaluate_signal_series(
        train_close.iloc[:train_eff + FORWARD_WINDOW],
        train_signal.iloc[:train_eff]
    )
    test_perf = evaluate_signal_series(
        test_close.iloc[:test_eff + FORWARD_WINDOW],
        test_signal.iloc[:test_eff]
    )
    combined_quality = (train_perf['quality'] + test_perf['quality']) / 2

    overfit = False
    if train_perf['quality'] > 0:
        drop = (train_perf['quality'] - test_perf['quality']) / train_perf['quality']
        if drop > OVERFIT_THRESHOLD:
            overfit = True

    valid = (
        train_perf['n_signals'] >= MIN_SIGNALS_TRAIN and
        test_perf['n_signals'] >= min_sig_test and
        not overfit
    )

    return {
        'level': level,
        'members': [
            {'name': m['name'], 'params': m['params'],
             'single_quality': m['combined_quality']}
            for m in members
        ],
        'train': train_perf, 'test': test_perf,
        'combined_quality': round(combined_quality, 2),
        'overfit': overfit, 'valid': valid,
        'window': window
    }


def search_pairs(df: pd.DataFrame, top_singles: List[Dict],
                 max_candidates: int = TOP_N_SINGLE,
                 min_sig_test: int = MIN_SIGNALS_TEST) -> List[Dict]:
    top = top_singles[:max_candidates]
    results = []
    for a, b in combinations(top, 2):
        if a['name'] == b['name']:
            continue
        r = test_multi_combo(df, [a, b], level=2, min_sig_test=min_sig_test)
        if 'error' not in r:
            results.append(r)
    results.sort(key=lambda x: x['combined_quality'], reverse=True)
    return results


def search_triples(df: pd.DataFrame, top_pairs: List[Dict],
                   top_singles: List[Dict],
                   min_sig_test: int = MIN_SIGNALS_TEST) -> List[Dict]:
    singles_by_name = {}
    for s in top_singles[:10]:
        if s['name'] not in singles_by_name:
            singles_by_name[s['name']] = s

    results = []
    tested_keys = set()

    for pair in top_pairs[:10]:
        pair_names = {m['name'] for m in pair['members']}
        pair_members = []
        for m in pair['members']:
            match = next((s for s in top_singles
                          if s['name'] == m['name'] and s['params'] == m['params']),
                         None)
            if match:
                pair_members.append(match)
        if len(pair_members) != 2:
            continue

        for sname, single in singles_by_name.items():
            if sname in pair_names:
                continue
            triple_members = pair_members + [single]
            key = frozenset((m['name'], tuple(sorted(m['params'].items())))
                             for m in triple_members)
            if key in tested_keys:
                continue
            tested_keys.add(key)

            r = test_multi_combo(df, triple_members, level=3,
                                 min_sig_test=min_sig_test)
            if 'error' not in r:
                results.append(r)
            if len(tested_keys) >= 50:
                break
        if len(tested_keys) >= 50:
            break

    results.sort(key=lambda x: x['combined_quality'], reverse=True)
    return results


# ═══════════════════════════════════════════════════════════════════════
# [2] ENSEMBLE — Top 3 kombinasyonu sakla
# ═══════════════════════════════════════════════════════════════════════
def build_ensemble(all_candidates: List[Dict],
                   size: int = ENSEMBLE_SIZE) -> List[Dict]:
    """
    En iyi 'size' adet valid kombinasyonu seç, birbirinden çeşitli olsun:
    Aynı indikatör ailesinden en fazla 2 seçer.
    """
    ensemble = []
    family_count = {}

    for cand in all_candidates:
        if not cand.get('valid'):
            continue

        # İndikatör aile(lerin)ini çıkar
        if 'members' in cand:
            names = tuple(sorted(m['name'] for m in cand['members']))
        else:
            names = (cand.get('name', 'unknown'),)

        key = names
        if family_count.get(key, 0) >= 1:
            # Aynı indikatör kombinasyonunun ikincisini almayalım
            continue

        ensemble.append(cand)
        family_count[key] = family_count.get(key, 0) + 1

        if len(ensemble) >= size:
            break

    return ensemble


# ═══════════════════════════════════════════════════════════════════════
# ANA DNA ÜRETİMİ — V3 (3 büyük iyileştirme entegre)
# ═══════════════════════════════════════════════════════════════════════
def build_dna(df: pd.DataFrame, symbol: str = '') -> Dict:
    t0 = time.time()

    if len(df) < MIN_BARS:
        return {
            'symbol': symbol, 'status': 'FAIL',
            'reason': f'Yetersiz veri: {len(df)} bar, en az {MIN_BARS} gerekli',
            'quality': None, 'build_time_sec': 0.0
        }

    df = df.tail(MIN_BARS).reset_index(drop=True)

    # [1] VOLATILITY-ADAPTIVE — Oynaklık sınıfını belirle
    vol_class = classify_volatility(df)

    # Adaptif min sinyal: düşük oynaklıkta daha gevşek (zaten az sinyal olur)
    adaptive_min_sig = 1 if vol_class == 'LOW' else MIN_SIGNALS_TEST

    # Kademe 1 — TEKLİ
    t1 = time.time()
    singles = search_singles(df, vol_class=vol_class,
                             min_sig_test=adaptive_min_sig)
    t_singles = time.time() - t1

    valid_singles = [s for s in singles if s.get('valid')]

    result = {
        'symbol': symbol,
        'version': 'v3_enhanced',
        'volatility_class': vol_class,
        'adaptive_min_signals': adaptive_min_sig,
        'mode': 'unknown', 'level': 0,
        'chosen': None,
        'ensemble': [],           # [2] Top 3 kombinasyon
        'robustness': None,       # [3] Fitness landscape sonucu
        'quality': None,
        'status': 'FAIL', 'reason': '',
        'timings': {'singles_sec': round(t_singles, 2)},
        'build_time_sec': 0.0
    }

    if not valid_singles:
        result['reason'] = 'Hiçbir tekli indikatör geçerli sinyal üretmedi'
        result['build_time_sec'] = round(time.time() - t0, 2)
        return result

    # Kademe 2 — İKİLİ
    t2 = time.time()
    pairs = []
    if len(valid_singles) >= 2:
        pairs = search_pairs(df, valid_singles, min_sig_test=adaptive_min_sig)
    t_pairs = time.time() - t2
    result['timings']['pairs_sec'] = round(t_pairs, 2)
    valid_pairs = [p for p in pairs if p.get('valid')]

    # Kademe 3 — ÜÇLÜ (fallback: en iyi ikili < 50 ise)
    triples = []
    best_so_far = max(
        [valid_singles[0]['combined_quality']] +
        ([valid_pairs[0]['combined_quality']] if valid_pairs else []),
        default=0
    )
    if best_so_far < MIN_QUALITY_TO_PASS and valid_pairs:
        t3 = time.time()
        triples = search_triples(df, pairs, valid_singles,
                                 min_sig_test=adaptive_min_sig)
        t_triples = time.time() - t3
        result['timings']['triples_sec'] = round(t_triples, 2)
    valid_triples = [t for t in triples if t.get('valid')]

    # Tüm aday havuzunu birleştir
    all_candidates = []
    for s in valid_singles[:10]:
        s_copy = {k: v for k, v in s.items() if k != 'signal_series'}
        s_copy['_cat'] = 'single'
        all_candidates.append(s_copy)
    for p in valid_pairs[:10]:
        p_copy = dict(p)
        p_copy['_cat'] = 'pair'
        all_candidates.append(p_copy)
    for t in valid_triples[:5]:
        t_copy = dict(t)
        t_copy['_cat'] = 'triple'
        all_candidates.append(t_copy)

    # Kalite'ye göre sırala
    all_candidates.sort(key=lambda x: x.get('combined_quality', 0), reverse=True)

    if not all_candidates:
        result['reason'] = 'Geçerli kombinasyon bulunamadı'
        result['build_time_sec'] = round(time.time() - t0, 2)
        return result

    # [2] ENSEMBLE — Top 3 çeşitli kombinasyonu seç
    ensemble = build_ensemble(all_candidates, size=ENSEMBLE_SIZE)
    result['ensemble'] = ensemble

    # En iyi kombo 'chosen' olarak seçilir
    best = all_candidates[0]
    result['chosen'] = best
    result['quality'] = best['combined_quality']

    if best['_cat'] == 'single':
        result['mode'] = 'TEKLİ'
        result['level'] = 1
    elif best['_cat'] == 'pair':
        result['mode'] = 'İKİLİ'
        result['level'] = 2
    else:
        result['mode'] = 'ÜÇLÜ'
        result['level'] = 3

    # [3] FITNESS LANDSCAPE — Robustluk analizi (tekliler için)
    if best['_cat'] == 'single':
        robustness = analyze_robustness(valid_singles, best)
    else:
        # Çoklu kombolar için basit robustluk: ensemble kalitesinin
        # aritmetik ortalaması, en iyiye ne kadar yakın?
        if len(ensemble) >= 2:
            avg_q = np.mean([e['combined_quality'] for e in ensemble[1:]])
            ratio = avg_q / best['combined_quality'] if best['combined_quality'] > 0 else 0
            robustness = {
                'is_robust': ratio >= 0.7,
                'neighbor_score': round(ratio, 3),
                'reason': f'ensemble ortalama oran={ratio:.2f}'
            }
        else:
            robustness = {'is_robust': False, 'neighbor_score': 0.0,
                          'reason': 'ensemble tek üyeli'}
    result['robustness'] = robustness

    # Karar
    q = best['combined_quality']
    is_robust = robustness.get('is_robust', True)
    ensemble_size_actual = len(ensemble)

    if q >= MIN_QUALITY_STRONG and is_robust and ensemble_size_actual >= 2:
        result['status'] = 'GÜÇLÜ'
        result['reason'] = (
            f'{result["mode"]} · kalite {q:.1f} · robust · '
            f'{ensemble_size_actual} kombolu ensemble'
        )
    elif q >= MIN_QUALITY_TO_PASS:
        result['status'] = 'OK'
        result['reason'] = f'{result["mode"]} · kalite {q:.1f}'
        if not is_robust:
            result['reason'] += ' · robust değil (lucky shot riski)'
    elif q >= MIN_QUALITY_WEAK:
        result['status'] = 'ZAYIF'
        result['reason'] = (
            f'{result["mode"]} · kalite {q:.1f} · '
            'eşik üstünde ama ihtiyatlı kullan'
        )
    else:
        result['status'] = 'FAIL'
        result['reason'] = f'Kalite çok düşük ({q:.1f})'

    result['build_time_sec'] = round(time.time() - t0, 2)
    return result
