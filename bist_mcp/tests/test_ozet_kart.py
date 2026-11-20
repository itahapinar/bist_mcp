"""Ozet kart: baslik rakamlari KODDA uretilir, model yeniden yazmaz.

Olculdu: arac temettu_12ay=0,2053 ve verim %1,84'u dort ayri yerde
(ozet, oranlar, temettu ve "0,00 DEME" notu) donderken model cevaba
"%0,0" yazdi. Uc yaklasim denendi (prompt kurali, uyari notu, ozet blogu);
hicbiri tutmadi. Rakamlar artik modelden gecmiyor.
"""

from bist_mcp.sunucu import ozet_kart

TAM = {
    "fiyat": 11.15,
    "piyasa_degeri": 6790000000.0,
    "pddd": 0.9654,
    "fk": None,
    "net_kar_tl": -44690000.0,
    "temettu_12ay": 0.2053,
    "temettu_verimi": 1.8412,
    "rsi_14": 54.82,
    "macd": -0.3428,
}


def test_rakamlar_turkce_bicimde():
    kart = ozet_kart(TAM)
    assert "11,15 TL" in kart
    assert "0,97" in kart          # PD/DD yuvarlanir
    assert "0,2053 TL" in kart     # temettu 4 basamak
    assert "%1,84" in kart
    assert "54,82" in kart


def test_bolme_isareti_ile_tablo_uretir():
    """bicim.py boru tablosunu hizali monospace bloga ceviriyor."""
    satirlar = [s for s in ozet_kart(TAM).split("\n") if s.strip()]
    assert all(s.startswith("|") and s.endswith("|") for s in satirlar), satirlar


def test_negatif_karda_fk_tanimsiz_yazilir():
    assert "tanımsız" in ozet_kart(TAM)
    assert "negatif" in ozet_kart(TAM)


def test_temettu_odenmisse_sifir_yazilmaz():
    """Modelin dusurdugu alan; kod asla 0 yazmamali."""
    kart = ozet_kart(TAM)
    assert "0,00 TL" not in kart
    assert "%0,00" not in kart


def test_veri_yoksa_sifir_degil_veri_yok():
    eksik = dict(TAM, temettu_12ay=None, temettu_verimi=None, rsi_14=None)
    kart = ozet_kart(eksik)
    assert kart.count("veri yok") >= 3
    assert "%0" not in kart


def test_gercekten_sifir_temettu_sifir_gosterilir():
    kart = ozet_kart(dict(TAM, temettu_12ay=0.0, temettu_verimi=0.0))
    assert "0,0000 TL" in kart or "0 TL" in kart


def test_bos_ozet_cokmez():
    assert ozet_kart({}).strip() == "" or "veri yok" in ozet_kart({})


def test_temettu_bilinmiyorsa_kart_sifir_gostermez():
    """Asil hata buydu: kart 0,0000 TL / %0,00 gosteriyordu."""
    kart = ozet_kart(dict(TAM, temettu_12ay=None, temettu_verimi=None))
    assert "0,0000 TL" not in kart
    assert "%0,00" not in kart
    assert kart.count("veri yok") >= 2


# --- Sirket kimligi --------------------------------------------------------
# Olculdu (canli bot): kart yalnizca rakamlari gosteriyordu, hangi hisse
# oldugu yazmiyordu. "thyao kac tl" cevabi da sadece "Son fiyat 296,00 TL"
# oldu; kullanici hangi sirket oldugunu goremedi.


def test_kart_basliginda_kod_ve_unvan_var():
    kart = ozet_kart(dict(TAM, kod="THYAO", unvan="TÜRK HAVA YOLLARI A.O."))
    ilk = kart.split("\n")[0]
    assert "THYAO" in ilk
    assert "TÜRK HAVA YOLLARI A.O." in ilk


def test_unvan_yoksa_kod_yeter():
    ilk = ozet_kart(dict(TAM, kod="THYAO")).split("\n")[0]
    assert "THYAO" in ilk


def test_kimlik_yoksa_baslik_satiri_olmaz():
    assert ozet_kart(TAM).split("\n")[0].startswith("|")
