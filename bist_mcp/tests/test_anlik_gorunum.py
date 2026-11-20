from bist_mcp.anlik_gorunum import AnlikGorunum, satir_hesapla

TEMEL = {
    "kod": "THYAO",
    "unvan": "TÜRK HAVA YOLLARI A.O.",
    "sektor": "Industrials",
    "hisse_adedi": 1_372_283_353,
    "ozkaynak_tl": 1_073_081_134_047,
    "net_kar_tl": 139_092_773_392,
}


def _gorunum(tmp_path):
    return AnlikGorunum(tmp_path / "g.db", kap=None, isyatirim=None, fiyat=None)


def test_satir_hesaplama_oranlari_tl_bazinda_uretir():
    satir = satir_hesapla(TEMEL, fiyat=296.00, temettu_12ay=0.0)
    assert round(satir["pddd"], 2) == 0.38
    assert 2.0 < satir["fk"] < 4.0
    assert satir["temettu_verimi"] == 0.0


def test_eksik_ozkaynakta_oranlar_none_ama_satir_uretilir():
    eksik = dict(TEMEL, ozkaynak_tl=None)
    satir = satir_hesapla(eksik, fiyat=296.00, temettu_12ay=0.0)
    assert satir["pddd"] is None
    assert satir["kod"] == "THYAO"
    assert satir["fiyat"] == 296.00


def test_tabloya_yazilan_satir_geri_okunur(tmp_path):
    gorunum = _gorunum(tmp_path)
    gorunum.satir_yaz(satir_hesapla(TEMEL, fiyat=296.00, temettu_12ay=0.0))
    okunan = gorunum.satirlari_sec()
    assert len(okunan) == 1
    assert okunan[0]["kod"] == "THYAO"


def test_fk_ustsiniri_filtreler(tmp_path):
    gorunum = _gorunum(tmp_path)
    gorunum.satir_yaz(satir_hesapla(TEMEL, fiyat=296.00, temettu_12ay=0.0))  # F/K ~2,9
    pahali = dict(TEMEL, kod="XXXXX", net_kar_tl=1_000_000_000)  # F/K ~406
    gorunum.satir_yaz(satir_hesapla(pahali, fiyat=296.00, temettu_12ay=0.0))

    assert [s["kod"] for s in gorunum.satirlari_sec(fk_max=10)] == ["THYAO"]


def test_temettu_verimi_altsiniri_filtreler(tmp_path):
    gorunum = _gorunum(tmp_path)
    gorunum.satir_yaz(satir_hesapla(TEMEL, fiyat=296.00, temettu_12ay=0.0))
    temettulu = dict(TEMEL, kod="GARAN")
    gorunum.satir_yaz(satir_hesapla(temettulu, fiyat=131.40, temettu_12ay=5.266887))

    assert [s["kod"] for s in gorunum.satirlari_sec(temettu_verimi_min=3.0)] == ["GARAN"]


def test_oranı_none_olan_hisse_filtreye_takilmaz(tmp_path):
    """Ozkaynagi bilinmeyen hisse 'F/K < 10' sonucuna sizmamali."""
    gorunum = _gorunum(tmp_path)
    gorunum.satir_yaz(satir_hesapla(dict(TEMEL, kod="BOSVE", net_kar_tl=None), 100.0, 0.0))
    assert gorunum.satirlari_sec(fk_max=10) == []


def test_sektore_gore_filtreler(tmp_path):
    gorunum = _gorunum(tmp_path)
    gorunum.satir_yaz(satir_hesapla(TEMEL, 296.00, 0.0))
    gorunum.satir_yaz(
        satir_hesapla(dict(TEMEL, kod="GARAN", sektor="Financial Services"), 131.40, 5.27)
    )
    assert [s["kod"] for s in gorunum.satirlari_sec(sektor="Industrials")] == ["THYAO"]


def test_bos_tabloda_yas_none(tmp_path):
    assert _gorunum(tmp_path).yas_saat() is None


def test_dolu_tabloda_yas_sifira_yakin(tmp_path):
    gorunum = _gorunum(tmp_path)
    gorunum.satir_yaz(satir_hesapla(TEMEL, 296.00, 0.0))
    assert gorunum.yas_saat() < 0.1


# --- Likidite: olu hisseler taramaya sizmamali ---


def test_hacim_alt_siniri_olu_hisseleri_eler(tmp_path):
    """Evren BIST geneli oldugu icin gunde birkac lot islem goren kabuk
    sirketler var; F/K'si dusuk diye listenin basina cikip alinamiyorlar.
    """
    gorunum = _gorunum(tmp_path)
    gorunum.satir_yaz(satir_hesapla(TEMEL, 296.00, 0.0, ortalama_hacim_tl=16_000_000_000))
    olu = dict(TEMEL, kod="OLUHS", net_kar_tl=1_000_000)  # cok dusuk F/K
    gorunum.satir_yaz(satir_hesapla(olu, 1.00, 0.0, ortalama_hacim_tl=12_000))

    hepsi = [s["kod"] for s in gorunum.satirlari_sec(fk_max=100000)]
    assert "OLUHS" in hepsi, "filtresiz taramada olu hisse gorunmeli"

    likit = [s["kod"] for s in gorunum.satirlari_sec(fk_max=100000, hacim_min=10_000_000)]
    assert likit == ["THYAO"]


def test_hacmi_bilinmeyen_hisse_hacim_filtresine_takilmaz(tmp_path):
    gorunum = _gorunum(tmp_path)
    gorunum.satir_yaz(satir_hesapla(TEMEL, 296.00, 0.0, ortalama_hacim_tl=None))
    assert gorunum.satirlari_sec(hacim_min=1_000) == []


def test_hacim_sutunu_yaziliyor_ve_okunuyor(tmp_path):
    gorunum = _gorunum(tmp_path)
    gorunum.satir_yaz(satir_hesapla(TEMEL, 296.00, 0.0, ortalama_hacim_tl=16_054_600_000))
    assert gorunum.satirlari_sec()[0]["ortalama_hacim_tl"] == 16_054_600_000


def test_hacme_gore_siralanabilir(tmp_path):
    gorunum = _gorunum(tmp_path)
    gorunum.satir_yaz(satir_hesapla(TEMEL, 296.00, 0.0, ortalama_hacim_tl=1_000))
    gorunum.satir_yaz(
        satir_hesapla(dict(TEMEL, kod="LIKIT"), 100.0, 0.0, ortalama_hacim_tl=9_000_000)
    )
    sonuc = gorunum.satirlari_sec(sirala="ortalama_hacim_tl")
    assert sonuc[0]["kod"] == "LIKIT"


# --- Sema gocu -------------------------------------------------------------
# Olculdu: diskteki gorunum.db hacim sutunu eklenmeden once yaratilmisti ve
# "no column named ortalama_hacim_tl" hatasi veriyordu. CREATE TABLE IF NOT
# EXISTS mevcut tabloya sutun EKLEMEZ; eski veritabani sessizce bozuk kalir
# ve hisse_tarama'nin yazmasi kirilir.

ESKI_SEMA = (
    "CREATE TABLE gorunum ("
    "  kod TEXT PRIMARY KEY, unvan TEXT, sektor TEXT,"
    "  hisse_adedi INTEGER, ozkaynak_tl REAL, net_kar_tl REAL,"
    "  fiyat REAL, temettu_12ay REAL, pddd REAL, fk REAL,"
    "  piyasa_degeri REAL, temettu_verimi REAL, guncelleme REAL"
    ")"
)


def _eski_veritabani(yol):
    import sqlite3

    baglanti = sqlite3.connect(yol)
    baglanti.execute(ESKI_SEMA)
    baglanti.execute(
        "INSERT INTO gorunum (kod, unvan, fiyat) VALUES ('THYAO', 'THY', 296.0)"
    )
    baglanti.commit()
    baglanti.close()


def test_eski_veritabanina_eksik_sutun_eklenir(tmp_path):
    yol = tmp_path / "g.db"
    _eski_veritabani(yol)

    gorunum = AnlikGorunum(yol, kap=None, isyatirim=None, fiyat=None)
    gorunum.satir_yaz(satir_hesapla(TEMEL, fiyat=296.00, temettu_12ay=0.0, ortalama_hacim_tl=1e9))

    satirlar = gorunum.satirlari_sec(hacim_min=1e8)
    assert [s["kod"] for s in satirlar] == ["THYAO"]


def test_gocte_mevcut_veri_korunur(tmp_path):
    yol = tmp_path / "g.db"
    _eski_veritabani(yol)

    gorunum = AnlikGorunum(yol, kap=None, isyatirim=None, fiyat=None)
    kayit = gorunum._baglanti.execute(
        "SELECT unvan, fiyat FROM gorunum WHERE kod = 'THYAO'"
    ).fetchone()
    assert kayit["unvan"] == "THY"
    assert kayit["fiyat"] == 296.0


# --- Kismi ilerleme --------------------------------------------------------
# Olculdu: tam_kurulum butun hisseleri gather ile bekleyip satirlari ancak
# hepsi bitince yaziyordu. Tarama ~7 dakika ve ~700 istek suruyor; surec o
# bitmeden kapanirsa HICBIR ilerleme kaydedilmiyor ve sonraki acilis ayni
# yuku bastan uretiyor. Bot gunlerce ayakta kalacagi icin her yeniden
# baslatma bu bedeli odetirdi.

import asyncio  # noqa: E402

from bist_mcp.kaynaklar.kap import Sirket  # noqa: E402


class SahteKap:
    async def sirket_dizini(self):
        return {
            k: Sirket(kod=k, unvan=f"{k} A.S.", mkk_oid="o", tip=None, tum_kodlar=(k,))
            for k in ("AAA", "BBB")
        }


class SahteFiyat:
    async def toplu(self, kodlar):
        return {
            k: {"fiyat": 100.0, "temettu_12ay": 0.0, "ortalama_hacim_tl": 1e9}
            for k in kodlar
        }

    async def toplu_kotasyon(self):
        """Ekran kotasyonu bu dosyanin konusu degil; aga cikmasin."""
        return {}

    async def sirket_bilgi(self, kod):
        return {"sector": "Industrials", "sharesOutstanding": 1_000_000}

    async def ceyreklik_net_kar_ttm(self, kod):
        """Ceyreklik kar bu dosyanin konusu degil; kumulatife dusulsun."""
        return None


class SahteIsYatirim:
    """BBB'de takilir; AAA'nin satirinin yazilip yazilmadigini olcmek icin."""

    def __init__(self, ozkaynak: dict | None = None):
        self.engel = asyncio.Event()
        self._ozkaynak = ozkaynak or {}

    async def oran_girdileri(self, kod, tip):
        if kod == "BBB":
            await self.engel.wait()
        return {
            "odenmis_sermaye": 1_000_000,
            "ozkaynak_tl": self._ozkaynak.get(kod, 500_000_000.0),
            "net_kar_ttm": 50_000_000.0,
            "net_kar_aciklama": "son 12 ay",
        }


def _tarama_gorunumu(tmp_path):
    isyatirim = SahteIsYatirim()
    gorunum = AnlikGorunum(
        tmp_path / "g.db", kap=SahteKap(), isyatirim=isyatirim, fiyat=SahteFiyat()
    )
    return gorunum, isyatirim


async def _satir_sayisi(gorunum) -> int:
    return gorunum._baglanti.execute("SELECT COUNT(*) FROM gorunum").fetchone()[0]


async def test_yarida_kesilen_tarama_tamamlanan_satirlari_korur(tmp_path):
    gorunum, isyatirim = _tarama_gorunumu(tmp_path)
    gorev = asyncio.create_task(gorunum.tam_kurulum(["AAA", "BBB"]))

    # AAA'nin yazilmasini bekle (kosul bazli, sabit uyku degil).
    for _ in range(200):
        if await _satir_sayisi(gorunum):
            break
        await asyncio.sleep(0.01)

    gorev.cancel()
    isyatirim.engel.set()
    try:
        await gorev
    except asyncio.CancelledError:
        pass

    assert await _satir_sayisi(gorunum) == 1, "tamamlanan satir diske yazilmadi"


async def test_tarama_bitince_tum_satirlar_yazilir(tmp_path):
    gorunum, isyatirim = _tarama_gorunumu(tmp_path)
    isyatirim.engel.set()
    yazilan = await gorunum.tam_kurulum(["AAA", "BBB"])
    assert yazilan == 2
    assert await _satir_sayisi(gorunum) == 2


# --- Coklu hisse sinifi ----------------------------------------------------
# Olculdu: finansal_oranlar coklu sinifta uyari doneyorken tarama tablosuna
# ayni sacma deger yaziliyordu -- ISATR PD/DD 272.562, ISBTR 28.242. Odenmis
# sermaye TUM siniflarin toplami oldugu icin bu siniflarin hisse adedi
# bilinmiyor; oran da piyasa degeri de guvenilmez.


class CokluSinifKap:
    async def sirket_dizini(self):
        return {
            "AAA": Sirket(kod="AAA", unvan="Tek A.S.", mkk_oid="o", tip=None,
                          tum_kodlar=("AAA",)),
            "BBB": Sirket(kod="BBB", unvan="Coklu A.S.", mkk_oid="o", tip=None,
                          tum_kodlar=("BBB", "CCC")),
        }


async def test_coklu_sinifta_MAKUL_oran_korunur(tmp_path):
    """KAP'ta "GARAN, TGB" gibi ikincil kodlar da coklu sinif gorunuyor.

    Bunlar ayri hisse sinifi DEGIL, ayni hissenin baska kodu. Coklu sinif
    diye kosulsuz oran silmek GARAN, VAKBN, YKBNK, TSKB gibi 21 saglam
    hissenin dogru oranini siliyordu (olculdu). Once makullige bakilir.
    """
    isyatirim = SahteIsYatirim()
    isyatirim.engel.set()
    gorunum = AnlikGorunum(
        tmp_path / "g.db", kap=CokluSinifKap(), isyatirim=isyatirim, fiyat=SahteFiyat()
    )
    await gorunum.tam_kurulum(["AAA", "BBB"])

    satir = gorunum._baglanti.execute(
        "SELECT * FROM gorunum WHERE kod = 'BBB'"
    ).fetchone()
    assert satir["pddd"] is not None, "makul oran coklu sinifta da korunmali"


async def test_coklu_sinifta_MAKULSUZ_oran_tabloya_yazilmaz(tmp_path):
    """ISATR PD/DD 272.562 gibi bir deger oran degil, hisse adedi hatasidir."""
    isyatirim = SahteIsYatirim(ozkaynak={"BBB": 1.0})  # defter degeri ~0 -> devasa PD/DD
    isyatirim.engel.set()
    gorunum = AnlikGorunum(
        tmp_path / "g.db", kap=CokluSinifKap(), isyatirim=isyatirim, fiyat=SahteFiyat()
    )
    await gorunum.tam_kurulum(["AAA", "BBB"])

    satirlar = {
        s["kod"]: s
        for s in gorunum._baglanti.execute("SELECT * FROM gorunum").fetchall()
    }
    assert satirlar["AAA"]["pddd"] is not None, "tek sinif etkilenmemeli"
    assert satirlar["BBB"]["pddd"] is None
    assert satirlar["BBB"]["fk"] is None
    assert satirlar["BBB"]["piyasa_degeri"] is None
    assert satirlar["BBB"]["fiyat"] == 100.0, "fiyat gecerli, silinmemeli"


def test_temettu_bilinmiyorsa_satirda_sifir_yazmaz():
    """Sessiz sifir "temettu odenmedi" diye okunuyordu."""
    satir = satir_hesapla(TEMEL, fiyat=296.00, temettu_12ay=None)
    assert satir["temettu_12ay"] is None
    assert satir["temettu_verimi"] is None
