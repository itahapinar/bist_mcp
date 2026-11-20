import asyncio

import pytest

from bist_mcp.hiz_sinir import HizSinirlayici


@pytest.mark.asyncio
async def test_es_zamanli_istekler_siraya_girer():
    """REGRESYON — kilitsiz surum es zamanlilikta hic sinirlamiyordu.

    Olculdu: 20 es zamanli istek 0,50 sn'de ates ediyordu (hepsi ilk
    saniyede). 630 hisselik toplu kurulumda bu, kaynak siteye yuzlerce
    es zamanli istek demek.
    """
    sinirlayici = HizSinirlayici(aralik_sn=0.05)
    anlar: list[float] = []

    async def istek():
        await sinirlayici.bekle()
        anlar.append(asyncio.get_event_loop().time())

    await asyncio.gather(*(istek() for _ in range(10)))

    anlar.sort()
    araliklar = [b - a for a, b in zip(anlar, anlar[1:])]
    assert len(araliklar) == 9
    assert all(a >= 0.04 for a in araliklar), f"istekler siraya girmedi: {araliklar}"


@pytest.mark.asyncio
async def test_toplam_sure_istek_sayisiyla_orantili():
    sinirlayici = HizSinirlayici(aralik_sn=0.05)
    basla = asyncio.get_event_loop().time()
    await asyncio.gather(*(sinirlayici.bekle() for _ in range(10)))
    gecen = asyncio.get_event_loop().time() - basla
    # 10 istek x 0,05 sn = ~0,45 sn (ilki beklemez)
    assert gecen >= 0.40, f"cok hizli bitti: {gecen:.3f} sn"


@pytest.mark.asyncio
async def test_ilk_istek_beklemez():
    sinirlayici = HizSinirlayici(aralik_sn=0.5)
    basla = asyncio.get_event_loop().time()
    await sinirlayici.bekle()
    assert asyncio.get_event_loop().time() - basla < 0.1


@pytest.mark.asyncio
async def test_arali_gecmisse_beklenmez():
    sinirlayici = HizSinirlayici(aralik_sn=0.05)
    await sinirlayici.bekle()
    await asyncio.sleep(0.1)
    basla = asyncio.get_event_loop().time()
    await sinirlayici.bekle()
    assert asyncio.get_event_loop().time() - basla < 0.02
