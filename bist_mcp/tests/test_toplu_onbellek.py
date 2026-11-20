"""Toplu fiyat indirmesinin onbellegi ve es zamanli tekillestirmesi.

Olculdu (GENKM, detayli_analiz): anlik_fiyat, finansal_oranlar ve
temettu_gecmisi ucu de fiyat.toplu cagiriyor. Onbellek olmadigi icin AYNI
indirme uc kez PARALEL yapiliyordu; biri bos donunce temettu "0,00" gibi
gorunuyordu (eski kodda sessiz sifir, yenisinde "bilinmiyor").
"""

import asyncio

import pytest

from bist_mcp.kaynaklar.fiyat import FiyatKaynak
from bist_mcp.onbellek import Onbellek

VERI = {"GENKM": {"fiyat": 11.15, "temettu_12ay": 0.2053, "tarih": "2026-09-04"}}


def _kaynak(tmp_path):
    kaynak = FiyatKaynak(Onbellek(tmp_path / "o.db"))
    sayac = {"indirme": 0}

    async def sahte_indir(kodlar):
        sayac["indirme"] += 1
        await asyncio.sleep(0.05)
        return dict(VERI)

    kaynak._toplu_indir = sahte_indir
    return kaynak, sayac


@pytest.mark.asyncio
async def test_ayni_istek_ikinci_kez_indirilmez(tmp_path):
    kaynak, sayac = _kaynak(tmp_path)
    assert await kaynak.toplu(["GENKM"]) == VERI
    assert await kaynak.toplu(["GENKM"]) == VERI
    assert sayac["indirme"] == 1, "ikinci cagri onbellekten gelmeliydi"


@pytest.mark.asyncio
async def test_es_zamanli_ayni_istek_tek_indirme_yapar(tmp_path):
    """detayli_analiz'in deseni: uc arac ayni anda ayni kodu istiyor."""
    kaynak, sayac = _kaynak(tmp_path)
    sonuclar = await asyncio.gather(*(kaynak.toplu(["GENKM"]) for _ in range(3)))
    assert all(s == VERI for s in sonuclar)
    assert sayac["indirme"] == 1, f"{sayac['indirme']} paralel indirme yapildi"


@pytest.mark.asyncio
async def test_farkli_kodlar_ayri_indirilir(tmp_path):
    kaynak, sayac = _kaynak(tmp_path)
    await kaynak.toplu(["GENKM"])
    await kaynak.toplu(["THYAO"])
    assert sayac["indirme"] == 2


@pytest.mark.asyncio
async def test_bos_sonuc_onbellege_yazilmaz(tmp_path):
    """Gecici indirme hatasi 60 saniye boyunca kalici "veri yok" olurdu."""
    kaynak, sayac = _kaynak(tmp_path)

    async def bos(kodlar):
        sayac["indirme"] += 1
        return {}

    dolu = kaynak._toplu_indir
    kaynak._toplu_indir = bos
    assert await kaynak.toplu(["GENKM"]) == {}

    kaynak._toplu_indir = dolu
    assert await kaynak.toplu(["GENKM"]) == VERI, "bos sonuc onbellekte kalmis"
