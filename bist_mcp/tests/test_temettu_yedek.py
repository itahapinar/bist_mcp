"""Canli temettu gelmezse gunluk gorunum tablosuna dus.

Olculdu (GENKM): sunucunun acilistaki tazelemesi yfinance'i mesgul ederken
tekil toplu indirme bos donuyor ve temettu "veri yok" cikiyor -- oysa deger
gorunum tablosunda duruyor (0,2053 TL). Temettu yillik bir olay; bir gunluk
anlik goruntu bu alan icin yeterince taze.
"""

from bist_mcp.sunucu import temettu_yedekli


def test_canli_veri_varsa_oldugu_gibi_kullanilir():
    deger, kaynak_notu = temettu_yedekli(0.2053, {"temettu_12ay": 0.9})
    assert deger == 0.2053
    assert kaynak_notu is None


def test_canli_yoksa_gorunum_tablosundan_alinir():
    deger, kaynak_notu = temettu_yedekli(None, {"temettu_12ay": 0.2053})
    assert deger == 0.2053
    assert "görünüm" in kaynak_notu.lower()


def test_ikisi_de_yoksa_bilinmiyor():
    assert temettu_yedekli(None, None) == (None, None)
    assert temettu_yedekli(None, {}) == (None, None)


def test_canli_sifir_yedege_dusmez():
    """Gercekten 0 temettu ile veri yokluğu ayri seyler."""
    deger, kaynak_notu = temettu_yedekli(0.0, {"temettu_12ay": 0.2053})
    assert deger == 0.0
    assert kaynak_notu is None


def test_fiyat_da_yedeklenir():
    """Verim hesabi icin fiyat gerekiyor; ikisi ayni kaynaktan gelmeli."""
    from bist_mcp.sunucu import fiyat_yedekli

    assert fiyat_yedekli(11.15, {"fiyat": 9.0}) == 11.15
    assert fiyat_yedekli(None, {"fiyat": 11.15}) == 11.15
    assert fiyat_yedekli(None, None) is None
