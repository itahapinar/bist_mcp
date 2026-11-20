import pytest

from bist_mcp.kaynaklar.kur import (
    TROY_ONS_GRAM,
    gecerli_varliklar,
    gram_altin_hesapla,
)


def test_gram_altin_ons_ve_kurdan_hesaplanir():
    """Olculen degerlerle: 4.429,80 USD/ons, USDTRY 48,4248."""
    sonuc = gram_altin_hesapla(4429.80, 48.4248)
    assert 6800 < sonuc < 7000
    assert round(sonuc, 2) == round(4429.80 * 48.4248 / TROY_ONS_GRAM, 2)


def test_gram_altin_sifir_girdide_hata_verir():
    with pytest.raises(ValueError):
        gram_altin_hesapla(0, 48.0)
    with pytest.raises(ValueError):
        gram_altin_hesapla(4429.80, 0)


def test_gecerli_varliklar_dovizi_ve_altini_icerir():
    varliklar = gecerli_varliklar()
    for beklenen in ("usdtry", "eurtry", "gram_altin", "ons_altin"):
        assert beklenen in varliklar


def test_troy_ons_sabiti_dogru():
    assert TROY_ONS_GRAM == pytest.approx(31.1034768)
