"""Doviz, altin ve emtia kurlari (yfinance).

Plandan sapma gerekcesi: bunlar once TCMB EVDS'e baglanmisti, ama EVDS API
anahtari gerektiriyor ve anahtar yoksa arac tamamen olu kaliyordu. Olculdu —
yfinance bu verileri anahtarsiz veriyor (USDTRY 48,4248 / EURTRY 56,2640 /
ons altin 4.429,80 USD). EVDS yalnizca enflasyon ve faiz icin kaldi
(bkz. tcmb.py); onlarin yfinance karsiligi yok.

Gram altin dogrudan bir sembol degil, hesaplanir:
    gram_TL = ons_USD * USDTRY / 31,1034768
"""

import asyncio

import yfinance as yf

from bist_mcp.onbellek import Onbellek

TROY_ONS_GRAM = 31.1034768
KUR_TTL = 300  # 5 dk

SEMBOLLER = {
    "usdtry": ("USDTRY=X", "USD/TRY"),
    "eurtry": ("EURTRY=X", "EUR/TRY"),
    "ons_altin": ("GC=F", "Ons altın (USD)"),
    "gumus": ("SI=F", "Ons gümüş (USD)"),
    "brent": ("BZ=F", "Brent petrol (USD)"),
}
# Hesaplanan varliklar; dogrudan sembolu yok.
TURETILEN = {"gram_altin": "Gram altın (TL)"}


def gecerli_varliklar() -> list[str]:
    return sorted([*SEMBOLLER, *TURETILEN])


def gram_altin_hesapla(ons_usd: float, usdtry: float) -> float:
    """Ons altin (USD) ve USD/TRY kurundan gram altin fiyati (TL)."""
    if ons_usd <= 0 or usdtry <= 0:
        raise ValueError("ons fiyati ve kur pozitif olmali")
    return ons_usd * usdtry / TROY_ONS_GRAM


class KurKaynak:
    def __init__(self, onbellek: Onbellek) -> None:
        self._onbellek = onbellek

    async def _son_fiyat(self, sembol: str) -> float | None:
        def _cek() -> float | None:
            veri = yf.Ticker(sembol).history(period="5d", interval="1d")
            if veri.empty:
                return None
            return float(veri["Close"].dropna().iloc[-1])

        return await asyncio.to_thread(_cek)

    async def kur(self, varlik: str) -> dict:
        ad = varlik.strip().lower()
        if ad not in SEMBOLLER and ad not in TURETILEN:
            return {
                "hata": f"gecersiz varlik: {varlik}. "
                f"Gecerli olanlar: {', '.join(gecerli_varliklar())}"
            }

        anahtar = f"kur:{ad}"
        onbellekli = self._onbellek.al(anahtar)
        if onbellekli is not None:
            return onbellekli

        if ad == "gram_altin":
            ons, usdtry = await asyncio.gather(
                self._son_fiyat(SEMBOLLER["ons_altin"][0]),
                self._son_fiyat(SEMBOLLER["usdtry"][0]),
            )
            if ons is None or usdtry is None:
                return {"hata": "gram altın için ons fiyatı veya USD/TRY kuru alınamadı."}
            sonuc = {
                "varlik": ad,
                "ad": TURETILEN[ad],
                "deger": round(gram_altin_hesapla(ons, usdtry), 2),
                "para_birimi": "TRY",
                "dayanak": {"ons_usd": round(ons, 2), "usdtry": round(usdtry, 4)},
            }
        else:
            sembol, baslik = SEMBOLLER[ad]
            deger = await self._son_fiyat(sembol)
            if deger is None:
                return {"hata": f"{varlik} için fiyat alınamadı."}
            sonuc = {
                "varlik": ad,
                "ad": baslik,
                "deger": round(deger, 4),
                "para_birimi": "TRY" if ad.endswith("try") else "USD",
            }

        self._onbellek.yaz(anahtar, sonuc, KUR_TTL)
        return sonuc
