"""Tam kurulumun ne zaman gerektigi.

Olculdu (08.09.2026): karar, kayit sayisini KAP evreniyle (807 ticker)
karsilastiriyordu. Fiyat verisi olan yalnizca ~630 hisse var, yani tablo
TAM DOLU olsa bile 630 < 807*0,9 = 726 ve her sunucu acilisinda ~13
dakikalik, ~700 istekli tam tarama kosuyordu; yfinance de bizi hiz
sinirina aliyordu.

Beklenen satir sayisini tahmin etmek yanlis temel: taramanin BITIP
bitmedigi dogrudan kaydedilir. Tarama basinda isaret silinir, sonunda
yazilir; yarida kesilirse isaret olmaz ve tablo yeniden kurulur.
"""

import pytest

from bist_mcp.anlik_gorunum import AnlikGorunum
from bist_mcp.sunucu import HAFTALIK_SAAT, tam_kurulum_gerekli


def test_hic_veri_yoksa_kurulur():
    assert tam_kurulum_gerekli(None, tarama_tamam=False)


def test_veri_eskiyse_kurulur():
    assert tam_kurulum_gerekli(HAFTALIK_SAAT + 1, tarama_tamam=True)


def test_taze_ve_tamamlanmis_taramada_kurulmaz():
    assert not tam_kurulum_gerekli(1.0, tarama_tamam=True)


def test_yarida_kesilen_tarama_yeniden_kurulur():
    assert tam_kurulum_gerekli(1.0, tarama_tamam=False)


def test_dolu_tablo_her_acilista_yeniden_kurulmaz():
    """Asil hata buydu: tablo dolu olmasina ragmen surekli kuruluyordu."""
    assert not tam_kurulum_gerekli(0.2, tarama_tamam=True)


# --- Tamamlanma isareti ----------------------------------------------------


def _gorunum(tmp_path):
    return AnlikGorunum(tmp_path / "g.db", kap=None, isyatirim=None, fiyat=None)


def test_yeni_veritabaninda_tarama_tamam_degildir(tmp_path):
    assert not _gorunum(tmp_path).tarama_tamam()


def test_bitis_yazilinca_tamam_olur(tmp_path):
    gorunum = _gorunum(tmp_path)
    gorunum.taramayi_bitir()
    assert gorunum.tarama_tamam()


def test_yeni_tarama_baslayinca_isaret_silinir(tmp_path):
    """Yarida kesilirse onceki taramanin isareti kalmamali."""
    gorunum = _gorunum(tmp_path)
    gorunum.taramayi_bitir()
    gorunum.taramaya_basla()
    assert not gorunum.tarama_tamam()


def test_isaret_yeniden_acilista_korunur(tmp_path):
    yol = tmp_path / "g.db"
    AnlikGorunum(yol, kap=None, isyatirim=None, fiyat=None).taramayi_bitir()
    assert AnlikGorunum(yol, kap=None, isyatirim=None, fiyat=None).tarama_tamam()
