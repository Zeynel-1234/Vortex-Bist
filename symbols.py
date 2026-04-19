# symbols.py - Geçici dosya
# Gerçek sembol listesi daha sonra eklenecek

BIST_SYMBOLS = ["THYAO", "GARAN", "AKBNK", "SASA", "PGSUS"]

def get_all():
    return BIST_SYMBOLS

def to_yf(sym):
    return sym + ".IS"

def from_yf(sym):
    return sym.replace(".IS", "")
