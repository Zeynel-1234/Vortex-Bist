"""
================================================================================
  Vortex-BIST · Supertrend × LSMA Crossover Scanner
  v1.0 — ADDITIVE MODULE — mevcut sisteme dokunmaz.

  Tarama Mantığı (günlük bar):
    - Yeşil çizgi  = Supertrend(ATR=25, factor=1.0)
    - Sarı çizgi   = LSMA(source=high, length=350, offset=60)
    - Koşul        = Supertrend > LSMA  (yukarı kesişim aktif)
    - Sınıflandırma= en son kesişim kapanışından bugüne % kazanç
        0%   ≤ Δ <  10%  →  YENİ
        10%  ≤ Δ <  20%  →  ORTA
        20%  ≤ Δ          →  YÜKSEK

  Entegrasyon (main.py'ye 2 satır):
    from crossover_scanner import router as crossover_router
    app.include_router(crossover_router)

  İsteğe bağlı (mevcut 630'luk listeyi enjekte et):
    from crossover_scanner import set_symbols
    set_symbols(BIST_LIST)      # ['AKBNK','GARAN',...]   (.IS suffix YOK)

  Sayfa: /crossover/
  API  : /crossover/api/scan, /crossover/api/status
================================================================================
"""

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import HTMLResponse
from datetime import datetime
import threading
import logging

import numpy as np
import pandas as pd

try:
    import yfinance as yf
    HAS_YF = True
except Exception:
    HAS_YF = False

log = logging.getLogger("crossover_scanner")
router = APIRouter(prefix="/crossover", tags=["crossover-scanner"])

# ============================================================================
#  BIST SEMBOL LİSTESİ
#  (Mevcut uygulamadaki tam 630'luk listeyi set_symbols(...) ile enjekte et.)
# ============================================================================
DEFAULT_BIST = [
    "A1CAP","ACSEL","ADEL","ADESE","ADGYO","AEFES","AFYON","AGESA","AGHOL","AGROT",
    "AHGAZ","AKBNK","AKCNS","AKENR","AKFGY","AKFIS","AKFYE","AKGRT","AKMGY","AKSA",
    "AKSEN","AKSGY","AKSUE","AKYHO","ALARK","ALBRK","ALCAR","ALCTL","ALFAS","ALKA",
    "ALKIM","ALKLC","ALMAD","ALTNY","ALVES","ANELE","ANGEN","ANHYT","ANSGR","ARASE",
    "ARCLK","ARDYZ","ARENA","ARSAN","ARTMS","ARZUM","ASELS","ASGYO","ASTOR","ASUZU",
    "ATAGY","ATAKP","ATATP","ATEKS","ATLAS","ATSYH","AVGYO","AVHOL","AVOD","AVPGY",
    "AVTUR","AYCES","AYDEM","AYEN","AYES","AYGAZ","AZTEK","BAGFS","BAHKM","BAKAB",
    "BALAT","BALSU","BANVT","BARMA","BASCM","BASGZ","BAYRK","BEGYO","BERA","BEYAZ",
    "BFREN","BIENY","BIGCH","BIMAS","BINBN","BINHO","BIOEN","BIZIM","BJKAS","BLCYT",
    "BMSCH","BMSTL","BNTAS","BOBET","BORLS","BORSK","BOSSA","BRISA","BRKO","BRKSN",
    "BRKVY","BRLSM","BRMEN","BRSAN","BRYAT","BSOKE","BTCIM","BUCIM","BULGS","BURCE",
    "BURVA","BVSAN","BYDNR","CANTE","CASA","CCOLA","CELHA","CEMAS","CEMTS","CEOEM",
    "CGCAM","CIMSA","CLEBI","CMBTN","CMENT","CONSE","COSMO","CRDFA","CRFSA","CUSAN",
    "CVKMD","CWENE","DAGHL","DAGI","DAPGM","DARDL","DCTTR","DERHL","DERIM","DESA",
    "DESPC","DEVA","DGATE","DGGYO","DGNMO","DIRIT","DITAS","DMRGD","DMSAS","DNISI",
    "DOAS","DOBUR","DOCO","DOFER","DOGUB","DOHOL","DOKTA","DURDO","DURKN","DYOBY",
    "DZGYO","EBEBK","ECILC","ECZYT","EDATA","EDIP","EFORC","EGEEN","EGEPO","EGGUB",
    "EGPRO","EGSER","EKER","EKGYO","EKIZ","EKOS","EKSUN","ELITE","EMKEL","EMNIS",
    "ENERY","ENJSA","ENKAI","ENSRI","ENTRA","EPLAS","ERBOS","ERCB","EREGL","ERSU",
    "ESCAR","ESCOM","ESEN","ETILR","ETYAT","EUHOL","EUKYO","EUPWR","EUREN","EUYO",
    "EYGYO","FADE","FENER","FLAP","FMIZP","FONET","FORMT","FORTE","FRIGO","FROTO",
    "FZLGY","GARAN","GARFA","GEDIK","GEDZA","GENIL","GENTS","GEREL","GESAN","GIPTA",
    "GLBMD","GLCVY","GLRYH","GLYHO","GMTAS","GOKNR","GOLTS","GOODY","GOZDE","GRNYO",
    "GRSEL","GRTHO","GSDDE","GSDHO","GSRAY","GUBRF","GUNDG","GWIND","HALKB","HATEK",
    "HATSN","HDFGS","HEDEF","HEKTS","HKTM","HLGYO","HOROZ","HRKET","HTTBT","HUBVC",
    "HUNER","HURGZ","ICBCT","ICUGS","IDGYO","IEYHO","IHAAS","IHEVA","IHGZT","IHLAS",
    "IHLGM","IHYAY","IMASM","INDES","INFO","INGRM","INTEK","INTEM","INVEO","INVES",
    "IPEKE","ISATR","ISBIR","ISBTR","ISCTR","ISDMR","ISFIN","ISGSY","ISGYO","ISKPL",
    "ISMEN","ISSEN","ISYAT","IZENR","IZFAS","IZINV","IZMDC","JANTS","KAPLM","KAREL",
    "KARSN","KARTN","KARYE","KATMR","KAYSE","KBORU","KCAER","KCHOL","KENT","KERVN",
    "KERVT","KFEIN","KGYO","KIMMR","KLGYO","KLKIM","KLMSN","KLNMA","KLRHO","KLSER",
    "KLSYN","KMPUR","KNFRT","KOCMT","KONKA","KONTR","KONYA","KOPOL","KORDS","KOTON",
    "KOZAA","KOZAL","KRDMA","KRDMB","KRDMD","KRGYO","KRONT","KRPLS","KRSTL","KRTEK",
    "KRVGD","KSTUR","KTLEV","KTSKR","KUTPO","KUVVA","KUYAS","KZBGY","KZGYO","LIDER",
    "LIDFA","LILAK","LINK","LKMNH","LMKDC","LOGO","LRSHO","LUKSK","LYDHO","MAALT",
    "MACKO","MAGEN","MAKIM","MAKTK","MANAS","MARBL","MARKA","MARTI","MAVI","MEDTR",
    "MEGAP","MEGMT","MEKAG","MEPET","MERCN","MERIT","MERKO","METRO","METUR","MGROS",
    "MHRGY","MIATK","MIPAZ","MMCAS","MNDRS","MNDTR","MOBTL","MOGAN","MPARK","MRGYO",
    "MRSHL","MSGYO","MTRKS","MTRYO","MZHLD","NATEN","NETAS","NIBAS","NTGAZ","NTHOL",
    "NUGYO","NUHCM","OBAMS","OBASE","ODAS","ODINE","OFSYM","ONCSM","ONRYT","ORCAY",
    "ORGE","ORMA","OSMEN","OSTIM","OTKAR","OTOKC","OTTO","OYAKC","OYAYO","OYLUM",
    "OYYAT","OZGYO","OZKGY","OZRDN","OZSUB","OZYSR","PAGYO","PAMEL","PAPIL","PARSN",
    "PASEU","PATEK","PCILT","PEHOL","PEKGY","PENGD","PENTA","PETKM","PETUN","PGSUS",
    "PINSU","PKART","PKENT","PLTUR","PNLSN","PNSUT","POLHO","POLTK","PRDGS","PRKAB",
    "PRKME","PRZMA","PSDTC","PSGYO","QNBFB","QNBFL","QUAGR","RALYH","RAYSG","REEDR",
    "RGYAS","RNPOL","RODRG","RTALB","RUBNS","RYGYO","RYSAS","SAFKR","SAHOL","SAMAT",
    "SANEL","SANFM","SANKO","SARKY","SASA","SAYAS","SDTTR","SEGYO","SEKFK","SEKUR",
    "SELEC","SELGD","SELVA","SEYKM","SILVR","SISE","SKBNK","SKTAS","SKYLP","SKYMD",
    "SMART","SMRTG","SNGYO","SNICA","SNKRN","SNPAM","SODSN","SOKE","SOKM","SONME",
    "SRVGY","SUMAS","SUNTK","SURGY","SUWEN","TABGD","TARKM","TATEN","TATGD","TAVHL",
    "TCELL","TCKRC","TDGYO","TEKTU","TERA","TETMT","TEZOL","TGSAS","THYAO","TKFEN",
    "TKNSA","TLMAN","TMPOL","TMSN","TNZTP","TOASO","TRCAS","TRGYO","TRILC","TSGYO",
    "TSKB","TSPOR","TTKOM","TTRAK","TUCLK","TUKAS","TUPRS","TUREX","TURGG","TURSG",
    "ULAS","ULKER","ULUFA","ULUSE","ULUUN","UMPAS","UNLU","USAK","UZERB","VAKBN",
    "VAKFN","VAKKO","VANGD","VBTYZ","VERTU","VERUS","VESBE","VESTL","VKFYO","VKGYO",
    "VKING","VRGYO","YAPRK","YATAS","YAYLA","YBTAS","YEOTK","YESIL","YGGYO","YGYO",
    "YIGIT","YKBNK","YKSLN","YONGA","YUNSA","YYAPI","YYLGD","ZEDUR","ZOREN","ZRGYO",
]

_symbols = list(DEFAULT_BIST)


def set_symbols(symbols):
    """Mevcut uygulamadaki tam BIST listesini buraya geçir (.IS suffix YOK)."""
    global _symbols
    if symbols:
        _symbols = [str(s).strip().upper().replace(".IS", "") for s in symbols if s]


# ============================================================================
#  CACHE
# ============================================================================
_cache = {
    "data": None,
    "last_updated": None,
    "scanning": False,
    "progress": 0,
    "total": 0,
    "error": None,
}
_lock = threading.Lock()


# ============================================================================
#  GÖSTERGE HESAPLAMALARI
# ============================================================================
def compute_lsma(prices: pd.Series, length: int = 350, offset: int = 60) -> pd.Series:
    """
    LSMA = ta.linreg(source, length, offset)
    Formül: intercept + slope * (length - 1 - offset)
    Her bar için geriye [length] çubukluk lineer regresyon yapılır.
    """
    arr = prices.values.astype(float)
    n = len(arr)
    out = np.full(n, np.nan)
    if n < length:
        return pd.Series(out, index=prices.index)

    from numpy.lib.stride_tricks import sliding_window_view
    windows = sliding_window_view(arr, length)  # (n-length+1, length)

    L = length
    x = np.arange(L, dtype=float)
    x_mean = (L - 1) / 2.0
    x_centered = x - x_mean
    x_var = (x_centered ** 2).sum()

    nan_mask = np.isnan(windows).any(axis=1)
    y_mean = np.nanmean(windows, axis=1)
    slope = ((windows - y_mean[:, None]) * x_centered).sum(axis=1) / x_var
    intercept = y_mean - slope * x_mean
    lsma_vals = intercept + slope * (L - 1 - offset)
    lsma_vals[nan_mask] = np.nan

    out[L - 1:] = lsma_vals
    return pd.Series(out, index=prices.index)


def compute_supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
                       length: int = 25, factor: float = 1.0):
    """Standart Supertrend — Wilder ATR ile."""
    h = high.values.astype(float)
    l = low.values.astype(float)
    c = close.values.astype(float)
    n = len(c)

    tr = np.zeros(n)
    if n == 0:
        empty = pd.Series([], index=close.index)
        return empty, empty
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))

    atr = np.full(n, np.nan)
    if n >= length:
        atr[length - 1] = np.mean(tr[:length])
        for i in range(length, n):
            atr[i] = (atr[i - 1] * (length - 1) + tr[i]) / length

    hl2 = (h + l) / 2.0
    ub = hl2 + factor * atr
    lb = hl2 - factor * atr

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    st = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)

    start = length - 1
    if start >= n:
        return pd.Series(st, index=close.index), pd.Series(direction, index=close.index)

    upper[start] = ub[start]
    lower[start] = lb[start]
    direction[start] = -1
    st[start] = upper[start]

    for i in range(start + 1, n):
        if ub[i] < upper[i - 1] or c[i - 1] > upper[i - 1]:
            upper[i] = ub[i]
        else:
            upper[i] = upper[i - 1]

        if lb[i] > lower[i - 1] or c[i - 1] < lower[i - 1]:
            lower[i] = lb[i]
        else:
            lower[i] = lower[i - 1]

        if st[i - 1] == upper[i - 1]:
            direction[i] = -1 if c[i] <= upper[i] else 1
        else:
            direction[i] = 1 if c[i] >= lower[i] else -1

        st[i] = lower[i] if direction[i] == 1 else upper[i]

    return pd.Series(st, index=close.index), pd.Series(direction, index=close.index)


# ============================================================================
#  ANALİZ
# ============================================================================
def _analyze_one(symbol: str, df: pd.DataFrame):
    """Tek hisse için kesişim analizi. None = koşul sağlanmadı / veri yetersiz."""
    try:
        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = df.columns.get_level_values(0)

        if "Close" not in df.columns or "High" not in df.columns or "Low" not in df.columns:
            return None

        close = pd.to_numeric(df["Close"], errors="coerce").dropna()
        high = pd.to_numeric(df["High"], errors="coerce").reindex(close.index)
        low = pd.to_numeric(df["Low"], errors="coerce").reindex(close.index)

        idx = close.index[close.notna() & high.notna() & low.notna()]
        if len(idx) < 410:                       # LSMA(350) için yeterli geçmiş gerek
            return None

        close = close.loc[idx]; high = high.loc[idx]; low = low.loc[idx]

        lsma = compute_lsma(high, length=350, offset=60)
        st, _direc = compute_supertrend(high, low, close, length=25, factor=1.0)

        if pd.isna(lsma.iloc[-1]) or pd.isna(st.iloc[-1]):
            return None
        if st.iloc[-1] <= lsma.iloc[-1]:        # şu an yeşil sarının ÜSTÜNDE değil
            return None

        # En güncel yukarı kesişimi bul (geriye yürü)
        diff = (st - lsma).values
        cross_idx = None
        for i in range(len(diff) - 1, 0, -1):
            d1, d0 = diff[i], diff[i - 1]
            if np.isnan(d1) or np.isnan(d0):
                break
            if d1 > 0 and d0 <= 0:
                cross_idx = i
                break
        if cross_idx is None:
            return None

        cross_close = float(close.iloc[cross_idx])
        cur_close = float(close.iloc[-1])
        if cross_close <= 0:
            return None

        pct = (cur_close - cross_close) / cross_close * 100.0
        if pct < 0:
            return None                          # güvenlik: kesişimden bu yana düşmüş

        if pct < 10:
            category = "YENİ"
        elif pct < 20:
            category = "ORTA"
        else:
            category = "YÜKSEK"

        days_since = int((close.index[-1] - close.index[cross_idx]).days)

        return {
            "symbol": symbol,
            "cross_date": close.index[cross_idx].strftime("%Y-%m-%d"),
            "cross_price": round(cross_close, 4),
            "current_price": round(cur_close, 4),
            "pct_change": round(float(pct), 2),
            "category": category,
            "days_since_cross": days_since,
            "lsma": round(float(lsma.iloc[-1]), 4),
            "supertrend": round(float(st.iloc[-1]), 4),
        }
    except Exception as e:
        log.warning("analyze_one(%s) failed: %s", symbol, e)
        return None


def run_full_scan():
    """Tüm sembolleri batch'ler halinde tara."""
    if not HAS_YF:
        with _lock:
            _cache["error"] = "yfinance yüklü değil. requirements.txt'e ekle: yfinance"
            _cache["scanning"] = False
        return

    with _lock:
        if _cache["scanning"]:
            return
        _cache["scanning"] = True
        _cache["progress"] = 0
        _cache["total"] = len(_symbols)
        _cache["error"] = None

    out = []
    BATCH = 30

    try:
        for batch_start in range(0, len(_symbols), BATCH):
            batch = _symbols[batch_start:batch_start + BATCH]
            tickers = " ".join([s + ".IS" for s in batch])

            try:
                bulk = yf.download(
                    tickers, period="2y", interval="1d",
                    progress=False, auto_adjust=True,
                    group_by="ticker", threads=True,
                )
            except Exception as e:
                log.warning("Batch indirme hatası (%s...): %s", batch[0], e)
                with _lock:
                    _cache["progress"] = min(batch_start + BATCH, len(_symbols))
                continue

            for sym in batch:
                ticker = sym + ".IS"
                try:
                    if isinstance(bulk.columns, pd.MultiIndex):
                        if ticker not in bulk.columns.get_level_values(0):
                            continue
                        sub = bulk[ticker]
                    else:
                        # tek sembol indirildiyse multi-index olmayabilir
                        sub = bulk
                    r = _analyze_one(sym, sub)
                    if r:
                        out.append(r)
                except Exception as e:
                    log.warning("%s parse hatası: %s", sym, e)

            with _lock:
                _cache["progress"] = min(batch_start + BATCH, len(_symbols))

        # Sıralama: YENİ → ORTA → YÜKSEK içinde %'ye göre artan/azalan
        cat_order = {"YENİ": 0, "ORTA": 1, "YÜKSEK": 2}
        out.sort(key=lambda x: (cat_order[x["category"]], -x["pct_change"]))

        with _lock:
            _cache["data"] = out
            _cache["last_updated"] = datetime.now().isoformat(timespec="seconds")

    except Exception as e:
        log.exception("run_full_scan failed")
        with _lock:
            _cache["error"] = str(e)

    finally:
        with _lock:
            _cache["scanning"] = False


# ============================================================================
#  ENDPOINTS
# ============================================================================
@router.get("/api/scan")
def api_scan(background: BackgroundTasks, refresh: bool = False):
    with _lock:
        empty = _cache["data"] is None
        is_scanning = _cache["scanning"]

    if (refresh or empty) and not is_scanning:
        background.add_task(run_full_scan)

    with _lock:
        return {
            "last_updated": _cache["last_updated"],
            "scanning": _cache["scanning"],
            "progress": _cache["progress"],
            "total": _cache["total"],
            "error": _cache["error"],
            "count": len(_cache["data"]) if _cache["data"] else 0,
            "results": _cache["data"] or [],
        }


@router.get("/api/status")
def api_status():
    with _lock:
        return {
            "last_updated": _cache["last_updated"],
            "scanning": _cache["scanning"],
            "progress": _cache["progress"],
            "total": _cache["total"],
            "has_data": _cache["data"] is not None,
            "error": _cache["error"],
            "symbol_count": len(_symbols),
        }


@router.get("/", response_class=HTMLResponse)
def page():
    return HTML_PAGE


# ============================================================================
#  HTML SAYFA  (var-only JS, XHR, template-literal yok — mobil uyumlu)
# ============================================================================
HTML_PAGE = r"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>🟢 Supertrend × LSMA · Vortex-BIST</title>
<style>
:root{--bg:#0a0a0a;--card:#121212;--bd:#1f1f1f;--bd2:#2a2a2a;
      --green:#7ed321;--green2:#1a3a1a;--yellow:#f5c542;--red:#e57373;
      --teal:#42d49c;--mut:#888;--txt:#e8e8e8;--dim:#aaa}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--txt);
     font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
     margin:0;padding:10px 8px 24px;letter-spacing:.01em}
h1{font-size:15px;margin:0 0 8px;color:var(--green);font-weight:700;letter-spacing:.05em}
h1 small{color:var(--mut);font-weight:500;letter-spacing:0;font-size:11px;display:block;margin-top:2px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;
      padding:10px;margin-bottom:8px}
.btn{background:var(--green2);color:var(--green);border:1px solid #2a5a2a;
     border-radius:6px;padding:9px 14px;font:600 13px/1 inherit;
     letter-spacing:.04em;cursor:pointer;margin-right:6px;outline:none}
.btn:active{background:#2a5a2a;transform:translateY(1px)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-sec{background:#181818;color:var(--dim);border-color:var(--bd2)}
.info{color:var(--mut);font-size:12px;margin-top:8px;min-height:14px}
.err{color:var(--red);font-size:12px;margin-top:6px}
.tabs{display:flex;gap:4px;margin-bottom:8px}
.tab{flex:1;background:var(--card);color:var(--mut);border:1px solid var(--bd);
     border-radius:7px;padding:9px 4px;text-align:center;font:600 12px/1.3 inherit;
     cursor:pointer;transition:all .15s}
.tab:active{transform:scale(.97)}
.tab.on{background:var(--green2);color:var(--green);border-color:#2a5a2a}
.tab .n{display:block;font-size:11px;color:var(--mut);font-weight:400;margin-top:2px}
.tab.on .n{color:var(--green)}
.legend{font-size:10.5px;color:var(--mut);margin:6px 2px;line-height:1.5}
.legend b{color:var(--txt);font-weight:600}
table{width:100%;border-collapse:collapse;font-size:12.5px}
thead{position:sticky;top:0;z-index:2}
th{background:#161616;color:var(--dim);padding:7px 4px;text-align:left;
   border-bottom:1px solid var(--bd2);font:600 11px/1.2 inherit;
   text-transform:uppercase;letter-spacing:.06em}
th.r,td.r{text-align:right}
td{padding:8px 4px;border-bottom:1px solid #161616;vertical-align:middle}
tr:active td{background:#101010}
.sym{color:var(--green);font-weight:700;letter-spacing:.04em}
.sym a{color:inherit;text-decoration:none}
.sym a:active{text-decoration:underline}
.cat{display:inline-block;padding:2px 7px;border-radius:11px;font-size:10.5px;
     font-weight:700;letter-spacing:.05em}
.cat-YENI {background:rgba(66,212,156,.14); color:var(--teal); border:1px solid rgba(66,212,156,.3)}
.cat-ORTA {background:rgba(245,197,66,.14); color:var(--yellow);border:1px solid rgba(245,197,66,.3)}
.cat-YUKSEK{background:rgba(229,115,115,.14);color:var(--red);  border:1px solid rgba(229,115,115,.3)}
.pct{color:var(--green);font-weight:700}
.dim{color:var(--mut);font-size:11px}
.empty{color:#555;text-align:center;padding:36px 8px;font-size:13px}
.bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.prog{flex:1;height:4px;background:#181818;border-radius:2px;overflow:hidden;
      margin-top:6px;display:none}
.prog.on{display:block}
.prog-fill{height:100%;background:var(--green);transition:width .3s}
.pulse{display:inline-block;width:7px;height:7px;border-radius:50%;
       background:var(--green);animation:p 1.1s infinite;margin-right:5px;
       vertical-align:middle}
@keyframes p{0%,100%{opacity:.25;transform:scale(.85)}50%{opacity:1;transform:scale(1.15)}}
.foot{color:#444;font-size:10px;text-align:center;margin-top:12px}
</style>
</head>
<body>

<h1>🟢 SUPERTREND × LSMA
  <small>Yeşil çizgi sarı çizginin üzerinde · günlük · kesişim sınıflandırması</small>
</h1>

<div class="card">
  <div class="bar">
    <button class="btn" id="btnScan">▶ TARA</button>
    <button class="btn btn-sec" id="btnRefresh">↻ YENİLE</button>
  </div>
  <div class="prog" id="prog"><div class="prog-fill" id="progFill" style="width:0%"></div></div>
  <div class="info" id="info">Hazırlanıyor...</div>
  <div class="err" id="err"></div>
</div>

<div class="tabs">
  <div class="tab on" data-cat="ALL">TÜMÜ<span class="n" id="cAll">0</span></div>
  <div class="tab" data-cat="YENI">🆕 YENİ<span class="n" id="cYeni">0</span></div>
  <div class="tab" data-cat="ORTA">⚡ ORTA<span class="n" id="cOrta">0</span></div>
  <div class="tab" data-cat="YUKSEK">🔥 YÜKSEK<span class="n" id="cYuksek">0</span></div>
</div>

<div class="legend">
  <b>YENİ</b>: kesişimden bu yana 0–10% · <b>ORTA</b>: 10–20% · <b>YÜKSEK</b>: 20%+
</div>

<div class="card" style="padding:0;overflow:hidden">
<table>
  <thead><tr>
    <th>HİSSE</th>
    <th>KESİŞİM</th>
    <th class="r">GÜN</th>
    <th class="r">FİYAT</th>
    <th class="r">%</th>
    <th>SINIF</th>
  </tr></thead>
  <tbody id="rows">
    <tr><td colspan="6" class="empty">Tarama için ▶ TARA basın.</td></tr>
  </tbody>
</table>
</div>

<div class="foot">Vortex-BIST · Supertrend(25,1) × LSMA(high,350,60) · v1.0</div>

<script>
var DATA=[]; var FILTER='ALL'; var pollT=null; var lastFetch=0;

function $(id){return document.getElementById(id);}
function fmt(n,d){if(n==null||isNaN(n))return '-';return Number(n).toFixed(d==null?2:d);}

function xhrGet(url, cb){
  var x=new XMLHttpRequest();
  x.open('GET', url, true);
  x.timeout=30000;
  x.onreadystatechange=function(){
    if(x.readyState!==4) return;
    if(x.status>=200 && x.status<300){
      try{cb(JSON.parse(x.responseText));}catch(e){cb(null);}
    } else { cb(null); }
  };
  x.ontimeout=function(){cb(null);};
  x.send();
}

function catKey(c){
  if(c==='YENİ') return 'YENI';
  if(c==='YÜKSEK') return 'YUKSEK';
  return 'ORTA';
}

function render(){
  var rows=$('rows'); var list;
  if(FILTER==='ALL'){ list=DATA; }
  else { list=[]; for(var i=0;i<DATA.length;i++){ if(catKey(DATA[i].category)===FILTER) list.push(DATA[i]); } }

  if(!list.length){
    rows.innerHTML='<tr><td colspan="6" class="empty">Eşleşen hisse yok.</td></tr>';
    return;
  }
  var h='', r, k, tvUrl;
  for(var j=0;j<list.length;j++){
    r=list[j]; k=catKey(r.category);
    tvUrl='https://tr.tradingview.com/chart/?symbol=BIST%3A'+r.symbol;
    h+='<tr>';
    h+='<td class="sym"><a href="'+tvUrl+'" target="_blank" rel="noopener">'+r.symbol+'</a></td>';
    h+='<td><div>'+r.cross_date+'</div><div class="dim">'+fmt(r.cross_price)+' ₺</div></td>';
    h+='<td class="r dim">'+r.days_since_cross+'</td>';
    h+='<td class="r">'+fmt(r.current_price)+'</td>';
    h+='<td class="r pct">+'+fmt(r.pct_change)+'%</td>';
    h+='<td><span class="cat cat-'+k+'">'+r.category+'</span></td>';
    h+='</tr>';
  }
  rows.innerHTML=h;
}

function updateCounts(){
  var a=DATA.length,y=0,o=0,k=0,c;
  for(var i=0;i<DATA.length;i++){
    c=DATA[i].category;
    if(c==='YENİ')y++;
    else if(c==='ORTA')o++;
    else if(c==='YÜKSEK')k++;
  }
  $('cAll').textContent=a;
  $('cYeni').textContent=y;
  $('cOrta').textContent=o;
  $('cYuksek').textContent=k;
}

function setProg(p,t){
  var pe=$('prog'), pf=$('progFill');
  if(t>0){
    pe.classList.add('on');
    pf.style.width=((p/t)*100).toFixed(0)+'%';
  } else { pe.classList.remove('on'); }
}

function statusPoll(){
  xhrGet('/crossover/api/status', function(d){
    if(!d){ $('info').textContent='⚠ Bağlantı hatası — tekrar deneyin.'; return; }
    if(d.error){ $('err').textContent=d.error; }
    else { $('err').textContent=''; }

    if(d.scanning){
      $('info').innerHTML='<span class="pulse"></span> Taranıyor… '+d.progress+' / '+d.total;
      setProg(d.progress, d.total);
      pollT=setTimeout(statusPoll, 2500);
      $('btnScan').disabled=true;
    } else {
      if(pollT){ clearTimeout(pollT); pollT=null; }
      $('btnScan').disabled=false;
      setProg(0,0);
      if(d.has_data){ fetchResults(false); }
      else { $('info').textContent='Veri yok. ▶ TARA basın.'; }
    }
  });
}

function fetchResults(force){
  if(Date.now()-lastFetch<700) return;
  lastFetch=Date.now();

  $('info').innerHTML='<span class="pulse"></span> Yükleniyor…';
  var url='/crossover/api/scan' + (force?'?refresh=true':'');
  xhrGet(url, function(d){
    if(!d){ $('info').textContent='⚠ Bağlantı hatası.'; return; }
    if(d.error){ $('err').textContent=d.error; } else { $('err').textContent=''; }

    if(d.scanning){
      $('info').innerHTML='<span class="pulse"></span> Tarama başlatıldı… '+d.progress+' / '+d.total;
      setProg(d.progress, d.total);
      $('btnScan').disabled=true;
      pollT=setTimeout(statusPoll, 2500);
      return;
    }
    DATA=d.results||[];
    updateCounts();
    render();
    var when = d.last_updated ? (' · son: '+d.last_updated.replace('T',' ')) : '';
    $('info').textContent = (DATA.length ? ('Toplam '+DATA.length+' hisse') : 'Hiç eşleşme yok') + when;
  });
}

var tabs=document.querySelectorAll('.tab');
for(var ti=0;ti<tabs.length;ti++){
  (function(t){
    t.addEventListener('click', function(){
      for(var j=0;j<tabs.length;j++){ tabs[j].classList.remove('on'); }
      t.classList.add('on');
      FILTER=t.getAttribute('data-cat');
      render();
    });
  })(tabs[ti]);
}

$('btnScan').addEventListener('click', function(){ fetchResults(true); });
$('btnRefresh').addEventListener('click', function(){ fetchResults(false); });

statusPoll();
</script>
</body>
</html>
"""
