"""Teknik analiz gostergeleri.

Girdi her zaman kapanis listesi ya da mum listesi; bu modul aga cikmaz.
"""

import pandas as pd


def rsi(kapanislar: list[float], periyot: int = 14) -> float | None:
    if len(kapanislar) < periyot + 1:
        return None

    seri = pd.Series(kapanislar, dtype="float64")
    fark = seri.diff().dropna()
    kazanc = fark.clip(lower=0).ewm(alpha=1 / periyot, adjust=False).mean()
    kayip = (-fark.clip(upper=0)).ewm(alpha=1 / periyot, adjust=False).mean()

    son_kayip = float(kayip.iloc[-1])
    if son_kayip == 0:
        return 100.0

    oran = float(kazanc.iloc[-1]) / son_kayip
    return round(100 - 100 / (1 + oran), 2)


def hareketli_ortalama(kapanislar: list[float], periyot: int) -> float | None:
    if len(kapanislar) < periyot:
        return None
    return round(sum(kapanislar[-periyot:]) / periyot, 2)


def macd(
    kapanislar: list[float], hizli: int = 12, yavas: int = 26, sinyal: int = 9
) -> dict | None:
    if len(kapanislar) < yavas + sinyal:
        return None

    seri = pd.Series(kapanislar, dtype="float64")
    macd_cizgisi = (
        seri.ewm(span=hizli, adjust=False).mean() - seri.ewm(span=yavas, adjust=False).mean()
    )
    sinyal_cizgisi = macd_cizgisi.ewm(span=sinyal, adjust=False).mean()

    return {
        "macd": round(float(macd_cizgisi.iloc[-1]), 4),
        "sinyal": round(float(sinyal_cizgisi.iloc[-1]), 4),
        "fark": round(float(macd_cizgisi.iloc[-1] - sinyal_cizgisi.iloc[-1]), 4),
    }


def destek_direnc(mumlar: list[dict]) -> dict:
    """Verilen pencerede en dusuk dip ve en yuksek tepe."""
    if not mumlar:
        return {"destek": None, "direnc": None}
    return {
        "destek": round(min(m["dusuk"] for m in mumlar), 2),
        "direnc": round(max(m["yuksek"] for m in mumlar), 2),
    }
