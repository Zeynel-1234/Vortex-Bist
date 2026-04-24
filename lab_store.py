"""
═══════════════════════════════════════════════════════════════════════
FRAKTAL KAHİN LAB — KALICI DNA SAKLAMA
───────────────────────────────────────────────────────────────────────
Amaç: Railway konteyner restart'ında DNA kartlarının kaybolmasını önlemek.

NASIL ÇALIŞIR:
  • Her DNA kartı JSON olarak `/data/dna_cards/SEMBOL.json` dosyasına yazılır
  • `/data` dizini Railway volume'ü (kalıcı disk) — restart'ta silinmez
  • Volume yoksa (lokal dev ortamı), `/tmp/dna_cards/` fallback kullanılır
  • Her kayıt `created_at` + `ttl_days` ile: 30 günden eski kartlar yeniden üretilir

DOSYA YAPISI:
  /data/dna_cards/
    THYAO.json
    TKNSA.json
    GARAN.json
    ...

GÜVENLİK:
  • Atomic write (önce .tmp, sonra rename) — dosya bozulması önlenir
  • UTF-8 encoding
  • Hata durumunda sessiz fail + log — ana akış bozulmaz
═══════════════════════════════════════════════════════════════════════
"""
import os
import json
import time
from typing import Dict, Optional, List


# ═══════════════════════════════════════════════════════════════════════
# DİZİN YÖNETİMİ
# ═══════════════════════════════════════════════════════════════════════
def _get_storage_dir() -> str:
    """
    DNA kartlarının saklanacağı dizini belirle.
    Railway volume varsa /data, yoksa /tmp kullan.
    """
    # Railway volume kontrolü
    if os.path.exists('/data') and os.access('/data', os.W_OK):
        base_dir = '/data/dna_cards'
    else:
        # Lokal veya Railway ücretsiz katmanı fallback
        base_dir = '/tmp/dna_cards'

    # Dizin yoksa oluştur
    try:
        os.makedirs(base_dir, exist_ok=True)
    except Exception as e:
        print(f"[LAB_STORE] Dizin oluşturulamadı: {e}")

    return base_dir


STORAGE_DIR = _get_storage_dir()
DEFAULT_TTL_DAYS = 30


# ═══════════════════════════════════════════════════════════════════════
# DOSYA OPERASYONLARI
# ═══════════════════════════════════════════════════════════════════════
def _dna_path(symbol: str) -> str:
    """Sembol için DNA dosya yolu."""
    clean = ''.join(c for c in symbol.upper() if c.isalnum())
    return os.path.join(STORAGE_DIR, f'{clean}.json')


def save_dna(symbol: str, dna_data: Dict,
             ttl_days: int = DEFAULT_TTL_DAYS) -> bool:
    """
    DNA kartını kalıcı diske yaz. Atomic write kullanır.

    Returns:
      True → başarılı
      False → hata (hata mesajı log'lanır ama raise edilmez)
    """
    if not symbol or not isinstance(dna_data, dict):
        return False

    path = _dna_path(symbol)
    tmp_path = path + '.tmp'

    # Meta bilgi ekle
    record = {
        **dna_data,
        '_stored_at': int(time.time()),
        '_ttl_days': ttl_days,
        '_expires_at': int(time.time()) + ttl_days * 86400
    }

    try:
        # Önce tmp dosyaya yaz
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(record, f, ensure_ascii=False, default=str)
        # Sonra atomic rename
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        print(f"[LAB_STORE] save_dna hata ({symbol}): {e}")
        # Tmp dosyayı temizlemeye çalış
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False


def load_dna(symbol: str) -> Optional[Dict]:
    """
    Diskten DNA kartını yükle.
    TTL dolmuşsa None döner (yeniden üretim gerekli).
    Dosya yoksa veya bozuksa None döner.
    """
    if not symbol:
        return None

    path = _dna_path(symbol)
    if not os.path.exists(path):
        return None

    try:
        with open(path, 'r', encoding='utf-8') as f:
            record = json.load(f)
    except Exception as e:
        print(f"[LAB_STORE] load_dna hata ({symbol}): {e}")
        return None

    # TTL kontrolü
    expires_at = record.get('_expires_at', 0)
    if expires_at > 0 and time.time() > expires_at:
        # Süresi dolmuş — dosyayı silmiyoruz, yeni üretim tetikleyecek
        return None

    return record


def is_cached(symbol: str) -> bool:
    """
    Sembolün geçerli (TTL içinde) DNA kartı var mı?
    """
    return load_dna(symbol) is not None


def delete_dna(symbol: str) -> bool:
    """Belirli bir sembolün DNA kartını sil."""
    if not symbol:
        return False
    path = _dna_path(symbol)
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
    except Exception as e:
        print(f"[LAB_STORE] delete_dna hata ({symbol}): {e}")
    return False


def list_all_dna() -> List[Dict]:
    """
    Saklanan tüm DNA kartlarının ÖZETİNİ döner.
    (Frontend için hızlı listeleme)
    """
    summaries = []
    try:
        for filename in os.listdir(STORAGE_DIR):
            if not filename.endswith('.json'):
                continue
            symbol = filename[:-5]  # .json'u kes
            record = load_dna(symbol)
            if record is None:
                continue

            # Kompakt özet
            chosen = record.get('chosen') or {}
            summary = {
                'symbol': record.get('symbol', symbol),
                'status': record.get('status'),
                'mode': record.get('mode'),
                'quality': record.get('quality'),
                'stored_at': record.get('_stored_at'),
                'expires_at': record.get('_expires_at'),
                'age_hours': round(
                    (time.time() - record.get('_stored_at', time.time())) / 3600, 1
                )
            }

            # Strateji özeti (indikatör adları)
            if chosen:
                if 'members' in chosen:
                    summary['indicators'] = [m.get('name') for m in chosen['members']]
                elif 'name' in chosen:
                    summary['indicators'] = [chosen['name']]

            summaries.append(summary)
    except Exception as e:
        print(f"[LAB_STORE] list_all_dna hata: {e}")

    # Kaliteye göre sırala (yüksek → düşük)
    summaries.sort(
        key=lambda x: x.get('quality') if x.get('quality') is not None else -1,
        reverse=True
    )
    return summaries


def storage_info() -> Dict:
    """Depolama durumu özeti."""
    try:
        files = [f for f in os.listdir(STORAGE_DIR) if f.endswith('.json')]
        total_size = sum(
            os.path.getsize(os.path.join(STORAGE_DIR, f))
            for f in files
        )
        return {
            'storage_dir': STORAGE_DIR,
            'is_persistent': STORAGE_DIR.startswith('/data'),
            'dna_count': len(files),
            'total_size_kb': round(total_size / 1024, 1),
            'files': sorted(files)
        }
    except Exception as e:
        return {
            'storage_dir': STORAGE_DIR,
            'error': str(e),
            'dna_count': 0
        }
