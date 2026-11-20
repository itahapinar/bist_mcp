"""Gercek sunuculara cikan testler: python -m pytest bist_mcp/ -m network"""

import pytest

from bist_mcp.hesap import pddd
from bist_mcp.kaynaklar.fiyat import FiyatKaynak
from bist_mcp.kaynaklar.isyatirim import IsYatirimIstemci, kalem_bul, tablo_bol
from bist_mcp.kaynaklar.kap import KapIstemci
from bist_mcp.kaynaklar.kur import KurKaynak
from bist_mcp.onbellek import Onbellek

pytestmark = pytest.mark.network


@pytest.fixture
def onbellek(tmp_path):
    return Onbellek(tmp_path / "e.db")


@pytest.mark.asyncio
async def test_kap_dizini_bankalari_cozer(onbellek):
    """Virgullu stockCode hatasinin regresyonu — canli veriyle.

    GARAN'in stockCode degeri "GARAN, TGB"; bolunmeden eslestirilirse
    bankalarin cogu kayboluyordu.
    """
    dizin = await KapIstemci(onbellek).sirket_dizini()
    assert len(dizin) > 780, f"beklenen ~807 ticker, gelen {len(dizin)}"
    for kod in ("GARAN", "YKBNK", "VAKBN", "HALKB", "ISCTR", "AKBNK"):
        assert kod in dizin, f"{kod} dizinde yok"
        assert dizin[kod].tip == "BNK"


@pytest.mark.asyncio
async def test_kap_bildirimleri_geliyor(onbellek):
    bildirimler = await KapIstemci(onbellek).bildirimler("ASELS", gun=120)
    assert len(bildirimler) > 5
    assert bildirimler[0]["konu"]
    assert bildirimler[0]["tarih"]


@pytest.mark.asyncio
async def test_isyatirim_utf8_bozulmuyor(onbellek):
    """Sunucu charset gondermiyor; Turkce bozulursa burada yakalanir."""
    veri = await IsYatirimIstemci(onbellek).mali_tablo("THYAO", tip=None)
    adlar = [k["ad"] for k in veri["kalemler"]]
    assert any("Özkaynaklar" in a for a in adlar), adlar[:5]


@pytest.mark.asyncio
async def test_yayimlanmamis_donem_secilmez(onbellek):
    """Takvim aritmetigi 2026/12'yi isteyip bos tablo aliyordu."""
    veri = await IsYatirimIstemci(onbellek).mali_tablo("THYAO", tip=None)
    assert veri["kalemler"], "tablo bos geldi - donem secimi bozulmus"
    assert veri["donemler"], "donem etiketi uretilmemis"


@pytest.mark.asyncio
async def test_degerler_sayi_olarak_geliyor(onbellek):
    """Is Yatirim string donduruyor; cevrilmezse oran hesabi bolemez."""
    veri = await IsYatirimIstemci(onbellek).mali_tablo("THYAO", tip=None)
    ozkaynak = kalem_bul(veri["kalemler"], "Özkaynaklar")
    assert isinstance(ozkaynak, float)
    assert ozkaynak > 1e11


@pytest.mark.asyncio
async def test_banka_bilancosu_bddk_formatinda(onbellek):
    veri = await IsYatirimIstemci(onbellek).mali_tablo("GARAN", tip="BNK")
    assert kalem_bul(veri["kalemler"], "XVI. ÖZKAYNAKLAR") is not None


@pytest.mark.asyncio
async def test_tablo_bolme_sanayi_ve_bankada_calisir(onbellek):
    istemci = IsYatirimIstemci(onbellek)

    sanayi = tablo_bol((await istemci.mali_tablo("THYAO", tip=None))["kalemler"])
    assert sanayi["bilanco"] and sanayi["gelir"] and sanayi["nakit"]

    banka = tablo_bol((await istemci.mali_tablo("GARAN", tip="BNK"))["kalemler"])
    assert banka["bilanco"] and banka["gelir"]
    assert banka["nakit"] == [], "bankalarda nakit akis tablosu yayimlanmiyor"


@pytest.mark.asyncio
async def test_thyao_pddd_canli_veriyle_makul(onbellek):
    """UCTAN UCA REGRESYON — projenin en kritik testi.

    yfinance bu hisse icin 18,64 veriyor (TL fiyat / USD ozkaynak).
    Sonuc 1'in ustundeyse oran katmani bozulmus demektir.
    """
    isy = IsYatirimIstemci(onbellek)
    fyt = FiyatKaynak(onbellek)

    veri = await isy.mali_tablo("THYAO", tip=None)
    ozkaynak = kalem_bul(veri["kalemler"], "Özkaynaklar")
    bilgi = await fyt.sirket_bilgi("THYAO")
    anlik = await fyt.anlik("THYAO")

    sonuc = pddd(anlik["fiyat"], ozkaynak, bilgi["sharesOutstanding"])
    assert 0.2 < sonuc < 1.0, f"PD/DD {sonuc} — yfinance tuzagi geri gelmis olabilir"


@pytest.mark.asyncio
async def test_toplu_indirme_temettu_getiriyor(onbellek):
    veri = await FiyatKaynak(onbellek).toplu(["GARAN", "TUPRS"])
    assert veri["GARAN"]["temettu_12ay"] > 0
    assert veri["GARAN"]["fiyat"] > 0


@pytest.mark.asyncio
async def test_endeks_verisi_geliyor(onbellek):
    """Olculdu: XU100.IS calisir, ^XU100 bos doner."""
    sonuc = await FiyatKaynak(onbellek).anlik("XU100")
    assert sonuc["fiyat"] > 1000


@pytest.mark.asyncio
async def test_doviz_ve_gram_altin_anahtarsiz_geliyor(onbellek):
    """EVDS anahtari olmadan da calismalilar (kur.py yfinance kullaniyor)."""
    kaynak = KurKaynak(onbellek)
    usdtry = await kaynak.kur("usdtry")
    altin = await kaynak.kur("gram_altin")
    assert usdtry["deger"] > 1
    assert altin["deger"] > 100
    assert altin["dayanak"]["usdtry"] > 1
