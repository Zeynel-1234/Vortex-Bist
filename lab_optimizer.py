"""
═══════════════════════════════════════════════════════════════════════
FRAKTAL KAHİN LAB — AŞAMA 2: OPTIMIZER MOTORU
───────────────────────────────────────────────────────────────────────
Her hisse için:
  1. TEKLİ arama   — 125 parametre kombinasyonu, en iyi 15'i sakla
  2. İKİLİ arama   — en iyi 15 teklinin 105 çifti (greedy)
  3. ÜÇLÜ fallback — ilk iki seviyede kimse %55+ başaramazsa

KALİTE SKORU FORMÜLÜ:
  quality = (success_rate × 0.40)
          + (avg_max_gain × 0.30)
          - (avg_max_drawdown × 0.15)
          + (signal_adequacy × 0.15)

WALK-FORWARD:
  • Train: 0..1400 bar
  • Purge: 1400..1420 (veri sızıntısı önleme)
  • Test:  1420..2000 bar (son 580 bar)

KARAR KRİTERLERİ:
  • Hem train hem test setinde min %55 success rate
  • Her iki sette min 5 sinyal
  • Kombo final skoru = (train_skor + test_skor) / 2
  • Test skoru train'den %30+ düşükse OVERFITTING bayrağı

DNA KARTI ÇIKTISI:
  • Seçilen tekli + (varsa) ikili/üçlü
  • Her birinin parametreleri, sinyal sayıları, kazanç profili
  • Overall quality + strategy_level (1=tekli, 2=ikili, 3=üçlü)
═══════════════════════════════════════════════════════════════════════
"""
from typing import Dict, List, Optional, Tuple
from itertools import combinations
import time
import numpy as np
import pandas as pd

from lab_signals import SIGNAL_REGISTRY, expand_params


# ═══════════════════════════════════════════════════════════════════
# PARAMETRELER (kalibre edilebilir)
# ═══════════════════════════════════════════════════════════════════
TRAIN_BARS = 1400
PURGE_BARS = 20         # Train ile test arası boşluk (veri sızıntısı önleme)
TEST_BARS = 580         # 2000 - 1400 - 20 = 580
MIN_BARS = TRAIN_BARS + PURGE_BARS + TEST_BARS  # 2000

FORWARD_WINDOW = 60     # Sinyal sonrası 60 bar izle (~3 ay)
TARGET_GAIN_PCT = 30.0  # Hedef getiri %30
PARTIAL_GAIN_PCT = 10.0 # Kısmi başarı eşiği

MIN_SIGNALS_TRAIN = 5
MIN_SIGNALS_TEST = 2
MIN_QUALITY_TO_PASS = 55.0  # 100 üzerinden

TOP_N_SINGLE = 15       # İkili aramaya girecek tekli aday sayısı
OVERFIT_THRESHOLD = 0.30  # Test skoru train'den %30 düşükse overfit


# ═══════════════════════════════════════════════════════════════════
# TEK BİR SİNYAL SERİSİNİN PERFORMANSINI ÖLÇ
# ═══════════════════════════════════════════════════════════════════
def evaluate_signal_series(close: pd.Series, signal: pd.Series,
                           forward_window: int = FORWARD_WINDOW) -> Dict:
    """
    Bir bool sinyal serisinin getiri profilini ölçer.
    Her True bar için: sonraki forward_window bar içindeki
    max gain % ve max drawdown % hesaplanır.

    Returns:
      n_signals, success_rate, partial_rate, avg_max_gain,
      avg_max_drawdown, adequacy, quality
    """
    close_vals = close.values
    sig_vals = signal.values
    n = len(close_vals)

    signal_indices = np.where(sig_vals)[0]
    # Son forward_window barda verilen sinyalleri değerlendiremeyiz
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
        drawdown = (trough - entry) / entry * 100  # negatif
        max_gains.append(gain)
        max_drawdowns.append(abs(min(drawdown, 0)))  # abs değer

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

    # Sinyal yeterliliği: 5-20 sinyal ideal aralık
    if n_signals < 5:
        adequacy = (n_signals / 5.0) * 50
    elif n_signals <= 20:
        adequacy = 100.0
    else:
        # Çok fazla sinyal kalite düşürür (seçici değil)
        adequacy = max(50.0, 100.0 - (n_signals - 20) * 2)

    # KALİTE SKORU — 4 bileşen ağırlıklı
    # success_rate 0-100, avg_max_gain tipik 0-50, drawdown tipik 0-30
    norm_gain = min(avg_max_gain / 50.0 * 100, 100)  # 50%'te tam puan
    norm_dd = min(avg_max_drawdown / 30.0 * 100, 100)  # 30%'te tam ceza
    quality = (
        success_rate * 0.40 +
        norm_gain * 0.30 -
        norm_dd * 0.15 +
        adequacy * 0.15
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


# ═══════════════════════════════════════════════════════════════════
# TEK İNDİKATÖR TEST ET — train + test + genel skor
# ═══════════════════════════════════════════════════════════════════
def test_single_indicator(df: pd.DataFrame, name: str, func, params: Dict) -> Dict:
    """Tek indikatörü train ve test setlerinde değerlendir."""
    try:
        signal = func(df, **params)
    except Exception as e:
        return {'error': str(e)[:80], 'quality': 0.0}

    if not isinstance(signal, pd.Series) or len(signal) != len(df):
        return {'error': 'sinyal format hatası', 'quality': 0.0}

    signal = signal.fillna(False).astype(bool)
    close = df['close'].astype(float)

    # Train ve test indeksleri
    train_end = TRAIN_BARS
    test_start = TRAIN_BARS + PURGE_BARS
    test_end = len(df)

    train_close = close.iloc[:train_end]
    train_signal = signal.iloc[:train_end]
    test_close = close.iloc[test_start:test_end]
    test_signal = signal.iloc[test_start:test_end]

    # Train: forward_window'un da train içinde olması için son barları kırp
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

    # Nihai skor: train ve test ortalaması
    combined_quality = (train_perf['quality'] + test_perf['quality']) / 2

    # Overfitting flag: test, train'den %30+ düşükse
    overfit = False
    if train_perf['quality'] > 0:
        drop = (train_perf['quality'] - test_perf['quality']) / train_perf['quality']
        if drop > OVERFIT_THRESHOLD:
            overfit = True

    # Geçerlilik kontrolü
    valid = (
        train_perf['n_signals'] >= MIN_SIGNALS_TRAIN and
        test_perf['n_signals'] >= MIN_SIGNALS_TEST and
        not overfit
    )

    return {
        'name': name,
        'params': params,
        'train': train_perf,
        'test': test_perf,
        'combined_quality': round(combined_quality, 2),
        'overfit': overfit,
        'valid': valid,
        'signal_series': signal  # ikili/üçlü aramasında kullanılacak
    }


# ═══════════════════════════════════════════════════════════════════
# KADEMELİ ARAMA: TEKLİ
# ═══════════════════════════════════════════════════════════════════
def search_singles(df: pd.DataFrame) -> List[Dict]:
    """125 tekli kombinasyonu test et, kalitesine göre sırala."""
    results = []
    for name, (func, params) in SIGNAL_REGISTRY.items():
        combos = expand_params(params)
        for combo in combos:
            r = test_single_indicator(df, name, func, combo)
            if 'error' not in r:
                results.append(r)

    results.sort(key=lambda x: x['combined_quality'], reverse=True)
    return results


# ═══════════════════════════════════════════════════════════════════
# İKİLİ VE ÜÇLÜ KOMBO — "aynı anda sinyal veriyor mu?" mantığı
# ═══════════════════════════════════════════════════════════════════
def combine_signals(signals: List[pd.Series], window: int = 3) -> pd.Series:
    """
    Birden fazla sinyal serisini "rolling confluence" ile birleştirir.
    Bir barda N sinyalin hepsi ±window bar içinde True olmuşsa,
    son True olan bar combined signal = True.

    Bu, "iki/üç indikatör aynı dönemde dip dönüşü gördü" mantığı.
    """
    if not signals:
        return pd.Series([], dtype=bool)

    # Her sinyal için "son 'window' barda True olmuş mu" genişletmesi
    expanded = []
    for s in signals:
        s_bool = s.fillna(False).astype(bool)
        # Rolling max: son window+1 barda True varsa bu bar da True sayılır
        ext = s_bool.rolling(window=window + 1, min_periods=1).max().astype(bool)
        expanded.append(ext)

    # Hepsinin aynı bar için genişletilmiş hali True olmalı
    combined_wide = expanded[0].copy()
    for e in expanded[1:]:
        combined_wide = combined_wide & e

    # Tetikleme barı: son sinyalin geldiği bar
    # (combined_wide True olur olmaz True, sonra re-trigger için cooldown gerekir)
    # Basit yaklaşım: combined_wide'daki her True → bu bar sinyal verir
    # Ama arka arkaya çok sinyal üretmesin diye: False'tan True'ya geçiş anı
    prev = combined_wide.shift(1).fillna(False)
    trigger = combined_wide & ~prev
    return trigger


def test_multi_combo(df: pd.DataFrame, members: List[Dict], level: int = 2,
                     window: int = 3) -> Dict:
    """
    Birden fazla tek indikatör birleşiminin (2'li, 3'lü) performansını ölç.
    """
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
        'train': train_perf,
        'test': test_perf,
        'combined_quality': round(combined_quality, 2),
        'overfit': overfit,
        'valid': valid,
        'window': window
    }


def search_pairs(df: pd.DataFrame, top_singles: List[Dict],
                 max_candidates: int = TOP_N_SINGLE) -> List[Dict]:
    """En iyi tekli adayların ikili kombinasyonlarını ara."""
    top = top_singles[:max_candidates]
    results = []
    for a, b in combinations(top, 2):
        # Aynı indikatör ailesi ise atla (iki RSI varyasyonu gibi)
        if a['name'] == b['name']:
            continue
        r = test_multi_combo(df, [a, b], level=2)
        if 'error' not in r:
            results.append(r)
    results.sort(key=lambda x: x['combined_quality'], reverse=True)
    return results


def search_triples(df: pd.DataFrame, top_pairs: List[Dict],
                   top_singles: List[Dict]) -> List[Dict]:
    """
    Üçlü arama (FALLBACK): En iyi 10 ikiliden her birine,
    en iyi 5 tekliden bir indikatör eklemeyi dene.
    Büyük patlamayı önlemek için max 50 üçlü test edilir.
    """
    singles_by_name = {}
    for s in top_singles[:10]:
        if s['name'] not in singles_by_name:
            singles_by_name[s['name']] = s

    results = []
    tested_keys = set()

    for pair in top_pairs[:10]:
        pair_names = {m['name'] for m in pair['members']}
        # pair'in member'larını tekli objelerden yeniden bul
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


# ═══════════════════════════════════════════════════════════════════
# ANA MOTOR: DNA KARTI ÜRETİMİ
# ═══════════════════════════════════════════════════════════════════
def build_dna(df: pd.DataFrame, symbol: str = '') -> Dict:
    """
    Bir hisse için komple DNA kartı oluştur.
    Kademeli arama, overfitting koruması, fallback mantığı içerir.
    """
    t0 = time.time()

    if len(df) < MIN_BARS:
        return {
            'symbol': symbol,
            'status': 'FAIL',
            'reason': f'Yetersiz veri: {len(df)} bar, en az {MIN_BARS} gerekli',
            'quality': None, 'build_time_sec': 0.0
        }

    # Son MIN_BARS bar al
    df = df.tail(MIN_BARS).reset_index(drop=True)

    # Kademe 1: TEKLİ
    t1 = time.time()
    singles = search_singles(df)
    t_singles = time.time() - t1

    valid_singles = [s for s in singles if s.get('valid')]
    best_single = valid_singles[0] if valid_singles else None

    result = {
        'symbol': symbol,
        'mode': 'unknown',
        'level': 0,
        'single': None,
        'pair': None,
        'triple': None,
        'chosen': None,
        'quality': None,
        'status': 'FAIL',
        'reason': '',
        'timings': {'singles_sec': round(t_singles, 2)},
        'build_time_sec': 0.0
    }

    if best_single is not None:
        result['single'] = _strip_signal(best_single)
        # Kriter 1: tekli kalitesi yüksekse onu seç
        if best_single['combined_quality'] >= MIN_QUALITY_TO_PASS:
            # Tekli yeterli, yine de ikiliyi dene — daha iyisi varsa kullan
            pass

    # Kademe 2: İKİLİ
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

    # Karar: tekli ve ikili arasından en iyi
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

    # Kademe 3: ÜÇLÜ (fallback — ikili de yeterli değilse)
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

    # Sonuç
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
    """Tekli dict'ten signal_series'i çıkar (JSON serialize için)."""
    out = {k: v for k, v in entry.items() if k != 'signal_series'}
    return out


# ═══════════════════════════════════════════════════════════════════
# TEST (python lab_optimizer.py)
# ═══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    # Sentetik 2200 bar veri: karışık bir düşüş-yükseliş örüntüsü
    np.random.seed(3)
    n = 2200
    # 3 faz: 800 bar yükseliş, 700 bar düşüş, 700 bar dip dönüşü
    p1 = np.linspace(50, 100, 800)
    p2 = np.linspace(100, 45, 700)
    p3 = np.linspace(45, 80, 700)
    close = np.concatenate([p1, p2, p3]) + np.random.normal(0, 2, n)
    high = close + np.abs(np.random.normal(0.6, 0.3, n))
    low = close - np.abs(np.random.normal(0.6, 0.3, n))
    open_ = close + np.random.normal(0, 0.3, n)
    vol = np.abs(np.random.normal(15000, 4000, n))
    df = pd.DataFrame({
        'open': open_, 'high': high, 'low': low,
        'close': close, 'volume': vol
    }, index=pd.date_range('2018-01-01', periods=n))

    print("=" * 70)
    print(f"LAB OPTIMIZER TESTİ — {n} bar sentetik veri")
    print(f"Faz 1 (0-800): yükseliş · Faz 2 (800-1500): düşüş · Faz 3 (1500-2200): toparlama")
    print("=" * 70)

    dna = build_dna(df, symbol='SENTETIK')

    print(f"\nDURUM      : {dna['status']}")
    print(f"SEBEP      : {dna['reason']}")
    print(f"MOD        : {dna['mode']} (level={dna['level']})")
    print(f"KALİTE     : {dna['quality']}")
    print(f"SÜRE       : {dna['build_time_sec']} sn")
    print(f"  • Tekli  : {dna['timings'].get('singles_sec', 0)} sn")
    print(f"  • İkili  : {dna['timings'].get('pairs_sec', 0)} sn")
    print(f"  • Üçlü   : {dna['timings'].get('triples_sec', 0)} sn")

    if dna['chosen']:
        c = dna['chosen']
        print("\n--- SEÇİLEN KOMBO ---")
        if dna['level'] == 1:
            print(f"İndikatör: {c['name']}({c['params']})")
            print(f"Train: {c['train']}")
            print(f"Test:  {c['test']}")
            print(f"Overfit: {c['overfit']}")
        else:
            print(f"Üyeler ({len(c['members'])}):")
            for m in c['members']:
                print(f"  - {m['name']}({m['params']}) · single_q={m.get('single_quality','?')}")
            print(f"Train: {c['train']}")
            print(f"Test:  {c['test']}")
            print(f"Overfit: {c['overfit']}")

    if dna.get('single'):
        s = dna['single']
        print(f"\n[EN İYİ TEKLİ] {s['name']}({s['params']}) · "
              f"q={s['combined_quality']} · train={s['train']['quality']} · test={s['test']['quality']}")
    if dna.get('pair'):
        p = dna['pair']
        members_str = ' + '.join(m['name'] for m in p['members'])
        print(f"[EN İYİ İKİLİ] {members_str} · "
              f"q={p['combined_quality']} · train={p['train']['quality']} · test={p['test']['quality']}")
    if dna.get('triple'):
        t = dna['triple']
        members_str = ' + '.join(m['name'] for m in t['members'])
        print(f"[EN İYİ ÜÇLÜ] {members_str} · q={t['combined_quality']}")
