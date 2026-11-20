"""Yonlu hacim: alim/satim baskisi tahmini.

Kullanici "4 eylulde kac hisse alinmis kac hisse satilmis" diye sordu.
Birebir cevabi yok: her islemin hem alicisi hem saticisi var, iki sayi
tanim geregi esittir (THYAO 04.09: 44.799.808 lot alinmis ve ayni kadar
satilmis). Farkli cikabilen tek olcu, islemin hangi tarafin AGRESIF
davranmasiyla gerceklestigi.

Siniflandirma tick testiyle yapilir: kapanis onceki kapanistan yuksekse
alici yonlu, dusukse satici yonlu; yatay bar son yonu devralir. Olculdu
(THYAO 04.09): acilis-kapanis yontemi hacmin %20,4'unu siniflandiramiyor,
tick testi %4,3.
"""

import pytest

from bist_mcp.hesap import yonlu_hacim_hesapla


def _bar(kapanis, hacim):
    return {"kapanis": kapanis, "hacim": hacim}


def test_yukselen_kapanislar_alici_yonlu():
    sonuc = yonlu_hacim_hesapla([_bar(10, 100), _bar(11, 200), _bar(12, 300)])
    assert sonuc["alici_yonlu_adet"] == 500
    assert sonuc["satici_yonlu_adet"] == 0


def test_dusen_kapanislar_satici_yonlu():
    sonuc = yonlu_hacim_hesapla([_bar(12, 100), _bar(11, 200), _bar(10, 300)])
    assert sonuc["satici_yonlu_adet"] == 500
    assert sonuc["alici_yonlu_adet"] == 0


def test_yatay_bar_son_yonu_devralir():
    """Fiyat degismeyen barda son agresif taraf devam ediyor sayilir."""
    sonuc = yonlu_hacim_hesapla([_bar(10, 100), _bar(11, 200), _bar(11, 300)])
    assert sonuc["alici_yonlu_adet"] == 500


def test_bastaki_yatay_barlar_siniflandirilamaz():
    """Onceki kapanis bilinmeden yon cikarilamaz; sifir gibi sunulmamali."""
    sonuc = yonlu_hacim_hesapla([_bar(10, 100), _bar(10, 200), _bar(11, 300)])
    assert sonuc["siniflandirilamayan_adet"] == 300
    assert sonuc["alici_yonlu_adet"] == 300


def test_toplam_ve_yuzdeler_tutarli():
    sonuc = yonlu_hacim_hesapla([_bar(10, 100), _bar(11, 300), _bar(10, 100)])
    assert sonuc["toplam_adet"] == 500
    assert (
        sonuc["alici_yonlu_adet"]
        + sonuc["satici_yonlu_adet"]
        + sonuc["siniflandirilamayan_adet"]
        == sonuc["toplam_adet"]
    )
    assert round(sonuc["alici_yuzde"] + sonuc["satici_yuzde"], 1) <= 100.0


def test_net_adet_farki_verir():
    sonuc = yonlu_hacim_hesapla([_bar(10, 100), _bar(11, 300), _bar(10, 100)])
    assert sonuc["net_adet"] == sonuc["alici_yonlu_adet"] - sonuc["satici_yonlu_adet"]


def test_hacimsiz_barlar_atilir():
    """Seans arasi bos barlar sonucu bozmamali."""
    sonuc = yonlu_hacim_hesapla([_bar(10, 0), _bar(11, 100)])
    assert sonuc["toplam_adet"] == 100


def test_bos_girdi_cokmez():
    sonuc = yonlu_hacim_hesapla([])
    assert sonuc["toplam_adet"] == 0
    assert sonuc["alici_yuzde"] is None


# --- Seans ayirma ----------------------------------------------------------
# Tarih verilmezse "son islem gunu" istenir; hafta sonu/tatilde bugunun
# verisi olmadigi icin son SEANS ayiklanir.

from bist_mcp.hesap import son_seansi_ayikla  # noqa: E402

IKI_GUN = [
    {"zaman": "2026-09-03 10:00", "kapanis": 10, "hacim": 100},
    {"zaman": "2026-09-03 10:05", "kapanis": 11, "hacim": 200},
    {"zaman": "2026-09-04 10:00", "kapanis": 12, "hacim": 300},
]


def test_son_seans_ayiklanir():
    assert [b["zaman"] for b in son_seansi_ayikla(IKI_GUN)] == ["2026-09-04 10:00"]


def test_tek_seansta_hepsi_kalir():
    assert len(son_seansi_ayikla(IKI_GUN[:2])) == 2


def test_bos_listede_cokmez():
    assert son_seansi_ayikla([]) == []


@pytest.mark.network
@pytest.mark.asyncio
async def test_bar_toplami_resmi_hacimden_dusuk_oldugu_soylenir():
    """Olculdu (THYAO 04.09): bar toplami 42,5 mn, resmi gunluk hacim 44,8 mn.

    Kullanici ikisini karsilastirinca tutarsizlik gorur; not bunu soylemeli.
    """
    from bist_mcp.sunucu import yonlu_hacim

    sonuc = await yonlu_hacim("THYAO", baslangic="2026-09-04")
    assert sonuc["toplam_adet"] > 0
    assert "resmî" in sonuc["not"] or "resmi" in sonuc["not"]


@pytest.mark.network
@pytest.mark.asyncio
async def test_gun_ve_hafta_ayri_sonuc_verir():
    from bist_mcp.sunucu import yonlu_hacim

    gun = await yonlu_hacim("THYAO", baslangic="2026-09-04")
    hafta = await yonlu_hacim("THYAO", baslangic="2026-09-01", bitis="2026-09-05")
    assert hafta["toplam_adet"] > gun["toplam_adet"]
    assert hafta["bar_sayisi"] > gun["bar_sayisi"]


def test_birim_acikca_hisse_adedi():
    """Olculdu: alan adi "lot" olunca model "1 lot = 100 hisse" deyip
    adetleri 100 katina cikardi. BIST'te 1 lot = 1 hissedir."""
    sonuc = yonlu_hacim_hesapla([_bar(10, 100), _bar(11, 200)])
    assert "hisse" in sonuc["birim"]
    assert not any(a.endswith("_lot") for a in sonuc), "lot adi kalmis"
