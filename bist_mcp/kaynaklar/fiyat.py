"""Fiyat ve OHLCV kaynagi (yfinance).

DIKKAT: yfinance'in turetilmis alanlari BIST'te bozuk. Olculen ornek —
THYAO priceToBook 18,64 diyor, gercek deger 0,38 (49 kat sapma). Sebep:
sirket finansallarini USD raporluyor, hissesi TRY islem goruyor ve yfinance
TL fiyati USD defter degerine boluyor. Ayni sekilde ASELS icin 0 haber
donuyor. Bu yuzden bu modulden yalnizca ham fiyat, OHLCV, temettu odemesi,
hisse adedi ve sektor cikar; oranlar hesap.py'de TL bazinda hesaplanir.

Endeksler de ayni ".IS" ekini alir (olculdu: XU100.IS calisir, ^XU100 bos).

Chart ustverisinden (history_metadata) yalnizca HAM kotasyon okunur:
regularMarketPrice/DayHigh/DayLow/Volume/Time ve previousClose. Bunlar
turetilmis alan degil, borsanin kendi rakamlaridir; yasak liste hesaplanmis
oranlar icindir. Gerekce ustveriyle_tamamla'da.
"""

import asyncio
import datetime as dt
import logging

import yfinance as yf

from bist_mcp.hiz_sinir import HizSinirlayici
from bist_mcp.onbellek import Onbellek

kayit = logging.getLogger(__name__)

IZINLI_INFO_ALANLARI = frozenset(
    {"sharesOutstanding", "sector", "currency", "financialCurrency", "longName"}
)
YASAK_INFO_ALANLARI = frozenset(
    {"priceToBook", "trailingPE", "forwardPE", "dividendYield", "marketCap", "bookValue"}
)

ANLIK_TTL = 60
GECMIS_TTL = 3600
BILGI_TTL = 7 * 24 * 3600
# Temettu odemesi yilda birkac kez; gunluk tazeleme fazlasiyla yeterli.
TEMETTU_TTL = 24 * 3600
# Finansal tablo ceyrekte bir degisir; gunluk tazeleme yeterli.
CEYREK_TTL = 24 * 3600
# Son 12 ay = son dort ceyrek.
CEYREK_SAYISI = 4
# Seans ici barlar gun icinde degisir; gecmis gunlerde sabittir.
SEANS_TTL = 300
HACIM_PENCERESI = 60  # likidite icin son 60 islem gunu

# Yahoo TEKIL uc noktalari (Ticker.history, Ticker.info) hizli ard arda
# cagrilinca YFRateLimitError veriyor. Olculdu: 630 hisselik tam kurulum
# sinirlayicisiz kosunca hem history hem info kilitlendi, yalnizca toplu
# download ayakta kaldi. Toplu indirmenin sinira ihtiyaci yok - o tek istek.
TEKIL_ISTEK_ARALIGI_SN = 0.6

# Yahoo ekran (screener) uc noktasi: borsanin TAMAMINI sayfa sayfa doner.
# Olculdu: exchange=IST -> 627 hisse, 250'lik 3 sayfa, 1,4 sn.
EKRAN_BORSASI = "IST"
EKRAN_SAYFA = 250
EKRAN_SAYFA_TAVANI = 8  # 2000 hisse; sonsuz dongu emniyeti


def bist_sembol(kod: str) -> str:
    kod = kod.strip().upper()
    return kod if kod.endswith(".IS") else f"{kod}.IS"


def info_suz(ham: dict) -> dict:
    """Yalnizca izinli alanlari birakir; turetilmis alanlar atilir."""
    return {k: v for k, v in ham.items() if k in IZINLI_INFO_ALANLARI}


def temettu_penceresi(odemeler: list[dict], yil: int, bugun=None) -> list[dict]:
    """Son `yil` yildaki odemeleri yeniden eskiye siralar."""
    bugun = bugun or dt.date.today()
    sinir = bugun - dt.timedelta(days=365 * yil)
    secilen = [o for o in odemeler if dt.date.fromisoformat(o["tarih"]) >= sinir]
    return sorted(secilen, key=lambda o: o["tarih"], reverse=True)


def kapanisi_olan_satirlar(veri):
    """Kapanis fiyati bos olan satirlari atar.

    Olculdu (MEKAG, 08.09.2026 05:30): Yahoo seans verisi yayimlanmadan
    once o gun icin satir donduruyor -- Volume dolu ama OHLC bos. Son
    satiri almak `anlik`ta fiyat=NaN uretiyor; model NaN'i gorup yanindaki
    onceki kapanisi aliyor ve O SATIRIN TARIHIYLE sunuyordu, yani hem
    fiyat hem tarih yanlis oluyordu. Ayni satirlar teknik_analiz'e sizinca
    RSI ve hareketli ortalamalar da NaN cikiyor.
    """
    if veri.empty or "Close" not in veri.columns:
        return veri
    return veri[veri["Close"].notna()]


def seans_gunu(ustveri: dict) -> str | None:
    """Chart ustverisindeki son islem anini BORSA saatiyle gune cevirir.

    Yerel saat ya da UTC kullanmak gun kaydirabilir; gmtoffset ustverinin
    kendi icinde geliyor.
    """
    an = ustveri.get("regularMarketTime")
    if an is None:
        return None
    try:
        fark = dt.timedelta(seconds=int(ustveri.get("gmtoffset") or 0))
        return str(dt.datetime.fromtimestamp(int(an), dt.timezone(fark)).date())
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def ustveriyle_tamamla(satir: dict, ustveri: dict) -> dict:
    """Gunluk seri son seansi vermediyse ayni cagrinin ustverisinden tamamlar.

    Olculdu (09.09.2026 01:28): Yahoo gunluk barlari BIST'te son seansin
    kapanisini saatlerce gec yayimliyor (Open/High/Low dolu, Close NaN) ve
    kimi zaman bir seansi (THYAO 07.09) hic vermiyor. Kapanisi bos satir
    atilinca geriye 1-2 seans eski satir kaliyor ve "son fiyat" diye
    sunuluyordu -- THYAO icin 296,00 TL / 04.09, gercegi 305,00 TL / 08.09.

    history_metadata ayni istekle geldigi icin bu duzeltme EK ISTEK
    GEREKTIRMEZ. Ustveri daha eski ya da ayni seansi gosteriyorsa satira
    dokunulmaz; gunluk seri saglikliyken davranis degismez.
    """
    gun = seans_gunu(ustveri)
    fiyat = ustveri.get("regularMarketPrice")
    if gun is None or fiyat is None:
        return satir
    if satir.get("tarih") and gun <= satir["tarih"]:
        return satir

    kapanis = round(float(fiyat), 2)
    # Ustverinin previousClose'u kendi degisim yuzdesiyle tutarli (olculdu:
    # 5 hissenin 5'inde birebir). Gunluk serinin son kapanisi ise arada
    # eksik seans varsa yanlis referans olur (THYAO: 04.09 kapanisi 296,00
    # ama gercek onceki seans 07.09 kapanisi 296,75).
    onceki = ustveri.get("previousClose")
    onceki_kapanis = round(float(onceki), 2) if onceki else satir.get("fiyat")

    return {
        **satir,
        "fiyat": kapanis,
        "onceki_kapanis": onceki_kapanis,
        "degisim_yuzde": (
            round((kapanis / onceki_kapanis - 1) * 100, 2) if onceki_kapanis else None
        ),
        "gun_yuksek": round(float(ustveri.get("regularMarketDayHigh") or fiyat), 2),
        "gun_dusuk": round(float(ustveri.get("regularMarketDayLow") or fiyat), 2),
        "hacim": int(ustveri.get("regularMarketVolume") or 0),
        "tarih": gun,
    }



# yfinance ceyreklik gelir tablosunda net kar satiri; ilk eslesen kullanilir.
NET_KAR_SATIRLARI = ("Net Income Common Stockholders", "Net Income")


def _bos_ceyrek(deger) -> bool:
    return deger is None or deger != deger  # NaN kendine esit degildir


def ceyreklik_toplam(degerler) -> float | None:
    """Son CEYREK_SAYISI ceyregin toplami. Pencere BITISIK olmali.

    Olculdu (GIPTA, 09.09.2026 04:27 -- kullanicinin gordugu F/K 145,65):
        2026-06-30      3.886.119
        2026-03-31   -103.901.230
        2025-12-31   -380.127.543
        2025-09-30      EKSIK
        2025-06-30    551.560.081
    Ilk surum bos ceyregi ATLAYIP bir oncekini aliyordu; son 12 ay yerine
    15 aylik DELIKLI pencere toplaniyor ve bir yil onceki 551 milyonluk
    ceyrek iceri giriyordu -> +71.417.427 ve F/K 145,65. Is Yatirim'in
    kumulatifi -336.474.281, yani sirket ZARARDA.

    Bastaki bos sutunlar atlanir (donem var ama rapor henuz gelmemis);
    ondan sonraki dortte bir bosluk varsa toplam VERILMEZ ve cagiran
    kumulatif formule duser.
    """
    dizi = list(degerler or ())
    bas = 0
    while bas < len(dizi) and _bos_ceyrek(dizi[bas]):
        bas += 1

    pencere = dizi[bas : bas + CEYREK_SAYISI]
    if len(pencere) < CEYREK_SAYISI or any(_bos_ceyrek(d) for d in pencere):
        return None
    return sum(float(d) for d in pencere)

def kotasyon_satiri(kayit_: dict) -> dict | None:
    """Ekran kaydini HAM kotasyona indirger.

    Beyaz liste zorunlu: ekran kaydi priceToBook, trailingPE, dividendYield,
    marketCap ve bookValue alanlarini da tasiyor -- kural 1 bunlari yasakliyor
    (THYAO priceToBook 18,64 diyor, gercegi 0,38).
    """
    sembol = kayit_.get("symbol")
    fiyat = kayit_.get("regularMarketPrice")
    if not sembol or fiyat is None:
        return None

    # Ekran ofseti MILISANIYE veriyor; saniye sanilirsa gun kayar.
    ofset_ms = kayit_.get("gmtOffSetMilliseconds")
    gun = seans_gunu(
        {
            "regularMarketTime": kayit_.get("regularMarketTime"),
            "gmtoffset": ofset_ms / 1000 if ofset_ms is not None else kayit_.get("gmtoffset"),
        }
    )
    if gun is None:
        return None

    onceki = kayit_.get("regularMarketPreviousClose")
    return {
        "kod": str(sembol).removesuffix(".IS").strip().upper(),
        "fiyat": round(float(fiyat), 2),
        "onceki_kapanis": round(float(onceki), 2) if onceki else None,
        "gun_yuksek": round(float(kayit_.get("regularMarketDayHigh") or fiyat), 2),
        "gun_dusuk": round(float(kayit_.get("regularMarketDayLow") or fiyat), 2),
        "hacim": int(kayit_.get("regularMarketVolume") or 0),
        "tarih": gun,
    }


def ekran_kotasyonlari(kayitlar) -> dict[str, dict]:
    """Ekran sayfalarini {KOD: kotasyon} sozlugune cevirir; bozuk kayit atilir."""
    kotasyonlar = {}
    for ham in kayitlar or ():
        satir = kotasyon_satiri(ham) if isinstance(ham, dict) else None
        if satir:
            kotasyonlar[satir["kod"]] = satir
    return kotasyonlar


def kotasyonla_tamamla(toplu: dict, kotasyonlar: dict) -> dict:
    """Toplu indirmede eksik kalan son seansi ekran kotasyonundan tamamlar.

    Olculdu (09.09.2026): yf.download son seansin kapanisini vermiyor
    (Close NaN) ve kimi seansi hic getirmiyor; tarama tablosu bu yuzden
    1-2 seans geride kaliyordu -- THYAO 296,00 (gercegi 305,00), SISE 39,08
    (gercegi 45,82). Beklemek cozmuyor: THYAO'nun 07.09 bari bir islem gunu
    sonra 1 aylik seride de yok.

    Ekran fiyatlari hisse basina kotasyonla BIREBIR ayni cikti (6 hissenin
    6'si), yani bu yaklasik bir dolgu degil. Yalnizca fiyat ve tarih
    degisir; temettu ile ortalama hacim toplu indirmenin isidir.

    Ekranda olmayan hisse (olculdu: ISATR, ISKUR, UMPAS) ve kotasyonun
    gelmedigi durum gunluk bara duser -- yani eski davranis korunur.
    """
    if not kotasyonlar:
        return toplu

    tamamlanan = {}
    for kod, satir in toplu.items():
        kotasyon = kotasyonlar.get(kod)
        if kotasyon and (not satir.get("tarih") or kotasyon["tarih"] > satir["tarih"]):
            satir = {**satir, "fiyat": kotasyon["fiyat"], "tarih": kotasyon["tarih"]}
        tamamlanan[kod] = satir
    return tamamlanan


def ortalama_hacim_tl(hacimler, kapanislar, gun: int = HACIM_PENCERESI) -> float | None:
    """Son `gun` islem gununun ortalama TL islem hacmi (adet x fiyat).

    Likidite olcusu olarak adet degil TL kullanilir: 1 TL'lik hisseden
    100.000 adet ile 400 TL'lik hisseden 100.000 adet ayni likidite degildir.
    """
    try:
        cerceve = (hacimler * kapanislar).dropna().tail(gun)
    except (TypeError, ValueError):
        return None
    if cerceve.empty:
        return None
    return round(float(cerceve.mean()), 2)


class FiyatKaynak:
    def __init__(self, onbellek: Onbellek) -> None:
        self._onbellek = onbellek
        # Ayni anda gelen ayni toplu istegi tek indirmede birlestirir.
        self._ucus_halinde: dict[str, asyncio.Future] = {}
        # Tekil cagrilar icin; toplu download bunu kullanmaz.
        self._sinirlayici = HizSinirlayici(TEKIL_ISTEK_ARALIGI_SN)

    async def anlik(self, kod: str) -> dict:
        anahtar = f"fiyat:anlik:{kod.upper()}"
        onbellekli = self._onbellek.al(anahtar)
        if onbellekli is not None:
            return onbellekli

        def _cek() -> dict:
            bilet = yf.Ticker(bist_sembol(kod))
            veri = kapanisi_olan_satirlar(bilet.history(period="5d", interval="1d"))
            satir: dict = {"kod": kod.upper(), "para_birimi": "TRY"}
            if not veri.empty:
                son = veri.iloc[-1]
                onceki = veri.iloc[-2] if len(veri) > 1 else son
                kapanis = float(son["Close"])
                onceki_kapanis = float(onceki["Close"])
                satir |= {
                    "fiyat": round(kapanis, 2),
                    "onceki_kapanis": round(onceki_kapanis, 2),
                    "degisim_yuzde": (
                        round((kapanis / onceki_kapanis - 1) * 100, 2)
                        if onceki_kapanis
                        else None
                    ),
                    "gun_yuksek": round(float(son["High"]), 2),
                    "gun_dusuk": round(float(son["Low"]), 2),
                    "hacim": int(son["Volume"]),
                    "tarih": str(veri.index[-1])[:10],
                }
            # Ustveri ayni istekle gelir; gunluk seri gecikmisse son seansi
            # o tasir. Bkz. ustveriyle_tamamla.
            try:
                ustveri = bilet.history_metadata or {}
            except Exception:  # noqa: BLE001 - ustveri yoksa gunluk seri yeter
                ustveri = {}
            satir = ustveriyle_tamamla(satir, ustveri)
            return satir if satir.get("fiyat") is not None else {}

        await self._sinirlayici.bekle()
        sonuc = await asyncio.to_thread(_cek)
        self._onbellek.yaz(anahtar, sonuc, ANLIK_TTL)
        return sonuc

    async def gecmis(self, kod: str, baslangic: str, bitis: str | None = None) -> list[dict]:
        bitis = bitis or baslangic
        anahtar = f"fiyat:gecmis:{kod.upper()}:{baslangic}:{bitis}"
        onbellekli = self._onbellek.al(anahtar)
        if onbellekli is not None:
            return onbellekli

        # Istenen gun kapali olabilir (hafta sonu/tatil); pencere +-5 gun genisletilir.
        bas = dt.date.fromisoformat(baslangic) - dt.timedelta(days=5)
        bit = dt.date.fromisoformat(bitis) + dt.timedelta(days=5)

        def _cek() -> list[dict]:
            veri = kapanisi_olan_satirlar(
                yf.Ticker(bist_sembol(kod)).history(
                    start=str(bas), end=str(bit), interval="1d"
                )
            )
            return [
                {
                    "tarih": str(idx)[:10],
                    "acilis": round(float(s["Open"]), 2),
                    "yuksek": round(float(s["High"]), 2),
                    "dusuk": round(float(s["Low"]), 2),
                    "kapanis": round(float(s["Close"]), 2),
                    "hacim": int(s["Volume"]),
                }
                for idx, s in veri.iterrows()
            ]

        await self._sinirlayici.bekle()
        sonuc = await asyncio.to_thread(_cek)
        self._onbellek.yaz(anahtar, sonuc, GECMIS_TTL)
        return sonuc

    async def _temettu_indir(self, kod: str) -> list[dict]:
        """yfinance temettu serisi: odeme tarihi ve hisse basina tutar."""

        def _cek() -> list[dict]:
            seri = yf.Ticker(bist_sembol(kod)).dividends
            return [
                {"tarih": str(idx)[:10], "hisse_basina_tl": round(float(tutar), 4)}
                for idx, tutar in seri.items()
                if float(tutar) > 0
            ]

        await self._sinirlayici.bekle()
        return await asyncio.to_thread(_cek)

    async def temettu_odemeleri(self, kod: str, yil: int = 5, bugun=None) -> list[dict]:
        """Gecmis temettu ODEMELERI: tarih + hisse basina tutar.

        Olculdu (DOAS): "temettu tarihleri" sorulunca arac yalnizca KAP
        DUYURU tarihlerini donduruyordu; duyuru tarihi odeme tarihi degildir
        ve hisse basina tutari hic vermiyordu.
        """
        anahtar = f"fiyat:temettu:{kod.strip().upper()}"
        ham = self._onbellek.al(anahtar)
        if ham is None:
            ham = await self._temettu_indir(kod)
            if ham:
                self._onbellek.yaz(anahtar, ham, TEMETTU_TTL)
        return temettu_penceresi(ham, yil, bugun)

    async def seans_barlari(
        self, kod: str, baslangic: str, bitis: str, aralik: str = "5m"
    ) -> list[dict]:
        """Seans ici barlar (varsayilan 5 dakikalik): zaman, kapanis, hacim.

        yfinance 5 dakikalik veriyi yalnizca son ~60 gun icin veriyor.
        """
        anahtar = f"fiyat:seans:{kod.upper()}:{baslangic}:{bitis}:{aralik}"
        onbellekli = self._onbellek.al(anahtar)
        if onbellekli is not None:
            return onbellekli

        def _cek() -> list[dict]:
            veri = kapanisi_olan_satirlar(
                yf.Ticker(bist_sembol(kod)).history(
                    start=baslangic, end=bitis, interval=aralik
                )
            )
            return [
                {
                    "zaman": str(idx)[:16],
                    "kapanis": round(float(s["Close"]), 2),
                    "hacim": int(s["Volume"]),
                }
                for idx, s in veri.iterrows()
            ]

        await self._sinirlayici.bekle()
        sonuc = await asyncio.to_thread(_cek)
        if sonuc:
            self._onbellek.yaz(anahtar, sonuc, SEANS_TTL)
        return sonuc

    async def sirket_bilgi(self, kod: str) -> dict:
        """Hisse adedi ve sektor. Turetilmis alanlar suzulur."""
        anahtar = f"fiyat:bilgi:{kod.upper()}"
        onbellekli = self._onbellek.al(anahtar)
        if onbellekli is not None:
            return onbellekli

        await self._sinirlayici.bekle()
        sonuc = info_suz(await asyncio.to_thread(lambda: yf.Ticker(bist_sembol(kod)).info))
        self._onbellek.yaz(anahtar, sonuc, BILGI_TTL)
        return sonuc

    async def ceyreklik_net_kar_ttm(self, kod: str) -> float | None:
        """Son dort ceyregin net kar toplami -- Is Yatirim TTM'ine ikinci gorus.

        Kural 2'nin kumulatif formulu enflasyon muhasebesinde isaret
        cevirebiliyor (bkz. hesap.ttm_capraz_gecerli). Burasi ceyreklik
        rakamlari toplar, yani donemler arasi cikarma yapmaz.

        DIKKAT: bu rakam sirketin RAPORLAMA para biriminde. TRY olup
        olmadigini cagiran denetler.
        """
        anahtar = f"fiyat:ceyrek_kar:{kod.strip().upper()}"
        onbellekli = self._onbellek.al(anahtar)
        if onbellekli is not None:
            return onbellekli.get("ttm")

        def _cek() -> float | None:
            cerceve = yf.Ticker(bist_sembol(kod)).quarterly_income_stmt
            if cerceve is None or getattr(cerceve, "empty", True):
                return None
            for ad in NET_KAR_SATIRLARI:
                if ad in cerceve.index:
                    return ceyreklik_toplam(list(cerceve.loc[ad]))
            return None

        await self._sinirlayici.bekle()
        try:
            sonuc = await asyncio.to_thread(_cek)
        except Exception:  # noqa: BLE001 - ikinci gorus yoksa asil rakam kalir
            kayit.warning("%s icin ceyreklik net kar alinamadi", kod, exc_info=True)
            return None
        self._onbellek.yaz(anahtar, {"ttm": sonuc}, CEYREK_TTL)
        return sonuc

    async def toplu_kotasyon(self) -> dict[str, dict]:
        """Borsanin tamaminin anlik kotasyonu; sayfa sayfa TEK ekran sorgusu.

        Olculdu: 627 hisse, 250'lik 3 sayfa, 1,4 sn. Hisse basina kotasyon
        cekmek ayni sonucu 630 istekle verirdi ve Yahoo'nun tekil uc noktalari
        o yukte YFRateLimitError veriyor (bkz. TEKIL_ISTEK_ARALIGI_SN).

        Ekran cokerse BOS sozluk doner: tamamlama devre disi kalir, tarama
        gunluk barla eski davranisiyla calismaya devam eder.
        """
        anahtar = f"fiyat:kotasyon:{EKRAN_BORSASI}"
        onbellekli = self._onbellek.al(anahtar)
        if onbellekli is not None:
            return onbellekli

        def _cek() -> dict[str, dict]:
            kayitlar: list[dict] = []
            for sayfa in range(EKRAN_SAYFA_TAVANI):
                yanit = yf.screen(
                    yf.EquityQuery("eq", ["exchange", EKRAN_BORSASI]),
                    offset=sayfa * EKRAN_SAYFA,
                    size=EKRAN_SAYFA,
                )
                gelen = (yanit or {}).get("quotes") or []
                kayitlar.extend(gelen)
                if len(gelen) < EKRAN_SAYFA:
                    break
            return ekran_kotasyonlari(kayitlar)

        ucus = self._ucus_halinde.get(anahtar)
        if ucus is None:
            ucus = asyncio.ensure_future(asyncio.to_thread(_cek))
            self._ucus_halinde[anahtar] = ucus
        try:
            sonuc = await asyncio.shield(ucus)
        except Exception:  # noqa: BLE001 - kotasyon yoksa gunluk bar yeter
            kayit.exception("Ekran kotasyonu alinamadi; toplu fiyatlar gunluk bara kaliyor")
            return {}
        finally:
            self._ucus_halinde.pop(anahtar, None)

        if sonuc:
            self._onbellek.yaz(anahtar, sonuc, ANLIK_TTL)
        return sonuc

    async def _toplu_indir(self, kodlar: list[str]) -> dict[str, dict]:
        """Tek yf.download cagrisi. Onbellek ve tekillestirme toplu()'da."""
        semboller = [bist_sembol(k) for k in kodlar]

        def _cek() -> dict[str, dict]:
            cerceve = yf.download(
                semboller,
                period="1y",
                interval="1d",
                actions=True,
                group_by="ticker",
                progress=False,
                auto_adjust=False,
                threads=True,
            )
            sonuc: dict[str, dict] = {}
            for kod, sembol in zip(kodlar, semboller):
                try:
                    kapanislar = cerceve[(sembol, "Close")].dropna()
                    if kapanislar.empty:
                        continue
                    temettuler = cerceve[(sembol, "Dividends")]
                    sonuc[kod.strip().upper()] = {
                        "fiyat": round(float(kapanislar.iloc[-1]), 2),
                        "temettu_12ay": round(float(temettuler[temettuler > 0].sum()), 4),
                        "ortalama_hacim_tl": ortalama_hacim_tl(
                            cerceve[(sembol, "Volume")], cerceve[(sembol, "Close")]
                        ),
                        "tarih": str(kapanislar.index[-1])[:10],
                    }
                except (KeyError, IndexError):
                    continue
            return sonuc

        return await asyncio.to_thread(_cek)

    async def toplu(self, kodlar: list[str]) -> dict[str, dict]:
        """Cok hisseyi TEK istekte ceker: fiyat, son 12 ay temettusu, hacim.

        Olculdu: 10 hisse 0,79 sn, 807 hisse 40 sn. Temettu ve hacim bu
        cagriya dahil oldugu icin hisse basina ayri istek gerekmez.

        `ortalama_hacim_tl` son 60 islem gununun ortalama TL islem hacmidir
        (adet x fiyat). Likidite olcusu olarak adet degil TL kullanilir:
        1 TL'lik hisseden 100.000 adet ile 400 TL'lik hisseden 100.000 adet
        ayni likidite degildir. Taramada olu hisseleri elemek icin var.

        Gunluk barlar son seansi kaciriyor (kural 37) ama tamamlama BURADA
        YAPILMAZ: bu cagrinin cagiranlarindan yalnizca tarama tablosu fiyati
        kullaniyor, `finansal_oranlar` ile `temettu_gecmisi` buradan sadece
        temettu ve hacim aliyor (fiyati `anlik`tan). Tamamlamayi buraya
        koymak o iki yola her soruda 3 gereksiz ekran istegi ekliyordu ve
        Yahoo hiz sinirini tetikliyordu (olculdu, 09.09.2026 02:13: FROTO
        icin ust uste "Too Many Requests"). Tamamlama AnlikGorunum'da.

        Sonuc ANLIK_TTL boyunca onbelleklenir ve ayni anda gelen ayni istek
        TEK indirmede birlesir. Olculdu: detayli_analiz icinde anlik_fiyat,
        finansal_oranlar ve temettu_gecmisi ucu birden bu cagriyi yapiyor;
        onbelleksiz surumde ayni indirme uc kez paralel gidiyordu ve biri
        bos donunce temettu "odenmemis" gibi gorunuyordu.
        """
        anahtar = "fiyat:toplu:" + ",".join(sorted(k.strip().upper() for k in kodlar))

        onbellekli = self._onbellek.al(anahtar)
        if onbellekli is not None:
            return onbellekli

        ucus = self._ucus_halinde.get(anahtar)
        if ucus is None:
            ucus = asyncio.ensure_future(self._toplu_indir(kodlar))
            self._ucus_halinde[anahtar] = ucus
        try:
            sonuc = await asyncio.shield(ucus)
        finally:
            self._ucus_halinde.pop(anahtar, None)

        # Bos sonuc yazilmaz: gecici bir indirme hatasi ANLIK_TTL boyunca
        # kalici "veri yok" haline gelirdi.
        if sonuc:
            self._onbellek.yaz(anahtar, sonuc, ANLIK_TTL)
        return sonuc
