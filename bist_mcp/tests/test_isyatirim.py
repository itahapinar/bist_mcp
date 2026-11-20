import datetime as dt

import pytest

from bist_mcp.kaynaklar.isyatirim import (
    IsYatirimIstemci,
    dolu_slotlar,
    donem_adaylari,
    donem_etiketi,
    kalem_ayikla,
    kalem_bul,
    sayiya_cevir,
    net_kar_ttm,
    OZKAYNAK_ADLARI,
    NET_KAR_ADLARI,
    ANA_OZKAYNAK_ADLARI,
    AZINLIK_OZKAYNAK_ADLARI,
    ANA_KAR_ADLARI,
    AZINLIK_KAR_ADLARI,
    ana_ortaklik_payi,
    hisse_adedi_sec,
    guncel_donem_sec,
    sifir_satirlari_at,
    tablo_bol,
)

HAM_YANIT = {
    "value": [
        {
            "itemDescTr": "Özkaynaklar",
            "itemCode": "2O",
            "value1": 1073081134047,
            "value2": 950000000000,
        },
        {
            "itemDescTr": "Dönem Karı (Zararı)",
            "itemCode": "2P",
            "value1": 139092773392,
            "value2": 120000000000,
        },
        {"itemDescTr": "Boş Kalem", "itemCode": "2Z", "value1": 0, "value2": 0},
        {"itemDescTr": "Kısmen Dolu", "itemCode": "2Y", "value1": 0, "value2": 55},
    ]
}


def test_kalem_ayiklama_ad_ve_degerleri_cikarir():
    kalemler = kalem_ayikla(HAM_YANIT)
    assert kalemler[0]["ad"] == "Özkaynaklar"
    assert kalemler[0]["degerler"] == [1073081134047, 950000000000]


def test_kalem_adlarina_dokunulmaz():
    """Banka bilancosunda 'XVI. ÖZKAYNAKLAR' neyse o kalir."""
    ham = {"value": [{"itemDescTr": "XVI. ÖZKAYNAKLAR", "value1": 446636140000}]}
    assert kalem_ayikla(ham)[0]["ad"] == "XVI. ÖZKAYNAKLAR"


def test_tum_donemlerde_sifir_olan_satir_atilir():
    """GARAN'in 192 satirinin yarisindan fazlasi boyle."""
    kalan = sifir_satirlari_at(kalem_ayikla(HAM_YANIT))
    adlar = [k["ad"] for k in kalan]
    assert "Boş Kalem" not in adlar
    assert "Kısmen Dolu" in adlar
    assert "Özkaynaklar" in adlar


def test_kalem_bul_ilk_eslesen_adayi_doner():
    kalemler = kalem_ayikla(HAM_YANIT)
    assert kalem_bul(kalemler, "XVI. ÖZKAYNAKLAR", "Özkaynaklar") == 1073081134047


def test_kalem_bul_eslesme_yoksa_none_doner():
    kalemler = kalem_ayikla(HAM_YANIT)
    assert kalem_bul(kalemler, "Olmayan Kalem") is None


def test_bos_yanit_bos_liste_doner():
    assert kalem_ayikla({"value": []}) == []
    assert kalem_ayikla({}) == []


# --- Donem secimi: takvim aritmetigi yerine bos slot atma ---

YAYIMLANMAMIS_ILK_SLOT = {
    "value": [
        {"itemDescTr": "Dönen Varlıklar", "value1": None, "value2": 512191000000,
         "value3": 485646000000, "value4": 513912099203},
        # Bu kalem en eski donemde raporlanmamis — slot bazinda hizalama sart.
        {"itemDescTr": "Seyrek Kalem", "value1": None, "value2": 10,
         "value3": 20, "value4": None},
    ]
}


def test_tamamen_bos_slot_tespit_edilir():
    """Olculdu (2026-09-05): 2026/9 henuz yayimlanmamis, tum satirlarda None."""
    assert dolu_slotlar(YAYIMLANMAMIS_ILK_SLOT) == [2, 3, 4]


def test_degerler_slot_bazinda_hizalanir():
    """REGRESYON: satir bazinda None atmak degerleri bir donem kaydiriyordu.

    'Seyrek Kalem' son donemde raporlanmamis; naif atma onu [10, 20] yapip
    20'yi yanlis doneme yazardi.
    """
    kalemler = kalem_ayikla(YAYIMLANMAMIS_ILK_SLOT)
    assert kalemler[0]["degerler"] == [512191000000, 485646000000, 513912099203]
    assert kalemler[1]["degerler"] == [10, 20, None]


def test_yillik_adaylar_bu_yildan_geriye_gider():
    adaylar = donem_adaylari("yillik", bugun=dt.date(2026, 9, 5))
    assert adaylar[:3] == [(2026, 12), (2025, 12), (2024, 12)]


def test_ceyreklik_adaylar_uc_ayda_bir_geriler():
    adaylar = donem_adaylari("ceyreklik", bugun=dt.date(2026, 9, 5))
    assert adaylar[:5] == [(2026, 12), (2026, 9), (2026, 6), (2026, 3), (2025, 12)]


def test_donem_etiketleri_turkce():
    assert donem_etiketi(2025, 12, "yillik") == "2025 yıllık"
    assert donem_etiketi(2026, 6, "ceyreklik") == "2026 ilk 6 ay"


# --- Deger tipi: Is Yatirim STRING doner ---

STRINGLI_YANIT = {
    "value": [
        {"itemDescTr": "Özkaynaklar", "value1": "1073081134047"},
        {"itemDescTr": "Zarar Kalemi", "value1": "-941964141907"},
        {"itemDescTr": "Sıfır Kalem", "value1": "0"},
    ]
}


def test_string_degerler_sayiya_cevrilir():
    """REGRESYON: ham deger '1073081134047' string gelir; oran hesabi bolemez."""
    assert sayiya_cevir("1073081134047") == 1073081134047.0
    assert sayiya_cevir("-941964141907") == -941964141907.0
    assert sayiya_cevir(None) is None
    assert sayiya_cevir("") is None


def test_kalem_ayikla_sayi_dondurur():
    kalemler = kalem_ayikla(STRINGLI_YANIT)
    assert kalemler[0]["degerler"] == [1073081134047.0]
    assert isinstance(kalemler[0]["degerler"][0], float)


def test_string_sifir_satiri_da_atilir():
    """REGRESYON: '0' != 0 oldugu icin sifir satirlari hic atilmiyordu."""
    kalan = sifir_satirlari_at(kalem_ayikla(STRINGLI_YANIT))
    assert [k["ad"] for k in kalan] == ["Özkaynaklar", "Zarar Kalemi"]


def test_turkce_ondalik_formati_da_cozulur():
    assert sayiya_cevir("1.234.567,89") == 1234567.89


# --- Tablo bolme: Is Yatirim bilanco+gelir+nakit'i TEK listede donduruyor ---

SANAYI_KALEMLERI = [
    {"ad": "Dönen Varlıklar", "degerler": [1]},
    {"ad": "TOPLAM KAYNAKLAR", "degerler": [2]},
    {"ad": "BRÜT KAR (ZARAR)", "degerler": [3]},
    {"ad": "DÖNEM KARI (ZARARI)", "degerler": [4]},
    {"ad": "İşletme Faaliyetlerinden Kaynaklanan Net Nakit", "degerler": [5]},
    {"ad": "Dönem Sonu Nakit", "degerler": [6]},
]

BANKA_KALEMLERI = [
    {"ad": "AKTİF TOPLAMI", "degerler": [1]},
    {"ad": "XVI. ÖZKAYNAKLAR", "degerler": [2]},
    {"ad": "PASİF TOPLAMI", "degerler": [3]},
    {"ad": "I. FAİZ GELİRLERİ", "degerler": [4]},
    {"ad": "XXIII. NET DÖNEM KARI/ZARARI (XVII+XXII)", "degerler": [5]},
]


def test_sanayi_tablosu_uce_bolunur():
    b = tablo_bol(SANAYI_KALEMLERI)
    assert [k["ad"] for k in b["bilanco"]] == ["Dönen Varlıklar", "TOPLAM KAYNAKLAR"]
    assert [k["ad"] for k in b["gelir"]] == ["BRÜT KAR (ZARAR)", "DÖNEM KARI (ZARARI)"]
    assert len(b["nakit"]) == 2


def test_banka_tablosunda_nakit_bolumu_yok():
    """Olculdu: GARAN gelir tablosuyla bitiyor, nakit akisi bolumu yok."""
    b = tablo_bol(BANKA_KALEMLERI)
    assert b["bilanco"][-1]["ad"] == "PASİF TOPLAMI"
    assert len(b["gelir"]) == 2
    assert b["nakit"] == []


def test_isaret_yoksa_uydurma_bolme_yapilmaz():
    kalemler = [{"ad": "Bilinmeyen Kalem", "degerler": [1]}]
    b = tablo_bol(kalemler)
    assert b["bilanco"] == []
    assert b["nakit"] == []


# --- Donem semantigi: ozkaynak STOK, net kar AKIS ---
# Olculdu (BETAE, 06.09.2026) - gercek degerler: PD/DD 5,59 / F/K 44,27
#   ozkaynak 2025 yillik  3.602.650.175  -> PD/DD 9,08  YANLIS
#   ozkaynak 2026 ilk 6ay 5.849.988.146  -> PD/DD 5,59  DOGRU
#   net kar  2025 yillik  1.079.327.517  -> F/K   30,32 YANLIS
#   net kar  TTM            739.138.194  -> F/K   44,27 DOGRU

BETAE_H1_2026 = 52_057_130
BETAE_H1_2025 = 392_246_453
BETAE_YIL_2025 = 1_079_327_517


def test_ttm_gecen_yil_ayni_donemi_cikarip_bu_yili_ekler():
    """REGRESYON: yillik kari kullanmak BETAE'de F/K'yi 30,32 gosteriyordu.

    Dogru pencere: gecen yil yillik - gecen yil ayni kumulatif + bu yil kumulatif
    """
    sonuc = net_kar_ttm(
        bu_yil_kumulatif=BETAE_H1_2026,
        gecen_yil_ayni_kumulatif=BETAE_H1_2025,
        gecen_yil_yillik=BETAE_YIL_2025,
        ay=6,
    )
    assert round(sonuc) == 739_138_194
    piyasa_degeri = 80.8 * 405_000_000
    assert round(piyasa_degeri / sonuc, 2) == 44.27


def test_donem_yillikse_ttm_dogrudan_o_degerdir():
    """Aralik kumulatifi zaten 12 aylik; duzeltme gerekmez."""
    sonuc = net_kar_ttm(
        bu_yil_kumulatif=BETAE_YIL_2025,
        gecen_yil_ayni_kumulatif=None,
        gecen_yil_yillik=None,
        ay=12,
    )
    assert sonuc == BETAE_YIL_2025


def test_eksik_gecmis_veride_ttm_none():
    """Gecen yilin verisi yoksa uydurma yapilmaz."""
    assert net_kar_ttm(BETAE_H1_2026, None, BETAE_YIL_2025, ay=6) is None
    assert net_kar_ttm(BETAE_H1_2026, BETAE_H1_2025, None, ay=6) is None


def test_guncel_donem_en_yeni_dolu_olani_secer():
    """2026/12 ve 2026/9 henuz yayimlanmamis; en yenisi 2026/6."""
    dolu = {(2026, 6): 100.0, (2026, 3): 50.0, (2025, 12): 200.0}
    assert guncel_donem_sec(dolu) == (2026, 6)


def test_guncel_donem_bos_sozlukte_none():
    assert guncel_donem_sec({}) is None


# --- Sirket tipine gore kalem adlari (4 ayri hesap plani) ---


def test_dort_hesap_planinin_ozkaynak_adi_taniniyor():
    """Tum evren tarandi (630 hisse); bu adlar olmadan koca kategoriler
    tamamen bos donuyordu:
      sigorta        -> ANSGR, TURSG      ("Özsermaye Toplamı")
      katilim bankasi-> ALBRK             ("ÖZKAYNAK", tekil)
    """
    for ad in ("Özkaynaklar", "XVI. ÖZKAYNAKLAR", "Özsermaye Toplamı", "ÖZKAYNAK"):
        assert ad in OZKAYNAK_ADLARI, f"{ad} eksik"


def test_dort_hesap_planinin_net_kar_adi_taniniyor():
    for ad in (
        "DÖNEM KARI (ZARARI)",
        "XXIII. NET DÖNEM KARI/ZARARI (XVII+XXII)",
        "XVIII. NET DÖNEM KARI/ZARARI (XVII+XXII)",
        "F-Dönem Net Karı",
    ):
        assert ad in NET_KAR_ADLARI, f"{ad} eksik"


def test_katilim_bankasi_roma_rakami_bankadan_farkli():
    """ALBRK XVIII kullaniyor, GARAN XXIII. Ikisi de listede olmali."""
    banka = "XXIII. NET DÖNEM KARI/ZARARI (XVII+XXII)"
    katilim = "XVIII. NET DÖNEM KARI/ZARARI (XVII+XXII)"
    assert banka != katilim
    assert banka in NET_KAR_ADLARI and katilim in NET_KAR_ADLARI


def test_kalem_bul_sigorta_adini_bulur():
    kalemler = [{"ad": "Özsermaye Toplamı", "degerler": [40_045_701_921.0]}]
    assert kalem_bul(kalemler, *OZKAYNAK_ADLARI) == 40_045_701_921.0


# --- Ana ortaklik payi: piyasa degeri sadece ana ortakligi temsil eder ---
# Olculdu (AHGAZ, 06.09.2026) - gercek PD/DD 1,72 / F/K 18,22
#   toplam ozkaynak 93,24 mlr icinde 33,30 mlr azinlik payi var
#   toplamla PD/DD 1,08 (yanlis) -> ana ortaklikla 1,67 (dogru araligi)

AHGAZ_BILANCO = [
    {"ad": "Özkaynaklar", "degerler": [93_243_496_922.0]},
    {"ad": "Ana Ortaklığa Ait Özkaynaklar", "degerler": [59_943_874_690.0]},
    {"ad": "Azınlık Payları", "degerler": [33_299_622_232.0]},
]
AHGAZ_GELIR = [
    {"ad": "DÖNEM KARI (ZARARI)", "degerler": [5_821_487_986.0]},
    {"ad": "Azınlık Payları", "degerler": [1_498_878_165.0]},
    {"ad": "Ana Ortaklık Payları", "degerler": [4_322_609_821.0]},
]
GARAN_BILANCO = [
    {"ad": "XVI. ÖZKAYNAKLAR", "degerler": [489_428_000_000.0]},
    {"ad": "16.5 Azınlık Payları", "degerler": [2_769_000_000.0]},
]


def test_dogrudan_ana_ortaklik_satiri_varsa_o_kullanilir():
    sonuc = ana_ortaklik_payi(
        AHGAZ_BILANCO, OZKAYNAK_ADLARI, ANA_OZKAYNAK_ADLARI, AZINLIK_OZKAYNAK_ADLARI
    )
    assert sonuc == 59_943_874_690.0


def test_dogrudan_satir_yoksa_toplamdan_azinlik_cikarilir():
    """Bankalarda ana ortaklik ozkaynagi ayri satir olarak verilmiyor."""
    sonuc = ana_ortaklik_payi(
        GARAN_BILANCO, OZKAYNAK_ADLARI, ANA_OZKAYNAK_ADLARI, AZINLIK_OZKAYNAK_ADLARI
    )
    assert sonuc == 489_428_000_000.0 - 2_769_000_000.0


def test_azinlik_yoksa_toplam_kullanilir():
    solo = [{"ad": "Özkaynaklar", "degerler": [1_000.0]}]
    assert ana_ortaklik_payi(
        solo, OZKAYNAK_ADLARI, ANA_OZKAYNAK_ADLARI, AZINLIK_OZKAYNAK_ADLARI
    ) == 1_000.0


def test_azinlik_paylari_bolum_bazinda_ayrisir():
    """REGRESYON: "Azınlık Payları" hem bilancoda hem gelirde geciyor.

    Duz ad aramasi ozkaynak azinligini (33,3 mlr) kar azinligi (1,5 mlr)
    yerine bulur ve net kari eksiye dusururdu.
    """
    kar = ana_ortaklik_payi(
        AHGAZ_GELIR, NET_KAR_ADLARI, ANA_KAR_ADLARI, AZINLIK_KAR_ADLARI
    )
    assert kar == 4_322_609_821.0
    assert kar > 0


def test_ana_ortaklik_toplamdan_kucuk_olmali():
    toplam = 93_243_496_922.0
    ana = ana_ortaklik_payi(
        AHGAZ_BILANCO, OZKAYNAK_ADLARI, ANA_OZKAYNAK_ADLARI, AZINLIK_OZKAYNAK_ADLARI
    )
    assert ana < toplam, "ana ortaklik payi konsolide toplami asamaz"


# --- Hisse adedi: odenmis sermaye vs yfinance ---
# Olculdu: yfinance geri alinmis paylari dusuyor ve dusuk kaliyor.
#   AHGAZ 2.528.516.915 / 2.600.000.000 = 0,973  -> orani %2,7 saptiriyordu


def test_odenmis_sermaye_tercih_edilir():
    assert hisse_adedi_sec(2_600_000_000, 2_528_516_915) == 2_600_000_000


def test_buyuk_sapmada_bile_odenmis_sermaye_kazanir():
    """REGRESYON: ilk surumde "cok saparsa yfinance'e don" kontrolu vardi ve
    TERS calisiyordu.

    KAP ucuncu kaynak olarak soruldu; kontrol edilebilen 6 vakanin 6'sinda
    da Is Yatirim dogru cikti. FLAP'ta yfinance 150.000 hisse diyor, gercek
    93.750.000 — 625 kat hata. Eski kontrol tam da burada yanlisi secerdi.
    """
    assert hisse_adedi_sec(93_750_000, 150_000) == 93_750_000        # FLAP
    assert hisse_adedi_sec(24_883_200, 829_440_000) == 24_883_200    # PKENT
    assert hisse_adedi_sec(270_000_000, 1_520_000_000) == 270_000_000  # GOODY


def test_tek_kaynak_varsa_o_kullanilir():
    assert hisse_adedi_sec(500, None) == 500
    assert hisse_adedi_sec(None, 700) == 700
    assert hisse_adedi_sec(None, None) is None


# --- Yedek hesap plani icin donem penceresi --------------------------------
# Olculdu (kod izlemesi, 09.09.2026): `oran_girdileri` birincil grup bos
# donunce gecen yila dusuyordu ama dustugu pencereyi DONGU DEGISKENINE
# yaziyordu. Sonuc: yedek grup (UFRS_K) bu yil hic sorulmuyor, gecen yilin
# ayni penceresi IKI KEZ isteniyordu.
#
# Olculen cagri sirasi (birincil bos, yedekte bu yil dolu):
#   XI_29  2026/12..  -> bos
#   XI_29  2025/12..  -> bos
#   UFRS_K 2025/12..  -> BU YIL HIC SORULMADI
#   UFRS_K 2025/12..  -> ayni istek tekrar
#
# Etkisi: KAP'ta financialType'i bos olan 315 ticker'in bankalari/sigortalari
# birincil grupta (XI_29) bos donuyor; yedek grup dogru veriyi tasidigi
# halde ya hic bulunamiyor ya da GECEN YILIN rakami "guncel donem" diye
# etiketleniyor.


class PencereIzleyen(IsYatirimIstemci):
    """Aga cikmaz; hangi grup hangi pencereyle sorulmus onu kaydeder."""

    def __init__(self, onbellek, dolu_grup, dolu_yil):
        super().__init__(onbellek)
        self.cagrilar: list[tuple[str, tuple[int, int]]] = []
        self._dolu_grup = dolu_grup
        self._dolu_yil = dolu_yil

    async def _getir(self, kod, grup, donemler):
        donemler = list(donemler)
        self.cagrilar.append((grup, donemler[0]))
        if grup == self._dolu_grup and donemler[0][0] == self._dolu_yil:
            return {
                "value": [
                    {"itemDescTr": "XVI. ÖZKAYNAKLAR", "value1": "1000"},
                    {"itemDescTr": "PASİF TOPLAMI", "value1": "2000"},
                    {
                        "itemDescTr": "XXIII. NET DÖNEM KARI/ZARARI (XVII+XXII)",
                        "value1": "500",
                    },
                ]
            }
        return {"value": []}


@pytest.mark.asyncio
async def test_yedek_grup_bu_yil_penceresiyle_de_sorulur(tmp_path):
    from bist_mcp.onbellek import Onbellek

    bu_yil = dt.date.today().year
    istemci = PencereIzleyen(
        Onbellek(tmp_path / "o.db"), dolu_grup="UFRS_K", dolu_yil=bu_yil
    )

    girdiler = await istemci.oran_girdileri("AAA", None)

    assert ("UFRS_K", (bu_yil, 12)) in istemci.cagrilar, istemci.cagrilar
    assert girdiler["ozkaynak_tl"] == 1000.0


@pytest.mark.asyncio
async def test_ayni_pencere_iki_kez_istenmez(tmp_path):
    from bist_mcp.onbellek import Onbellek

    istemci = PencereIzleyen(Onbellek(tmp_path / "o.db"), dolu_grup="YOK", dolu_yil=0)

    await istemci.oran_girdileri("AAA", None)

    assert len(istemci.cagrilar) == len(set(istemci.cagrilar)), istemci.cagrilar
