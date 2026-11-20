from bist_mcp.kaynaklar.kap import Sirket, dizin_kur, tablo_grubu_sec, yedek_grup

GARAN_HAM = {
    "stockCode": "GARAN, TGB",
    "kapMemberTitle": "TÜRKİYE GARANTİ BANKASI A.Ş.",
    "mkkMemberOid": "4028e4a140f2ed720140f37cb2a601b7",
    "financialType": "BNK",
}
ASELS_HAM = {
    "stockCode": "ASELS",
    "kapMemberTitle": "ASELSAN ELEKTRONİK SANAYİ VE TİCARET A.Ş.",
    "mkkMemberOid": "4028e4a1413b7ef401413bc2251e0047",
    "financialType": "SIR",
}
THYAO_HAM = {
    "stockCode": "THYAO",
    "kapMemberTitle": "TÜRK HAVA YOLLARI A.O.",
    "mkkMemberOid": "4028e4a140f2ed7201410a1a1c1d0001",
    "financialType": None,
}


def test_virgullu_stockcode_her_kod_icin_giris_acar():
    """Olculmus hata: GARAN'in stockCode degeri "GARAN, TGB".

    Tam eslesme aranirsa GARAN, YKBNK, VAKBN, HALKB, ISCTR kaybediliyordu.
    """
    dizin = dizin_kur([GARAN_HAM])
    assert set(dizin) == {"GARAN", "TGB"}
    assert dizin["GARAN"].mkk_oid == "4028e4a140f2ed720140f37cb2a601b7"
    assert dizin["TGB"].mkk_oid == dizin["GARAN"].mkk_oid


def test_her_giris_kendi_kodunu_tasir():
    dizin = dizin_kur([GARAN_HAM])
    assert dizin["GARAN"].kod == "GARAN"
    assert dizin["TGB"].kod == "TGB"


def test_tek_kodlu_sirket_normal_islenir():
    dizin = dizin_kur([ASELS_HAM])
    assert dizin["ASELS"] == Sirket(
        kod="ASELS",
        unvan="ASELSAN ELEKTRONİK SANAYİ VE TİCARET A.Ş.",
        mkk_oid="4028e4a1413b7ef401413bc2251e0047",
        tip="SIR",
        tum_kodlar=("ASELS",),
    )
    assert not dizin["ASELS"].coklu_sinif


def test_kodsuz_kayit_atlanir():
    dizin = dizin_kur(
        [{"stockCode": "-", "mkkMemberOid": "x"}, {"stockCode": "", "mkkMemberOid": "y"}]
    )
    assert dizin == {}


def test_banka_tipleri_ufrs_k_grubuna_gider():
    for tip in ("BNK", "SIG", "FFF", "KTL"):
        assert tablo_grubu_sec(tip) == "UFRS_K"


def test_sanayi_ve_bos_tip_xi_29_grubuna_gider():
    for tip in ("SIR", "HLD", "GYO", None):
        assert tablo_grubu_sec(tip) == "XI_29"


def test_bos_tip_yedek_gerektirir():
    """807 ticker'in 315'inde financialType bos — THYAO ve EREGL dahil.

    Bos tip XI_29'a gider ama yedek deneme kaldirilamaz.
    """
    dizin = dizin_kur([THYAO_HAM])
    grup = tablo_grubu_sec(dizin["THYAO"].tip)
    assert grup == "XI_29"
    assert yedek_grup(grup) == "UFRS_K"
    assert yedek_grup("UFRS_K") == "XI_29"


# --- Coklu hisse sinifi ---
# Olculdu: ISATR/ISBTR/ISCTR/ISKUR/TIB ayni sirket (Turkiye Is Bankasi),
# KAP'ta tek kayit, odenmis sermaye 10 mlr TL. Bu sermayeyi tek sinifa
# atamak ISATR'da PD/DD'yi 272.562 gosteriyordu.

IS_BANKASI_HAM = {
    "stockCode": "ISATR, ISBTR, ISCTR, ISKUR, TIB",
    "kapMemberTitle": "TÜRKİYE İŞ BANKASI A.Ş.",
    "mkkMemberOid": "oid-isbank",
    "financialType": "BNK",
}


def test_coklu_sinif_isaretleniyor():
    dizin = dizin_kur([IS_BANKASI_HAM])
    assert dizin["ISATR"].coklu_sinif
    assert dizin["ISCTR"].coklu_sinif
    assert dizin["ISATR"].tum_kodlar == ("ISATR", "ISBTR", "ISCTR", "ISKUR", "TIB")


def test_tek_sinif_coklu_isaretlenmez():
    dizin = dizin_kur([ASELS_HAM])
    assert not dizin["ASELS"].coklu_sinif


def test_iki_kodlu_sirket_de_coklu_sayilir():
    """GARAN, TGB - ikinci kod ayri bir siniftir."""
    dizin = dizin_kur([GARAN_HAM])
    assert dizin["GARAN"].coklu_sinif
    assert dizin["GARAN"].tum_kodlar == ("GARAN", "TGB")
