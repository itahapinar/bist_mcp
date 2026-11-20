import datetime as dt

import pytest

from bist_mcp.kaynaklar.kap import (
    AZAMI_ARALIK_GUN,
    KapIstemci,
    bildirim_sadelestir,
    tarih_pencereleri,
    tekillestir,
)
from bist_mcp.onbellek import Onbellek

HAM_BILDIRIM = {
    "publishDate": "03.09.2026 18:15:48",
    "disclosureClass": "ODA",
    "subject": "Yönetim Kurulu Komiteleri",
    "summary": "Kredi Komitesi Üye Değişikliği",
    "stockCodes": "GARAN, TGB",
    "disclosureIndex": "1301003",
    "attachmentCount": 0,
    "kapTitle": "TÜRKİYE GARANTİ BANKASI A.Ş.",
    "isOldKap": False,
    "ruleType": "X",
}


async def _patlayan():
    raise AssertionError("onbellek doluyken aga cikilmamaliydi")


def test_bildirim_sadelestirme_gerekli_alanlari_tutar():
    sade = bildirim_sadelestir(HAM_BILDIRIM)
    assert sade == {
        "tarih": "03.09.2026 18:15:48",
        "konu": "Yönetim Kurulu Komiteleri",
        "ozet": "Kredi Komitesi Üye Değişikliği",
        "sinif": "ODA",
        "bildirim_no": "1301003",
        "ek_sayisi": 0,
    }


def test_bildirim_sadelestirme_bos_ozeti_atlar():
    ham = dict(HAM_BILDIRIM, summary=None)
    assert bildirim_sadelestir(ham)["ozet"] is None


@pytest.mark.asyncio
async def test_dizin_onbellekten_okunur_ag_beklenmez(tmp_path):
    """Dizin onbellekteyse istemci aga cikmaz."""
    onbellek = Onbellek(tmp_path / "t.db")
    onbellek.yaz(
        "kap:sirket_listesi",
        [
            {
                "stockCode": "ASELS",
                "kapMemberTitle": "ASELSAN",
                "mkkMemberOid": "oid1",
                "financialType": "SIR",
            }
        ],
        ttl_saniye=600,
    )

    istemci = KapIstemci(onbellek)
    istemci._ham_sirket_listesi_getir = _patlayan  # aga cikarsa test kirilir

    dizin = await istemci.sirket_dizini()
    assert dizin["ASELS"].mkk_oid == "oid1"


# --- Tarih araligi bolme ---------------------------------------------------
# Olculen (2026-09-06, THYAO ve MEKAG): byCriteria 365 gunluk araligi kabul
# edip 88/98 kayit donuyor, 366 gun HTTP 500 veriyor. temettu_gecmisi 400 gun
# istedigi icin her cagrida kiriliyordu.


def test_tarih_penceresi_azami_araligi_asmaz():
    bitis = dt.date(2026, 9, 6)
    pencereler = tarih_pencereleri(bitis - dt.timedelta(days=400), bitis)
    assert len(pencereler) == 2
    assert all((b - a).days <= AZAMI_ARALIK_GUN for a, b in pencereler)


def test_tarih_penceresi_araligi_bosluksuz_ve_ustuste_binmeden_kaplar():
    bitis = dt.date(2026, 9, 6)
    baslangic = bitis - dt.timedelta(days=400)
    pencereler = tarih_pencereleri(baslangic, bitis)
    assert pencereler[0][0] == baslangic
    assert pencereler[-1][1] == bitis
    for onceki, sonraki in zip(pencereler, pencereler[1:]):
        assert sonraki[0] == onceki[1] + dt.timedelta(days=1)


def test_tarih_penceresi_kisa_aralikta_tek_parca_kalir():
    bitis = dt.date(2026, 9, 6)
    baslangic = bitis - dt.timedelta(days=90)
    assert tarih_pencereleri(baslangic, bitis) == [(baslangic, bitis)]


def test_tarih_penceresi_tam_sinirda_bolunmez():
    bitis = dt.date(2026, 9, 6)
    baslangic = bitis - dt.timedelta(days=AZAMI_ARALIK_GUN)
    assert tarih_pencereleri(baslangic, bitis) == [(baslangic, bitis)]


def test_tekillestirme_ayni_bildirimi_bir_kez_tutar_ve_yeniden_eskiye_sirala():
    eski = dict(HAM_BILDIRIM, disclosureIndex="1", publishDate="01.02.2026 10:00:00")
    yeni = dict(HAM_BILDIRIM, disclosureIndex="2", publishDate="03.09.2026 18:15:48")
    sonuc = tekillestir([eski, yeni, dict(eski)])
    assert [k["disclosureIndex"] for k in sonuc] == ["2", "1"]


@pytest.mark.asyncio
async def test_bir_yildan_uzun_gecmis_parcalanip_birlestirilir(tmp_path):
    """400 gun istendiginde tek 500'luk istek yerine iki gecerli istek gider."""
    onbellek = Onbellek(tmp_path / "t.db")
    onbellek.yaz(
        "kap:sirket_listesi",
        [{"stockCode": "THYAO", "kapMemberTitle": "THY", "mkkMemberOid": "oid1"}],
        ttl_saniye=600,
    )
    istemci = KapIstemci(onbellek)

    istenen: list[tuple[dt.date, dt.date]] = []

    async def sahte(_oturumlu, _oid, baslangic, bitis):
        if (bitis - baslangic).days > AZAMI_ARALIK_GUN:
            raise AssertionError("365 gunden uzun aralik KAP'ta HTTP 500 doner")
        istenen.append((baslangic, bitis))
        return [dict(HAM_BILDIRIM, disclosureIndex=str(len(istenen)))]

    istemci._ham_bildirimler = sahte

    sonuc = await istemci.bildirimler("THYAO", gun=400)

    assert len(istenen) == 2
    assert {k["bildirim_no"] for k in sonuc} == {"1", "2"}
