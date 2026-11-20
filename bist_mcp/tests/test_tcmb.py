import pytest

from bist_mcp.kaynaklar.tcmb import GOSTERGELER, TcmbIstemci, evds_ayikla, seri_kodu_bul
from bist_mcp.onbellek import Onbellek

HAM = {
    "items": [
        {"Tarih": "01-2026", "TP_FG_J0": "72,5"},
        {"Tarih": "02-2026", "TP_FG_J0": "68,3"},
        {"Tarih": "03-2026", "TP_FG_J0": None},
    ]
}


def test_evds_ayiklama_turkce_ondalik_virgulu_cozer():
    sonuc = evds_ayikla(HAM, "TP.FG.J0")
    assert sonuc[0] == {"tarih": "01-2026", "deger": 72.5}
    assert sonuc[1]["deger"] == 68.3


def test_bos_degerler_atlanir():
    assert len(evds_ayikla(HAM, "TP.FG.J0")) == 2


def test_gostergeler_yalnizca_makro_icerir():
    """Doviz ve altin kur.py'de; EVDS anahtari olmadan da calismalilar."""
    assert set(GOSTERGELER) == {"tufe", "ufe", "politika_faizi", "tahvil_2y"}
    assert "usdtry" not in GOSTERGELER
    assert "gram_altin" not in GOSTERGELER


def test_seri_kodu_bulma_bilinmeyen_gosterge_hata_verir():
    with pytest.raises(ValueError) as hata:
        seri_kodu_bul("olmayan_gosterge")
    assert "olmayan_gosterge" in str(hata.value)


def test_seri_kodu_buyuk_kucuk_harf_duyarsiz():
    assert seri_kodu_bul("TUFE") == seri_kodu_bul("tufe")


@pytest.mark.asyncio
async def test_anahtarsiz_istemci_net_mesaj_doner(tmp_path):
    """Anahtar yoksa cokmez, aciklayici mesaj doner; diger araclar etkilenmez."""
    istemci = TcmbIstemci(Onbellek(tmp_path / "t.db"), api_anahtari=None)
    assert not istemci.etkin
    sonuc = await istemci.gosterge("tufe")
    assert "EVDS_API_KEY" in sonuc["hata"]
    assert "Döviz ve altın bundan etkilenmez" in sonuc["hata"]
