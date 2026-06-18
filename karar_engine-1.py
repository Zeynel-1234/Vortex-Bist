"""
═══════════════════════════════════════════════════════════════
karar_engine.py — Faz 4: NİHAİ KARAR (Birleşik Karar Motoru) v1.0
───────────────────────────────────────────────────────────────
Tüm katmanları TEK bir şeffaf kararda birleştirir:

  Kapı 0  REJİM        (RISK_ON / NÖTR / RISK_OFF)  → çarpan
  Kapı 1  SİNYAL       (nvs/bkm/gs/gunluk/kesisim birleşimi)
  Kapı 2  GÖRECELİ GÜÇ (RS vs XU100 yüzdelik)
  Kapı 3  LİKİDİTE     (işlenemezse SERT VETO)
  +       ÖĞRENİLMİŞ AĞIRLIK (olgunlaşınca sinyalleri kanıta göre tartar)
  +       İŞLEM PLANI  (ATR stop/hedef/lot — yalnız tekil karar görünümünde)

DÜRÜST TASARIM:
  Ağırlıklar (ÖĞREN) henüz olgun değilse sistem onları beklemez —
  geçici olarak sinyalleri EŞİT tartar ve bunu açıkça belirtir.
  Kanıt biriktikçe (forward isabet) otomatik olarak öğrenilmiş
  ağırlığa geçer. Likidite SERT filtredir: illikit hisse, skoru ne
  olursa olsun "KAÇIN".

SKOR:  final = (0.5·sinyal_güven + 0.5·RS) × rejim_çarpanı × 100
KARAR: ≥65 GÜÇLÜ AL · ≥45 AL · ≥25 İZLE · <25 KAÇIN · illikit → KAÇIN

ENDPOINTLER:
  /karar/{symbol}  → tek hisse, tam döküm + işlem planı
  /karar/top       → bugünün en iyi adayları (sıralı)
  /karar/dashboard → görsel panel

KURULUM (main.py'a 2 satır):
    from karar_engine import install_karar
    install_karar(app)
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
import json

try:
    import requests
except Exception:
    requests = None

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


BASE_URL = os.environ.get("OGREN_BASE_URL", "").rstrip("/")
CORE_SIGNALS = ["nvs", "bkm", "gs", "gunluk", "kesisim"]
REGIME_MULT = {"RISK_ON": 1.0, "NOTR": 0.55, "RISK_OFF": 0.15}
W_SIGNAL = 0.5      # sinyal birleşimi ağırlığı
W_RS = 0.5          # göreceli güç ağırlığı
LEARN_MIN = 0.05    # öğrenilmiş güven bunun altındaysa geçici eşit tartıma düş


def _self_base():
    if BASE_URL:
        return BASE_URL
    return "http://127.0.0.1:" + str(os.environ.get("PORT", "10000"))


def _get_json(url, timeout=120):
    try:
        if requests is not None:
            r = requests.get(url, timeout=timeout)
            return r.json() if 200 <= r.status_code < 300 else None
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "karar/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _active_signals(scan_row, in_crossover):
    out = []
    if scan_row:
        if "AL" in (scan_row.get("nvs_label") or "").upper():
            out.append("nvs")
        if (scan_row.get("bkm") or 0) >= 70:
            out.append("bkm")
        if (scan_row.get("guven_skoru") or 0) >= 45:
            out.append("gs")
        if (scan_row.get("gunluk_degisim") or 0) > 0:
            out.append("gunluk")
    if in_crossover:
        out.append("kesisim")
    return out


def decide(symbol, active_signals, learned_conf, weights_detail,
           regime, rs_score, tradable) -> dict:
    """Saf karar birleştiricisi (test edilebilir).
    active_signals: aktif tekil sinyaller (nvs/bkm/...).
    learned_conf: ÖĞREN'in öğrenilmiş güveni (aktif sinyal ağırlıkları toplamı, 0-1).
    regime: RISK_ON/NOTR/RISK_OFF.  rs_score: 0-100 veya None.  tradable: bool/None.
    """
    core = [s for s in active_signals if s in CORE_SIGNALS]

    # Sinyal güven bileşeni (0-1): öğrenilmiş olgunsa onu, değilse geçici eşit tartım
    if learned_conf is not None and learned_conf >= LEARN_MIN:
        conf_sig = min(1.0, learned_conf)
        sig_mode = "öğrenilmiş ağırlık"
    else:
        conf_sig = len(core) / float(len(CORE_SIGNALS))   # eşit: kaç sinyal aktif / 5
        sig_mode = "geçici eşit (ağırlıklar öğreniliyor)"

    rs_comp = (rs_score / 100.0) if isinstance(rs_score, (int, float)) else 0.0
    rs_comp = max(0.0, min(1.0, rs_comp))

    raw = W_SIGNAL * conf_sig + W_RS * rs_comp            # 0-1
    mult = REGIME_MULT.get(regime, 0.5)
    final = round(raw * mult * 100, 1)

    # Likidite SERT veto
    if tradable is False:
        verdict = "KAÇIN"
        reason = "İllikit/işlenemez (manipülasyon & kayma riski)"
    else:
        if final >= 65:
            verdict = "GÜÇLÜ AL"
        elif final >= 45:
            verdict = "AL"
        elif final >= 25:
            verdict = "İZLE"
        else:
            verdict = "KAÇIN"
        reason = "rejim=%s · sinyal=%d/5 · RS=%s" % (
            regime, len(core), ("%.0f" % rs_score) if rs_score is not None else "—")

    return {
        "symbol": symbol,
        "karar": verdict,
        "skor": final,
        "neden": reason,
        "rejim": regime,
        "rejim_carpani": mult,
        "aktif_sinyaller": core,
        "sinyal_guven": round(conf_sig, 3),
        "sinyal_mod": sig_mode,
        "rs_score": rs_score,
        "rs_bilesen": round(rs_comp, 3),
        "tradable": tradable,
        "ham_skor_0_1": round(raw, 3),
    }


# ════════════════════════════════════════════════════════════════
def _gather_single(symbol):
    base = _self_base()
    symbol = symbol.upper().strip()
    # ÖĞREN skor (aktif sinyaller + öğrenilmiş güven + rejim)
    osc = _get_json(base + "/ogren/score/" + symbol) or {}
    active = osc.get("active_signals", [])
    learned = osc.get("raw_confidence")
    regime = osc.get("regime")
    if not regime:
        regime = (_get_json(base + "/ogren/regime") or {}).get("regime", "NOTR")
    # RS + likidite
    rs = _get_json(base + "/rs/" + symbol) or {}
    rs_score = rs.get("rs_score")
    tradable = rs.get("tradable")
    return active, learned, regime, rs_score, tradable


karar_router = APIRouter(prefix="/karar", tags=["nihai-karar"])


@karar_router.get("/top")
def karar_top(limit: int = 30):
    """Bugünün en iyi adayları — tüm katmanları birleştirip sıralar (işlem planı yok)."""
    base = _self_base()
    scan = _get_json(base + "/scan?limit=900") or {}
    scan_rows = scan.get("results") or scan.get("rows") or []
    scan_map = {}
    for r in scan_rows:
        s = (r.get("sembol") or r.get("symbol") or "").upper()
        if s:
            scan_map[s] = r
    xo = _get_json(base + "/crossover/api/scan") or {}
    xset = set((r.get("symbol") or "").upper() for r in (xo.get("results") or []))
    rs = _get_json(base + "/rs/rank?limit=900&tradable_only=false") or {}
    rs_map = {r["symbol"]: r for r in rs.get("rows", [])}
    wjson = _get_json(base + "/ogren/weights") or {}
    weights = wjson.get("weights", {})
    regime = (_get_json(base + "/ogren/regime") or {}).get("regime", "NOTR")

    # aday evreni: scan ∪ crossover
    syms = set(scan_map.keys()) | xset
    out = []
    for sym in syms:
        row = scan_map.get(sym)
        active = _active_signals(row, sym in xset)
        if not active:
            continue
        learned = 0.0
        for s in active:
            learned += (weights.get(s, {}) or {}).get("weight", 0.0)
        rsr = rs_map.get(sym, {})
        d = decide(sym, active, learned, weights, regime,
                   rsr.get("rs_score"), rsr.get("tradable"))
        out.append(d)
    out.sort(key=lambda d: d["skor"], reverse=True)
    return {"regime": regime, "count": len(out), "rows": out[:limit]}


@karar_router.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    data = karar_top(40)
    regime = data.get("regime", "—")
    rc = {"RISK_ON": "#7ed321", "NOTR": "#f5c542", "RISK_OFF": "#ff5a5a"}.get(regime, "#888")
    vcol = {"GÜÇLÜ AL": "#7ed321", "AL": "#a6d860", "İZLE": "#f5c542", "KAÇIN": "#ff5a5a"}
    tr = ""
    for r in data.get("rows", []):
        c = vcol.get(r["karar"], "#888")
        tr += ("<tr><td><b>%s</b></td><td style='color:%s;font-weight:700'>%s</td>"
               "<td>%.0f</td><td>%s</td><td>%s</td><td>%s</td></tr>") % (
            r["symbol"], c, r["karar"], r["skor"],
            ("%.0f" % r["rs_score"]) if r.get("rs_score") is not None else "—",
            len(r.get("aktif_sinyaller", [])),
            "✓" if r.get("tradable") else "✗")
    html = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'><title>NİHAİ KARAR</title><style>
body{background:#050505;color:#ddd;font:14px system-ui;margin:0;padding:16px}
h1{color:#7ed321;font-size:18px}table{width:100%%;border-collapse:collapse;font-size:13px}
td,th{padding:7px 8px;border-bottom:1px solid #161616;text-align:left}th{color:#7ed321}
.reg{font:700 20px system-ui;color:%s}.muted{color:#777;font-size:12px}
</style></head><body>
<h1>🧭 NİHAİ KARAR · Birleşik Motor</h1>
<div class=muted>Rejim + Sinyal + Göreceli Güç + Likidite + (öğrenilmiş ağırlık)</div>
<div class=reg>Piyasa: %s</div>
<table><tr><th>Sembol</th><th>Karar</th><th>Skor</th><th>RS</th><th>Sinyal</th><th>Likit</th></tr>%s</table>
<div class=muted style='margin-top:12px'>Skor = (0.5·sinyal + 0.5·RS) × rejim. İllikit = otomatik KAÇIN.
Ağırlıklar olgunlaşınca sinyaller kanıta göre tartılır. Tek hisse: /karar/SEMBOL</div>
</body></html>""" % (rc, regime, tr or "<tr><td colspan=6 class=muted>Veri yok — /scan, /rs/refresh, /ogren/run çalışmış olmalı</td></tr>")
    return HTMLResponse(html)


@karar_router.get("/{symbol}")
def karar_one(symbol: str, risk: float = 1.0, capital: float = 100000.0):
    active, learned, regime, rs_score, tradable = _gather_single(symbol)
    weights = (_get_json(_self_base() + "/ogren/weights") or {}).get("weights", {})
    d = decide(symbol.upper().strip(), active, learned, weights,
               regime, rs_score, tradable)
    plan = None
    if d["karar"] in ("GÜÇLÜ AL", "AL", "İZLE"):
        plan = _get_json(_self_base() + "/plan/" + symbol.upper().strip() +
                         "?risk=%s&capital=%s&use_regime=true" % (risk, capital))
    d["islem_plani"] = plan
    return d


def install_karar(app) -> None:
    app.include_router(karar_router)
