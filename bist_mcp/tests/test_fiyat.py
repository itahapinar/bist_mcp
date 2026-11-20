from bist_mcp.kaynaklar.fiyat import (
    IZINLI_INFO_ALANLARI,
    YASAK_INFO_ALANLARI,
    bist_sembol,
    info_suz,
)

# Gercek yfinance ciktisi: THYAO'nun priceToBook'u 18,64 ama gercek deger 0,38.
# Sebep: TL fiyat / USD ozkaynak. Bu alan asla okunmamali.
THYAO_INFO = {
    "sharesOutstanding": 1372283353,
    "sector": "Industrials",
    "currency": "TRY",
    "financialCurrency": "USD",
    "priceToBook": 18.635105,
    "trailingPE": None,
    "dividendYield": 2.28,
}


def test_yasak_alanlar_suzulur():
    sonuc = info_suz(THYAO_INFO)
    for alan in ("priceToBook", "trailingPE", "dividendYield"):
        assert alan not in sonuc


def test_izinli_alanlar_korunur():
    sonuc = info_suz(THYAO_INFO)
    assert sonuc["sharesOutstanding"] == 1372283353
    assert sonuc["sector"] == "Industrials"
    assert sonuc["financialCurrency"] == "USD"


def test_yasak_ve_izinli_kumeler_kesismiyor():
    assert not (IZINLI_INFO_ALANLARI & YASAK_INFO_ALANLARI)


def test_priceToBook_yasak_kumede():
    """Regresyon: bu alanin izinli kumeye tasinmasi 49 kat hata geri getirir."""
    assert "priceToBook" in YASAK_INFO_ALANLARI
    assert "trailingPE" in YASAK_INFO_ALANLARI
    assert "dividendYield" in YASAK_INFO_ALANLARI


def test_bist_sembolu_is_ekiyle_uretilir():
    assert bist_sembol("THYAO") == "THYAO.IS"
    assert bist_sembol("thyao") == "THYAO.IS"
    assert bist_sembol("GARAN.IS") == "GARAN.IS"


def test_endeksler_de_ayni_eki_alir():
    """Olculdu: BIST endeksleri Yahoo'da XU100.IS formatinda; ^XU100 bos doner."""
    assert bist_sembol("XU100") == "XU100.IS"
    assert bist_sembol("XBANK") == "XBANK.IS"


# --- Yahoo hiz siniri: tekil uc noktalar sinirlanmali ---


def test_tekil_cagrilar_hiz_sinirlayiciya_bagli():
    """REGRESYON — olculdu: sinirlayicisiz 630 hisselik kurulum sonrasi
    Yahoo hem Ticker.history hem Ticker.info icin YFRateLimitError verdi,
    yalnizca toplu download ayakta kaldi.

    Hiz sinirlayici Is Yatirim ve KAP'a eklenmisti ama yfinance'e
    eklenmemisti; bu test o bosluğun geri gelmesini engeller.
    """
    import inspect

    from bist_mcp.kaynaklar import fiyat as modul

    for metot in (modul.FiyatKaynak.anlik, modul.FiyatKaynak.gecmis, modul.FiyatKaynak.sirket_bilgi):
        kaynak = inspect.getsource(metot)
        assert "_sinirlayici.bekle()" in kaynak, f"{metot.__name__} hiz siniri uygulamiyor"


def test_toplu_indirme_sinirlanmaz():
    """Toplu indirme TEK istek; sinirlamak gereksiz yere yavaslatirdi."""
    import inspect

    from bist_mcp.kaynaklar.fiyat import FiyatKaynak

    assert "_sinirlayici.bekle()" not in inspect.getsource(FiyatKaynak.toplu)


def test_tekil_aralik_makul():
    from bist_mcp.kaynaklar.fiyat import TEKIL_ISTEK_ARALIGI_SN

    assert 0.3 <= TEKIL_ISTEK_ARALIGI_SN <= 2.0
