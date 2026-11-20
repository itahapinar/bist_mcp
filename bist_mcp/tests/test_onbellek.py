from pathlib import Path

from bist_mcp.onbellek import Onbellek


def test_yazilan_deger_geri_okunur(tmp_path: Path):
    onbellek = Onbellek(tmp_path / "test.db")
    onbellek.yaz("thyao:fiyat", {"fiyat": 296.0}, ttl_saniye=60)
    assert onbellek.al("thyao:fiyat") == {"fiyat": 296.0}


def test_olmayan_anahtar_none_doner(tmp_path: Path):
    onbellek = Onbellek(tmp_path / "test.db")
    assert onbellek.al("hic_yazilmadi") is None


def test_suresi_gecen_deger_none_doner(tmp_path: Path):
    saat = {"an": 1000.0}
    onbellek = Onbellek(tmp_path / "test.db", zaman=lambda: saat["an"])
    onbellek.yaz("thyao:fiyat", 296.0, ttl_saniye=60)

    saat["an"] = 1059.0
    assert onbellek.al("thyao:fiyat") == 296.0

    saat["an"] = 1061.0
    assert onbellek.al("thyao:fiyat") is None


def test_turkce_karakter_bozulmadan_saklanir(tmp_path: Path):
    onbellek = Onbellek(tmp_path / "test.db")
    onbellek.yaz("garan:kalem", "XVI. ÖZKAYNAKLAR", ttl_saniye=60)
    assert onbellek.al("garan:kalem") == "XVI. ÖZKAYNAKLAR"
