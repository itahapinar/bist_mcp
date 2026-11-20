"""Oran hesaplari — TL bazinda.

Hicbir saglayicinin hazir oran alani kullanilmaz. Olculen gerekce: yfinance
THYAO icin priceToBook = 18,64 veriyor, gercek deger 0,38 (49 kat). Sebep
sirketin finansallarini USD raporlamasi. Buradaki tum hesaplar Is Yatirim'dan
gelen TL rakamlarla yapilir.
"""


def defter_degeri(ozkaynak_tl: float, hisse_adedi: int) -> float:
    """Pay basina defter degeri (TL)."""
    if hisse_adedi <= 0:
        raise ValueError("hisse adedi pozitif olmali")
    return ozkaynak_tl / hisse_adedi


def pddd(fiyat_tl: float, ozkaynak_tl: float, hisse_adedi: int) -> float | None:
    """Piyasa degeri / defter degeri. Negatif ozkaynakta None."""
    if ozkaynak_tl <= 0:
        return None
    return fiyat_tl / defter_degeri(ozkaynak_tl, hisse_adedi)


def piyasa_degeri(fiyat_tl: float, hisse_adedi: int) -> float:
    if hisse_adedi <= 0:
        raise ValueError("hisse adedi pozitif olmali")
    return fiyat_tl * hisse_adedi


def fk(fiyat_tl: float, hisse_adedi: int, net_kar_tl: float) -> float | None:
    """Fiyat / kazanc. Zarar eden sirkette anlamsiz oldugu icin None."""
    if net_kar_tl <= 0:
        return None
    return piyasa_degeri(fiyat_tl, hisse_adedi) / net_kar_tl



# Yabanci para raporlayan sirkette ceyreklik rakam TL kumulatiften ~40 kat
# kucuk kalir (USD/TRY ~43, EUR/TRY ~47; olculdu THYAO 49,6x). Gercek TRY
# raporlayanlarda ise olculen en uc oran 14,89x (ISGYO), %99 dilim 12,50x.
# 25x bu iki kumenin arasindaki bosluğun ortasinda.
OLCEK_TAVANI = 25.0


def _ayni_olcekte(a: float, b: float) -> bool:
    buyuk, kucuk = max(abs(a), abs(b)), min(abs(a), abs(b))
    return kucuk > 0 and buyuk / kucuk <= OLCEK_TAVANI


def net_kar_sec(
    kumulatif: float | None,
    ceyreklik: float | None,
    para_birimi: str | None,
    kumulatif_aciklama: str,
) -> tuple[float | None, str]:
    """Son 12 ay karini secer: CEYREKLIK TOPLAM birincil, kumulatif yedek.

    NEDEN — kural 2'nin formulu (gecen yil yillik - gecen yil ayni kumulatif
    + bu yil kumulatif) FARKLI RAPORLARDAN gelen rakamlari cikariyor. TMS-29
    enflasyon muhasebesinde yillik rapor tum yili yil sonu satin alma gucune
    tasir, ara donem raporlari kendi donemlerinde kalir; ikisini cikarmak
    gecersiz. Ceyreklik toplam boyle bir cikarma icermez.

    Olculdu (150 hisselik orneklem, 137 karsilastirilabildi, 09.09.2026):
        isaret ters  5 (%3,6)  PGSUS, BRISA, ISGYO, MRSHL, GSRAY
        sapma >%10  77 (%56,2)          medyan sapma %12
    Gecise dair etki: F/K'larin medyani 1,07x oynuyor, 77 artiyor 24
    azaliyor, 3'u zarara dondugu icin kayboluyor. Zaten bozuk olanlar
    duzeliyor (ISBTR 188.788 -> 0,22; UFUK 1.524 -> 120).

    Kullanicinin referansiyla dogrulandi: KRDMD F/K 12,10 -> 7,85 (referans
    8,28); TAVHL kumulatifte %9,5 fazlaydi.

    PARA BIRIMI TRY DEGILSE CEYREKLIK KULLANILMAZ. THYAO finansallarini USD
    raporluyor: Is Yatirim 133,05 mlr TL, yfinance 2,685 mlr USD. USD kari
    TL fiyata bolmek kural 1'deki 49 kat hatanin ta kendisidir.

    Zarar oldugu gibi dondurulur; fk() zaten pozitif olmayan karda None verir.
    """
    if not ceyreklik:
        return kumulatif, kumulatif_aciklama

    birim = (para_birimi or "").strip().upper()
    if birim == "TRY":
        return ceyreklik, "son 4 ceyregin toplami"
    if birim:
        return kumulatif, kumulatif_aciklama  # bilinen yabanci para: asla

    # Para birimi HIC bilinmiyor (olculdu: 627 hissenin 133'unde alan bos,
    # ne ekranda ne Ticker.info'da). Bunlari kumulatife birakmak evrenin
    # %21'ini bozuk birakirdi; olcek kontrolu kur uyusmazligini eliyor.
    if kumulatif is None or _ayni_olcekte(kumulatif, ceyreklik):
        return ceyreklik, "son 4 ceyregin toplami"
    return kumulatif, kumulatif_aciklama


def temettu_verimi(temettu_12ay_tl: float | None, fiyat_tl: float | None) -> float | None:
    """Son 12 ayda odenen temettunun fiyata orani (yuzde)."""
    if temettu_12ay_tl is None or not fiyat_tl:
        return None
    if fiyat_tl <= 0:
        raise ValueError("fiyat pozitif olmali")
    return temettu_12ay_tl / fiyat_tl * 100


# PD/DD bu araligin disindaysa oran guvenilmez sayilir: ozkaynak erimis
# olabilir ya da hisse adedi yanlis cozulmustur.
MAKUL_PDDD = (0.01, 50.0)


def oran_makul(pddd_degeri: float | None) -> bool:
    """PD/DD makul araliktaysa True. None ise karar verilemez, True doner."""
    if pddd_degeri is None:
        return True
    return MAKUL_PDDD[0] <= pddd_degeri <= MAKUL_PDDD[1]


# --- Yonlu hacim -----------------------------------------------------------
# Kullanici "kac hisse alinmis kac hisse satilmis" diye sordu. Birebir
# cevabi yok: her islemin hem alicisi hem saticisi var, iki sayi tanim
# geregi esittir. Farkli cikabilen tek olcu, islemin hangi tarafin AGRESIF
# davranmasiyla gerceklestigidir.
#
# Tick testi: kapanis onceki kapanistan yuksekse alici yonlu, dusukse
# satici yonlu, esitse son yon devam eder. Olculdu (THYAO 04.09, 5 dk):
# acilis-kapanis yontemi hacmin %20,4'unu siniflandiramiyor, tick testi
# %4,3. TAHMINDIR -- gercek yontem her islemin alis mi satis fiyatindan
# gectigine bakar, onun icin tick verisi gerekir.
YONTEM = "tick testi (5 dakikalik barlarda kapanis yonu)"


def yonlu_hacim_hesapla(barlar: list[dict]) -> dict:
    """Barlari alici/satici yonlu hacme ayirir."""
    dolu = [b for b in barlar if (b.get("hacim") or 0) > 0]

    alici = satici = bilinmeyen = 0
    onceki = None
    son_yon = 0

    for bar in dolu:
        kapanis, hacim = bar["kapanis"], bar["hacim"]
        if onceki is None or kapanis == onceki:
            yon = son_yon
        else:
            yon = 1 if kapanis > onceki else -1
        onceki = kapanis
        if yon:
            son_yon = yon

        if yon > 0:
            alici += hacim
        elif yon < 0:
            satici += hacim
        else:
            bilinmeyen += hacim

    toplam = alici + satici + bilinmeyen
    pay = lambda x: round(x / toplam * 100, 1) if toplam else None  # noqa: E731
    return {
        "alici_yonlu_adet": alici,
        "satici_yonlu_adet": satici,
        "siniflandirilamayan_adet": bilinmeyen,
        "toplam_adet": toplam,
        "alici_yuzde": pay(alici),
        "satici_yuzde": pay(satici),
        "net_adet": alici - satici,
        "birim": "hisse adedi (BIST'te 1 lot = 1 hisse)",
        "bar_sayisi": len(dolu),
        "yontem": YONTEM,
    }


def son_seansi_ayikla(barlar: list[dict]) -> list[dict]:
    """Yalnizca en son gunun barlarini birakir.

    Tarih verilmediginde "son islem gunu" isteniyor; hafta sonu ve tatilde
    bugunun verisi olmadigi icin gun secmek yerine gelen barlarin son gunu
    alinir.
    """
    if not barlar:
        return []
    son_gun = barlar[-1]["zaman"][:10]
    return [b for b in barlar if b["zaman"][:10] == son_gun]
