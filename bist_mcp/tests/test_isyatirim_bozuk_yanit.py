"""Is Yatirim JSON yerine baska bir govde donunce arac COKMEMELI.

Olculdu (09.09.2026, canli tarama sirasinda): `MaliTablo` uc noktasi HTTP
200 dondu ama govde JSON degildi; `yanit.json()` JSONDecodeError firlatti
ve cagri zinciri tepeye kadar coktu:

    File "bist_mcp/kaynaklar/isyatirim.py", line 369, in _getir
        return yanit.json()
    json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

`raise_for_status()` bunu yakalamiyor -- durum kodu 200. Ayni tarama 120
ticker'da tekrarlanmadi, yani KALICI degil GECICI bir kaynak davranisi.

Etkisi iki yerde agir:
  * `finansal_oranlar` tum cagriyi hataya cevirir (tek bir gecici govde
    yuzunden fiyat ve piyasa degeri de kaybolur),
  * `tam_kurulum` istisnayi `return_exceptions=True` ile yutar ve hisse
    tarama tablosundan SESSIZCE duser.

Dogru davranis, modulun kendi deseni: bos yanit = veri yok. Cagiran zaten
yedek gruba ve gecen yil penceresine dusuyor, en sonunda da "finansal
tablo bulunamadi" notunu uretiyor. tcmb.py ayni korumayi icerik tipine
bakarak yapiyor.
"""

import pytest

from bist_mcp.kaynaklar import isyatirim as isy_modulu
from bist_mcp.kaynaklar.isyatirim import IsYatirimIstemci
from bist_mcp.onbellek import Onbellek

WAF_SAYFASI = "<html><head><title>Bir hata olustu</title></head><body></body></html>"


class SahteYanit:
    def __init__(self, govde: str):
        self.status_code = 200
        self.text = govde
        self.headers = {"content-type": "text/html; charset=utf-8"}

    def raise_for_status(self):
        return None  # 200; durum kodu sorunu isaret etmiyor

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


class SahteIstemci:
    def __init__(self, **_):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, *_, **__):
        return SahteYanit(WAF_SAYFASI)


@pytest.fixture
def istemci(tmp_path, monkeypatch):
    monkeypatch.setattr(isy_modulu.httpx, "AsyncClient", SahteIstemci)
    return IsYatirimIstemci(Onbellek(tmp_path / "o.db"))


@pytest.mark.asyncio
async def test_json_olmayan_yanit_bos_sayilir(istemci):
    assert await istemci._getir("AAA", "XI_29", [(2026, 12)]) == {}


@pytest.mark.asyncio
async def test_oran_girdileri_cokmez(istemci):
    girdiler = await istemci.oran_girdileri("AAA", None)
    assert girdiler["ozkaynak_tl"] is None
    assert girdiler["net_kar_ttm"] is None


@pytest.mark.asyncio
async def test_mali_tablo_cokmez(istemci):
    tablo = await istemci.mali_tablo("AAA", None)
    assert tablo == {"donemler": [], "kalemler": []}


# --- JSON ama sozluk degil -------------------------------------------------
# Bu sekil OLCULMEDI; yukaridaki olculmus vakanin (JSON disi govde) bitisik
# durumu. Ayni kaynak beklenmedik bir govde donduruyorsa liste/metin de
# donebilir ve `ham.get("value")` cagiran her yol (dolu_slotlar, kalem_ayikla)
# AttributeError ile coker -- yani duzeltilen coksmenin aynisi, bir adim
# ileride. Savunma katmani olarak kapatiliyor.


class SozlukOlmayanYanit(SahteYanit):
    def json(self):
        return []  # gecerli JSON, yanlis sekil


class SozlukOlmayanIstemci(SahteIstemci):
    async def get(self, *_, **__):
        return SozlukOlmayanYanit("[]")


@pytest.fixture
def liste_donduren(tmp_path, monkeypatch):
    monkeypatch.setattr(isy_modulu.httpx, "AsyncClient", SozlukOlmayanIstemci)
    return IsYatirimIstemci(Onbellek(tmp_path / "o2.db"))


@pytest.mark.asyncio
async def test_sozluk_olmayan_json_bos_sayilir(liste_donduren):
    assert await liste_donduren._getir("AAA", "XI_29", [(2026, 12)]) == {}


@pytest.mark.asyncio
async def test_sozluk_olmayan_jsonda_oran_girdileri_cokmez(liste_donduren):
    girdiler = await liste_donduren.oran_girdileri("AAA", None)
    assert girdiler["ozkaynak_tl"] is None
