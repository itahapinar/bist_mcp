"""Gecmis temettu ODEMELERI: tarih + hisse basina tutar.

Olculdu (DOAS): kullanici "temettu tarihleri" isteyince arac yalnizca KAP
DUYURU tarihlerini donduruyordu ("Kar Payi Dagitim Islemlerine Iliskin
Bildirim, 08.04.2026"). Duyuru tarihi odeme tarihi degildir ve hisse
basina tutari hic vermiyordu.
"""

import datetime as dt

import pytest

from bist_mcp.kaynaklar.fiyat import FiyatKaynak, temettu_penceresi
from bist_mcp.onbellek import Onbellek

BUGUN = dt.date(2026, 9, 7)
HAM = [
    {"tarih": "2026-05-20", "hisse_basina_tl": 15.0},
    {"tarih": "2025-11-12", "hisse_basina_tl": 15.0},
    {"tarih": "2021-06-01", "hisse_basina_tl": 3.5},
]


def test_pencere_disindaki_odemeler_elenir():
    secilen = temettu_penceresi(HAM, yil=2, bugun=BUGUN)
    assert [o["tarih"] for o in secilen] == ["2026-05-20", "2025-11-12"]


def test_yeniden_eskiye_siralanir():
    karisik = [HAM[1], HAM[0]]
    assert [o["tarih"] for o in temettu_penceresi(karisik, yil=5, bugun=BUGUN)] == [
        "2026-05-20",
        "2025-11-12",
    ]


def test_bos_liste_cokmez():
    assert temettu_penceresi([], yil=5, bugun=BUGUN) == []


def _kaynak(tmp_path):
    kaynak = FiyatKaynak(Onbellek(tmp_path / "o.db"))
    sayac = {"n": 0}

    async def sahte(kod):
        sayac["n"] += 1
        return list(HAM)

    kaynak._temettu_indir = sahte
    return kaynak, sayac


@pytest.mark.asyncio
async def test_odemeler_tarih_ve_tutar_verir(tmp_path):
    kaynak, _ = _kaynak(tmp_path)
    odemeler = await kaynak.temettu_odemeleri("DOAS", yil=5, bugun=BUGUN)
    assert odemeler[0] == {"tarih": "2026-05-20", "hisse_basina_tl": 15.0}


@pytest.mark.asyncio
async def test_ikinci_cagri_onbellekten_gelir(tmp_path):
    kaynak, sayac = _kaynak(tmp_path)
    await kaynak.temettu_odemeleri("DOAS", bugun=BUGUN)
    await kaynak.temettu_odemeleri("DOAS", bugun=BUGUN)
    assert sayac["n"] == 1


@pytest.mark.network
@pytest.mark.asyncio
async def test_gercek_hissede_odeme_tarihi_ve_tutari_gelir():
    """DOAS: kullanicinin eksik gordugu alan."""
    from bist_mcp.sunucu import temettu_gecmisi

    sonuc = await temettu_gecmisi("DOAS", yil=3)

    assert sonuc["odemeler"], "odeme gecmisi bos"
    ilk = sonuc["odemeler"][0]
    assert len(ilk["tarih"]) == 10 and ilk["tarih"][4] == "-"
    assert ilk["hisse_basina_tl"] > 0
    # Duyuru ile odeme ayri alanlarda durmali
    assert "kap_bildirimleri" in sonuc


def test_odeme_varsa_duzeltme_notu_eklenir():
    """Tutarlar bugunku hisse adedine gore duzeltilmis seriden geliyor;
    KAP'ta ilan edilen brut tutarla birebir olmayabilir."""
    from bist_mcp.sunucu import odeme_notu

    metin = odeme_notu([{"tarih": "2024-04-19", "hisse_basina_tl": 40.9091}])
    assert "düzeltilmiş" in metin.lower()
    assert "kap" in metin.lower()


def test_odeme_yoksa_not_da_yok():
    from bist_mcp.sunucu import odeme_notu

    assert odeme_notu([]) is None
