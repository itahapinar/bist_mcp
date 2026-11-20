"""Gunluk hafif tazeleme HAFTALIK tam kurulumu KILITLEMEMELI.

Iki kademe farkli hizda degisen sutunlari tazeliyor:
  gunluk hafif tazeleme -> fiyat, temettu, hacim
  haftalik tam kurulum  -> ustune ozkaynak, net kar, hisse adedi, sektor

Ama ikisi de `satir_hesapla` uzerinden gecip ayni `guncelleme` damgasini
`time.time()` yapiyordu (anlik_gorunum.py:95). `yas_saat()` MIN(guncelleme)
okudugu icin gunluk tazeleme YAS SAYACINI HER GUN SIFIRLIYOR; boylece
`tam_kurulum_gerekli` haftalik esigi hicbir zaman goremiyor ve tam kurulum
ilk kurulumdan sonra BIR DAHA CALISMIYOR.

Sonuc: fiyat her gun tazeleniyor ama ozkaynak ve net kar ilk kurulduklari
gunde donuyor. `hisse_tarama`'nin F/K ve PD/DD siralamasi zamanla bayat
kar rakamlariyla hesaplanir -- sessizce, hicbir uyari vermeden.

Cozum: fiyat kademesi finansal kademenin saatine dokunmaz. Ayri damga
(`finansal_guncelleme`) tam kurulumda yazilir, hafif tazelemede korunur.
"""

import time

import pytest

from bist_mcp.anlik_gorunum import AnlikGorunum
from bist_mcp.kaynaklar.kap import Sirket
from bist_mcp.sunucu import HAFTALIK_SAAT, tam_kurulum_gerekli

KODLAR = ["AAA"]


class SahteKap:
    async def sirket_dizini(self):
        return {
            "AAA": Sirket(kod="AAA", unvan="AAA A.S.", mkk_oid="o", tip=None,
                          tum_kodlar=("AAA",))
        }


class SahteIsYatirim:
    async def oran_girdileri(self, kod, tip):
        return {
            "odenmis_sermaye": 1_000_000,
            "ozkaynak_tl": 500_000_000.0,
            "ozkaynak_donem": "2026 ilk 6 ay",
            "net_kar_ttm": 50_000_000.0,
            "net_kar_aciklama": "son 12 ay",
        }


class SahteFiyat:
    async def toplu(self, kodlar):
        return {k: {"fiyat": 100.0, "temettu_12ay": 0.0, "ortalama_hacim_tl": 1e9}
                for k in kodlar}

    async def toplu_kotasyon(self):
        return {}

    async def sirket_bilgi(self, kod):
        return {"sector": "Industrials", "sharesOutstanding": 1_000_000,
                "financialCurrency": "TRY"}

    async def ceyreklik_net_kar_ttm(self, kod):
        return None


def _gorunum(tmp_path):
    return AnlikGorunum(tmp_path / "g.db", kap=SahteKap(), isyatirim=SahteIsYatirim(),
                        fiyat=SahteFiyat())


def _bir_hafta_gecir(gorunum):
    """Satirlardaki TUM zaman damgalarini haftalik esigin otesine tasir."""
    eski = time.time() - (HAFTALIK_SAAT + 1) * 3600
    damgalar = [s["name"] for s in gorunum._baglanti.execute("PRAGMA table_info(gorunum)")
                if s["name"].endswith("guncelleme")]
    assert damgalar, "zaman damgasi sutunu yok"
    for ad in damgalar:
        gorunum._baglanti.execute(f"UPDATE gorunum SET {ad} = ?", (eski,))
    gorunum._baglanti.commit()


@pytest.mark.asyncio
async def test_gunluk_tazeleme_haftalik_kurulumu_kilitlemez(tmp_path):
    """ASIL HATA: hafif tazeleme yas sayacini sifirlayip tam kurulumu oluyordu."""
    g = _gorunum(tmp_path)
    await g.tam_kurulum(KODLAR)
    _bir_hafta_gecir(g)

    assert tam_kurulum_gerekli(g.finansal_yas_saat(), g.tarama_tamam())

    await g.hafif_tazele(KODLAR)  # gunluk tazeleme: yalnizca fiyat kademesi

    assert tam_kurulum_gerekli(g.finansal_yas_saat(), g.tarama_tamam()), (
        "gunluk fiyat tazelemesi haftalik finansal tazelemeyi kilitledi"
    )


@pytest.mark.asyncio
async def test_tam_kurulum_finansal_saati_sifirlar(tmp_path):
    g = _gorunum(tmp_path)
    await g.tam_kurulum(KODLAR)
    _bir_hafta_gecir(g)
    await g.tam_kurulum(KODLAR)

    assert not tam_kurulum_gerekli(g.finansal_yas_saat(), g.tarama_tamam())


@pytest.mark.asyncio
async def test_veri_yasi_fiyat_kademesini_yansitmaya_devam_eder(tmp_path):
    """REGRESYON: hisse_tarama'nin `veri_yasi_saat` alani FIYAT yasidir."""
    g = _gorunum(tmp_path)
    await g.tam_kurulum(KODLAR)
    _bir_hafta_gecir(g)
    await g.hafif_tazele(KODLAR)

    assert g.yas_saat() < 1.0


@pytest.mark.asyncio
async def test_eski_veritabaninda_finansal_yas_bilinmez(tmp_path):
    """Goc: sutun sonradan eklendi, eski satirlarda NULL -> bir kez tam kurulum."""
    g = _gorunum(tmp_path)
    await g.tam_kurulum(KODLAR)
    g._baglanti.execute("UPDATE gorunum SET finansal_guncelleme = NULL")
    g._baglanti.commit()

    assert g.finansal_yas_saat() is None
    assert tam_kurulum_gerekli(g.finansal_yas_saat(), g.tarama_tamam())


# --- Bakim dongusu dogru saate bakmali -------------------------------------
# Yukaridaki testler `finansal_yas_saat()`i DOGRUDAN cagiriyor, yani
# sunucu.gorunum_bakim icindeki baglanti kapsam disi kaliyordu: karar tekrar
# `yas_saat()`e cevrilse testler yine gecerdi. Hatanin yasadigi yer tam da
# o satirdi, bu yuzden ayrica sinaniyor.


@pytest.mark.asyncio
async def test_bakim_dongusu_finansal_saate_bakar(monkeypatch):
    import asyncio

    from bist_mcp import sunucu

    sorulanlar: list[str] = []

    class SahteGorunum:
        def yas_saat(self):
            sorulanlar.append("fiyat")
            return 0.0

        def finansal_yas_saat(self):
            sorulanlar.append("finansal")
            return 0.0

        def tarama_tamam(self):
            return True

        async def tam_kurulum(self, evren):
            return 0

        async def hafif_tazele(self, evren):
            return 0

    async def sahte_evren(_kap):
        return ["AAA"]

    async def dongu_disina_cik(_sure):
        raise asyncio.CancelledError

    monkeypatch.setattr(sunucu, "gorunum", SahteGorunum())
    monkeypatch.setattr(sunucu, "tarama_evreni", sahte_evren)
    monkeypatch.setattr(sunucu.asyncio, "sleep", dongu_disina_cik)

    with pytest.raises(asyncio.CancelledError):
        await sunucu.gorunum_bakim()

    assert "finansal" in sorulanlar, "haftalik karar finansal saate bakmiyor"
