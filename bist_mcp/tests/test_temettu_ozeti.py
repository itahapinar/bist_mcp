"""Temettu ozeti: sessiz sifir yok, odenmis temettu vurgulanir.

Olculdu (GENKM): arac temettu_12ay=0,2053 ve verim %1,84 donderken model
cevaba "0,00 TL" ve "temettu dagitimi yapilmamaktadir" yazdi. Veri
dogruydu, hata modeldeydi; `not` alani modelin uydugu tek mekanizma
oldugu icin uyari oraya konuyor.

Ayrica temettu_gecmisi veri gelmedigi durumda da 0.0 donuyordu: "temettu
odenmedi" ile "veri yok" ayirt edilemiyordu.
"""

from bist_mcp.sunucu import temettu_ozeti


def test_odenmis_temettu_verimle_birlikte_doner():
    ozet = temettu_ozeti(0.2053, 11.15)
    assert ozet["son_12ay_toplam_tl"] == 0.2053
    assert round(ozet["temettu_verimi"], 2) == 1.84


def test_odenmis_temettude_odenmedi_demeyi_yasaklayan_not_var():
    not_alani = temettu_ozeti(0.2053, 11.15)["not"]
    assert "0,2053" in not_alani
    assert "odenmedi" in not_alani.lower(), "modele acikca yasaklanmali"


def test_gercekten_temettu_yoksa_uyari_notu_olmaz():
    ozet = temettu_ozeti(0.0, 11.15)
    assert ozet["son_12ay_toplam_tl"] == 0.0
    assert ozet["temettu_verimi"] == 0.0
    assert "not" not in ozet


def test_veri_yoksa_sifir_gibi_sunulmaz():
    """Sessiz sifir "temettu yok" diye okunuyordu."""
    ozet = temettu_ozeti(None, 11.15)
    assert ozet["son_12ay_toplam_tl"] is None
    assert ozet["temettu_verimi"] is None
    assert "bilinmiyor" in ozet["not"].lower()


def test_fiyat_yoksa_verim_hesaplanmaz():
    ozet = temettu_ozeti(0.2053, None)
    assert ozet["son_12ay_toplam_tl"] == 0.2053
    assert ozet["temettu_verimi"] is None


def test_ondalik_ayirici_her_degerde_virgul():
    """Ilk surum tek bir degere ozel replace yapiyordu; genellenmiyordu."""
    assert "1,2345" in temettu_ozeti(1.2345, 100.0)["not"]
    assert "9,8765" in temettu_ozeti(9.8765, 100.0)["not"]
