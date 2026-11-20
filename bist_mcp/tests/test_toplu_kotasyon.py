"""Toplu indirme de son seansi kaciriyordu; ekran kotasyonuyla tamamlanir.

Kural 36 tekil `anlik` yolunu duzeltti (history_metadata ayni istekle
geliyor). Ama tarama tablosunu dolduran `toplu()` `yf.download` kullaniyor
ve o uc nokta hisse basina ustveri VERMIYOR. Sonuc (olculdu, 09.09.2026
01:17 taramasi): gorunum.db'de THYAO 296,00 (gercegi 305,00), SISE 39,08
(gercegi 45,82) -- F/K ve PD/DD de bu fiyatlardan turuyordu.

Beklemek cozmuyor: THYAO'nun 07.09 gunluk bari bir islem gunu sonra, 1 aylik
seride de HALA yok. Bosluk kalici.

Cozum olarak Yahoo ekran (screener) uc noktasi olculdu:
    yf.screen(EquityQuery("eq", ["exchange", "IST"]), size=250)
    -> 627 hisse, 3 istek, 1,4 sn
Fiyatlar hisse basina kotasyonla BIREBIR ayni (THYAO 305,00, SISE 45,82,
INTET 68,20, ASELS 390,00, MEKAG 3,02, SARAE 81,75). Yani yaklasik degil.

Tarama tablosundaki 630 kodun 627'si kapsaniyor; ISATR, ISKUR ve UMPAS
ekranda yok, onlar gunluk bara duser.

DIKKAT: ekran kaydi priceToBook/trailingPE/dividendYield/marketCap gibi
YASAK alanlari da tasiyor (kural 1). Kotasyon satiri bu yuzden beyaz liste
ile kurulur.
"""

import pytest

from bist_mcp.kaynaklar.fiyat import (
    YASAK_INFO_ALANLARI,
    ekran_kotasyonlari,
    kotasyon_satiri,
    kotasyonla_tamamla,
)

# Gercek ekran kaydi (kisaltilmis): THYAO, 08.09.2026 kapanisi.
THYAO_KAYIT = {
    "symbol": "THYAO.IS",
    "regularMarketPrice": 305.0,
    "regularMarketTime": 1788880198,
    "gmtOffSetMilliseconds": 10800000,
    "regularMarketPreviousClose": 296.75,
    "regularMarketDayHigh": 305.5,
    "regularMarketDayLow": 295.75,
    "regularMarketVolume": 50542920,
    "currency": "TRY",
    # Kural 1'in yasakladigi alanlar; ekran bunlari da gonderiyor.
    "priceToBook": 18.635105,
    "trailingPE": 12.4,
    "dividendYield": 2.28,
    "marketCap": 418546422665,
    "bookValue": 16.37,
}

# yf.download'dan gelen satir: son gecerli kapanis 04.09, iki seans eski.
THYAO_TOPLU = {
    "fiyat": 296.0,
    "temettu_12ay": 3.5,
    "ortalama_hacim_tl": 13_000_000_000.0,
    "tarih": "2026-09-04",
}


def test_kotasyon_satiri_ham_alanlari_alir():
    k = kotasyon_satiri(THYAO_KAYIT)
    assert k["kod"] == "THYAO"
    assert k["fiyat"] == 305.0
    assert k["tarih"] == "2026-09-08"


def test_kotasyon_satiri_yasak_alanlari_tasimaz():
    """REGRESYON kural 1: ekran hazir oranlari da gonderiyor, sizmamali."""
    k = kotasyon_satiri(THYAO_KAYIT)
    assert not (set(k) & YASAK_INFO_ALANLARI)


def test_kotasyon_satiri_milisaniyelik_ofseti_cevirir():
    """Ekran gmtOffSetMilliseconds veriyor; saniye sanilirsa gun kayar."""
    assert kotasyon_satiri(THYAO_KAYIT)["tarih"] == "2026-09-08"


def test_fiyati_olmayan_kayit_atilir():
    assert kotasyon_satiri({"symbol": "XXXX.IS", "regularMarketTime": 1788880198}) is None


def test_zamani_olmayan_kayit_atilir():
    assert kotasyon_satiri({"symbol": "XXXX.IS", "regularMarketPrice": 5.0}) is None


def test_sembolsuz_kayit_atilir():
    assert kotasyon_satiri({"regularMarketPrice": 5.0, "regularMarketTime": 1}) is None


def test_ekran_kotasyonlari_koda_gore_dizilir():
    d = ekran_kotasyonlari([THYAO_KAYIT, {"bozuk": True}])
    assert set(d) == {"THYAO"}
    assert d["THYAO"]["fiyat"] == 305.0


def test_gecikmis_toplu_satir_kotasyondan_tamamlanir():
    sonuc = kotasyonla_tamamla({"THYAO": THYAO_TOPLU}, ekran_kotasyonlari([THYAO_KAYIT]))
    assert sonuc["THYAO"]["fiyat"] == 305.0
    assert sonuc["THYAO"]["tarih"] == "2026-09-08"


def test_temettu_ve_hacim_korunur():
    """Fiyat kotasyondan gelir ama temettu/hacim toplu indirmenin isi."""
    sonuc = kotasyonla_tamamla({"THYAO": THYAO_TOPLU}, ekran_kotasyonlari([THYAO_KAYIT]))
    assert sonuc["THYAO"]["temettu_12ay"] == 3.5
    assert sonuc["THYAO"]["ortalama_hacim_tl"] == 13_000_000_000.0


def test_toplu_guncelse_dokunulmaz():
    guncel = {"THYAO": {**THYAO_TOPLU, "tarih": "2026-09-08", "fiyat": 305.0}}
    assert kotasyonla_tamamla(guncel, ekran_kotasyonlari([THYAO_KAYIT])) == guncel


def test_kotasyon_daha_eskiyse_dokunulmaz():
    ileri = {"THYAO": {**THYAO_TOPLU, "tarih": "2026-09-09", "fiyat": 310.0}}
    assert kotasyonla_tamamla(ileri, ekran_kotasyonlari([THYAO_KAYIT])) == ileri


def test_ekranda_olmayan_hisse_gunluk_barda_kalir():
    """Olculdu: ISATR, ISKUR, UMPAS ekranda yok."""
    toplu = {"ISATR": {**THYAO_TOPLU}}
    assert kotasyonla_tamamla(toplu, ekran_kotasyonlari([THYAO_KAYIT])) == toplu


def test_kotasyon_gelmezse_toplu_aynen_doner():
    """Ekran ucu nokta bozulursa tarama eski davranisla calismaya devam eder."""
    toplu = {"THYAO": THYAO_TOPLU}
    assert kotasyonla_tamamla(toplu, {}) == toplu


def test_ekran_fazla_hisse_getirse_de_toplu_buyumez():
    """Ekran 627 hisse doner; toplu() yalnizca istenen kodlari kapsamali."""
    sonuc = kotasyonla_tamamla({}, ekran_kotasyonlari([THYAO_KAYIT]))
    assert sonuc == {}


# --- tarama tablosu gercekten tamamliyor mu ---
#
# Tamamlama toplu()'da DEGIL AnlikGorunum'da: toplu()'yu cagiran
# finansal_oranlar ve temettu_gecmisi fiyati kullanmiyor (onlar `anlik`tan
# aliyor), oraya koymak her soruya 3 gereksiz ekran istegi ekliyordu ve
# Yahoo hiz sinirini tetikliyordu (olculdu 09.09.2026 02:13, FROTO).


def _gorunum(tmp_path, kotasyonlar):
    from bist_mcp.anlik_gorunum import AnlikGorunum

    class SahteFiyat:
        async def toplu(self, kodlar):
            return {"THYAO": dict(THYAO_TOPLU)}

        async def toplu_kotasyon(self):
            return kotasyonlar

    gorunum = AnlikGorunum(tmp_path / "g.db", kap=None, isyatirim=None, fiyat=SahteFiyat())
    gorunum.satir_yaz({"kod": "THYAO", "hisse_adedi": 1_000_000, "fiyat": 296.0})
    return gorunum


@pytest.mark.asyncio
async def test_tarama_fiyati_kotasyondan_tamamlanir(tmp_path):
    gorunum = _gorunum(tmp_path, ekran_kotasyonlari([THYAO_KAYIT]))
    assert await gorunum.hafif_tazele(["THYAO"]) == 1
    assert gorunum.satir_al("THYAO")["fiyat"] == 305.0


@pytest.mark.asyncio
async def test_ekran_cokerse_tarama_gunluk_barla_devam_eder(tmp_path):
    """REGRESYON: kotasyon ucu noktasi bozulursa tarama durmamali."""
    gorunum = _gorunum(tmp_path, {})
    assert await gorunum.hafif_tazele(["THYAO"]) == 1
    assert gorunum.satir_al("THYAO")["fiyat"] == 296.0


@pytest.mark.asyncio
async def test_oran_yolunda_ekran_istegi_YAPILMAZ():
    """REGRESYON (olculdu 09.09.2026 02:13): finansal_oranlar/temettu_gecmisi
    fiyati `anlik`tan aliyor; toplu() icine tamamlama koymak her soruya 3
    ekran istegi ekliyor ve Yahoo "Too Many Requests" veriyordu."""
    import inspect

    from bist_mcp.kaynaklar import fiyat as modul

    assert "toplu_kotasyon" not in inspect.getsource(modul.FiyatKaynak.toplu)


@pytest.mark.network
@pytest.mark.asyncio
async def test_canli_ekran_borsanin_tamamini_getirir():
    """Olculdu: 627 hisse. Uc nokta degisirse bu test dusmeli."""
    from bist_mcp.kaynaklar.fiyat import FiyatKaynak
    from bist_mcp.onbellek import Onbellek

    kotasyonlar = await FiyatKaynak(Onbellek(":memory:")).toplu_kotasyon()
    assert len(kotasyonlar) > 500, f"yalnizca {len(kotasyonlar)} hisse geldi"
    assert "THYAO" in kotasyonlar
    assert not (set(kotasyonlar["THYAO"]) & YASAK_INFO_ALANLARI)


@pytest.mark.network
@pytest.mark.asyncio
async def test_canli_ekran_fiyati_tekil_kotasyonla_ayni():
    """Yaklasik degil, BIREBIR olmali."""
    import yfinance as yf

    from bist_mcp.kaynaklar.fiyat import FiyatKaynak
    from bist_mcp.onbellek import Onbellek

    kotasyonlar = await FiyatKaynak(Onbellek(":memory:")).toplu_kotasyon()
    for kod in ("THYAO", "ASELS", "SISE"):
        tekil = round(float(yf.Ticker(f"{kod}.IS").fast_info["lastPrice"]), 2)
        assert kotasyonlar[kod]["fiyat"] == pytest.approx(tekil, abs=0.01), kod
