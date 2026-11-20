"""`finansal_oranlar` notu, HESAPLANAN oranla celismemeli.

Olculdu (kod okumasi + asagidaki testler): `not` alani Is Yatirim'in HAM
alanlarina bakiyordu (`girdiler["net_kar_ttm"]`), oysa F/K'yi uretmek icin
kullanilan kar `net_kar_sec` ile SECILEN kardir. Kumulatif formul
"eksik gecmis: uydurma yapma" diyip None dondugunde ama yfinance'in
ceyreklik toplami geldiginde satirda gercek bir F/K var, not ise
"Son 12 ay kari hesaplanamadi; F/K verilemiyor" diyordu.

Bu celiski dogrudan kullaniciya gidiyor: sistem promptu kural 3 modele
`not` alanini AYNEN aktarmasini soyluyor, ozet kart da F/K'yi basiyor.
Kullanici ayni cevapta hem rakami hem "verilemiyor"u goruyor.
"""

import pytest

from bist_mcp import sunucu
from bist_mcp.kaynaklar.kap import Sirket

SIRKET = Sirket(kod="AAA", unvan="AAA A.S.", mkk_oid="o", tip=None, tum_kodlar=("AAA",))


class SahteKap:
    async def sirket_dizini(self):
        return {"AAA": SIRKET}


class SahteIsYatirim:
    def __init__(self, ozkaynak, net_kar_ttm):
        self._ozkaynak = ozkaynak
        self._net_kar = net_kar_ttm

    async def oran_girdileri(self, kod, tip):
        return {
            "odenmis_sermaye": 1_000_000,
            "ozkaynak_tl": self._ozkaynak,
            "ozkaynak_donem": "2026 ilk 6 ay",
            "net_kar_ttm": self._net_kar,
            "net_kar_aciklama": "son 12 ay (2026/06 itibarıyla)",
        }


class SahteFiyat:
    def __init__(self, ceyreklik):
        self._ceyreklik = ceyreklik

    async def anlik(self, kod):
        return {"kod": "AAA", "fiyat": 100.0, "para_birimi": "TRY"}

    async def toplu(self, kodlar):
        return {"AAA": {"fiyat": 100.0, "temettu_12ay": 1.0, "ortalama_hacim_tl": 1e9}}

    async def sirket_bilgi(self, kod):
        return {
            "sector": "Industrials",
            "sharesOutstanding": 1_000_000,
            "financialCurrency": "TRY",
        }

    async def ceyreklik_net_kar_ttm(self, kod):
        return self._ceyreklik


class SahteGorunum:
    def satir_al(self, kod):
        return None


def _kur(monkeypatch, ozkaynak, net_kar_ttm, ceyreklik):
    monkeypatch.setattr(sunucu, "kap", SahteKap())
    monkeypatch.setattr(sunucu, "isyatirim", SahteIsYatirim(ozkaynak, net_kar_ttm))
    monkeypatch.setattr(sunucu, "fiyat", SahteFiyat(ceyreklik))
    monkeypatch.setattr(sunucu, "gorunum", SahteGorunum())


@pytest.mark.asyncio
async def test_ceyreklikten_gelen_kar_varken_fk_verilemiyor_denmez(monkeypatch):
    """ASIL HATA: kumulatif formul None, ceyreklik toplam dolu."""
    _kur(monkeypatch, ozkaynak=500_000_000.0, net_kar_ttm=None, ceyreklik=25_000_000.0)

    satir = await sunucu.finansal_oranlar("AAA")

    assert satir["fk"] == pytest.approx(4.0)  # 100 x 1.000.000 / 25.000.000
    assert "F/K verilemiyor" not in (satir.get("not") or "")


@pytest.mark.asyncio
async def test_ozkaynak_yokken_sadece_pddd_eksik_denir(monkeypatch):
    """Is Yatirim'da ozkaynak yok ama ceyreklik kar var: F/K gecerli."""
    _kur(monkeypatch, ozkaynak=None, net_kar_ttm=None, ceyreklik=25_000_000.0)

    satir = await sunucu.finansal_oranlar("AAA")
    aciklama = satir.get("not") or ""

    assert satir["fk"] == pytest.approx(4.0)
    assert satir["pddd"] is None
    assert "PD/DD" in aciklama
    assert "F/K" not in aciklama


@pytest.mark.asyncio
async def test_kar_gercekten_yoksa_fk_verilemiyor_denir(monkeypatch):
    """REGRESYON: uyari kaybolmamali; kar hicbir kaynaktan gelmiyorsa soylenir."""
    _kur(monkeypatch, ozkaynak=500_000_000.0, net_kar_ttm=None, ceyreklik=None)

    satir = await sunucu.finansal_oranlar("AAA")

    assert satir["fk"] is None
    assert "F/K verilemiyor" in (satir.get("not") or "")


@pytest.mark.asyncio
async def test_hicbir_finansal_yoksa_iki_oran_da_bilinmiyor_denir(monkeypatch):
    _kur(monkeypatch, ozkaynak=None, net_kar_ttm=None, ceyreklik=None)

    satir = await sunucu.finansal_oranlar("AAA")
    aciklama = satir.get("not") or ""

    assert satir["fk"] is None and satir["pddd"] is None
    assert "F/K ve PD/DD" in aciklama


# --- Zarar dalindaki PD/DD iddiasi ----------------------------------------
# Zarar mesaji kosulsuz "PD/DD gecerlidir" diyordu ama PD/DD ayni satirda
# None olabiliyor:
#   * hesap.pddd() NEGATIF ozkaynakta None doner (dokumante edilmis kural),
#   * satir_hesapla ozkaynak yoksa oran uretmez (anlik_gorunum.py:82),
#   * sonraki makullük kontrolu bunu yakalayamaz: oran_makul(None) True.
# "Zarar eden + ozkaynagi erimis sirket" uydurma bir bileske degil, sikintili
# sirketin tipik profili. Sistem promptu kural 3 notu modele aynen aktarttigi
# icin kullanici "PD/DD veri yok" satirinin yaninda "PD/DD gecerlidir"
# cumlesini goruyordu.


@pytest.mark.asyncio
async def test_zararda_ozkaynak_yoksa_pddd_gecerli_denmez(monkeypatch):
    _kur(monkeypatch, ozkaynak=None, net_kar_ttm=None, ceyreklik=-25_000_000.0)

    satir = await sunucu.finansal_oranlar("AAA")

    assert satir["pddd"] is None
    assert "PD/DD gecerlidir" not in (satir.get("not") or "")


@pytest.mark.asyncio
async def test_zararda_negatif_ozkaynakta_pddd_gecerli_denmez(monkeypatch):
    _kur(monkeypatch, ozkaynak=-500_000_000.0, net_kar_ttm=None, ceyreklik=-25_000_000.0)

    satir = await sunucu.finansal_oranlar("AAA")
    aciklama = satir.get("not") or ""

    assert satir["pddd"] is None
    assert "PD/DD gecerlidir" not in aciklama
    assert "NEGATIF" in aciklama  # ozkaynagin erimis oldugu SOYLENMELI


@pytest.mark.asyncio
async def test_zararda_ozkaynak_saglamsa_pddd_gecerli_denir(monkeypatch):
    """REGRESYON: saglam vakada zarar mesaji ve PD/DD iddiasi korunmali."""
    _kur(monkeypatch, ozkaynak=500_000_000.0, net_kar_ttm=None, ceyreklik=-25_000_000.0)

    satir = await sunucu.finansal_oranlar("AAA")
    aciklama = satir.get("not") or ""

    assert satir["pddd"] is not None
    assert "ZARAR" in aciklama
    assert "PD/DD gecerlidir" in aciklama
