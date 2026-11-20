import pytest

from bist_mcp.hesap import defter_degeri, fk, pddd, piyasa_degeri, temettu_verimi

# Olculen gercek degerler (2026-09-05):
THYAO_FIYAT = 296.00
THYAO_OZKAYNAK_TL = 1_073_081_134_047  # Is Yatirim, TL
THYAO_HISSE_ADEDI = 1_372_283_353
THYAO_NET_KAR_TL = 139_092_773_392


def test_thyao_pddd_yfinance_tuzagina_dusmez():
    """REGRESYON — projenin en kritik testi.

    yfinance bu hisse icin priceToBook = 18,64 veriyor cunku TL fiyati
    USD ozkaynaga boluyor. TL ozkaynakla dogru sonuc 0,38. Bu test
    kirilirsa oran katmani 49 kat hatali veri uretiyor demektir.
    """
    sonuc = pddd(THYAO_FIYAT, THYAO_OZKAYNAK_TL, THYAO_HISSE_ADEDI)
    assert round(sonuc, 2) == 0.38
    assert sonuc < 1.0, "yfinance'in 18,64 degeri geri geldi"


def test_thyao_defter_degeri():
    # 1.073.081.134.047 / 1.372.283.353 = 781,9676...
    assert round(defter_degeri(THYAO_OZKAYNAK_TL, THYAO_HISSE_ADEDI), 2) == 781.97


def test_thyao_fk_makul_aralikta():
    sonuc = fk(THYAO_FIYAT, THYAO_HISSE_ADEDI, THYAO_NET_KAR_TL)
    assert 2.0 < sonuc < 4.0


def test_zarar_eden_sirkette_fk_none_doner():
    assert fk(100.0, 1_000_000, -5_000_000) is None
    assert fk(100.0, 1_000_000, 0) is None


def test_garan_temettu_verimi():
    """Olculen: 5,267 TL temettu / 131,40 TL fiyat = %4,01."""
    assert round(temettu_verimi(5.266887, 131.40), 2) == 4.01


def test_temettu_odenmemisse_sifir():
    assert temettu_verimi(0.0, 296.0) == 0.0


def test_piyasa_degeri():
    assert piyasa_degeri(296.00, 1_372_283_353) == pytest.approx(406_195_872_488, rel=1e-6)


def test_sifir_hisse_adedi_hata_verir():
    with pytest.raises(ValueError):
        defter_degeri(1_000_000, 0)


def test_negatif_ozkaynakta_pddd_none_doner():
    """Teknik iflastaki sirkette PD/DD anlamsizdir."""
    assert pddd(10.0, -500_000, 1_000) is None


def test_makul_oran_araligi():
    """ISATR'de PD/DD 272.562 cikmisti; boyle bir deger oran degil, hatadir."""
    from bist_mcp.hesap import oran_makul

    assert oran_makul(1.13)
    assert oran_makul(None), "veri yoksa karar verilemez"
    assert not oran_makul(272562.0)
    assert not oran_makul(0.0)


def test_temettu_verisi_yoksa_verim_sifir_degil_bilinmiyor():
    """Olculdu: toplu indirme bos donunce temettu 0.0 sayiliyordu ve cevap
    "temettu odenmemis" diyordu. Odenmemis olmakla bilinmemek ayri seyler."""
    assert temettu_verimi(None, 296.0) is None
    assert temettu_verimi(0.0, 296.0) == 0.0
