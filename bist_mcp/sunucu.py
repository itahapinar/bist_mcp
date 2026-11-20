"""BIST MCP sunucusu — stdio.

Claude Desktop'a baglamak icin:
  komut : python
  args  : ["-m", "bist_mcp.sunucu"]
  cwd   : proje koku
"""

import asyncio
import contextlib
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from bist_mcp.anlik_gorunum import AnlikGorunum, satir_hesapla
from bist_mcp.evren import tarama_evreni
from bist_mcp.hesap import (
    oran_makul,
    son_seansi_ayikla,
    temettu_verimi,
    net_kar_sec,
    yonlu_hacim_hesapla,
)
from bist_mcp.kaynaklar.fiyat import FiyatKaynak
from bist_mcp.kaynaklar.isyatirim import IsYatirimIstemci, hisse_adedi_sec, tablo_bol
from bist_mcp.kaynaklar.kap import KapIstemci
from bist_mcp.kaynaklar.kur import KurKaynak
from bist_mcp.kaynaklar.tcmb import TcmbIstemci
from bist_mcp.onbellek import Onbellek

load_dotenv()

KOK = Path(__file__).resolve().parent.parent
# Sunucu bir ALT SUREC; stderr botun terminaline karisiyor ve kalici kayit
# birakmiyor. Kendi dosyasi olmadan tam taramanin durumu gorulemiyordu.
LOG_DOSYASI = KOK / "bist-mcp.log"
onbellek = Onbellek(KOK / "onbellek.db")
kap = KapIstemci(onbellek)
isyatirim = IsYatirimIstemci(onbellek)
fiyat = FiyatKaynak(onbellek)
kur = KurKaynak(onbellek)
tcmb = TcmbIstemci(onbellek, os.getenv("EVDS_API_KEY"))
gorunum = AnlikGorunum(KOK / "gorunum.db", kap, isyatirim, fiyat)

GUNLUK_SANIYE = 24 * 3600
HAFTALIK_SAAT = 7 * 24


def tam_kurulum_gerekli(yas_saat: float | None, tarama_tamam: bool) -> bool:
    """Tam taramanin gerekip gerekmedigi.

    Karar iki seye bakar: veri YASI ve son taramanin BITIP bitmedigi.

    Onceki surum kayit sayisini KAP evreniyle karsilastiriyordu ve bu
    yanlis temeldi: fiyat verisi olan ~630 hisse, 807 tickerlik evrenin
    %90'ini (726) hicbir zaman gecemiyor. Tablo tam dolu olsa bile "eksik"
    sayiliyor ve her sunucu acilisinda ~13 dakikalik, ~700 istekli tarama
    kosuyordu (olculdu, 08.09.2026).

    Beklenen satir sayisini tahmin etmek yerine tamamlanma dogrudan
    kaydediliyor; yarida kesilen tarama isaret birakmadigi icin tablo
    yeniden kurulur.
    """
    if yas_saat is None or yas_saat > HAFTALIK_SAAT:
        return True
    return not tarama_tamam


kayit = logging.getLogger("bist_mcp")


async def gorunum_bakim() -> None:
    """Anlik gorunumu iki kademede taze tutar (spec §7.2).

    Yas haftalik esigi asmissa tam kurulum (~15 dk), asmamissa hafif
    tazeleme (~5 sn). Hata durumunda loglanir ve bir sonraki turda yeniden
    denenir; sunucu calismaya devam eder.
    """
    while True:
        try:
            evren = await tarama_evreni(kap)
            # FINANSAL saat: `yas_saat()` fiyat kademesini olcuyor ve gunluk
            # tazeleme onu her gun sifirliyor -- o damgaya bakmak haftalik
            # kurulumu kalici olarak kilitliyordu.
            yas = gorunum.finansal_yas_saat()
            if tam_kurulum_gerekli(yas, gorunum.tarama_tamam()):
                kayit.info("Anlik gorunum tam kuruluyor (~15 dk, %d ticker)", len(evren))
                basladi = time.monotonic()
                yazilan = await gorunum.tam_kurulum(evren)
                kayit.info(
                    "Tam kurulum bitti: %d hisse, %.1f dakika",
                    yazilan,
                    (time.monotonic() - basladi) / 60,
                )
            else:
                kayit.info("Hafif tazeleme bitti: %d hisse", await gorunum.hafif_tazele(evren))
        except Exception:
            kayit.exception("Gorunum tazelemesi basarisiz; bir sonraki turda tekrar denenecek")

        await asyncio.sleep(GUNLUK_SANIYE)


@contextlib.asynccontextmanager
async def yasam_dongusu(_sunucu: FastMCP):
    """Arka plan bakim gorevini sunucu omru boyunca ayakta tutar.

    DIKKAT: lifespan FastMCP'ye KURULUS aninda verilmelidir. Sonradan
    `sunucu.settings.lifespan = ...` atamak ise yaramaz — dusuk seviye
    sunucu lifespan'i __init__ aninda bagliyor (dogrulandi).
    """
    gorev = asyncio.create_task(gorunum_bakim())
    try:
        yield {}
    finally:
        gorev.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await gorev


sunucu = FastMCP("bist", lifespan=yasam_dongusu)


async def _sirket(kod: str):
    return (await kap.sirket_dizini()).get(kod.strip().upper())


# --------------------------------------------------------------------------
# Cekirdek araclar
# --------------------------------------------------------------------------


@sunucu.tool()
async def hisse_ara(isim: str) -> list[dict]:
    """Sirket adindan BIST hisse kodunu bulur. Ornek: 'aselsan' -> ASELS.

    Kullanicinin hisse kodunu degil sirket adini yazdigi durumlarda kullan.
    """
    aranan = isim.strip().upper()
    dizin = await kap.sirket_dizini()

    gorulen: set[str] = set()
    sonuc = []
    for s in dizin.values():
        if s.mkk_oid in gorulen:
            continue
        if aranan in s.unvan.upper() or aranan == s.kod:
            gorulen.add(s.mkk_oid)
            sonuc.append({"kod": s.kod, "unvan": s.unvan})
    return sonuc[:10]


@sunucu.tool()
async def anlik_fiyat(kod: str) -> dict:
    """Hissenin guncel fiyatini, gunluk degisimini ve hacmini verir (TL).

    'THYAO kac TL', 'ASELS ne kadar oldu' gibi sorularda kullan.
    """
    sonuc = await fiyat.anlik(kod)
    if not sonuc:
        return {"hata": f"{kod.upper()} icin fiyat verisi bulunamadi."}
    # Unvan olmadan model cevapta hangi sirket oldugunu soylemiyordu
    # (olculdu: "thyao kac tl" -> yalnizca "Son fiyat 296,00 TL").
    sirket = await _sirket(kod)
    return {**sonuc, "unvan": sirket.unvan if sirket else None}


@sunucu.tool()
async def gecmis_fiyat(kod: str, baslangic: str, bitis: str | None = None) -> dict:
    """Belirli tarih araligindaki gunluk fiyatlari verir (YYYY-AA-GG).

    Tek gun icin bitis bos birakilir. Istenen gun borsa kapaliysa (hafta
    sonu/tatil) o gun listede olmaz ama cevresindeki islem gunleri doner;
    kullaniciya borsanin kapali oldugunu ve en yakin islem gununu soyle.
    """
    mumlar = await fiyat.gecmis(kod, baslangic, bitis)
    if not mumlar:
        return {"hata": f"{kod.upper()} icin {baslangic} civarinda fiyat verisi yok."}
    istenen = [m for m in mumlar if m["tarih"] == baslangic]
    sirket = await _sirket(kod)
    return {
        "kod": kod.upper(),
        "unvan": sirket.unvan if sirket else None,
        "istenen_tarih": baslangic,
        "istenen_gun_islem_gordu": bool(istenen),
        "gunler": mumlar,
    }


@sunucu.tool()
async def sirket_profili(kod: str) -> dict:
    """Sirketin kunyesi: unvan, sirket tipi, sektor, hisse adedi ve
    finansallarini hangi para biriminde raporladigi.
    """
    sirket = await _sirket(kod)
    if sirket is None:
        return {"hata": f"{kod.upper()} icin KAP kaydi bulunamadi."}
    bilgi = await fiyat.sirket_bilgi(kod)
    return {
        "kod": sirket.kod,
        "unvan": sirket.unvan,
        "tip": sirket.tip,
        "sektor": bilgi.get("sector"),
        "hisse_adedi": bilgi.get("sharesOutstanding"),
        "raporlama_para_birimi": bilgi.get("financialCurrency"),
        "islem_para_birimi": bilgi.get("currency"),
    }


@sunucu.tool()
async def finansal_tablo(
    kod: str,
    tablo: Literal["bilanco", "gelir", "nakit"] = "bilanco",
    donem: Literal["yillik", "ceyreklik"] = "yillik",
    adet: int = 2,
) -> dict:
    """Finansal tablolari verir. Rakamlar TL'dir ve Is Yatirim'dan gelir.

    Bankalar BDDK formatinda doner ('XVI. ÖZKAYNAKLAR' gibi) ve bankalarda
    nakit akis tablosu YOKTUR. Cevapta rakamin hangi doneme ait oldugunu
    'donemler' alanina bakarak mutlaka belirt.
    """
    sirket = await _sirket(kod)
    veri = await isyatirim.mali_tablo(kod, sirket.tip if sirket else None, donem, adet)
    if not veri["kalemler"]:
        return {"hata": f"{kod.upper()} icin {donem} finansal tablo bulunamadi."}

    bolumler = tablo_bol(veri["kalemler"])
    secilen = bolumler[tablo]
    if not secilen:
        if tablo == "nakit" and sirket and sirket.tip:
            return {
                "hata": f"{kod.upper()} bir banka/finans kurulusu; bu formatta "
                "nakit akis tablosu yayimlanmiyor. bilanco veya gelir dene."
            }
        return {"hata": f"{kod.upper()} icin {tablo} bolumu bulunamadi."}

    return {
        "kod": kod.upper(),
        "tablo": tablo,
        "donem": donem,
        "donemler": veri["donemler"],
        "kalemler": secilen,
    }


@sunucu.tool()
async def finansal_oranlar(kod: str) -> dict:
    """Degerleme oranlari: F/K, PD/DD, piyasa degeri, temettu verimi.

    Oranlar Is Yatirim'in TL rakamlariyla BURADA hesaplanir; hazir oran
    alanlari kullanilmaz. Gerekce: yabanci kaynaklar finansallarini dolar
    raporlayan sirketlerde (ornegin THYAO) 49 kata varan hata veriyor.
    """
    sirket = await _sirket(kod)
    girdiler = await isyatirim.oran_girdileri(kod, sirket.tip if sirket else None)
    bilgi = await fiyat.sirket_bilgi(kod)
    anlik = await fiyat.anlik(kod)
    if not anlik:
        return {"hata": f"{kod.upper()} icin fiyat verisi bulunamadi."}

    toplu = await fiyat.toplu([kod])

    # Son 12 ay kari: ceyreklik toplam birincil, kumulatif formul yedek.
    # Bkz. hesap.net_kar_sec -- enflasyon muhasebesi kumulatifi sisiriyor.
    net_kar, net_kar_aciklama = net_kar_sec(
        girdiler["net_kar_ttm"],
        await fiyat.ceyreklik_net_kar_ttm(kod),
        bilgi.get("financialCurrency"),
        girdiler["net_kar_aciklama"],
    )

    temettu, temettu_notu = temettu_yedekli(
        toplu.get(kod.strip().upper(), {}).get("temettu_12ay"),
        gorunum.satir_al(kod),
    )

    satir = satir_hesapla(
        {
            "kod": kod.upper(),
            "unvan": sirket.unvan if sirket else None,
            "sektor": bilgi.get("sector"),
            "hisse_adedi": hisse_adedi_sec(
                girdiler.get("odenmis_sermaye"), bilgi.get("sharesOutstanding")
            ) or 0,
            # Ozkaynak STOK -> guncel bilanco; net kar AKIS -> son 12 ay
            "ozkaynak_tl": girdiler["ozkaynak_tl"],
            "net_kar_tl": net_kar,
        },
        anlik["fiyat"],
        # Varsayilan 0.0 YOK: toplu indirme bos donunce "temettu odenmemis"
        # gibi okunuyordu (olculdu, GENKM). Bilinmemek ile odenmemek ayri.
        temettu,
        toplu.get(kod.strip().upper(), {}).get("ortalama_hacim_tl"),
    )
    satir.pop("guncelleme", None)
    satir.pop("finansal_guncelleme", None)
    satir["ozkaynak_donemi"] = girdiler["ozkaynak_donem"]
    satir["net_kar_donemi"] = net_kar_aciklama

    aciklama = oran_notu(
        kod.upper(),
        girdiler["ozkaynak_tl"],
        net_kar,
        satir.get("pddd"),
        satir.get("temettu_12ay"),
        temettu_notu,
    )
    if aciklama:
        satir["not"] = aciklama

    # Makullük kontrolu. Coklu hisse sinifi olan sirketlerde odenmis sermaye
    # TUM siniflarin toplamidir ve tek sinifa atanamaz; ISATR'da PD/DD
    # 272.562 gibi sacma bir sonuc cikiyordu. Sayiyi uydurmak yerine
    # guvenilmez oldugunu soyle.
    pddd_degeri = satir.get("pddd")
    if not oran_makul(pddd_degeri):
        if sirket and sirket.coklu_sinif:
            satir["not"] = (
                f"{kod.upper()} coklu hisse sinifi olan bir sirketin "
                f"({', '.join(sirket.tum_kodlar)}) tek sinifi. Odenmis sermaye tum "
                "siniflarin toplami oldugu icin bu sinifin hisse adedi bilinmiyor ve "
                "F/K ile PD/DD GUVENILMEZ. Bu oranlari verme; ana sinifi oner."
            )
        else:
            satir["not"] = (
                f"PD/DD ({pddd_degeri:.1f}) olagandisi. Sirketin ozkaynagi erimis "
                "olabilir ya da veri hatali olabilir; bu orani kesin bir olcu gibi "
                "sunma, temkinli aktar."
            )
    return satir


def odeme_notu(odemeler: list[dict]) -> str | None:
    """Odeme tutarlarinin hangi bazda oldugunu soyler.

    Kaynak seri, sonradan yapilan bolunme/bedelsiz islemlerine gore
    duzeltilmis tutarlar veriyor (DOAS'ta 40,9091 TL gibi kusuratli
    degerler bundan). Karsilastirma icin dogru baz budur ama o tarihte
    KAP'ta ilan edilen brut tutarla birebir ayni olmayabilir.
    """
    if not odemeler:
        return None
    return (
        "Ödeme tutarları, sonraki bölünme/bedelsiz işlemlerine göre "
        "düzeltilmiş seriden gelir; o tarihte KAP'ta ilan edilen brüt tutarla "
        "birebir aynı olmayabilir. Karşılaştırma için bu baz doğrudur."
    )


def oran_notu(
    kod: str,
    ozkaynak_tl: float | None,
    net_kar: float | None,
    pddd_degeri: float | None,
    temettu_12ay: float | None,
    temettu_notu: str | None,
) -> str | None:
    """Oran satirina eklenecek uyari metni; yoksa None.

    Kaynakta finansal tablosu olmayan hisseler var (olculdu: 630 islem
    goren hissenin 21'i, cogu faktoring ve finansal kiralama). Sessizce
    bos oran dondurmek "sifir" gibi okunabilir; durum acikca soylenir.

    KARARIN DAYANAGI SECILEN KARDIR, kaynak alan degil. Is Yatirim'in
    kumulatif formulu "eksik gecmis: uydurma yapma" deyip None dondugunde
    yfinance'in ceyreklik toplami devreye giriyor (bkz. hesap.net_kar_sec)
    ve satirda GERCEK bir F/K oluyor. Not ham `net_kar_ttm` alanina
    bakinca "F/K verilemiyor" diyordu; sistem promptu kural 3 modele bu
    notu aynen aktarttigi icin kullanici ayni cevapta hem F/K rakamini hem
    "verilemiyor" cumlesini goruyordu.
    """
    if net_kar is not None and net_kar <= 0:
        # PD/DD IDDIASI HESAPLANAN DEGERE BAKAR. Kosulsuz "PD/DD gecerlidir"
        # demek ayni celiskiyi uretiyordu: hesap.pddd() negatif ozkaynakta
        # None doner ve sonraki makullük kontrolu bunu yakalayamaz
        # (oran_makul(None) True). Zarar eden + ozkaynagi erimis sirket
        # sikintili sirketin tipik profili, uc bir durum degil.
        if pddd_degeri is not None:
            pddd_cumlesi = "PD/DD gecerlidir."
        elif ozkaynak_tl is not None and ozkaynak_tl <= 0:
            pddd_cumlesi = (
                f"Ozkaynagi da NEGATIF ({ozkaynak_tl:,.0f} TL), yani defter degeri "
                "erimis; PD/DD bu yuzden TANIMSIZ. Bunu da soyle."
            )
        else:
            pddd_cumlesi = "PD/DD de hesaplanamadi; onu da BILINMIYOR diye soyle."
        return (
            f"{kod} son 12 ayda ZARAR etti ({net_kar:,.0f} TL). F/K zararda "
            "tanimsizdir, bu yuzden verilmiyor -- 'hesaplanamiyor' deme, sirketin "
            f"ZARAR ETTIGINI soyle. {pddd_cumlesi}"
        )
    if ozkaynak_tl is None and net_kar is None:
        return (
            f"{kod} icin Is Yatirim'da finansal tablo bulunamadi, bu yuzden "
            "F/K ve PD/DD hesaplanamadi. Fiyat ve piyasa degeri gecerlidir. "
            "Bu oranlarin BILINMEDIGINI soyle; sifir ya da dusuk gibi sunma."
        )
    if ozkaynak_tl is None:
        return "Ozkaynak verisi bulunamadi; PD/DD hesaplanamadi."
    if net_kar is None:
        return "Son 12 ay kari hesaplanamadi; F/K verilemiyor."
    if temettu_12ay is None:
        return (
            "Temettu verisi alinamadi; tutar ve verim BILINMIYOR. "
            "'Temettu odenmemis' DEME."
        )
    return temettu_notu or None


def temettu_yedekli(canli, gorunum_satiri) -> tuple[float | None, str | None]:
    """Canli temettu gelmezse gunluk gorunum tablosundaki degeri kullanir.

    Olculdu (GENKM): sunucunun acilistaki tazelemesi yfinance'i mesgul
    ederken tekil toplu indirme bos donuyor ve temettu "veri yok" cikiyor --
    oysa deger gorunum tablosunda duruyor. Temettu yillik bir olay; bir
    gunluk anlik goruntu bu alan icin yeterince taze. Fiyat icin ayni sey
    yapilmaz, orada bir gun eski veri yaniltir.
    """
    if canli is not None:
        return canli, None
    yedek = (gorunum_satiri or {}).get("temettu_12ay")
    if yedek is None:
        return None, None
    return yedek, "Temettü, günlük görünüm tablosundan alındı (canlı veri gelmedi)."


def fiyat_yedekli(canli, gorunum_satiri):
    """Temettu verimi hesabi icin fiyat; canli yoksa gorunum tablosundan."""
    return canli if canli is not None else (gorunum_satiri or {}).get("fiyat")


def _virgullu(deger: float, basamak: int) -> str:
    """Turkce ondalik ayirici. Tek bir degere ozel replace calismaz."""
    return f"{deger:.{basamak}f}".replace(".", ",")


def temettu_ozeti(son_12ay_tl: float | None, fiyat_tl: float | None) -> dict:
    """Temettu alanlarini sessiz sifir birakmadan derler.

    Iki olculmus sorun:
      - Veri gelmediginde 0.0 donuyordu; "temettu odenmedi" ile "veri yok"
        ayirt edilemiyordu.
      - Temettu ODENMIS olmasina ragmen (GENKM 0,2053 TL, verim %1,84)
        model cevaba "0,00 TL, dagitim yapilmamaktadir" yazdi. `not` alani
        modelin uydugu tek mekanizma; uyari oraya konuyor.
    """
    if son_12ay_tl is None:
        return {
            "son_12ay_toplam_tl": None,
            "temettu_verimi": None,
            "not": "Temettu verisi alinamadi; tutar BILINMIYOR. Sifir gibi sunma.",
        }

    verim = temettu_verimi(son_12ay_tl, fiyat_tl) if fiyat_tl else None
    ozet: dict = {"son_12ay_toplam_tl": son_12ay_tl, "temettu_verimi": verim}

    if son_12ay_tl > 0:
        verim_yazi = f", verim %{_virgullu(verim, 2)}" if verim is not None else ""
        ozet["not"] = (
            f"Son 12 ayda hisse basina {_virgullu(son_12ay_tl, 4)} TL temettu "
            f"ODENDI{verim_yazi}. Bu rakami aynen aktar; 'temettu odenmedi' "
            "ya da '0,00' DEME."
        )
    return ozet


@sunucu.tool()
async def temettu_gecmisi(kod: str, yil: int = 5) -> dict:
    """Temettu ODEME gecmisi: her odemenin tarihi ve HISSE BASINA tutari.

    `odemeler` alani asil cevaptir: gercekten para odenen tarihler ve
    tutarlar. "Temettu tarihleri" sorulursa BUNLARI ver.

    `kap_bildirimleri` ise DUYURU tarihleridir (yonetim kurulu teklifi,
    genel kurul karari, odeme tarihi belirlenmesi). Duyuru tarihi odeme
    tarihi DEGILDIR; ikisini karistirma, gerekiyorsa ayri baslikta ver.

    Tarihleri gun.ay.yil olarak sun.
    """
    toplu = await fiyat.toplu([kod])
    odemeler = await fiyat.temettu_odemeleri(kod, yil)
    bildirimler = await kap.bildirimler(kod, gun=400)
    canli = toplu.get(kod.strip().upper(), {})
    yedek = gorunum.satir_al(kod)
    temettu, _ = temettu_yedekli(canli.get("temettu_12ay"), yedek)
    anahtarlar = ("temettü", "kar payı", "sermaye artırım", "bedelsiz")
    ilgili = [
        b
        for b in bildirimler
        if any(a in f"{b.get('konu') or ''} {b.get('ozet') or ''}".lower() for a in anahtarlar)
    ]
    sirket = await _sirket(kod)
    return {
        "kod": kod.upper(),
        "unvan": sirket.unvan if sirket else None,
        # finansal_oranlar ile AYNI yedegi kullanir; yoksa kart "0,2053 TL"
        # derken bu bolum "veri yok" diyor ve cevap kendiyle celisiyordu.
        **temettu_ozeti(temettu, fiyat_yedekli(canli.get("fiyat"), yedek)),
        "odemeler": odemeler,
        "odeme_sayisi": len(odemeler),
        "odeme_notu": odeme_notu(odemeler),
        "kap_bildirimleri": ilgili[:10],
    }


@sunucu.tool()
async def kap_bildirimleri(kod: str, gun: int = 90) -> list[dict]:
    """Sirketin KAP aciklamalari (varsayilan son 90 gun).

    Ozel durum aciklamalari, finansal rapor duyurulari, yonetim
    degisiklikleri burada cikar. Sirket haberi sorularinda bunu kullan.
    """
    return await kap.bildirimler(kod, gun)


@sunucu.tool()
async def kap_bildirim_detay(bildirim_no: str) -> dict:
    """Tek bir KAP bildiriminin tam metnini verir.

    kap_bildirimleri sonucundaki bildirim_no ile cagrilir; ozet yetmediginde
    kullan.
    """
    return await kap.bildirim_detay(bildirim_no)


# --------------------------------------------------------------------------
# Analiz ve piyasa araclari
# --------------------------------------------------------------------------

# Olculdu: BIST endeksleri Yahoo'da "XU100.IS" formatinda; "^XU100" bos doner.
ENDEKSLER = {
    "XU100": "BIST 100",
    "XU030": "BIST 30",
    "XU050": "BIST 50",
    "XBANK": "BIST Bankacılık",
    "XUSIN": "BIST Sınai",
    "XUTEK": "BIST Teknoloji",
    "XUMAL": "BIST Mali",
}


@sunucu.tool()
async def teknik_analiz(kod: str) -> dict:
    """RSI, MACD, 20/50/200 gunluk hareketli ortalamalar ve destek/direnc.

    Son bir yillik fiyat verisine dayanir. Yorumu sun ama al/sat tavsiyesi
    verme.
    """
    import datetime as dt

    from bist_mcp import teknik

    bugun = dt.date.today()
    mumlar = await fiyat.gecmis(kod, str(bugun - dt.timedelta(days=400)), str(bugun))
    if not mumlar:
        return {"hata": f"{kod.upper()} icin fiyat gecmisi bulunamadi."}

    kapanislar = [m["kapanis"] for m in mumlar]
    sirket = await _sirket(kod)
    return {
        "kod": kod.upper(),
        "unvan": sirket.unvan if sirket else None,
        "son_kapanis": kapanislar[-1],
        "rsi_14": teknik.rsi(kapanislar),
        "macd": teknik.macd(kapanislar),
        "ma_20": teknik.hareketli_ortalama(kapanislar, 20),
        "ma_50": teknik.hareketli_ortalama(kapanislar, 50),
        "ma_200": teknik.hareketli_ortalama(kapanislar, 200),
        "son_3ay_destek_direnc": teknik.destek_direnc(mumlar[-63:]),
    }



# --- Detayli analiz --------------------------------------------------------
# Olculdu (canli bot, GENKM): "detayli analiz" istendiginde model 3-4 arac
# cagirip duruyordu. RSI/MACD hic gelmedi ve gelir tablosu cekilmedigi icin
# "detayli gelir tablosu yok" deyip EBIT'i ve brut marji TAHMIN ETTI -- oysa
# veri kaynakta vardi. Zinciri modele biraktikca eksik kaliyor ve tur tavani
# (5) da yetismiyor; tek cagrida hepsi toplaniyor.
ANALIZ_BOLUMLERI = (
    "profil",
    "fiyat",
    "oranlar",
    "teknik",
    "bilanco",
    "gelir_tablosu",
    "nakit_akis",
    "temettu",
    "sektor",
    "kap",
)


# Baslik rakamlari KODDA uretilir. Olculdu: arac temettu_12ay=0,2053 ve
# verim %1,84'u dort ayri yerde (ozet, oranlar, temettu ve "0,00 DEME"
# notu) donderken model cevaba "%0,0" yazdi. Prompt kurali, uyari notu ve
# ozet blogu denendi; hicbiri tutmadi. Bu tablo modelden gecmez.
KART_SATIRLARI = (
    ("Son fiyat", "fiyat", "tl"),
    ("Piyasa değeri", "piyasa_degeri", "tam_tl"),
    ("PD/DD", "pddd", "oran"),
    ("F/K", "fk", "fk"),
    ("Temettü (12 ay)", "temettu_12ay", "temettu"),
    ("Temettü verimi", "temettu_verimi", "yuzde"),
    ("RSI (14)", "rsi_14", "oran"),
    ("MACD", "macd", "dort"),
)
VERI_YOK = "veri yok"


def _bicimle(deger, tur: str, ozet: dict) -> str:
    if deger is None:
        if tur == "fk":
            net_kar = ozet.get("net_kar_tl")
            if net_kar is not None and net_kar < 0:
                return "tanımsız (net kâr negatif)"
        return VERI_YOK
    if tur == "tl":
        return f"{_virgullu(deger, 2)} TL"
    if tur == "tam_tl":
        # Binlik ayirici nokta; bicim.py bunu "6,79 milyar TL" diye kisaltir.
        return f"{deger:,.0f}".replace(",", ".") + " TL"
    if tur == "temettu":
        return f"{_virgullu(deger, 4)} TL"
    if tur == "yuzde":
        return f"%{_virgullu(deger, 2)}"
    if tur == "dort":
        return _virgullu(deger, 4)
    return _virgullu(deger, 2)


def ozet_kart(ozet: dict) -> str:
    """Baslik rakamlarini markdown boru tablosu olarak uretir.

    Model bu tabloyu yeniden yazmaz; ajan tarafi cevabin basina oldugu gibi
    ekler ve bicim.py hizali monospace bloga cevirir.

    Ust satirda HANGI HISSE oldugu yazar: olculdu, kullanici yalnizca
    rakamlari gorunce hangi sirket oldugunu bilemiyordu.
    """
    if not ozet:
        return ""

    tablo = "\n".join(
        f"| {etiket} | {_bicimle(ozet.get(alan), tur, ozet)} |"
        for etiket, alan, tur in KART_SATIRLARI
    )
    kimlik = " — ".join(x for x in (ozet.get("kod"), ozet.get("unvan")) if x)
    return f"**{kimlik}**\n{tablo}" if kimlik else tablo


OZET_ALANLARI = (
    "fiyat",
    "piyasa_degeri",
    "pddd",
    "fk",
    "net_kar_tl",
    "temettu_12ay",
    "temettu_verimi",
)


def _ozet_cikar(oranlar, teknik) -> dict:
    """Baslik rakamlarini en basa kompakt bir blokta toplar.

    Olculdu: arac temettu_12ay=0,2053'u iki ayri bolumde ve uyari notuyla
    donderken model cevaba "-" yazdi. Payload 10 bolum, tam bilanco ve
    gelir tablosu iceriyor; onemli rakamlar en basta tekrarlaniyor.
    """
    ozet = {ad: (oranlar or {}).get(ad) for ad in OZET_ALANLARI}
    ozet["unvan"] = (oranlar or {}).get("unvan")
    macd = (teknik or {}).get("macd")
    ozet["rsi_14"] = (teknik or {}).get("rsi_14")
    ozet["macd"] = macd.get("macd") if isinstance(macd, dict) else macd
    return ozet


def analizi_derle(kod: str, sonuclar: dict) -> dict:
    """Bolum sonuclarini tek cevaba toplar, alinamayanlari ACIKCA sayar.

    Eksigi gizlemek modelin rakam uydurmasina yol aciyor; hangi bolumun
    gelmedigi soylenirse "yok" diyor.
    """
    def _gecerli(ad):
        s = sonuclar.get(ad)
        return None if (s is None or isinstance(s, BaseException)
                        or (isinstance(s, dict) and "hata" in s)) else s

    ozet = _ozet_cikar(_gecerli("oranlar"), _gecerli("teknik"))
    ozet["kod"] = kod.upper()
    derlenen: dict = {
        "kod": kod.upper(),
        "ozet": ozet,
        # Ajan bu tabloyu cevabin basina OLDUGU GIBI ekler; rakamlar
        # modelden gecmez (bkz. ozet_kart).
        "ozet_kart": ozet_kart(ozet),
    }
    eksik: list[str] = []

    for ad in ANALIZ_BOLUMLERI:
        sonuc = sonuclar.get(ad)
        gecersiz = (
            sonuc is None
            or isinstance(sonuc, BaseException)
            or (isinstance(sonuc, dict) and "hata" in sonuc)
        )
        derlenen[ad] = None if gecersiz else sonuc
        if gecersiz:
            eksik.append(ad)

    derlenen["eksik_bolumler"] = eksik
    if eksik:
        derlenen["not"] = (
            f"Su bolumler alinamadi: {', '.join(eksik)}. Bunlari BILINMIYOR "
            "diye soyle; tahmin etme, uydurma, 'yaklasik' diye rakam uretme."
        )
    return derlenen


@sunucu.tool()
async def detayli_analiz(kod: str) -> dict:
    """Bir hissenin TUM verisini tek cagrida toplar; detayli analiz icin bunu kullan.

    Icerir: sirket profili, anlik fiyat, degerleme oranlari (F/K, PD/DD),
    TEKNIK gostergeler (RSI, MACD, hareketli ortalamalar, destek/direnc),
    bilanco, GELIR TABLOSU, nakit akis, temettu gecmisi, sektor konumu ve
    son KAP bildirimleri.

    "Detayli analiz", "her seyi anlat", "genis analiz" gibi isteklerde
    araclari tek tek cagirmak yerine BUNU cagir. `eksik_bolumler` alanindaki
    bolumler icin veri YOKTUR; onlari bilinmiyor diye soyle, tahmin etme.
    """
    gorevler = {
        "profil": sirket_profili(kod),
        "fiyat": anlik_fiyat(kod),
        "oranlar": finansal_oranlar(kod),
        "teknik": teknik_analiz(kod),
        "bilanco": finansal_tablo(kod, "bilanco", "yillik", 2),
        "gelir_tablosu": finansal_tablo(kod, "gelir", "yillik", 2),
        "nakit_akis": finansal_tablo(kod, "nakit", "yillik", 2),
        "temettu": temettu_gecmisi(kod),
        "sektor": sektor_karsilastirma(kod),
        "kap": kap_bildirimleri(kod, 90),
    }
    tamamlanan = await asyncio.gather(*gorevler.values(), return_exceptions=True)
    return analizi_derle(kod, dict(zip(gorevler, tamamlanan)))

@sunucu.tool()
async def yonlu_hacim(
    kod: str, baslangic: str | None = None, bitis: str | None = None
) -> dict:
    """Alim/satim baskisi: hacmin ne kadari alici, ne kadari satici yonlu.

    "Kac hisse alinmis kac hisse satilmis" sorusunun birebir cevabi YOKTUR:
    her islemin hem alicisi hem saticisi vardir, iki sayi tanim geregi
    esittir ve gunluk hacme esittir. Farkli cikabilen tek olcu, islemin
    hangi tarafin AGRESIF davranmasiyla gerceklestigidir; bu arac onu verir.

    Tarih verilmezse son islem gunu kullanilir. Hafta icin baslangic ve
    bitis ver (gg dahil, ISO: 2026-09-01).

    SONUC TAHMINDIR. 5 dakikalik barlarda tick testiyle hesaplanir; gercek
    yontem her islemin alis mi satis fiyatindan gectigine bakar ve bunun
    icin tick verisi gerekir. Cevapta tahmin oldugunu SOYLE.
    """
    import datetime as dt

    bugun = dt.date.today()
    if baslangic:
        bas = dt.date.fromisoformat(baslangic)
        bit = dt.date.fromisoformat(bitis) if bitis else bas
        barlar = await fiyat.seans_barlari(kod, str(bas), str(bit + dt.timedelta(days=1)))
        tek_seans = False
    else:
        # Hafta sonu/tatilde bugunun verisi yok; son 7 gun cekilip son seans alinir.
        barlar = await fiyat.seans_barlari(
            kod, str(bugun - dt.timedelta(days=7)), str(bugun + dt.timedelta(days=1))
        )
        tek_seans = True

    if not barlar:
        return {
            "hata": f"{kod.upper()} icin seans ici veri bulunamadi. "
            "5 dakikalik veri yalnizca son ~60 gun icin var."
        }

    if tek_seans:
        barlar = son_seansi_ayikla(barlar)

    sonuc = yonlu_hacim_hesapla(barlar)
    sirket = await _sirket(kod)
    return {
        "kod": kod.upper(),
        "unvan": sirket.unvan if sirket else None,
        "baslangic": barlar[0]["zaman"],
        "bitis": barlar[-1]["zaman"],
        **sonuc,
        "not": (
            "1) Rakamlar HISSE ADEDIDIR. BIST'te 1 lot = 1 hissedir; lot "
            "cevrimi YAPMA, 100 ile carpma. "
            "2) Bu bir TAHMINDIR, gercek emir sayisi degildir: 5 dakikalik "
            "barlarda tick testiyle hesaplanir. "
            "3) Alinan toplam hisse ile satilan toplam hisse zaten esittir "
            "(ikisi de gunluk hacim kadar). Burada olculen AYRI bir sey: "
            "hacmin ne kadari alicinin, ne kadari saticinin agresif "
            "davranmasiyla gerceklesmis. "
            "4) Bar toplami resmî gunluk hacimden dusuk kalabilir (olculdu, "
            "THYAO 04.09: 42,5 milyon / resmî 44,8 milyon); yuzdeler bar "
            "toplami uzerinden hesaplanir. Bunlari cevapta acikca yaz."
        ),
    }


@sunucu.tool()
async def hisse_karsilastir(kodlar: list[str]) -> list[dict]:
    """Iki ile bes hisseyi temel oranlariyla yan yana koyar.

    'X mi Y mi daha ucuz', 'bunlari karsilastir' sorularinda kullan.
    """
    secilen = [k.strip().upper() for k in kodlar][:5]
    if len(secilen) < 2:
        return [{"hata": "en az iki hisse kodu gerekli"}]
    return list(await asyncio.gather(*(finansal_oranlar(kod) for kod in secilen)))


@sunucu.tool()
async def sektor_karsilastirma(kod: str) -> dict:
    """Hissenin kendi sektorundeki konumu: sektor ortalamasi ve akran sayisi.

    Tarama tablosuna dayanir (BIST geneli, islem goren hisseler).
    """
    bilgi = await fiyat.sirket_bilgi(kod)
    sektor = bilgi.get("sector")
    if not sektor:
        return {"hata": f"{kod.upper()} icin sektor bilgisi bulunamadi."}

    akranlar = gorunum.satirlari_sec(sektor=sektor, adet=100)
    if not akranlar:
        return {
            "kod": kod.upper(),
            "sektor": sektor,
            "hata": "Sektor tablosu henuz kurulmadi ya da bu sektorde baska "
            "hisse yok. Tekil oranlar icin finansal_oranlar kullan.",
        }

    fkler = [a["fk"] for a in akranlar if a["fk"]]
    pdddler = [a["pddd"] for a in akranlar if a["pddd"]]
    return {
        "kod": kod.upper(),
        "sektor": sektor,
        "sektordeki_sirket_sayisi": len(akranlar),
        "sektor_ortalama_fk": round(sum(fkler) / len(fkler), 2) if fkler else None,
        "sektor_ortalama_pddd": round(sum(pdddler) / len(pdddler), 2) if pdddler else None,
        "kapsam": "BIST geneli",
    }


@sunucu.tool()
async def hisse_tarama(
    fk_max: float | None = None,
    fk_min: float | None = None,
    pddd_max: float | None = None,
    temettu_verimi_min: float | None = None,
    piyasa_degeri_min: float | None = None,
    hacim_min: float | None = None,
    sektor: str | None = None,
    sirala: str = "piyasa_degeri",
    adet: int = 20,
) -> dict:
    """Verilen kriterlere uyan hisseleri listeler. Kriterler VE ile birlesir.

    Kapsam BIST'in tamami (~630 islem goren hisse), sadece BIST-100 degil.

    `hacim_min` gunluk ortalama TL islem hacmi alt siniridir ve OLU HISSELERI
    ELEMEK ICIN ONEMLIDIR: evrende gunde birkac lot islem goren kabuk
    sirketler var, bunlar "F/K'si dusuk" diye listenin basina cikar ama
    alinip satilamaz. Kullanici likidite belirtmediyse 10000000 (10 milyon TL)
    gibi bir taban kullan ve bunu cevabinda soyle.

    CEVAP YAZARKEN DIKKAT — cok dusuk F/K genellikle ucuzluk degil muhasebe
    etkisidir. Olculen ornek: ISGSY'nin F/K'si 0,21; piyasa degeri 1,08 milyar
    TL iken net kari 5,23 milyar TL gorunuyor, cunku bir girisim sermayesi
    ortakligi ve "kar"i portfoy yeniden degerleme kazanci — nakit kar degil.
    Holdingler, GYO'lar ve yatirim ortakliklari bu yuzden listenin basina
    cikar. F/K'si 2'nin altinda bir sirketi ucuz diye sunma; sirketin ne is
    yaptigina bak (gerekirse sirket_profili cagir) ve rakamin neden dusuk
    oldugunu acikla. Isletme karliligi aranan taramalarda fk_min=3 gibi bir
    alt sinir vermek daha anlamli sonuc verir.

    temettu_verimi_min yuzde olarak verilir (ornek: 5 = %5).
    sirala: fk, pddd, temettu_verimi, ortalama_hacim_tl veya piyasa_degeri.
    """
    satirlar = gorunum.satirlari_sec(
        fk_max=fk_max,
        fk_min=fk_min,
        pddd_max=pddd_max,
        temettu_verimi_min=temettu_verimi_min,
        piyasa_degeri_min=piyasa_degeri_min,
        hacim_min=hacim_min,
        sektor=sektor,
        sirala=sirala,
        adet=adet,
    )
    yas = gorunum.yas_saat()
    if yas is None:
        return {
            "hata": "Tarama tablosu henuz kurulmadi. Sunucu acilisinda arka planda "
            "kuruluyor, yaklasik 15 dakika surer. Biraz sonra tekrar dene. "
            "Tekil sorular (fiyat, oran, KAP) simdi de calisiyor."
        }
    return {
        "kapsam": "BIST geneli (islem goren tum hisseler)",
        "hacim_filtresi_tl": hacim_min,
        "veri_yasi_saat": round(yas, 1),
        "sonuc_sayisi": len(satirlar),
        "hisseler": satirlar,
    }


@sunucu.tool()
async def endeks_verisi(endeks: str = "XU100") -> dict:
    """BIST endekslerinin guncel degeri.

    Gecerli: XU100, XU030, XU050, XBANK (bankacilik), XUSIN (sinai),
    XUTEK (teknoloji), XUMAL (mali).
    """
    ad = endeks.strip().upper()
    if ad not in ENDEKSLER:
        return {"hata": f"gecersiz endeks: {endeks}. Gecerli: {', '.join(ENDEKSLER)}"}
    sonuc = await fiyat.anlik(ad)
    if not sonuc:
        return {"hata": f"{ad} icin veri alinamadi."}
    sonuc["ad"] = ENDEKSLER[ad]
    return sonuc


@sunucu.tool()
async def doviz_altin(varlik: str = "usdtry") -> dict:
    """Doviz kuru, altin ve emtia fiyati.

    Gecerli: usdtry, eurtry, gram_altin, ons_altin, gumus, brent.
    Gram altin ons fiyati ve USD/TRY kurundan hesaplanir; dayanak degerler
    cevapta yer alir.
    """
    return await kur.kur(varlik)


@sunucu.tool()
async def makro_gosterge(gosterge: str = "tufe", son_kayit: int = 12) -> dict:
    """TCMB makro gostergeleri: tufe, ufe, politika_faizi, tahvil_2y.

    Enflasyona gore reel getiri sorularinda tufe ile birlikte kullan.
    Doviz ve altin icin bunu DEGIL, doviz_altin aracini kullan.
    """
    from bist_mcp.kaynaklar.tcmb import GOSTERGELER

    if gosterge.strip().lower() not in GOSTERGELER:
        return {"hata": f"gecersiz gosterge. Gecerli: {', '.join(sorted(GOSTERGELER))}"}
    return await tcmb.gosterge(gosterge, son_kayit)


def log_kur(dosya: Path | None = None) -> None:
    """Konsol + doner dosya.

    `force=True` SART. Olculdu (09.09.2026): yfinance import sirasinda root
    logger'a bir RichHandler kuruyor ve `logging.basicConfig` root'ta zaten
    handler varsa HICBIR SEY YAPMAZ -- yani sunucunun kendi bicimi hic
    uygulanmiyordu.

    Dosya da SART: sunucu botun alt sureci oldugu icin stderr'i terminale
    karisiyor ve geriye kayit kalmiyordu. Olculdu: `borsa-ajan.log`'da
    "bist_mcp" gecen tek satir yok. Tam tarama ~15 dakika suruyor;
    kullanicinin ne oldugunu sonradan gorebilmesi gerekiyor.
    """
    dosya = dosya or LOG_DOSYASI
    doner = logging.handlers.RotatingFileHandler(
        dosya, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stderr), doner],
        force=True,
    )


def main() -> None:
    log_kur()
    sunucu.run()


if __name__ == "__main__":
    main()
