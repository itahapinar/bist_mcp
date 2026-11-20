import pytest

from bist_mcp.sunucu import sunucu

CEKIRDEK = {
    "hisse_ara",
    "anlik_fiyat",
    "gecmis_fiyat",
    "sirket_profili",
    "finansal_tablo",
    "finansal_oranlar",
    "temettu_gecmisi",
    "kap_bildirimleri",
    "kap_bildirim_detay",
    "detayli_analiz",
    "yonlu_hacim",
}


@pytest.mark.asyncio
async def test_cekirdek_araclar_kayitli():
    adlar = {a.name for a in await sunucu.list_tools()}
    assert CEKIRDEK <= adlar


@pytest.mark.asyncio
async def test_her_aracin_turkce_aciklamasi_var():
    for arac in await sunucu.list_tools():
        assert arac.description, f"{arac.name} aciklamasiz"
        assert len(arac.description) > 20, f"{arac.name} aciklamasi cok kisa"


@pytest.mark.asyncio
async def test_finansal_tablo_parametreleri_sinirli():
    """'all' secenegi modele sunulmaz; tek basina baglami sisiriyor."""
    arac = next(a for a in await sunucu.list_tools() if a.name == "finansal_tablo")
    tablo = arac.inputSchema["properties"]["tablo"]
    assert set(tablo["enum"]) == {"bilanco", "gelir", "nakit"}


@pytest.mark.asyncio
async def test_hicbir_aracta_market_parametresi_yok():
    """Kodda 'bist' sabit; model BIST disina cikamaz."""
    for arac in await sunucu.list_tools():
        assert "market" not in arac.inputSchema.get("properties", {})


ANALIZ_VE_MAKRO = {
    "teknik_analiz",
    "hisse_karsilastir",
    "sektor_karsilastirma",
    "hisse_tarama",
    "endeks_verisi",
    "doviz_altin",
    "makro_gosterge",
}


@pytest.mark.asyncio
async def test_toplam_18_arac_kayitli():
    adlar = {a.name for a in await sunucu.list_tools()}
    assert CEKIRDEK | ANALIZ_VE_MAKRO == adlar
    assert len(adlar) == 18


@pytest.mark.asyncio
async def test_analist_gorusu_araci_yok():
    """Bilincli karar: guvenilir kaynagi yok, uydurma arac modeli yaniltir."""
    adlar = {a.name for a in await sunucu.list_tools()}
    assert "analist_gorusu" not in adlar


@pytest.mark.asyncio
async def test_hisse_karsilastir_liste_alir():
    arac = next(a for a in await sunucu.list_tools() if a.name == "hisse_karsilastir")
    assert arac.inputSchema["properties"]["kodlar"]["type"] == "array"


@pytest.mark.asyncio
async def test_belgelerdeki_arac_sayisi_kodla_ayni():
    """Arac eklendiginde README ve CLAUDE.md guncellenmeyi unutuluyordu;
    sayi iki kez geride kaldi (16 yazarken 17, sonra 18 arac vardi)."""
    import io
    import re
    from pathlib import Path

    kok = Path(__file__).resolve().parent.parent.parent
    gercek = len(await sunucu.list_tools())
    for dosya in ("README.md", "CLAUDE.md"):
        metin = io.open(kok / dosya, encoding="utf-8").read()
        # Yalnizca TOPLAM sayiyi bildiren cumleler; "3-4 arac cagirip
        # duruyor" gibi anlatimlar sayilmaz.
        yazilanlar = {int(x) for x in re.findall(r"(\d+) araçlı|(\d+) araç\.", metin) for x in x if x}
        assert yazilanlar, f"{dosya} icinde toplam arac sayisi gecmiyor"
        assert yazilanlar == {gercek}, f"{dosya}: {yazilanlar} yaziyor, gercek {gercek}"
