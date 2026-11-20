"""Coklu sinifta iptal edilen oranlar her hafif tazelemede geri geliyordu.

Olculdu (gorunum.db, 09.09.2026): 24 coklu sinif hisse oran uretiyor ve
ikisi apacik sacma --

    ISATR  PD/DD 272.562,08   F/K 1.821.862,35
    ISBTR  PD/DD  28.241,93   F/K   188.788,38

Sebep: `tam_kurulum` coklu sinifta makul olmayan orani None yapiyor ama
satirda `ozkaynak_tl` ve `hisse_adedi` duruyor; `hafif_tazele` satiri okuyup
`satir_hesapla` ile oranlari YENIDEN HESAPLIYOR ve iptal her acilista
bozuluyordu.

Cozum: iptal satirda `oran_gecersiz` olarak SAKLANIR ve hafif tazeleme onu
korur. Isaretin kendisi yazilir cunku ozkaynak/hisse adedi silinmez -- onlar
tarama disi sorularda hala ise yarar.
"""

import pytest

from bist_mcp.anlik_gorunum import AnlikGorunum, SUTUNLAR, oranlari_iptal_et


def test_iptal_oranlari_siler_isareti_birakir():
    satir = oranlari_iptal_et(
        {"kod": "ISATR", "pddd": 272562.08, "fk": 1821862.35, "piyasa_degeri": 1e12,
         "ozkaynak_tl": 5e10, "hisse_adedi": 200000}
    )
    assert satir["pddd"] is None
    assert satir["fk"] is None
    assert satir["piyasa_degeri"] is None
    assert satir["oran_gecersiz"] == 1


def test_ozkaynak_ve_hisse_adedi_korunur():
    """Tarama disi sorularda bu alanlar hala ise yariyor."""
    satir = oranlari_iptal_et({"kod": "ISATR", "ozkaynak_tl": 5e10, "hisse_adedi": 200000})
    assert satir["ozkaynak_tl"] == 5e10
    assert satir["hisse_adedi"] == 200000


def test_oran_gecersiz_sutunu_semada():
    """Sutun SUTUN_TIPLERI'nde olmali; yoksa eski veritabanlarina goc etmez."""
    assert "oran_gecersiz" in SUTUNLAR


class _SahteFiyat:
    def __init__(self, fiyat=512925.0):
        self._fiyat = fiyat

    async def toplu(self, kodlar):
        return {k: {"fiyat": self._fiyat, "temettu_12ay": 0.0} for k in kodlar}

    async def toplu_kotasyon(self):
        return {}


@pytest.mark.asyncio
async def test_hafif_tazeleme_iptali_bozmaz(tmp_path):
    """REGRESYON: kullanicinin gordugu ISATR 272.562'lik PD/DD budur."""
    g = AnlikGorunum(tmp_path / "g.db", kap=None, isyatirim=None, fiyat=_SahteFiyat())
    g.satir_yaz(
        oranlari_iptal_et(
            {"kod": "ISATR", "ozkaynak_tl": 50_000_000_000.0, "hisse_adedi": 200_000,
             "temettu_12ay": 0.0}
        )
    )
    assert await g.hafif_tazele(["ISATR"]) == 1
    satir = g.satir_al("ISATR")
    assert satir["pddd"] is None, "iptal edilen oran hafif tazelemede geri geldi"
    assert satir["fk"] is None
    assert satir["piyasa_degeri"] is None
    assert satir["oran_gecersiz"] == 1


@pytest.mark.asyncio
async def test_iptal_edilmemis_satir_normal_tazelenir(tmp_path):
    """Isaret yoksa oranlar her zamanki gibi yeniden hesaplanmali."""
    g = AnlikGorunum(tmp_path / "g.db", kap=None, isyatirim=None, fiyat=_SahteFiyat(100.0))
    g.satir_yaz(
        {"kod": "AAA", "ozkaynak_tl": 1_000_000_000.0, "hisse_adedi": 10_000_000,
         "net_kar_tl": 100_000_000.0, "temettu_12ay": 0.0}
    )
    assert await g.hafif_tazele(["AAA"]) == 1
    satir = g.satir_al("AAA")
    assert satir["pddd"] == pytest.approx(1.0)
    assert satir["fk"] == pytest.approx(10.0)
    assert not satir["oran_gecersiz"]


@pytest.mark.asyncio
async def test_iptal_edilen_satir_taramada_listelenmez(tmp_path):
    """Oranlar None oldugu icin filtreler zaten elemeli; guvence testi."""
    g = AnlikGorunum(tmp_path / "g.db", kap=None, isyatirim=None, fiyat=_SahteFiyat())
    g.satir_yaz(oranlari_iptal_et({"kod": "ISATR", "ozkaynak_tl": 5e10, "hisse_adedi": 2e5}))
    g.satir_yaz({"kod": "AAA", "pddd": 0.5, "fk": 8.0, "piyasa_degeri": 1e9})
    kodlar = [s["kod"] for s in g.satirlari_sec(pddd_max=1.0)]
    assert kodlar == ["AAA"]
