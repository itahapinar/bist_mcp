"""Enflasyon muhasebesi TTM'in isaretini cevirebiliyor; capraz kontrol sart.

Kullanicinin gordugu hata (09.09.2026 02:33): "fk pd" -> PGSUS icin
F/K 68,06. Sirket son 12 ayda ZARAR ediyor, F/K verilmemeliydi.

Is Yatirim'in ham rakamlari (PGSUS, XI_29, TL):
    2025/6  kumulatif    2.497.837.000
    2025/9  kumulatif   13.326.667.532
    2025/12 kumulatif   16.192.047.503
    2026/3  kumulatif   -7.758.354.000
    2026/6  kumulatif  -12.551.835.000

Kural 2'nin formulu: TTM = 16.192.047.503 - 2.497.837.000 + (-12.551.835.000)
                         = 1.142.375.503  -> F/K 68,06

Ama yfinance'in CEYREKLIK net karlari (ayni sirket, TRY):
    Q3-2025 +11.057.598.135   Q4-2025    -224.379.368
    Q1-2026  -7.758.354.000   Q2-2026 -4.793.480.000
    toplam  -1.718.615.233  -> ZARAR, F/K yok

Sebep TMS-29 (enflasyon muhasebesi): YILLIK rapor tum yili yil sonu satin
alma gucune tasiyor, ara donem raporlari kendi donemlerinin gucunde kaliyor.
Ikisini cikarmak gecersiz. Ozkaynakta ayni izi birakiyor -- 2025/9'da
112.697.676.495, 2025/12'de 137.605.332.119: bir ceyrekte +24,9 milyar
artis, o ceyregin kari ise ~2,9 milyar.

Ornekleme (14 hisse) capraz kontrolun ne kadar dar oldugunu gosterdi:
saglikli TRY raporlayanlarda iki hesap %1-11 arasinda ayrisiyor, YALNIZCA
PGSUS'ta isaret degisiyor.

DIKKAT — capraz kontrol yalnizca TRY raporlayanlarda gecerli. THYAO
finansallarini USD raporluyor: Is Yatirim 133.050.933.601 TL, yfinance
2.685.000.000 USD diyor (%98 "fark"). Bu kural 1'in ta kendisi; para
birimi TRY degilse capraz kontrol YAPILMAZ.
"""

import pytest

from bist_mcp.hesap import net_kar_sec

PGSUS_ISYAT = 1_142_375_503
PGSUS_YF = -1_718_615_233


def _sec(kumulatif, ceyreklik, pb="TRY"):
    return net_kar_sec(kumulatif, ceyreklik, pb, "son 12 ay (2026/06 itibarıyla)")


def test_ceyreklik_toplam_birincildir():
    """Kullanicinin gordugu hata: PGSUS F/K 68,06 -- sirket zarar ediyor."""
    deger, aciklama = _sec(PGSUS_ISYAT, PGSUS_YF)
    assert deger == PGSUS_YF
    assert "ceyre" in aciklama.lower()


def test_zarar_oldugu_gibi_dondurulur():
    """fk() zaten pozitif olmayan karda None veriyor; burada bastirilmaz."""
    deger, _ = _sec(PGSUS_ISYAT, PGSUS_YF)
    assert deger < 0


def test_ceyreklik_yoksa_kumulatife_dusulur():
    """Olculdu: yfinance BIST'te her sirkete ceyreklik vermiyor (BETAE)."""
    deger, aciklama = _sec(739_138_194, None)
    assert deger == 739_138_194
    assert aciklama == "son 12 ay (2026/06 itibarıyla)"


def test_para_birimi_TRY_degilse_kumulatif_kalir():
    """REGRESYON kural 1: THYAO finansallarini USD raporluyor.

    Is Yatirim 133,05 mlr TL, yfinance 2,685 mlr USD. USD rakami TL fiyatla
    bolmek 49 kat hatanin ta kendisi; ceyreklik toplam ASLA kullanilmaz.
    """
    deger, _ = _sec(133_050_933_601, 2_685_000_000, "USD")
    assert deger == 133_050_933_601


def test_para_birimi_bilinmiyorsa_kumulatif_kalir():
    assert _sec(133_050_933_601, 2_685_000_000, None)[0] == 133_050_933_601
    assert _sec(133_050_933_601, 2_685_000_000, "")[0] == 133_050_933_601


def test_para_birimi_kucuk_harfle_de_kabul_edilir():
    assert _sec(PGSUS_ISYAT, PGSUS_YF, "try")[0] == PGSUS_YF


def test_ikisi_de_yoksa_none():
    assert _sec(None, None)[0] is None


def test_kumulatif_yoksa_ceyreklik_kullanilir():
    deger, _ = _sec(None, 4_567_698_148)
    assert deger == 4_567_698_148


def test_saglikli_hissede_de_ceyreklik_kullanilir():
    """FROTO: 33,2 mlr -> 29,6 mlr. Olculen medyan degisim 1,07x."""
    assert _sec(33_200_527_986, 29_646_515_000)[0] == 29_646_515_000


# --- para birimi bilinmiyorsa: olcek koruması ---
#
# Olculdu: 627 hissenin 490'i TRY raporluyor, 4'u yabanci (THYAO USD, TAVHL
# EUR, ENKAI, DOCO), 133'unde alan HIC YOK -- ne ekranda ne Ticker.info'da
# (currency=TRY ama financialCurrency=None). O 133'u kumulatife birakmak
# evrenin %21'ini bozuk birakirdi.
#
# Ayrim olcekten yapilir. TRY raporlayan 137 hissede |kumulatif/ceyreklik|:
#     medyan 1,08x   %90 dilim 1,34x   %99 dilim 12,50x   MAKS 14,89x (ISGYO)
# Kur uyusmazliginda ise THYAO 49,6x; USD/TRY ~43 ve EUR/TRY ~47 oldugu icin
# yabanci para raporlayan her sirket 40x uzerine cikar. 25x bu bosluğun tam
# ortasinda.


def test_para_birimi_bilinmiyorsa_ayni_olcekte_ceyreklik_kullanilir():
    deger, aciklama = _sec(33_200_527_986, 29_646_515_000, None)
    assert deger == 29_646_515_000
    assert "ceyre" in aciklama.lower()


def test_para_birimi_bilinmiyorken_olcek_capsa_kumulatif_kalir():
    """THYAO deseni: 133,05 mlr TL'ye karsi 2,685 mlr USD -> 49,6x."""
    deger, _ = _sec(133_050_933_601, 2_685_000_000, None)
    assert deger == 133_050_933_601


def test_bilinmeyen_para_biriminde_esik_altindaki_fark_kabul_edilir():
    """ISGYO 14,89x ile olculen en uc gercek TRY vakasi; bastirilmamali."""
    deger, _ = _sec(14_890_000_000, 1_000_000_000, None)
    assert deger == 1_000_000_000


def test_bilinmeyen_para_biriminde_ters_yonlu_olcek_capmasi_da_reddedilir():
    deger, _ = _sec(1_000_000_000, 30_000_000_000, None)
    assert deger == 1_000_000_000


def test_TRY_biliniyorsa_olcek_kontrolu_UYGULANMAZ():
    """REGRESYON: ISGYO gibi uc vakalar tam da duzeltilmek istenenler."""
    deger, _ = _sec(133_050_933_601, 2_685_000_000, "TRY")
    assert deger == 2_685_000_000


def test_bilinen_yabanci_para_birimi_olcek_yakin_olsa_da_reddedilir():
    """EUR raporlayan bir sirkette rakamlar tesadufen yakin olabilir."""
    deger, _ = _sec(5_773_964_238, 5_500_000_000, "EUR")
    assert deger == 5_773_964_238


# --- ceyreklik toplam ---


def test_ceyreklik_toplam_son_dordu_toplar():
    from bist_mcp.kaynaklar.fiyat import ceyreklik_toplam

    # PGSUS: Q2-2026, Q1-2026, Q4-2025, Q3-2025 (yeniden eskiye) + fazlasi
    assert ceyreklik_toplam(
        [-4_793_480_000, -7_758_354_000, -224_379_368, 11_057_598_135, 5_132_457_000]
    ) == pytest.approx(PGSUS_YF)


def test_ARADA_BOSLUK_VARSA_TOPLAM_VERILMEZ():
    """REGRESYON -- kullanicinin gordugu hata (09.09.2026 04:27): GIPTA F/K 145,65.

    yfinance GIPTA icin Q3-2025'i BOS donuyor:
        2026-06-30      3.886.119
        2026-03-31   -103.901.230
        2025-12-31   -380.127.543
        2025-09-30      EKSIK
        2025-06-30    551.560.081
    Eski surum bosu ATLAYIP bir oncekini aliyordu: son 12 ay yerine 15 aylik
    DELIKLI pencere toplaniyor ve bir yil onceki 551 milyonluk ceyrek iceri
    giriyordu -> +71.417.427 ve F/K 145,65. Is Yatirim'in kumulatifi ise
    -336.474.281, yani sirket ZARARDA ve F/K hic olmamali.
    """
    assert ceyreklik_toplam_gipta() is None


def ceyreklik_toplam_gipta():
    from bist_mcp.kaynaklar.fiyat import ceyreklik_toplam

    return ceyreklik_toplam(
        [3_886_119, -103_901_230, -380_127_543, float("nan"), 551_560_081, -54_948_687]
    )


def test_henuz_aciklanmamis_ceyrek_atlanir():
    """Bas taraftaki bos sutun 'donem var ama rapor gelmedi' demek; atlanir."""
    from bist_mcp.kaynaklar.fiyat import ceyreklik_toplam

    assert ceyreklik_toplam([None, 1.0, 2.0, 3.0, 4.0, 99.0]) == 10.0


def test_bastaki_bos_atlandiktan_sonra_bosluk_yine_reddedilir():
    from bist_mcp.kaynaklar.fiyat import ceyreklik_toplam

    assert ceyreklik_toplam([None, 1.0, 2.0, float("nan"), 3.0, 4.0]) is None


def test_eksik_ceyrek_varsa_toplam_verilmez():
    """Uc ceyregi toplayip 'son 12 ay' demek capraz kontrolu yaniltirdi."""
    from bist_mcp.kaynaklar.fiyat import ceyreklik_toplam

    assert ceyreklik_toplam([1.0, 2.0, 3.0]) is None
    assert ceyreklik_toplam([]) is None
    assert ceyreklik_toplam(None) is None


def test_dortten_fazlasi_varsa_yalnizca_son_dort():
    from bist_mcp.kaynaklar.fiyat import ceyreklik_toplam

    assert ceyreklik_toplam([1.0, 2.0, 3.0, 4.0, 1000.0]) == 10.0


@pytest.mark.network
@pytest.mark.asyncio
async def test_canli_PGSUS_fk_verilmez():
    """REGRESYON (kullanicinin gordugu hata, 09.09.2026 02:33): F/K 68,06."""
    from bist_mcp import sunucu

    arac = getattr(sunucu.finansal_oranlar, "fn", sunucu.finansal_oranlar)
    sonuc = await arac("PGSUS")
    assert sonuc["fk"] is None, f"F/K yine veriliyor: {sonuc['fk']}"
    assert sonuc["net_kar_tl"] < 0, "zarar pozitif gorunuyor"
    assert "ZARAR" in (sonuc.get("not") or ""), "model zararı soylemeye yonlendirilmiyor"
    assert sonuc["pddd"] is not None, "PD/DD gecerli, o bastirilmamali"


@pytest.mark.network
@pytest.mark.asyncio
async def test_canli_saglikli_hisseler_etkilenmez():
    """Capraz kontrol dar olmali; THYAO (USD raporluyor) dahil bozulmamali."""
    from bist_mcp import sunucu

    arac = getattr(sunucu.finansal_oranlar, "fn", sunucu.finansal_oranlar)
    for kod in ("THYAO", "FROTO", "BIMAS"):
        sonuc = await arac(kod)
        assert sonuc["fk"] is not None, f"{kod} icin F/K kayboldu"


# --- tarama tablosu da ayni kari kullanmali ---


def _tarama(tmp_path, ceyreklik, para_birimi="TRY"):
    """Minimal tam_kurulum ortami: tek hisse, sabit rakamlar."""
    from bist_mcp.anlik_gorunum import AnlikGorunum
    from bist_mcp.kaynaklar.kap import Sirket

    class SahteKap:
        async def sirket_dizini(self):
            return {"AAA": Sirket(kod="AAA", unvan="AAA A.S.", mkk_oid="o", tip=None,
                                  tum_kodlar=("AAA",))}

    class SahteIsYatirim:
        async def oran_girdileri(self, kod, tip):
            return {
                "odenmis_sermaye": 1_000_000,
                "ozkaynak_tl": 500_000_000.0,
                "ozkaynak_donem": "2026 ilk 6 ay",
                "net_kar_ttm": 50_000_000.0,       # kumulatif formul
                "net_kar_aciklama": "son 12 ay (2026/06 itibarıyla)",
            }

    class SahteFiyat:
        async def toplu(self, kodlar):
            return {k: {"fiyat": 100.0, "temettu_12ay": 0.0, "ortalama_hacim_tl": 1e9}
                    for k in kodlar}

        async def toplu_kotasyon(self):
            return {}

        async def sirket_bilgi(self, kod):
            return {"sector": "Industrials", "sharesOutstanding": 1_000_000,
                    "financialCurrency": para_birimi}

        async def ceyreklik_net_kar_ttm(self, kod):
            return ceyreklik

    return AnlikGorunum(tmp_path / "g.db", kap=SahteKap(), isyatirim=SahteIsYatirim(),
                        fiyat=SahteFiyat())


@pytest.mark.asyncio
async def test_taramada_da_ceyreklik_kar_kullanilir(tmp_path):
    """hisse_tarama F/K'ya gore siraliyor; ayni kari kullanmazsa siralama bozuk."""
    g = _tarama(tmp_path, ceyreklik=25_000_000.0)
    await g.tam_kurulum(["AAA"])
    satir = g.satir_al("AAA")
    assert satir["net_kar_tl"] == 25_000_000.0
    # piyasa degeri 100 x 1.000.000 = 100.000.000 -> F/K 4,00 (kumulatifle 2,00 olurdu)
    assert satir["fk"] == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_taramada_ceyreklik_yoksa_kumulatife_dusulur(tmp_path):
    g = _tarama(tmp_path, ceyreklik=None)
    await g.tam_kurulum(["AAA"])
    assert g.satir_al("AAA")["net_kar_tl"] == 50_000_000.0


@pytest.mark.asyncio
async def test_taramada_TRY_disi_para_biriminde_kumulatif_kalir(tmp_path):
    """REGRESYON kural 1: USD kari TL fiyata bolmek 49 kat hata."""
    g = _tarama(tmp_path, ceyreklik=25_000_000.0, para_birimi="USD")
    await g.tam_kurulum(["AAA"])
    assert g.satir_al("AAA")["net_kar_tl"] == 50_000_000.0


@pytest.mark.asyncio
async def test_taramada_zarar_fk_uretmez(tmp_path):
    g = _tarama(tmp_path, ceyreklik=-25_000_000.0)
    await g.tam_kurulum(["AAA"])
    satir = g.satir_al("AAA")
    assert satir["net_kar_tl"] == -25_000_000.0
    assert satir["fk"] is None
