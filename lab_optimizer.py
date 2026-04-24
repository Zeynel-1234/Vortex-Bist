"""
═══════════════════════════════════════════════════════════════════════
FRAKTAL KAHİN LAB — v2 (KANITLANMIŞ / STABİL / GÜVENLİ)
───────────────────────────────────────────────────────────────────────
Bu versiyon canlı testte 13 hisseden 6'sını OK statüsünde verdi.
Hiçbir yeni özellik eklenmeden, tam olarak çalışan halde geri getirildi.

KADEMELİ ARAMA:
  1. TEKLİ arama   — 125 parametre kombinasyonu
  2. İKİLİ arama   — en iyi 15 teklinin 105 çifti
  3. ÜÇLÜ fallback — ikili yeterli değilse

KALİTE FORMÜLÜ:
  quality = success_rate × 0.35
          + avg_max_gain × 0.35
          + adequacy × 0.15
          - avg_max_drawdown × 0.15

EŞİKLER:
  • MIN_QUALITY_TO_PASS = 50 (OK statüsü için)
  • MIN_SIGNALS_TRAIN = 5
  • MIN_SIGNALS_TEST = 2
  • OVERFIT_THRESHOLD = 0.30 (train'den %30+ düşüş = overfit)

WALK-FORWARD:
  • Train: 0..1400 bar
  • Purge: 1400..1420 (veri sızıntısı önleme)
  • Test:  1420..2000 bar
═══════════════════════════════════════════════════════════════════════
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

TOP_N_SINGLE = 15
OVERFIT_THRESHOLD = 0.30


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
        return {
            'n_signals': 0, 'success_rate': 0.0, 'partial_rate': 0.0,
            'avg_max_gain': 0.0, 'avg_max_drawdown': 0.0,
            'adequacy': 0.0, 'quality': 0.0
        }

    max_gains = []
    max_drawdowns = []
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
        return {
            'n_signals': 0, 'success_rate': 0.0, 'partial_rate': 0.0,
            'avg_max_gain': 0.0, 'avg_max_drawdown': 0.0,
            'adequacy': 0.0, 'quality': 0.0
        }

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


# ═══════════════════════════════════════════════════════════════════════
# TEK İNDİKATÖR TESTİ
# ═══════════════════════════════════════════════════════════════════════
def test_single_indicator(df: pd.DataFrame, name: str, func, params: Dict) -> Dict:
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
    test_end = len(df)

    train_close = close.iloc[:train_end]
    train_signal = signal.iloc[:train_end]
    test_close = close.iloc[test_start:test_end]
    test_signal = signal.iloc[test_start:test_end]

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
        test_perf['n_signals'] >= MIN_SIGNALS_TEST and
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
# KADEMELİ ARAMA
# ═══════════════════════════════════════════════════════════════════════
def search_singles(df: pd.DataFrame) -> List[Dict]:
    results = []
    for name, (func, params) in SIGNAL_REGISTRY.items():
        combos = expand_params(params)
        for combo in combos:
            r = test_single_indicator(df, name, func, combo)
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
                     window: int = 3) -> Dict:
    signals = [m['signal_series'] for m in members]
    combined = combine_signals(signals, window=window)

    close = df['close'].astype(float)
    train_end = TRAIN_BARS
    test_start = TRAIN_BARS + PURGE_BARS
    test_end = len(df)

    train_close = close.iloc[:train_end]
    train_signal = combined.iloc[:train_end]
    test_close = close.iloc[test_start:test_end]
    test_signal = combined.iloc[test_start:test_end]

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
        test_perf['n_signals'] >= MIN_SIGNALS_TEST and
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
                 max_candidates: int = TOP_N_SINGLE) -> List[Dict]:
    top = top_singles[:max_candidates]
    results = []
    for a, b in combinations(top, 2):
        if a['name'] == b['name']:
            continue
        r = test_multi_combo(df, [a, b], level=2)
        if 'error' not in r:
            results.append(r)
    results.sort(key=lambda x: x['combined_quality'], reverse=True)
    return results


def search_triples(df: pd.DataFrame, top_pairs: List[Dict],
                   top_singles: List[Dict]) -> List[Dict]:
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

            r = test_multi_combo(df, triple_members, level=3)
            if 'error' not in r:
                results.append(r)
            if len(tested_keys) >= 50:
                break
        if len(tested_keys) >= 50:
            break

    results.sort(key=lambda x: x['combined_quality'], reverse=True)
    return results


# ═══════════════════════════════════════════════════════════════════════
# ANA DNA ÜRETİMİ
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

    t1 = time.time()
    singles = search_singles(df)
    t_singles = time.time() - t1

    valid_singles = [s for s in singles if s.get('valid')]
    best_single = valid_singles[0] if valid_singles else None

    result = {
        'symbol': symbol, 'mode': 'unknown', 'level': 0,
        'single': None, 'pair': None, 'triple': None,
        'chosen': None, 'quality': None,
        'status': 'FAIL', 'reason': '',
        'timings': {'singles_sec': round(t_singles, 2)},
        'build_time_sec': 0.0,
        'version': 'v2_stable'
    }

    if best_single is not None:
        result['single'] = _strip_signal(best_single)

    t2 = time.time()
    pairs = []
    if valid_singles and len(valid_singles) >= 2:
        pairs = search_pairs(df, valid_singles)
    t_pairs = time.time() - t2
    result['timings']['pairs_sec'] = round(t_pairs, 2)

    valid_pairs = [p for p in pairs if p.get('valid')]
    best_pair = valid_pairs[0] if valid_pairs else None
    if best_pair:
        result['pair'] = best_pair

    best = None
    best_src = None
    best_q = -1
    if best_single and best_single['combined_quality'] > best_q:
        best = best_single
        best_q = best_single['combined_quality']
        best_src = 'single'
    if best_pair and best_pair['combined_quality'] > best_q:
        best = best_pair
        best_q = best_pair['combined_quality']
        best_src = 'pair'

    if best_q < MIN_QUALITY_TO_PASS and valid_singles and valid_pairs:
        t3 = time.time()
        triples = search_triples(df, pairs, valid_singles)
        t_triples = time.time() - t3
        result['timings']['triples_sec'] = round(t_triples, 2)
        valid_triples = [t for t in triples if t.get('valid')]
        if valid_triples:
            best_triple = valid_triples[0]
            result['triple'] = best_triple
            if best_triple['combined_quality'] > best_q:
                best = best_triple
                best_q = best_triple['combined_quality']
                best_src = 'triple'

    if best_src == 'single':
        result['chosen'] = _strip_signal(best)
        result['level'] = 1
        result['mode'] = 'TEKLİ'
    elif best_src == 'pair':
        result['chosen'] = best
        result['level'] = 2
        result['mode'] = 'İKİLİ'
    elif best_src == 'triple':
        result['chosen'] = best
        result['level'] = 3
        result['mode'] = 'ÜÇLÜ'

    result['quality'] = best_q if best_q >= 0 else None

    if best_q >= MIN_QUALITY_TO_PASS:
        result['status'] = 'OK'
        result['reason'] = f'{result["mode"]} · kalite {best_q:.1f}/100'
    elif best is not None:
        result['status'] = 'ZAYIF'
        result['reason'] = f'En iyi kombo kalite eşiğinin altında ({best_q:.1f}<{MIN_QUALITY_TO_PASS})'
    else:
        result['status'] = 'FAIL'
        result['reason'] = 'Geçerli indikatör kombinasyonu bulunamadı'

    result['build_time_sec'] = round(time.time() - t0, 2)
    return result


def _strip_signal(entry: Dict) -> Dict:
    return {k: v for k, v in entry.items() if k != 'signal_series'}
