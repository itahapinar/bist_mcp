"""KAP oturum cerezi HER istekte tasinmali.

Olculen WAF davranisi (README, hiz sinirlari): API cagrisindan once
`/tr/bildirim-sorgu`'ya GET atilip oturum cerezi alinmazsa WAF baglantiyi
~6 saniyede dusuruyor.

BULUNAN HATA: `_oturum_isitildi` bayragi ISTEMCIDE degil ISTEMCI NESNESINDE
tutuluyordu, ama her cagri kendi `httpx.AsyncClient`'ini acip kapatiyor —
yani cerez ilk cagriyla birlikte cope gidiyor. Ilk cagridan sonra bayrak
True kaldigi icin sonraki hicbir cagri isinma GET'ini atmiyor ve KAP
API'sine CEREZSIZ gidiyor.

Canli logda goruldu (09.09.2026 17:29 ve 17:31): acilistaki iki
`GET /tr/bildirim-sorgu`'dan sonra `attachment-detail` cagrisi oncesinde
hicbir isinma yok.
"""

import asyncio
from typing import ClassVar

import httpx
import pytest

from bist_mcp.kaynaklar import kap as kap_modulu
from bist_mcp.kaynaklar.kap import KapIstemci
from bist_mcp.onbellek import Onbellek

DIZIN = [
    {
        "stockCode": "ASELS",
        "kapMemberTitle": "ASELSAN",
        "mkkMemberOid": "oid-asels",
        "financialType": "SIR",
    },
    {
        "stockCode": "THYAO",
        "kapMemberTitle": "TURK HAVA YOLLARI",
        "mkkMemberOid": "oid-thyao",
        "financialType": "SIR",
    },
]


class SahteYanit:
    def __init__(self, govde):
        self._govde = govde

    def raise_for_status(self):
        return None

    def json(self):
        return self._govde


class SahteWaf:
    """Cerezsiz gelen API cagrisini dusuren istemci; olculen WAF davranisi."""

    acilan: ClassVar[list["SahteWaf"]] = []

    def __init__(self, **kwargs):
        # Kod paylasilan bir kavanoz verirse cerez istemciler arasi yasar.
        self._kavanoz = kwargs.get("cookies")
        self._isitildi = False
        SahteWaf.acilan.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    @property
    def _cerezli(self) -> bool:
        return self._isitildi or bool(self._kavanoz and list(self._kavanoz))

    async def get(self, url, **_):
        await asyncio.sleep(0)  # denetimi birak: yaris kosulu ancak boyle gorunur
        if url == kap_modulu.BILDIRIM_SORGU_SAYFASI:
            self._isitildi = True
            if self._kavanoz is not None:
                # httpx.Cookies(kavanoz) ham kavanozu SARAR, kopyalamaz.
                httpx.Cookies(self._kavanoz).set(
                    "KAPSESSION", "abc", domain="www.kap.org.tr"
                )
            return SahteYanit({})
        if not self._cerezli:
            raise httpx.ReadError("WAF baglantiyi dusurdu (cerez yok)")
        return SahteYanit({})

    async def post(self, url, **_):
        if not self._cerezli:
            raise httpx.ReadError("WAF baglantiyi dusurdu (cerez yok)")
        return SahteYanit([])


@pytest.fixture
def istemci(tmp_path, monkeypatch):
    SahteWaf.acilan = []
    monkeypatch.setattr(kap_modulu.httpx, "AsyncClient", SahteWaf)
    onbellek = Onbellek(tmp_path / "o.db")
    onbellek.yaz("kap:sirket_listesi", DIZIN, ttl_saniye=600)
    return KapIstemci(onbellek)


@pytest.mark.asyncio
async def test_ikinci_cagri_da_cerezle_gider(istemci):
    """ASIL HATA: ikinci cagri cerezsiz gidiyor ve WAF baglantiyi dusuruyor."""
    await istemci.bildirimler("ASELS", gun=30)
    await istemci.bildirimler("THYAO", gun=30)


@pytest.mark.asyncio
async def test_bildirim_detayi_da_cerezle_gider(istemci):
    await istemci.bildirimler("ASELS", gun=30)
    await istemci.bildirim_detay("1657935")


@pytest.mark.asyncio
async def test_isinma_her_cagride_tekrarlanmaz(istemci):
    """Cerez paylasildiginda ikinci istemcinin yeniden isinmasi gerekmez."""
    await istemci.bildirimler("ASELS", gun=30)
    isinan = sum(1 for c in SahteWaf.acilan if c._isitildi)
    await istemci.bildirimler("THYAO", gun=30)
    assert sum(1 for c in SahteWaf.acilan if c._isitildi) == isinan


# --- Es zamanli cagrilarda tek isinma --------------------------------------
# Olculdu (canli log, 09.09.2026): 17:29:03,139 ve 17:29:04,212'de IKI ayri
# GET /tr/bildirim-sorgu var. Aradaki 1,07 sn hiz sinirlayicinin arali ile
# ortusuyor -- yani ikinci gorev "cerez var mi" kontrolunu birincinin isinmasi
# bitmeden gecti. Ajan ayni turdaki arac cagrilarini asyncio.gather ile
# calistirdigi icin bu desen her soguk baslangicta tekrarlanabilir.


@pytest.mark.asyncio
async def test_es_zamanli_cagrilar_tek_isinma_yapar(istemci):
    await asyncio.gather(
        istemci.bildirimler("ASELS", gun=30),
        istemci.bildirimler("THYAO", gun=30),
    )
    assert sum(1 for c in SahteWaf.acilan if c._isitildi) == 1
