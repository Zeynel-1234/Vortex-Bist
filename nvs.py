"""
═══════════════════════════════════════════════════════════════
BIST VORTEX v7.3 · NIHAI VORTEX SKORU (NVS) — Python Port
───────────────────────────────────────────────────────────────
b-165.html'deki JavaScript formüllerinin birebir Python kopyası.
Hiçbir matematik değiştirilmedi.

NVS = (A × 0.40) + (B × 0.25) + (C × 0.20) + (D × 0.15)
A = BKM skoru (3 zaman dilimi sentezi)
B = Güven Skoru × 100 (indikatör uyum oranı)
C = Günlük baz skor (adaptif ağırlıklı)
D = Makro filtre skoru (aylık trend kalitesi)

KARAR EŞİKLERİ:
NVS ≥ 80 → GÜÇLÜ AL
NVS ≥ 65 → AL
NVS ≥ 45 → NÖTR
NVS ≥ 30 → SAT
NVS < 30 → GÜÇLÜ SAT
═══════════════════════════════════════════════════════════════
"""

import math
from typing import Dict, List, Optional, Any


# ─── GUARD: Güvenli sayı ─────────────────────────────────────
def safe(v, default=0.0):
    """null/NaN → varsayılan"""
    if v is None:
        return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


# ─── WEIGHT ANOMALY GUARD ────────────────────────────────────
INDICATOR_KEYS = ['rec', 'rsi', 'stoch', 'macd', 'ema20', 'ema50', 'ema200', 'vol', 'adx']


def clamp_wm(w: Dict) -> Dict:
    """Adaptif ağırlıkları [0.2, 3.0] bandına zorla"""
    out = {}
    for k in INDICATOR_KEYS:
        out[k] = max(0.2, min(3.0, safe(w.get(k), 1.0)))
    return out


def get_wm(adaptive_weights: Optional[Dict] = None) -> Dict:
    """
    Adaptif ağırlıkları döndür. Yoksa hepsi 1.0 (öğrenme öncesi default).
    İleride DNA öğrenme sistemi entegre edilince adaptive_weights dolar.
    """
    if adaptive_weights and adaptive_weights.get('gen', 0) > 0:
        return clamp_wm(adaptive_weights)
    return {k: 1.0 for k in INDICATOR_KEYS}


# ════════════════════════════════════════════════════════════════
# A — GÜNLÜK BAZ SKOR (Adaptif ağırlıklı, 0-100)
# ════════════════════════════════════════════════════════════════
def adaptive_base_score(rec, rsi, stoch, mh, e20, e50, e200, vol, va, adx,
                        adaptive_weights: Optional[Dict] = None) -> int:
    """
    Adaptif baz skor. b-165 satır 285-302'nin birebir kopyası.
    
    Katkılar maksimum:
      rec×25 + rsi×20 + stoch×12 + macd×7
      + ema20×6 + ema50×4 + ema200×3 + vol×5 + adx×3 = 85p üzeri
    """
    wm = get_wm(adaptive_weights)
    s = 50.0  # baz nötr
    
    if rec is not None and not (isinstance(rec, float) and math.isnan(rec)):
        s += safe(rec, 0) * 25 * wm['rec']
    
    if rsi is not None and not (isinstance(rsi, float) and math.isnan(rsi)):
        s += (50 - safe(rsi, 50)) / 50 * 20 * wm['rsi']
    
    if stoch is not None and not (isinstance(stoch, float) and math.isnan(stoch)):
        s += (50 - safe(stoch, 50)) / 50 * 12 * wm['stoch']
    
    if mh is not None and not (isinstance(mh, float) and math.isnan(mh)):
        s += (7 if mh > 0 else -7) * wm['macd']
    
    if e20 is not None and not (isinstance(e20, float) and math.isnan(e20)):
        s += (6 if e20 > 0 else -6) * wm['ema20']
    
    if e50 is not None and not (isinstance(e50, float) and math.isnan(e50)):
        s += (4 if e50 > 0 else -4) * wm['ema50']
    
    if e200 is not None and not (isinstance(e200, float) and math.isnan(e200)):
        s += (3 if e200 > 0 else -3) * wm['ema200']
    
    if vol is not None and va is not None and va > 0:
        vr = vol / va
        if vr > 2.5:
            s += 5 * wm['vol']
        elif vr > 1.8:
            s += 3 * wm['vol']
        elif vr < 0.6:
            s -= 4 * wm['vol']
    
    if adx is not None and not (isinstance(adx, float) and math.isnan(adx)) and adx > 20 and rec is not None:
        s += (1 if rec > 0 else -1) * (3 if adx > 30 else 1) * wm['adx']
    
    return int(max(0, min(100, round(s))))


# ════════════════════════════════════════════════════════════════
# B — GÜVEN SKORU (0-1, sonra ×100 olarak NVS'e girer)
# CS = I_uyum × 0.62 + OT
# ════════════════════════════════════════════════════════════════
def calc_cs(daily_vd: float, d_data: Dict) -> float:
    """
    Güven Skoru. b-165 satır 311-335'in birebir kopyası.
    
    daily_vd: günlük baz skor (VD[sym])
    d_data: günlük indikatörler dict (rec, rsi, stoch, macd, ema20, ema50, ema200, vol, vol_avg, adx)
    """
    bull = safe(daily_vd, 50) > 50
    
    rsi = d_data.get('rsi')
    stoch = d_data.get('stoch')
    mh = d_data.get('macd')
    e20 = d_data.get('ema20')
    e50 = d_data.get('ema50')
    e200 = d_data.get('ema200')
    rec = d_data.get('rec')
    vol = d_data.get('vol')
    va = d_data.get('vol_avg')
    adx = d_data.get('adx')
    
    votes = 0
    total = 0
    
    if rsi is not None:
        total += 1
        if (bull and rsi < 50) or (not bull and rsi > 55):
            votes += 1
    
    if stoch is not None:
        total += 1
        if (bull and stoch < 55) or (not bull and stoch > 65):
            votes += 1
    
    if mh is not None:
        total += 1
        if (bull and mh > 0) or (not bull and mh < 0):
            votes += 1
    
    if e20 is not None:
        total += 1
        if (bull and e20 > 0) or (not bull and e20 < 0):
            votes += 1
    
    if e50 is not None:
        total += 1
        if (bull and e50 > 0) or (not bull and e50 < 0):
            votes += 1
    
    if e200 is not None:
        total += 1
        if (bull and e200 > 0) or (not bull and e200 < 0):
            votes += 1
    
    if rec is not None:
        total += 1
        if (bull and rec > 0) or (not bull and rec < 0):
            votes += 1
    
    if adx is not None:
        total += 1
        if adx > 20:
            votes += 1
    
    Iu = votes / total if total > 0 else 0.5
    
    # Bear market cezası
    if e200 is not None and e200 < 0 and bull:
        Iu *= 0.7
    
    # Oyun Teorisi düzeltmesi
    OT = 0.0
    if vol is not None and va is not None and va > 0:
        vr2 = vol / va
        if vr2 > 1.8 and rsi is not None and rsi < 45:
            OT = 0.15
        elif vr2 < 0.6 and rsi is not None and rsi > 60:
            OT = -0.20
        elif vr2 > 1.5:
            OT = 0.08
    
    return max(0.0, min(1.0, Iu * 0.62 + OT))


# ════════════════════════════════════════════════════════════════
# C — BİLİŞİK KARAR MATRİSİ / BKM (0-100)
# 3 zaman diliminin çarpımsal sentezi
# ════════════════════════════════════════════════════════════════
def comp_score(VD_sym: float, VW_sym: float, VM_sym: float, d_data: Dict) -> int:
    """
    BKM. b-165 satır 344-367'nin birebir kopyası.
    
    VD_sym: günlük baz skor
    VW_sym: haftalık baz skor
    VM_sym: aylık baz skor
    d_data: günlük indikatörler (rsi, macd, vol, vol_avg, ema20, ema50, ema200, adx, rec)
    """
    D = safe(VD_sym, 50)
    W = safe(VW_sym, 50)
    M = safe(VM_sym, 50)
    
    Dn = (D - 50) / 50
    Wn = (W - 50) / 50
    Mn = (M - 50) / 50
    
    # Aylık kapı (Mn>0 → büyütür, Mn<0 → küçültür)
    Mg = 1 + Mn * 0.40 if Mn > 0 else 1 + Mn * 0.60
    
    # Haftalık amplifikatör (yön uyumlu mu?)
    Wa = 1 + abs(Wn) * 0.35 if Dn * Wn > 0 else 1 - abs(Wn) * 0.25
    
    raw = Dn * Wa * Mg
    
    # Confluence amplifier (aşırı net sinyalde büyüt)
    if abs(raw) > 0.5:
        raw = raw * (1 + abs(raw) * 0.30)
    
    # Bonus düzeltmeleri
    b = 0.0
    rsi = d_data.get('rsi')
    mh = d_data.get('macd')
    vol = d_data.get('vol')
    va = d_data.get('vol_avg')
    e20 = d_data.get('ema20')
    e50 = d_data.get('ema50')
    e200 = d_data.get('ema200')
    adx = d_data.get('adx')
    rec = d_data.get('rec')
    
    if rsi is not None and mh is not None:
        if rsi < 40 and mh > 0:
            b += 0.08
        if rsi > 65 and mh < 0:
            b -= 0.08
    
    if vol is not None and va is not None and va > 0:
        vr3 = vol / va
        if raw > 0.3 and vr3 > 1.8:
            b += 0.06
        if raw > 0 and vr3 < 0.6:
            b -= 0.10
    
    if e20 is not None and e50 is not None and e200 is not None:
        if e20 > 0 and e50 > 0 and e200 > 0:
            b += 0.06
        elif e20 < 0 and e50 < 0 and e200 < 0:
            b -= 0.06
    
    if adx is not None and adx > 28 and rec is not None:
        b += (1 if rec > 0 else -1) * 0.04
    
    return int(max(0, min(100, round((raw + b) * 50 + 50))))


# ════════════════════════════════════════════════════════════════
# D — MAKRO FİLTRE SKORU (0-100)
# Aylık RSI + EMA trend uyumu + MACD yönü
# ════════════════════════════════════════════════════════════════
def macro_score(m_data: Dict, w_data: Dict) -> int:
    """
    Makro skor. b-165 satır 373-382'nin birebir kopyası.
    
    m_data: aylık indikatörler (rsi, macd, rec)
    w_data: haftalık indikatörler (ema20, ema50)
    """
    s = 50.0
    
    mr = m_data.get('rsi')
    mm = m_data.get('macd')
    mrec = m_data.get('rec')
    we = w_data.get('ema20')
    we2 = w_data.get('ema50')
    
    if mr is not None:
        s += (50 - mr) / 50 * 25
    
    if mm is not None:
        s += 12 if mm > 0 else -12
    
    if mrec is not None:
        s += mrec * 20
    
    if we is not None and we2 is not None:
        s += 8 if we > we2 else -8
    
    return int(max(0, min(100, round(s))))


# ════════════════════════════════════════════════════════════════
# NVS — NİHAİ VORTEX SKORU
# Formül: NVS = A×0.40 + B×0.25 + C×0.20 + D×0.15
# ════════════════════════════════════════════════════════════════
def calc_nvs(bkm: float, cs: float, daily_base: float, macro: float) -> int:
    """
    Final NVS hesaplama. b-165 satır 390-402'nin birebir kopyası.
    
    bkm: BKM skoru (0-100)
    cs: Güven Skoru (0-1, ×100 yapılır)
    daily_base: Günlük baz skor (0-100)
    macro: Makro skor (0-100)
    """
    A = max(0, min(100, safe(bkm, 50)))
    B = max(0, min(100, safe(cs, 0.5) * 100))
    C = max(0, min(100, safe(daily_base, 50)))
    D = max(0, min(100, safe(macro, 50)))
    
    nvs = A * 0.40 + B * 0.25 + C * 0.20 + D * 0.15
    return int(max(0, min(100, round(nvs))))


# ════════════════════════════════════════════════════════════════
# NVS ETİKETİ ve RENGİ
# ════════════════════════════════════════════════════════════════
def nvs_label(n: int) -> Dict:
    """b-165 satır 405-411'in birebir kopyası"""
    if n >= 80:
        return {'t': 'GÜÇLÜ AL', 'c': '#22c55e', 'bg': '#052e16', 'emoji': '🟢'}
    if n >= 65:
        return {'t': 'AL', 'c': '#86efac', 'bg': '#022d10', 'emoji': '🟩'}
    if n >= 45:
        return {'t': 'NÖTR', 'c': '#94a3b8', 'bg': '#1e293b', 'emoji': '⬜'}
    if n >= 30:
        return {'t': 'SAT', 'c': '#fca5a5', 'bg': '#3b1010', 'emoji': '🟥'}
    return {'t': 'GÜÇLÜ SAT', 'c': '#ef4444', 'bg': '#450a0a', 'emoji': '🔴'}


def sig_label(s: Optional[float]) -> Dict:
    """Genel sinyal etiketi (D/W/M/BKM için). b-165 satır 466-473."""
    if s is None:
        return {'t': '—', 'bg': '#1e293b', 'c': '#475569'}
    if s >= 75:
        return {'t': 'G.AL', 'bg': '#14532d', 'c': '#22c55e'}
    if s >= 60:
        return {'t': 'AL', 'bg': '#052e16', 'c': '#86efac'}
    if s >= 42:
        return {'t': 'NOTR', 'bg': '#1e293b', 'c': '#94a3b8'}
    if s >= 28:
        return {'t': 'SAT', 'bg': '#3b1010', 'c': '#fca5a5'}
    return {'t': 'G.SAT', 'bg': '#450a0a', 'c': '#ef4444'}


def cs_label(cs: float) -> Dict:
    """Güven Skoru etiketi. b-165 satır 474-479."""
    if cs >= 0.80:
        return {'t': 'YUKSEK', 'c': '#22c55e'}
    if cs >= 0.65:
        return {'t': 'ORTA', 'c': '#86efac'}
    if cs >= 0.45:
        return {'t': 'DUSUK', 'c': '#e8b84b'}
    return {'t': 'YOK', 'c': '#ef4444'}


# ════════════════════════════════════════════════════════════════
# TOP FACTORS — En etkili 3 gösterge
# ════════════════════════════════════════════════════════════════
def top_factors(d_data: Dict, daily_vd: float,
                adaptive_weights: Optional[Dict] = None) -> List[Dict]:
    """
    NVS'e en çok katkı yapan 3 göstergeyi döndürür.
    b-165 satır 414-438'in birebir kopyası.
    """
    wm = get_wm(adaptive_weights)
    bull = safe(daily_vd, 50) > 50
    
    rec = d_data.get('rec')
    rsi = d_data.get('rsi')
    stoch = d_data.get('stoch')
    mh = d_data.get('macd')
    e20 = d_data.get('ema20')
    e50 = d_data.get('ema50')
    e200 = d_data.get('ema200')
    vol = d_data.get('vol')
    va = d_data.get('vol_avg')
    adx = d_data.get('adx')
    
    factors = []
    
    if rec is not None:
        v = 1 if rec > 0.3 else (-1 if rec < -0.3 else 0)
        factors.append({'n': 'TV Tavsiyesi', 'v': v, 'w': 25 * wm['rec'],
                        'raw': f"{rec:.2f}", 'unit': ''})
    
    if rsi is not None:
        ri = (50 - rsi) / 50
        v = 1 if ri > 0.1 else (-1 if ri < -0.1 else 0)
        factors.append({'n': 'RSI', 'v': v, 'w': 20 * wm['rsi'],
                        'raw': f"{rsi:.0f}", 'unit': ''})
    
    if mh is not None:
        factors.append({'n': 'MACD Histogram', 'v': 1 if mh > 0 else -1,
                        'w': 7 * wm['macd'], 'raw': f"{mh:.4f}", 'unit': ''})
    
    if e20 is not None:
        factors.append({'n': 'EMA20 Pozisyonu', 'v': 1 if e20 > 0 else -1,
                        'w': 6 * wm['ema20'], 'raw': 'Üst' if e20 > 0 else 'Alt', 'unit': ''})
    
    if e200 is not None:
        factors.append({'n': 'EMA200 (Makro)', 'v': 1 if e200 > 0 else -1,
                        'w': 3 * wm['ema200'], 'raw': 'Üst' if e200 > 0 else 'Alt', 'unit': ''})
    
    if stoch is not None:
        si = (50 - stoch) / 50
        v = 1 if si > 0.15 else (-1 if si < -0.15 else 0)
        factors.append({'n': 'Stoch %K', 'v': v, 'w': 12 * wm['stoch'],
                        'raw': f"{stoch:.0f}", 'unit': ''})
    
    if vol is not None and va is not None and va > 0:
        vr = vol / va
        v = 1 if vr > 1.5 else (-1 if vr < 0.7 else 0)
        factors.append({'n': 'Hacim Oranı', 'v': v, 'w': 5,
                        'raw': f"{vr:.1f}×", 'unit': ''})
    
    if adx is not None:
        factors.append({'n': 'ADX Güç', 'v': 1 if adx > 25 else 0,
                        'w': 3 * wm['adx'], 'raw': f"{adx:.0f}", 'unit': ''})
    
    # Katkı: yön × ağırlık
    for f in factors:
        f['impact'] = f['v'] * f['w']
    
    # Mutlak etkiye göre sırala, ilk 3
    factors.sort(key=lambda x: abs(x['impact']), reverse=True)
    return factors[:3]


# ════════════════════════════════════════════════════════════════
# MASTER FUNCTION — Tek bir hisse için tam NVS analizi
# ════════════════════════════════════════════════════════════════
def analyze_nvs(symbol: str, d_data: Dict, w_data: Dict, m_data: Dict,
                adaptive_weights: Optional[Dict] = None) -> Dict:
    """
    Tek hissenin NVS'ini ve tüm bileşenlerini hesaplar.
    
    symbol: 'THYAO' gibi
    d_data: günlük indikatörler {rec, rsi, stoch, macd, ema20, ema50, ema200, vol, vol_avg, adx}
    w_data: haftalık indikatörler {rec, rsi, stoch, macd, ema20, ema50}
    m_data: aylık indikatörler {rec, rsi, stoch, macd, ema20, ema50}
    adaptive_weights: DNA öğrenme ağırlıkları (opsiyonel)
    
    Returns: Tam NVS analizi dict
    """
    # 1. Günlük baz skor (D)
    VD = adaptive_base_score(
        rec=d_data.get('rec'),
        rsi=d_data.get('rsi'),
        stoch=d_data.get('stoch'),
        mh=d_data.get('macd'),
        e20=d_data.get('ema20'),
        e50=d_data.get('ema50'),
        e200=d_data.get('ema200'),
        vol=d_data.get('vol'),
        va=d_data.get('vol_avg'),
        adx=d_data.get('adx'),
        adaptive_weights=adaptive_weights
    )
    
    # 2. Haftalık baz skor (W)
    VW = adaptive_base_score(
        rec=w_data.get('rec'),
        rsi=w_data.get('rsi'),
        stoch=w_data.get('stoch'),
        mh=w_data.get('macd'),
        e20=w_data.get('ema20'),
        e50=w_data.get('ema50'),
        e200=None, vol=None, va=None, adx=None,
        adaptive_weights=adaptive_weights
    )
    
    # 3. Aylık baz skor (M)
    VM = adaptive_base_score(
        rec=m_data.get('rec'),
        rsi=m_data.get('rsi'),
        stoch=m_data.get('stoch'),
        mh=m_data.get('macd'),
        e20=m_data.get('ema20'),
        e50=m_data.get('ema50'),
        e200=None, vol=None, va=None, adx=None,
        adaptive_weights=adaptive_weights
    )
    
    # 4. BKM (Bilişik Karar Matrisi)
    VC = comp_score(VD, VW, VM, d_data)
    
    # 5. Güven Skoru
    CS = calc_cs(VD, d_data)
    
    # 6. Makro skor
    MAC = macro_score(m_data, w_data)
    
    # 7. NVS (Nihai Vortex Skoru)
    NVS = calc_nvs(bkm=VC, cs=CS, daily_base=VD, macro=MAC)
    
    # 8. Etiketler
    nvs_lbl = nvs_label(NVS)
    cs_lbl = cs_label(CS)
    
    # 9. Top 3 faktör
    top = top_factors(d_data, VD, adaptive_weights)
    
    return {
        'sembol': symbol,
        'nvs': NVS,
        'nvs_label': nvs_lbl['t'],
        'nvs_color': nvs_lbl['c'],
        'nvs_bg': nvs_lbl['bg'],
        'bkm': VC,
        'gunluk': VD,
        'haftalik': VW,
        'aylik': VM,
        'makro': MAC,
        'guven_skoru': round(CS * 100, 1),
        'guven_label': cs_lbl['t'],
        'guven_color': cs_lbl['c'],
        'top_factors': top,
        'agirlik_dagilimi': {
            'BKM_40': VC,
            'CS_25': round(CS * 100),
            'Gunluk_20': VD,
            'Makro_15': MAC
        },
        'sinyaller': {
            'D': sig_label(VD),
            'W': sig_label(VW),
            'M': sig_label(VM),
            'BKM': sig_label(VC),
            'NVS': nvs_lbl
        }
    }


# ════════════════════════════════════════════════════════════════
# UNIT TEST — Bu dosyayı doğrudan çalıştırırsan test çıktısı verir
# ════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    # b-165 ekran görüntüsündeki HUBVC değerleriyle test
    # Beklenen: NVS=83, BKM=100, CS=62%, Günlük=95, Makro=58
    test_d = {
        'rec': 0.291, 'rsi': 48.1, 'stoch': 33.7, 'macd': 0.0108,
        'ema20': 1, 'ema50': -1, 'ema200': 1,  # Üst/Alt → 1/-1
        'vol': 2.0, 'vol_avg': 1.0,  # 2.0× hacim
        'adx': 35.0
    }
    test_w = {
        'rec': 0.288, 'rsi': 52.9, 'stoch': 33.7, 'macd': 0.0108,
        'ema20': 1, 'ema50': 1
    }
    test_m = {
        'rec': 0.288, 'rsi': 52.9, 'stoch': 33.7, 'macd': 0.0108,
        'ema20': 1, 'ema50': 1
    }
    
    result = analyze_nvs('HUBVC', test_d, test_w, test_m)
    print("=" * 60)
    print(f"TEST: {result['sembol']}")
    print(f"NVS:    {result['nvs']} → {result['nvs_label']}")
    print(f"BKM:    {result['bkm']}")
    print(f"Günlük: {result['gunluk']}")
    print(f"Haft.:  {result['haftalik']}")
    print(f"Aylık:  {result['aylik']}")
    print(f"Makro:  {result['makro']}")
    print(f"CS:     {result['guven_skoru']}% ({result['guven_label']})")
    print("Top 3 Faktör:")
    for f in result['top_factors']:
        print(f"  · {f['n']}: {f['raw']} (impact: {f['impact']:+.1f})")
    print("=" * 60)
