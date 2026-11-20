"""Yahoo, seans verisi yayimlanmadan once fiyatsiz satir donuyor.

Olculdu (MEKAG, 08.09.2026 05:30):
    2026-09-04  Open 2.95  Close 2.97  Volume 4.480.048
    2026-09-07  Open NaN   Close NaN   Volume 5.153.270
Kod son satiri aldigi icin fiyat NaN oluyor, model de yanindaki 04.09
kapanisini alip 07.09 TARIHIYLE sunuyordu. Ayni satirlar teknik_analiz'e
sizinca RSI ve hareketli ortalamalar da NaN cikiyor.
"""

import math

import pandas as pd
import pytest

from bist_mcp.kaynaklar.fiyat import kapanisi_olan_satirlar


def _cerceve(kapanislar):
    gunler = pd.to_datetime([f"2026-09-{g:02d}" for g in range(1, len(kapanislar) + 1)])
    return pd.DataFrame(
        {
            "Open": kapanislar,
            "High": kapanislar,
            "Low": kapanislar,
            "Close": kapanislar,
            "Volume": [100] * len(kapanislar),
        },
        index=gunler,
    )


def test_kapanisi_bos_satir_atilir():
    kalan = kapanisi_olan_satirlar(_cerceve([2.95, 2.97, float("nan")]))
    assert len(kalan) == 2
    assert not any(math.isnan(x) for x in kalan["Close"])


def test_son_gecerli_satir_en_sonda_kalir():
    """anlik son satiri aliyor; filtreleme sirayi bozmamali."""
    kalan = kapanisi_olan_satirlar(_cerceve([2.95, 2.97, float("nan")]))
    assert kalan["Close"].iloc[-1] == 2.97
    assert str(kalan.index[-1])[:10] == "2026-09-02"


def test_dolu_cerceve_degismez():
    cerceve = _cerceve([2.95, 2.97])
    assert len(kapanisi_olan_satirlar(cerceve)) == 2


def test_bos_cerceve_cokmez():
    assert kapanisi_olan_satirlar(pd.DataFrame()).empty


def test_close_sutunu_yoksa_dokunulmaz():
    cerceve = pd.DataFrame({"Volume": [1, 2]})
    assert len(kapanisi_olan_satirlar(cerceve)) == 2


@pytest.mark.network
@pytest.mark.asyncio
async def test_anlik_nan_fiyat_dondurmez():
    """Kullanicinin gordugu hata: MEKAG icin fiyat NaN geliyordu."""
    from bist_mcp.kaynaklar.fiyat import FiyatKaynak
    from bist_mcp.onbellek import Onbellek

    sonuc = await FiyatKaynak(Onbellek(":memory:")).anlik("MEKAG")
    assert sonuc, "fiyat verisi gelmedi"
    assert not math.isnan(sonuc["fiyat"])
    assert not math.isnan(sonuc["onceki_kapanis"])
