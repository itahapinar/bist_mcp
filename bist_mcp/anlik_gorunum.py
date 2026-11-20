"""Tarama icin BIST-100 anlik gorunumu.

Iki kademeli tazeleme (spec §7.2): sutunlarin degisme hizi cok farkli.
Fiyat her gun degisir, ozkaynak/net kar ceyrekte bir, hisse adedi ve sektor
neredeyse hic.

  Gunluk hafif tazeleme  ~5 sn,  2 istek  — sadece toplu indirme
  Haftalik tam kurulum  ~15 dk, ~1.300 istek — Is Yatirim + yfinance info

  Sureler evren BIST-100'den 807 ticker'a cikinca degisti; yukaridaki
  rakam iki tam kosunun kendi loguyla olculdu (09.09.2026 04:01->04:16
  15,4 dk / 04:39->04:54 14,6 dk, 1.299 Is Yatirim istegi).
"""

import asyncio
import logging
import sqlite3
import time
from pathlib import Path

from bist_mcp.hesap import (
    fk,
    net_kar_sec,
    oran_makul,
    pddd,
    piyasa_degeri,
    temettu_verimi,
)
from bist_mcp.kaynaklar.fiyat import kotasyonla_tamamla
from bist_mcp.kaynaklar.isyatirim import (  # noqa: F401
    NET_KAR_ADLARI,
    OZKAYNAK_ADLARI,
    hisse_adedi_sec,
)

kayit = logging.getLogger(__name__)

# Sutun -> SQLite tipi. Tek kaynak: hem CREATE TABLE hem de eski
# veritabanlarina sutun ekleyen goc buradan okur.
SUTUN_TIPLERI = {
    "kod": "TEXT PRIMARY KEY",
    "unvan": "TEXT",
    "sektor": "TEXT",
    "hisse_adedi": "INTEGER",
    "ozkaynak_tl": "REAL",
    "net_kar_tl": "REAL",
    "fiyat": "REAL",
    "temettu_12ay": "REAL",
    "pddd": "REAL",
    "fk": "REAL",
    "piyasa_degeri": "REAL",
    "temettu_verimi": "REAL",
    "ortalama_hacim_tl": "REAL",
    # Coklu sinifta guvenilmez oran iptal edilir; isaret SATIRDA kalir ki
    # hafif tazeleme oranlari yeniden hesaplayip iptali bozmasin.
    "oran_gecersiz": "INTEGER",
    "guncelleme": "REAL",
    # IKI KADEME, IKI SAAT. Tek damga kullanmak haftalik tazelemeyi
    # kilitliyordu: gunluk hafif tazeleme de `guncelleme`yi bugune cekiyor,
    # `yas_saat()` MIN(guncelleme) okudugu icin haftalik esik hicbir zaman
    # asilmiyor ve tam kurulum ilk kurulumdan sonra BIR DAHA kosmuyordu
    # (olculdu: esige bir gun kala gunluk tazeleme yasi 169 saatten 0'a
    # dusuruyor). Fiyat kademesi bu damgaya DOKUNMAZ.
    "finansal_guncelleme": "REAL",
}
SUTUNLAR = tuple(SUTUN_TIPLERI)

# 630 hisselik tam kurulumda tum gorevleri ayni anda baslatmak, hiz
# sinirlayiciyi kuyruga sokmasa bile yuzlerce acik baglanti demek.
ES_ZAMANLI_TAVAN = 8

def satir_hesapla(
    temel: dict, fiyat: float, temettu_12ay: float, ortalama_hacim_tl: float | None = None
) -> dict:
    """Temel veriden turetilmis oranlari hesaplar.

    Eksik ozkaynak/net kar oranlari None yapar ama satiri dusurmez —
    fiyat ve sektor yine tarama disi sorularda ise yarar.
    """
    hisse_adedi = temel.get("hisse_adedi") or 0
    ozkaynak = temel.get("ozkaynak_tl")
    net_kar = temel.get("net_kar_tl")

    return {
        "kod": temel["kod"],
        "unvan": temel.get("unvan"),
        "sektor": temel.get("sektor"),
        "hisse_adedi": hisse_adedi,
        "ozkaynak_tl": ozkaynak,
        "net_kar_tl": net_kar,
        "fiyat": fiyat,
        "temettu_12ay": temettu_12ay,
        "pddd": pddd(fiyat, ozkaynak, hisse_adedi) if ozkaynak and hisse_adedi else None,
        "fk": fk(fiyat, hisse_adedi, net_kar) if net_kar and hisse_adedi else None,
        "piyasa_degeri": piyasa_degeri(fiyat, hisse_adedi) if hisse_adedi else None,
        "temettu_verimi": temettu_verimi(temettu_12ay, fiyat) if fiyat else None,
        "ortalama_hacim_tl": (
            ortalama_hacim_tl
            if ortalama_hacim_tl is not None
            else temel.get("ortalama_hacim_tl")
        ),
        "guncelleme": time.time(),
        # Fiyat kademesi bunu tasir; yalnizca tam_kurulum tazeler.
        "finansal_guncelleme": temel.get("finansal_guncelleme"),
    }



def oranlari_iptal_et(satir: dict) -> dict:
    """Guvenilmez oranlari siler ve iptali SATIRA yazar.

    Olculdu (gorunum.db, 09.09.2026): ISATR PD/DD 272.562, ISBTR 28.242.
    tam_kurulum bunlari None yapiyordu ama ozkaynak ve hisse adedi satirda
    kaldigi icin hafif_tazele `satir_hesapla` ile oranlari yeniden uretiyor
    ve iptal her acilista bozuluyordu. Isaret kalici oldugu icin artik
    bozulmuyor.

    Ozkaynak ve hisse adedi SILINMEZ: tarama disi sorularda ise yariyorlar.
    """
    return {
        **satir,
        "pddd": None,
        "fk": None,
        "piyasa_degeri": None,
        "oran_gecersiz": 1,
    }

class AnlikGorunum:
    def __init__(self, db_yolu: Path, kap, isyatirim, fiyat) -> None:
        self._kap = kap
        self._isyatirim = isyatirim
        self._fiyat = fiyat
        self._baglanti = sqlite3.connect(db_yolu, check_same_thread=False)
        self._baglanti.row_factory = sqlite3.Row
        alanlar = ", ".join(f"{ad} {tip}" for ad, tip in SUTUN_TIPLERI.items())
        self._baglanti.execute(f"CREATE TABLE IF NOT EXISTS gorunum ({alanlar})")
        self._eksik_sutunlari_ekle()
        self._tarama_tablosunu_kur()
        self._baglanti.commit()

    def _eksik_sutunlari_ekle(self) -> None:
        """Eski veritabanlarina sonradan eklenen sutunlari kazandirir.

        CREATE TABLE IF NOT EXISTS mevcut tabloya sutun EKLEMEZ. Hacim sutunu
        eklendiginde diskteki gorunum.db eski semada kaldi ve satir_yaz
        "no column named ortalama_hacim_tl" ile kirildi -- yani hisse_tarama
        eski kurulumlarda sessizce calismiyordu.
        """
        var_olan = {
            s["name"] for s in self._baglanti.execute("PRAGMA table_info(gorunum)")
        }
        for ad, tip in SUTUN_TIPLERI.items():
            if ad in var_olan:
                continue
            # PRIMARY KEY sonradan eklenemez; zaten tablo varsa anahtar da vardir.
            self._baglanti.execute(
                f"ALTER TABLE gorunum ADD COLUMN {ad} {tip.replace(' PRIMARY KEY', '')}"
            )
            kayit.info("gorunum tablosuna %s sutunu eklendi", ad)

    def satir_yaz(self, satir: dict) -> None:
        self._baglanti.execute(
            f"INSERT OR REPLACE INTO gorunum ({','.join(SUTUNLAR)}) "
            f"VALUES ({','.join('?' * len(SUTUNLAR))})",
            tuple(satir.get(s) for s in SUTUNLAR),
        )
        self._baglanti.commit()

    def satir_al(self, kod: str) -> dict | None:
        """Tek hissenin anlik goruntu satiri; canli veri gelmediginde yedek."""
        satir = self._baglanti.execute(
            "SELECT * FROM gorunum WHERE kod = ?", (kod.strip().upper(),)
        ).fetchone()
        return dict(satir) if satir else None

    def _tarama_tablosunu_kur(self) -> None:
        """Taramanin tamamlanip tamamlanmadigini tutan tek satirlik tablo.

        Beklenen satir sayisini tahmin etmek yanlis temeldi: fiyat verisi
        olan hisse sayisi (~630) KAP evreninden (807) az oldugu icin tablo
        dolu olsa bile "eksik" sayiliyor ve her acilista tam tarama
        kosuyordu. Bitis dogrudan kaydedilir.
        """
        self._baglanti.execute(
            "CREATE TABLE IF NOT EXISTS tarama ("
            "  id INTEGER PRIMARY KEY CHECK (id = 1), bitis REAL"
            ")"
        )

    def taramaya_basla(self) -> None:
        """Tarama basinda isareti siler; yarida kesilirse geride kalmaz."""
        self._baglanti.execute("DELETE FROM tarama")
        self._baglanti.commit()

    def taramayi_bitir(self) -> None:
        self._baglanti.execute(
            "INSERT OR REPLACE INTO tarama (id, bitis) VALUES (1, ?)", (time.time(),)
        )
        self._baglanti.commit()

    def tarama_tamam(self) -> bool:
        satir = self._baglanti.execute("SELECT bitis FROM tarama WHERE id = 1").fetchone()
        return satir is not None and satir["bitis"] is not None

    def kayit_sayisi(self) -> int:
        return self._baglanti.execute("SELECT COUNT(*) FROM gorunum").fetchone()[0]

    def yas_saat(self) -> float | None:
        satir = self._baglanti.execute(
            "SELECT MIN(guncelleme) AS en_eski FROM gorunum"
        ).fetchone()
        if satir is None or satir["en_eski"] is None:
            return None
        return (time.time() - satir["en_eski"]) / 3600

    def finansal_yas_saat(self) -> float | None:
        """Finansal kademenin (ozkaynak, net kar, hisse adedi) yasi.

        Haftalik tam kurulum karari BUNA bakar, `yas_saat()`e degil:
        oradaki damga gunluk fiyat tazelemesiyle her gun sifirlaniyor.
        Sutun sonradan eklendigi icin eski satirlarda NULL olabilir; o
        durumda yas BILINMIYOR sayilir ve tam kurulum bir kez kosar.
        """
        satir = self._baglanti.execute(
            "SELECT MIN(finansal_guncelleme) AS en_eski FROM gorunum"
        ).fetchone()
        if satir is None or satir["en_eski"] is None:
            return None
        return (time.time() - satir["en_eski"]) / 3600

    def satirlari_sec(
        self,
        fk_max: float | None = None,
        fk_min: float | None = None,
        pddd_max: float | None = None,
        temettu_verimi_min: float | None = None,
        piyasa_degeri_min: float | None = None,
        hacim_min: float | None = None,
        sektor: str | None = None,
        sirala: str = "piyasa_degeri",
        adet: int = 20,
    ) -> list[dict]:
        kosullar: list[str] = []
        degerler: list[object] = []

        for alan, islec, deger in (
            ("fk", "<=", fk_max),
            ("fk", ">=", fk_min),
            ("pddd", "<=", pddd_max),
            ("temettu_verimi", ">=", temettu_verimi_min),
            ("piyasa_degeri", ">=", piyasa_degeri_min),
            ("ortalama_hacim_tl", ">=", hacim_min),
        ):
            if deger is not None:
                kosullar.append(f"({alan} IS NOT NULL AND {alan} {islec} ?)")
                degerler.append(deger)

        if sektor:
            kosullar.append("sektor = ?")
            degerler.append(sektor)

        if sirala not in SUTUNLAR:
            sirala = "piyasa_degeri"
        yon = "ASC" if sirala in ("fk", "pddd") else "DESC"

        sorgu = "SELECT * FROM gorunum"
        if kosullar:
            sorgu += " WHERE " + " AND ".join(kosullar)
        sorgu += f" ORDER BY {sirala} IS NULL, {sirala} {yon} LIMIT ?"
        degerler.append(adet)

        return [dict(s) for s in self._baglanti.execute(sorgu, degerler).fetchall()]

    async def _fiyatlar(self, kodlar: list[str]) -> dict[str, dict]:
        """Toplu indirme + ekran kotasyonu.

        Gunluk barlar son seansi vermiyor (kural 37); fiyat SAKLANDIGI icin
        tamamlama burada yapilir. Kotasyon gelmezse gunluk bara dusulur,
        tarama durmaz.
        """
        toplu = await self._fiyat.toplu(kodlar)
        return kotasyonla_tamamla(toplu, await self._fiyat.toplu_kotasyon())

    async def hafif_tazele(self, kodlar: list[str]) -> int:
        """Gunluk — sadece fiyat ve temettu. Olculen: ~5 sn, 2 istek."""
        toplu = await self._fiyatlar(kodlar)
        guncellenen = 0
        for kod, veri in toplu.items():
            mevcut = self._baglanti.execute(
                "SELECT * FROM gorunum WHERE kod = ?", (kod,)
            ).fetchone()
            if mevcut is None:
                continue
            satir = satir_hesapla(
                dict(mevcut),
                veri["fiyat"],
                veri["temettu_12ay"],
                veri.get("ortalama_hacim_tl"),
            )
            # satir_hesapla oranlari sifirdan hesaplar; iptal edilmis satirda
            # bu, tam_kurulum'un kararini geri alirdi.
            if mevcut["oran_gecersiz"]:
                satir = oranlari_iptal_et(satir)
            self.satir_yaz(satir)
            guncellenen += 1
        return guncellenen

    async def tam_kurulum(self, kodlar: list[str]) -> int:
        """Haftalik — Is Yatirim + yfinance info.

        Yalnizca toplu indirmede fiyati gelen hisseler islenir: KAP dizini
        807 ticker veriyor ama 630'unda fiyat var, kalani islem gormeyen ya
        da ikincil kodlar. Onlara istek atmak bosuna yuk olurdu.
        """
        self.taramaya_basla()
        dizin = await self._kap.sirket_dizini()
        toplu = await self._fiyatlar(kodlar)
        tavan = asyncio.Semaphore(ES_ZAMANLI_TAVAN)
        yazilan = 0

        async def _bir_hisse(kod: str) -> None:
            nonlocal yazilan
            async with tavan:
                sirket = dizin.get(kod)
                piyasa = toplu[kod]

                girdiler, bilgi, ceyreklik = await asyncio.gather(
                    self._isyatirim.oran_girdileri(kod, sirket.tip if sirket else None),
                    self._fiyat.sirket_bilgi(kod),
                    self._fiyat.ceyreklik_net_kar_ttm(kod),
                )

                # Kumulatif formul enflasyon muhasebesinde sisiyor; tarama da
                # finansal_oranlar ile AYNI kari kullanmali, yoksa F/K'ya gore
                # siralama iki ayri gercekligi karistirir. Bkz. net_kar_sec.
                net_kar, _ = net_kar_sec(
                    girdiler["net_kar_ttm"],
                    ceyreklik,
                    bilgi.get("financialCurrency"),
                    girdiler.get("net_kar_aciklama") or "",
                )

                satir = satir_hesapla(
                    {
                        "kod": kod,
                        "unvan": sirket.unvan if sirket else None,
                        "sektor": bilgi.get("sector"),
                        "hisse_adedi": hisse_adedi_sec(
                            girdiler.get("odenmis_sermaye"),
                            bilgi.get("sharesOutstanding"),
                        ) or 0,
                        # Ozkaynak STOK -> guncel bilanco; net kar AKIS -> TTM
                        "ozkaynak_tl": girdiler["ozkaynak_tl"],
                        "net_kar_tl": net_kar,
                        # Finansal kademe BURADA tazelenir; hafif tazeleme
                        # bu damgaya dokunmaz.
                        "finansal_guncelleme": time.time(),
                    },
                    piyasa["fiyat"],
                    piyasa["temettu_12ay"],
                    piyasa.get("ortalama_hacim_tl"),
                )

            # Coklu hisse sinifinda odenmis sermaye TUM siniflarin toplami
            # olabilir; o zaman tek sinifin hisse adedi bilinmiyor ve oran
            # sacmaliyor (olculdu: ISATR PD/DD 272.562, ISBTR 28.242).
            # AMA "GARAN, TGB" gibi ikincil kodlar da coklu gorunuyor ve
            # onlarin orani dogru; kosulsuz silmek GARAN, VAKBN, YKBNK dahil
            # 21 saglam hisseyi bozuyordu. Once makullige bakilir.
            if sirket and sirket.coklu_sinif and not oran_makul(satir.get("pddd")):
                satir = oranlari_iptal_et(satir)

            # Satir HEMEN yazilir, gather'in sonu beklenmez: tarama ~15 dakika
            # ve ~1.300 istek suruyor, surec o bitmeden kapanirsa tum ilerleme
            # kaybolur ve sonraki acilis ayni yuku bastan uretir.
            self.satir_yaz(satir)
            yazilan += 1

        await asyncio.gather(*(_bir_hisse(k) for k in toplu), return_exceptions=True)
        self.taramayi_bitir()
        return yazilan
