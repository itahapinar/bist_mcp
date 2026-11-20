"""Yahoo gunluk serisi son seansi gec yayimliyor; anlik fiyat geride kaliyordu.

Olculdu (09.09.2026 01:28, seans kapaliyken). yf.Ticker.history(period="5d"):

    THYAO  2026-09-04 Close 296,00 | 2026-09-08 Open/High/Low dolu, Close NaN
           07.09 satiri seride HIC YOK
    SISE   2026-09-04 Close  39,08 | 07.09 ve 08.09 satirlari yok

Kapanisi bos satir dogru sekilde atiliyor ama geriye kalan son satir 1-2
seans eski; bot onu "son fiyat" diye sunuyordu (kullanicinin gordugu hata:
THYAO 296,00 TL / 04.09.2026, gercegi 305,00 TL / 08.09.2026).

Ayni history() cagrisinin ustverisi (history_metadata) o seansi eksiksiz
tasiyor: regularMarketPrice 305,00, DayHigh 305,50, DayLow 295,75,
Volume 50.542.920, Time 08.09.2026 18:09 +03. EK ISTEK GEREKMEZ.

Olculen sapma (gunluk seri -> ustveri): SISE 39,08 -> 45,82 (%17),
INTET 74,55 -> 68,20 (%9), EREGL 37,20 -> 39,92 (%7). Ornekteki 13
hissenin 13'u de gecikmisti.
"""

import datetime as dt

import pytest

from bist_mcp.kaynaklar.fiyat import seans_gunu, ustveriyle_tamamla

# Gercek olcum: THYAO, 08.09.2026 kapanisi.
THYAO_USTVERI = {
    "regularMarketPrice": 305.0,
    "regularMarketTime": 1788880198,  # 08.09.2026 18:09:58 +03
    "regularMarketDayHigh": 305.5,
    "regularMarketDayLow": 295.75,
    "regularMarketVolume": 50542920,
    "previousClose": 296.75,
    "gmtoffset": 10800,
}

# Gunluk seriden kurulan satir: son gecerli kapanis 04.09, iki seans eski.
THYAO_SATIR = {
    "kod": "THYAO",
    "fiyat": 296.0,
    "onceki_kapanis": 291.5,
    "degisim_yuzde": 1.54,
    "gun_yuksek": 299.0,
    "gun_dusuk": 292.25,
    "hacim": 44799808,
    "tarih": "2026-09-04",
    "para_birimi": "TRY",
}


def test_seans_gunu_borsa_saatiyle_hesaplanir():
    assert seans_gunu(THYAO_USTVERI) == "2026-09-08"


def test_seans_gunu_yerel_saat_dilimine_kaymaz():
    """gmtoffset kullanilmazsa UTC'ye gore gun kayabilir."""
    gece = {"regularMarketTime": 1788901200, "gmtoffset": 10800}  # 09.09 00:00 +03
    assert seans_gunu(gece) == "2026-09-09"


def test_zaman_yoksa_gun_bilinmez():
    assert seans_gunu({}) is None
    assert seans_gunu({"regularMarketTime": None}) is None


def test_gecikmis_seri_ustveriden_tamamlanir():
    """Kullanicinin gordugu hata: 296,00 TL / 04.09 yerine 305,00 TL / 08.09."""
    sonuc = ustveriyle_tamamla(THYAO_SATIR, THYAO_USTVERI)
    assert sonuc["fiyat"] == 305.0
    assert sonuc["tarih"] == "2026-09-08"
    assert sonuc["gun_yuksek"] == 305.5
    assert sonuc["gun_dusuk"] == 295.75
    assert sonuc["hacim"] == 50542920


def test_onceki_kapanis_ve_degisim_ustveriden_gelir():
    """Ara seans (07.09) gunluk seride hic yok; degisim ustveriye dayanmali."""
    sonuc = ustveriyle_tamamla(THYAO_SATIR, THYAO_USTVERI)
    assert sonuc["onceki_kapanis"] == 296.75
    assert sonuc["degisim_yuzde"] == 2.78


def test_kimlik_alanlari_korunur():
    sonuc = ustveriyle_tamamla(THYAO_SATIR, THYAO_USTVERI)
    assert sonuc["kod"] == "THYAO"
    assert sonuc["para_birimi"] == "TRY"


def test_gunluk_seri_guncelse_dokunulmaz():
    """Saglikli gun: ustveri ayni seansi gosteriyor, satir degismemeli."""
    satir = {**THYAO_SATIR, "tarih": "2026-09-08", "fiyat": 305.0}
    assert ustveriyle_tamamla(satir, THYAO_USTVERI) == satir


def test_ustveri_daha_eskiyse_dokunulmaz():
    satir = {**THYAO_SATIR, "tarih": "2026-09-09", "fiyat": 310.0}
    assert ustveriyle_tamamla(satir, THYAO_USTVERI) == satir


def test_ustveri_yoksa_satir_aynen_doner():
    assert ustveriyle_tamamla(THYAO_SATIR, {}) == THYAO_SATIR


def test_ustveride_fiyat_yoksa_dokunulmaz():
    eksik = {k: v for k, v in THYAO_USTVERI.items() if k != "regularMarketPrice"}
    assert ustveriyle_tamamla(THYAO_SATIR, eksik) == THYAO_SATIR


def test_gunluk_seri_bosken_ustveriden_satir_kurulur():
    """Yeni halka arzlarda gunluk bar hic olmayabilir; kotasyon yine de var."""
    sonuc = ustveriyle_tamamla({"kod": "THYAO", "para_birimi": "TRY"}, THYAO_USTVERI)
    assert sonuc["fiyat"] == 305.0
    assert sonuc["tarih"] == "2026-09-08"
    assert sonuc["kod"] == "THYAO"


def test_gun_yuksek_dusuk_yoksa_fiyata_duser():
    yalin = {
        "regularMarketPrice": 305.0,
        "regularMarketTime": 1788880198,
        "gmtoffset": 10800,
    }
    sonuc = ustveriyle_tamamla(THYAO_SATIR, yalin)
    assert sonuc["gun_yuksek"] == 305.0
    assert sonuc["gun_dusuk"] == 305.0
    assert sonuc["hacim"] == 0


def test_onceki_kapanis_yoksa_gunluk_serinin_son_kapanisi_kullanilir():
    yalin = {
        "regularMarketPrice": 305.0,
        "regularMarketTime": 1788880198,
        "gmtoffset": 10800,
    }
    sonuc = ustveriyle_tamamla(THYAO_SATIR, yalin)
    assert sonuc["onceki_kapanis"] == 296.0
    assert sonuc["degisim_yuzde"] == 3.04


def test_bozuk_zaman_damgasi_cokmez():
    assert seans_gunu({"regularMarketTime": "abc"}) is None
    assert ustveriyle_tamamla(THYAO_SATIR, {"regularMarketTime": "abc"}) == THYAO_SATIR


@pytest.mark.network
@pytest.mark.asyncio
async def test_anlik_yahoo_kotasyonuyla_ayni_seansi_verir():
    """REGRESYON: anlik fiyat, Yahoo'nun kendi kotasyonundan geri kalmamali.

    Bagimsiz uc nokta (fast_info) ile karsilastirilir; gunluk seri gecikince
    bu test eski kodda THYAO icin 296,00 != 305,00 diye duserdi.
    """
    import yfinance as yf

    from bist_mcp.kaynaklar.fiyat import FiyatKaynak, bist_sembol
    from bist_mcp.onbellek import Onbellek

    sonuc = await FiyatKaynak(Onbellek(":memory:")).anlik("THYAO")
    kotasyon = yf.Ticker(bist_sembol("THYAO")).fast_info["lastPrice"]
    assert sonuc["fiyat"] == pytest.approx(round(float(kotasyon), 2), rel=0.005)


@pytest.mark.network
@pytest.mark.asyncio
async def test_anlik_tarihi_son_islem_gununden_geri_kalmaz():
    from bist_mcp.kaynaklar.fiyat import FiyatKaynak
    from bist_mcp.onbellek import Onbellek

    sonuc = await FiyatKaynak(Onbellek(":memory:")).anlik("THYAO")
    yas = (dt.date.today() - dt.date.fromisoformat(sonuc["tarih"])).days
    assert yas <= 4, f"fiyat {yas} gun eski: {sonuc['tarih']}"
