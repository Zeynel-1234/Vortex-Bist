import numpy as np
import pandas as pd
from fastapi import APIRouter
from indicators import fetch_ohlc  # fonksiyon başka dosyadaysa burayı değiştir

router = APIRouter()
FEATS = ["r1", "r5", "hacim", "ema_uzak", "rsi", "atr_yuzde"]


def _features(df):
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    d = c.diff()
    up = d.clip(lower=0).rolling(14).mean()
    dn = (-d.clip(upper=0)).rolling(14).mean().replace(0, np.nan)
    out = pd.DataFrame(index=df.index)
    out["r1"] = np.log(c).diff()
    out["r5"] = np.log(c).diff(5)
    out["hacim"] = np.log((v + 1) / (v.rolling(20).mean() + 1))
    out["ema_uzak"] = (c - c.ewm(span=10, adjust=False).mean()) / atr
    out["rsi"] = (100 - 100 / (1 + up / dn)) / 100 - 0.5
    out["atr_yuzde"] = atr / c
    out["sonraki"] = c.shift(-1) / c - 1
    return out


def _sig(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def _fit(X, y, lam=1.0):
    Xb = np.c_[np.ones(len(X)), X]
    w = np.zeros(Xb.shape[1])
    pen = np.eye(len(w)) * lam
    pen[0, 0] = 0
    for _ in range(50):
        p = _sig(Xb @ w)
        g = Xb.T @ (p - y) + pen @ w
        H = Xb.T @ (Xb * (p * (1 - p))[:, None]) + pen
        w -= np.linalg.solve(H, g)
    return w


def _prob(w, X):
    return _sig(np.c_[np.ones(len(X)), X] @ w)


def _auc(y, p):
    r = pd.Series(p).rank().values
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return 0.5
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


@router.get("/model/{sembol}")
def model(sembol: str):
    df = fetch_ohlc(sembol, period="max")
    if df is None:
        return {"hata": "Veri çekilemedi"}
    f = _features(df).replace([np.inf, -np.inf], np.nan)
    son_satir = f.iloc[[-1]][FEATS].dropna()
    f = f.dropna()
    if len(f) < 300:
        return {"hata": f"Yetersiz veri: {len(f)} gün"}

    k = int(len(f) * 0.7)
    tr, te = f.iloc[:k], f.iloc[k:]
    mu, sd = tr[FEATS].mean(), tr[FEATS].std().replace(0, 1)
    Xtr = ((tr[FEATS] - mu) / sd).values
    Xte = ((te[FEATS] - mu) / sd).values
    ytr = (tr["sonraki"] > 0).astype(float).values
    yte = (te["sonraki"] > 0).astype(float).values

    w = _fit(Xtr, ytr)
    pte = _prob(w, Xte)

    taban = float(max(yte.mean(), 1 - yte.mean()))
    isabet = float(((pte > 0.5) == (yte == 1)).mean())
    z = (isabet - taban) / np.sqrt(taban * (1 - taban) / len(yte))
    auc = _auc(yte, pte)
    sec = pte > 0.55
    ort_sec = float(te["sonraki"][sec].mean() * 100) if sec.sum() >= 20 else None
    ort_tum = float(te["sonraki"].mean() * 100)
    var_mi = bool(z > 1.96 and auc > 0.53)

    ort_yuk = float(tr["sonraki"][tr["sonraki"] > 0].mean())
    ort_dus = float(-tr["sonraki"][tr["sonraki"] <= 0].mean())
    sonuc = {
        "sembol": sembol.upper(),
        "gun_sayisi": len(f),
        "ilk_tarih": str(f.index[0])[:10],
        "test_gun": len(te),
        "katsayilar": {n: round(float(x), 3) for n, x in zip(["b0"] + FEATS, w)},
        "test_isabet": round(isabet, 4),
        "test_taban_oran": round(taban, 4),
        "z_skoru": round(float(z), 2),
        "test_auc": round(auc, 4),
        "p>0.55_ort_getiri_%": ort_sec,
        "tum_gunler_ort_getiri_%": round(ort_tum, 3),
        "EDGE_VAR_MI": var_mi,
    }
    if len(son_satir):
        p = float(_prob(w, ((son_satir - mu) / sd).values)[0])
        sonuc["yarin_yukselis_olasiligi"] = round(p, 4)
        sonuc["beklenen_getiri_%"] = round((p * ort_yuk - (1 - p) * ort_dus) * 100, 3)
        sonuc["not"] = ("Test dilimi anlamlı üstünlük gösterdi."
                        if var_mi else
                        "Test dilimi üstünlük GÖSTERMEDİ, bu tahmine güvenme.")
    return sonuc
