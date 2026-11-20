"""Is Yatirim finansal tablo kaynagi.

Olculen sonuclar: THYAO 147 kalem (XI_29), GARAN 192 kalem BDDK formati
(UFRS_K). Tekil cagri suresi ~0,31 sn.

DONEM SECIMI — takvim aritmetigi ile tahmin edilmez. Olculen davranis
(2026-09-05): 2026/12 ve 2026/9 bos doner (henuz yayimlanmadi), 2026/6 ve
2025/12 dolu. Sirketler raporlarini farkli tarihlerde acikladigi icin
"su an hangi donem yayimlanmistir" hesabi kirilgan. Bunun yerine yeni'den
eskiye aday donemler istenir ve BOS DONEN SLOTLAR ATILIR: karisik pencerede
yayimlanmamis donem None gelir, digerleri dolu gelir (olculdu).
"""

import asyncio
import datetime as dt
import logging

import httpx

from bist_mcp.hiz_sinir import HizSinirlayici
from bist_mcp.kaynaklar.kap import tablo_grubu_sec, yedek_grup
from bist_mcp.onbellek import Onbellek

kayit = logging.getLogger(__name__)

KOK = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx"
ISTEK_ARALIGI_SN = 0.5  # kisisel kullanim; 2 istek/sn tavani
TABLO_TTL = 24 * 3600
SLOT_SAYISI = 4  # API tek istekte en fazla 4 donem tasiyor


def donem_adaylari(donem: str, bugun: dt.date | None = None) -> list[tuple[int, int]]:
    """Yeniden eskiye aday (yil, ay) ciftleri.

    Agresif baslar — en yeni adaylar yayimlanmamis olabilir; bos slotlar
    sonradan atilir.
    """
    bugun = bugun or dt.date.today()

    if donem == "yillik":
        return [(bugun.year - i, 12) for i in range(6)]

    adaylar: list[tuple[int, int]] = []
    yil, ay = bugun.year, 12
    while len(adaylar) < 12:
        adaylar.append((yil, ay))
        ay -= 3
        if ay == 0:
            yil, ay = yil - 1, 12
    return adaylar


def donem_etiketi(yil: int, ay: int, donem: str) -> str:
    if donem == "yillik":
        return f"{yil} yıllık"
    return f"{yil} ilk {ay} ay"


def sayiya_cevir(ham_deger) -> float | None:
    """Is Yatirim degerleri STRING doner ('1073081134047', '-941964141907').

    Sayiya cevrilmezse iki hata olusur: oran hesaplari string bolemez ve
    sifir satirlari atilmaz ('0' != 0).
    """
    if ham_deger is None or ham_deger == "":
        return None
    if isinstance(ham_deger, (int, float)):
        return float(ham_deger)
    metin = str(ham_deger).strip().replace(" ", "")
    # Turkce format ihtimaline karsi: nokta binlik, virgul ondalik
    if "," in metin:
        metin = metin.replace(".", "").replace(",", ".")
    try:
        return float(metin)
    except ValueError:
        return None


def dolu_slotlar(ham: dict) -> list[int]:
    """Verisi olan slot numaralarini (1..4) doner.

    Yayimlanmamis donem tum satirlarda None gelir; o slot atilir.
    """
    satirlar = ham.get("value") or []
    return [
        i
        for i in range(1, SLOT_SAYISI + 1)
        if any(s.get(f"value{i}") is not None for s in satirlar)
    ]


def kalem_ayikla(ham: dict, slotlar: list[int] | None = None) -> list[dict]:
    """Is Yatirim yanitini {ad, degerler} listesine cevirir.

    Kalem adlarina dokunulmaz: 'XVI. OZKAYNAKLAR' neyse o kalir.

    Degerler her satirda AYNI slotlardan alinir. Satir bazinda None atmak
    hataliydi: bazi kalemler bir donemde raporlanmiyor (olculdu: slot4'te
    145, digerlerinde 147 kalem dolu) ve o satirlarda degerler bir donem
    kayiyordu.
    """
    satirlar = ham.get("value") or []
    if slotlar is None:
        slotlar = dolu_slotlar(ham)

    kalemler = []
    for satir in satirlar:
        ad = (satir.get("itemDescTr") or "").strip()
        if not ad:
            continue
        kalemler.append(
            {"ad": ad, "degerler": [sayiya_cevir(satir.get(f"value{i}")) for i in slotlar]}
        )
    return kalemler


def sifir_satirlari_at(kalemler: list[dict]) -> list[dict]:
    """Tum donemlerde 0 ya da bos olan satirlari atar."""
    return [k for k in kalemler if any(d not in (0, None) for d in k["degerler"])]


# Is Yatirim bilanco, gelir ve nakit akisini TEK listede dondurur. Bolme
# noktalari olculdu (THYAO sanayi 104 kalem, GARAN banka 99 kalem):
#   bilanco sonu  -> "TOPLAM KAYNAKLAR" (sanayi) / "PASİF TOPLAMI" (banka)
#   nakit basi    -> "İşletme Faaliyetlerinden Kaynaklanan Net Nakit"
# Bankalarda nakit akisi bolumu YOKTUR; GARAN gelir tablosuyla bitiyor.
BILANCO_SONU_ADLARI = ("TOPLAM KAYNAKLAR", "PASİF TOPLAMI")
NAKIT_BASI_ADLARI = ("İşletme Faaliyetlerinden Kaynaklanan Net Nakit",)


def _ilk_indeks(kalemler: list[dict], adaylar: tuple[str, ...]) -> int | None:
    for i, kalem in enumerate(kalemler):
        if kalem["ad"].strip() in adaylar:
            return i
    return None


def tablo_bol(kalemler: list[dict]) -> dict[str, list[dict]]:
    """Duz kalem listesini bilanco / gelir / nakit bolumlerine ayirir.

    Isaret bulunamazsa o bolum bos doner — uydurma bolme yapilmaz.
    """
    bilanco_son = _ilk_indeks(kalemler, BILANCO_SONU_ADLARI)
    nakit_bas = _ilk_indeks(kalemler, NAKIT_BASI_ADLARI)

    if bilanco_son is None:
        return {"bilanco": [], "gelir": kalemler, "nakit": []}

    gelir_son = nakit_bas if nakit_bas is not None else len(kalemler)
    return {
        "bilanco": kalemler[: bilanco_son + 1],
        "gelir": kalemler[bilanco_son + 1 : gelir_son],
        "nakit": kalemler[nakit_bas:] if nakit_bas is not None else [],
    }


# Ayni kavramin sirket tipine gore farkli adlari. Uc ayri hesap plani var:
#   sanayi/ticaret -> "Özkaynaklar" / "DÖNEM KARI (ZARARI)"
#   banka (BDDK)   -> "XVI. ÖZKAYNAKLAR" / "XXIII. NET DÖNEM KARI/ZARARI"
#   sigorta        -> "Özsermaye Toplamı" / "F-Dönem Net Karı"
#   katilim bankasi-> "ÖZKAYNAK" (tekil) / "XVIII. NET DÖNEM KARI/ZARARI"
#
# Tum evren tarandi (630 islem goren hisse): bu adlarla 609'u cozuluyor.
# Kalan 21'inin Is Yatirim'da hic finansal tablosu yok (cogu faktoring ve
# finansal kiralama: GARFA, VAKFA, ISFIN, QNBFK...) - bu bizim eksigimiz
# degil, kaynakta veri yok.
OZKAYNAK_ADLARI = (
    "XVI. ÖZKAYNAKLAR",
    "Özkaynaklar",
    "Özsermaye Toplamı",
    "ÖZSERMAYE TOPLAMI",
    "ÖZKAYNAK",
    "Ana Ortaklığa Ait Özkaynaklar",
)
NET_KAR_ADLARI = (
    "XXIII. NET DÖNEM KARI/ZARARI (XVII+XXII)",
    "DÖNEM KARI (ZARARI)",
    "Dönem Karı (Zararı)",
    "XVIII. NET DÖNEM KARI/ZARARI (XVII+XXII)",
    "F-Dönem Net Karı",
    "N- Dönem Net Karı veya Zararı",
    "Dönem Net Karı",
)


# ANA ORTAKLIK PAYI — piyasa degeri YALNIZCA ana ortakligin hissedarlarini
# temsil eder. Konsolide toplam ozkaynak/kar icinde bagli ortakliklarin
# baskalarina ait paylari da vardir; onlari cikarmadan bolmek orani
# oldugundan DUSUK gosterir.
#
# Olculdu (AHGAZ, 06.09.2026) - gercek: PD/DD 1,72 / F/K 18,22
#   toplam ozkaynak 93,24 mlr - azinlik 33,30 mlr = ana ortaklik 59,94 mlr
#   toplam kar 5,82 mlr, ana ortaklik payi 4,32 mlr
#   toplamla PD/DD 1,08 (yanlis), ana ortaklikla 1,72 (dogru)
ANA_OZKAYNAK_ADLARI = ("Ana Ortaklığa Ait Özkaynaklar", "Ana Ortaklık Özkaynakları")
AZINLIK_OZKAYNAK_ADLARI = (
    "Azınlık Payları",
    "16.5 Azınlık Payları",
    "Kontrol Gücü Olmayan Paylar",
)
ANA_KAR_ADLARI = (
    "Ana Ortaklık Payları",
    "23.1 Grubun Karı/Zararı",
    "18.1 Grubun Karı/Zararı",
    "Grubun Karı/Zararı",
)
AZINLIK_KAR_ADLARI = (
    "Azınlık Payları",
    "23.2 Azınlık Hakları Karı/Zararı (-)",
    "18.2 Azınlık Hakları Karı/Zararı (-)",
    "Kontrol Gücü Olmayan Paylar",
)


# BIST'te nominal deger neredeyse her zaman 1 TL, yani odenmis sermaye =
# hisse adedi. Turk kaynaklari orani bundan hesapliyor. yfinance'in
# sharesOutstanding'i geri alinmis paylari dusuyor ve dusuk kaliyor:
#   AHGAZ  yfinance 2.528.516.915 / odenmis 2.600.000.000 = 0,973
#   THYAO  yfinance 1.372.283.353 / odenmis 1.380.000.000 = 0,994
# AHGAZ'daki %2,7 fark, olculen oran sapmasiyla birebir ortusuyordu.
ODENMIS_SERMAYE_ADLARI = (
    "Ödenmiş Sermaye",
    "A- Ödenmiş Sermaye",
    "I. ÖDENMİŞ SERMAYE",
    "Ödenmiş sermaye",
)
def hisse_adedi_sec(odenmis_sermaye: float | None, yfinance_adet: int | None) -> int | None:
    """Hisse adedini secer: odenmis sermaye BIRINCIL, yfinance yalnizca yedek.

    Ilk surumde "cok saparsa yfinance'e don" diye bir makullük kontrolu
    vardi; TERS calisiyordu. Tum evren tarandi, 28 hissede iki kaynak
    %10'dan fazla ayrisiyor. KAP'in kendi odenmis sermayesi ucuncu kaynak
    olarak sorulunca kontrol edilebilen 6 vakanin 6'sinda da Is Yatirim'i
    destekledi:

      kod    Is Yatirim   yfinance      KAP          dogru olan
      FLAP   93.750.000   150.000       93.750.000   Is Yatirim
      PKENT  24.883.200   829.440.000   24.883.200   Is Yatirim
      ORGE   80.000.000   400.000.000   80.000.000   Is Yatirim
      KRTEK  35.100.498   137.984.613   35.100.498   Is Yatirim
      GOODY  270.000.000  1.520.000.000 270.000.000  Is Yatirim
      MPARK  191.012.000  102.122.233   208.037.202  Is Yatirim

    yfinance bu hisselerde 625 kata varan hata yapiyor; eski kontrol tam
    da bu vakalarda dogru degeri reddedip yanlisi seciyordu.
    """
    if odenmis_sermaye:
        return int(odenmis_sermaye)
    return int(yfinance_adet) if yfinance_adet else None


def _bolumde_bul(kalemler: list[dict], adaylar: tuple[str, ...]) -> float | None:
    """Yalnizca verilen bolum icinde arar.

    Bolum ayrimi sart: "Azınlık Payları" hem bilancoda hem gelir tablosunda
    geciyor (AHGAZ'da biri 33,3 mlr ozkaynak, digeri 1,5 mlr kar). Duz ad
    aramasi ilk buldugunu doner ve iki kavrami karistirir.
    """
    for aday in adaylar:
        for kalem in kalemler:
            if kalem["ad"].strip() == aday:
                degerler = [d for d in kalem["degerler"] if d is not None]
                if degerler:
                    return degerler[0]
    return None


def ana_ortaklik_payi(
    bolum: list[dict], toplam_adlari: tuple[str, ...],
    ana_adlari: tuple[str, ...], azinlik_adlari: tuple[str, ...],
) -> float | None:
    """Ana ortakliga dusen tutari doner.

    Sirasiyla: dogrudan ana ortaklik satiri -> toplam eksi azinlik -> toplam.
    """
    dogrudan = _bolumde_bul(bolum, ana_adlari)
    if dogrudan is not None:
        return dogrudan

    toplam = _bolumde_bul(bolum, toplam_adlari)
    if toplam is None:
        return None

    azinlik = _bolumde_bul(bolum, azinlik_adlari)
    return toplam - azinlik if azinlik is not None else toplam


def guncel_donem_sec(dolu_donemler: dict[tuple[int, int], float]) -> tuple[int, int] | None:
    """Verisi olan donemlerden en yenisini secer."""
    return max(dolu_donemler) if dolu_donemler else None


def net_kar_ttm(
    bu_yil_kumulatif: float | None,
    gecen_yil_ayni_kumulatif: float | None,
    gecen_yil_yillik: float | None,
    ay: int,
) -> float | None:
    """Son 12 ayin net kari.

    NEDEN GEREKLI — net kar bir AKIS kalemidir, ozkaynak gibi bir bakiye
    degildir. Gecen yilin tam yil karini bugunun fiyatina bolmek de, bu
    yilin 6 aylik karini bolmek de yanlistir.

    Is Yatirim donemleri KUMULATIF verir (period=6 -> yilin ilk 6 ayi), bu
    yuzden formul:
        TTM = gecen yil yillik - gecen yil ayni kumulatif + bu yil kumulatif

    Olculdu (BETAE, 06.09.2026):
        2025 yillik 1.079.327.517 - 2025 ilk 6 ay 392.246.453
        + 2026 ilk 6 ay 52.057.130 = 739.138.194  -> F/K 44,27 (dogru)
        Yillik kari kullanmak F/K'yi 30,32 gosteriyordu (yanlis).
    """
    if bu_yil_kumulatif is None:
        return None
    if ay == 12:
        return bu_yil_kumulatif  # Aralik kumulatifi zaten 12 aylik
    if gecen_yil_ayni_kumulatif is None or gecen_yil_yillik is None:
        return None  # eksik gecmis: uydurma yapma
    return gecen_yil_yillik - gecen_yil_ayni_kumulatif + bu_yil_kumulatif


def kalem_bul(kalemler: list[dict], *adaylar: str) -> float | None:
    """Verilen adaylardan ilk eslesenin ilk donem degerini doner."""
    for aday in adaylar:
        for kalem in kalemler:
            if kalem["ad"].strip().upper() == aday.strip().upper():
                degerler = [d for d in kalem["degerler"] if d is not None]
                return degerler[0] if degerler else None
    return None


class IsYatirimIstemci:
    def __init__(self, onbellek: Onbellek) -> None:
        self._onbellek = onbellek
        self._sinirlayici = HizSinirlayici(ISTEK_ARALIGI_SN)

    async def _bekle(self) -> None:
        await self._sinirlayici.bekle()

    async def _getir(self, kod: str, grup: str, donemler: list[tuple[int, int]]) -> dict:
        """Is Yatirim MaliTablo cagrisi.

        DIKKAT — endpoint TAM 4 DONEM istiyor. Olculdu: 2 ya da 3 donemle
        istek atilinca hata vermiyor, sessizce BOS liste donuyor. Eksik
        gelen pencere burada doldurulur ki hicbir cagiran bu tuzaga
        dusmesin.

        DIKKAT — yanit HTTP 200 olup JSON OLMAYABILIR. Olculdu (09.09.2026,
        canli tarama): govde JSON degildi, `yanit.json()` JSONDecodeError
        firlatti ve cagri zinciri tepeye kadar coktu; `raise_for_status()`
        bunu gormuyor cunku durum kodu 200. Ayni tarama 120 ticker'da
        tekrarlanmadi, yani gecici. Bos yanit = veri yok sayilir: cagiran
        zaten yedek gruba ve gecen yil penceresine dusuyor.
        """
        donemler = list(donemler[:SLOT_SAYISI])
        while len(donemler) < SLOT_SAYISI and donemler:
            son_yil, son_ay = donemler[-1]
            donemler.append((son_yil - 1, son_ay))

        parametreler = {
            "companyCode": kod.upper(),
            "exchange": "TRY",
            "financialGroup": grup,
        }
        for sira, (yil, ay) in enumerate(donemler, start=1):
            parametreler[f"year{sira}"] = yil
            parametreler[f"period{sira}"] = ay

        async with httpx.AsyncClient(follow_redirects=True) as istemci:
            await self._bekle()
            yanit = await istemci.get(
                f"{KOK}/MaliTablo",
                params=parametreler,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"},
                timeout=30.0,
            )
            yanit.raise_for_status()
            try:
                sonuc = yanit.json()
            except ValueError as hata:  # JSONDecodeError da bunun altinda
                kayit.warning(
                    "%s/%s icin Is Yatirim JSON disi yanit dondu (HTTP %s, %s): %s",
                    kod.upper(),
                    grup,
                    yanit.status_code,
                    yanit.headers.get("content-type"),
                    hata,
                )
                return {}

            # Sozluk degilse de bos say. Bu sekil OLCULMEDI; ustteki olculmus
            # vakanin bitisik durumu. Cagiranlar `ham.get("value")` yaptigi
            # icin liste/metin gelirse ayni cokme bir adim ileride olurdu
            # (dolu_slotlar, kalem_ayikla).
            if not isinstance(sonuc, dict):
                kayit.warning(
                    "%s/%s icin Is Yatirim sozluk yerine %s dondu",
                    kod.upper(),
                    grup,
                    type(sonuc).__name__,
                )
                return {}
            return sonuc

    async def _pencere_dene(
        self, kod: str, grup: str, pencere: list[tuple[int, int]]
    ) -> tuple[list[dict], list[str], str]:
        ham = await self._getir(kod, grup, pencere)
        slotlar = dolu_slotlar(ham)
        if not slotlar:
            return [], [], ""
        kalemler = sifir_satirlari_at(kalem_ayikla(ham, slotlar))
        etiketler = [pencere[i - 1] for i in slotlar]
        return kalemler, etiketler, grup

    @staticmethod
    def _slot_degeri(ham: dict, slot: int, adaylar: tuple[str, ...]) -> float | None:
        """Belirli bir slottaki (donemdeki) kalem degeri."""
        for aday in adaylar:
            for satir in ham.get("value") or []:
                if (satir.get("itemDescTr") or "").strip().upper() == aday.strip().upper():
                    deger = sayiya_cevir(satir.get(f"value{slot}"))
                    if deger is not None:
                        return deger
        return None

    async def oran_girdileri(self, kod: str, tip: str | None) -> dict:
        """PD/DD ve F/K icin DOGRU DONEMDEKI girdileri doner.

        Iki kalem turu farkli donem mantigi ister:
          * ozkaynak bir STOK (bakiye) -> en guncel bilanco kullanilir
          * net kar bir AKIS -> son 12 ay (TTM) hesaplanir

        Olculdu (BETAE): yillik ozkaynak PD/DD'yi 9,08 gosteriyordu, guncel
        bilancoyla 5,59 (dogru). Yillik kar F/K'yi 30,32 gosteriyordu, TTM
        ile 44,27 (dogru).
        """
        bugun = dt.date.today()
        bu_yil_pencere = [(bugun.year, ay) for ay in (12, 9, 6, 3)]
        gecen_yil_pencere = [(bugun.year - 1, ay) for ay in (12, 9, 6, 3)]

        for grup in (tablo_grubu_sec(tip), yedek_grup(tablo_grubu_sec(tip))):
            # Pencere YEREL: onceki surumde gecen yila dusus `bu_yil_pencere`
            # degiskenini eziyordu ve yedek grup BU YIL hic sorulmuyordu.
            # Olculdu: XI_29 bos -> XI_29 gecen yil bos -> UFRS_K gecen yil
            # (iki kez, ayni istek). KAP'ta financialType'i bos olan 315
            # ticker'in bankalari tam da bu yoldan geciyor; ya hic veri
            # bulunamiyor ya da GECEN YILIN rakami "guncel donem" etiketiyle
            # donuyordu.
            pencere = bu_yil_pencere
            ham = await self._getir(kod, grup, pencere)
            slotlar = dolu_slotlar(ham)
            if not slotlar:
                # Bu yil hic yayin yok: gecen yila dus
                pencere = gecen_yil_pencere
                ham = await self._getir(kod, grup, pencere)
                slotlar = dolu_slotlar(ham)
                if not slotlar:
                    continue

            slot = min(slotlar)  # en yeni donem ilk slotta
            yil, ay = pencere[slot - 1]
            bolumler = tablo_bol(kalem_ayikla(ham, [slot]))
            ozkaynak = ana_ortaklik_payi(
                bolumler["bilanco"], OZKAYNAK_ADLARI,
                ANA_OZKAYNAK_ADLARI, AZINLIK_OZKAYNAK_ADLARI,
            )
            kar_kumulatif = ana_ortaklik_payi(
                bolumler["gelir"], NET_KAR_ADLARI,
                ANA_KAR_ADLARI, AZINLIK_KAR_ADLARI,
            )

            net_kar = net_kar_ttm(kar_kumulatif, None, None, ay)
            if net_kar is None and kar_kumulatif is not None:
                # Kumulatif donem yil sonu degil: gecen yilin ayni donemi ve
                # yilligi gerekiyor. Ikisi tek istekte alinir.
                gecmis_pencere = [(yil - 1, ay), (yil - 1, 12)]
                gecmis = await self._getir(kod, grup, gecmis_pencere)

                def _ana_kar(slot: int) -> float | None:
                    bol = tablo_bol(kalem_ayikla(gecmis, [slot]))
                    return ana_ortaklik_payi(
                        bol["gelir"], NET_KAR_ADLARI, ANA_KAR_ADLARI, AZINLIK_KAR_ADLARI
                    )

                net_kar = net_kar_ttm(kar_kumulatif, _ana_kar(1), _ana_kar(2), ay)

            if ozkaynak is not None or net_kar is not None:
                return {
                    "odenmis_sermaye": _bolumde_bul(
                        bolumler["bilanco"], ODENMIS_SERMAYE_ADLARI
                    ),
                    "ozkaynak_tl": ozkaynak,
                    "ozkaynak_donem": donem_etiketi(yil, ay, "ceyreklik" if ay != 12 else "yillik"),
                    "net_kar_ttm": net_kar,
                    "net_kar_aciklama": (
                        f"{yil} yıllık" if ay == 12 else f"son 12 ay ({yil}/{ay:02d} itibarıyla)"
                    ),
                }

        return {
            "odenmis_sermaye": None,
            "ozkaynak_tl": None,
            "ozkaynak_donem": None,
            "net_kar_ttm": None,
            "net_kar_aciklama": None,
        }

    async def mali_tablo(
        self, kod: str, tip: str | None, donem: str = "yillik", adet: int = 2
    ) -> dict:
        """Finansal tabloyu doner: {'donemler': [...], 'kalemler': [...]}.

        Yanlis grup bos tablo dondurdugu icin birincil grup bos gelirse yedek
        grup denenir — bu deneme kaldirilamaz (807 ticker'in 315'inde tip bos).
        En yeni pencere tamamen bossa bir sonraki pencere denenir (en fazla 2).
        """
        anahtar = f"isy:{kod.upper()}:{donem}:{adet}"
        onbellekli = self._onbellek.al(anahtar)
        if onbellekli is not None:
            return onbellekli

        adaylar = donem_adaylari(donem)
        birincil = tablo_grubu_sec(tip)

        sonuc: dict = {"donemler": [], "kalemler": []}
        for grup in (birincil, yedek_grup(birincil)):
            for pencere_no in (0, 1):
                pencere = adaylar[pencere_no * SLOT_SAYISI : (pencere_no + 1) * SLOT_SAYISI]
                if not pencere:
                    break
                kalemler, donemler, _ = await self._pencere_dene(kod, grup, pencere)
                if kalemler:
                    sonuc = {
                        "donemler": [donem_etiketi(y, a, donem) for y, a in donemler][:adet],
                        "kalemler": [
                            {"ad": k["ad"], "degerler": k["degerler"][:adet]} for k in kalemler
                        ],
                    }
                    break
            if sonuc["kalemler"]:
                break

        self._onbellek.yaz(anahtar, sonuc, TABLO_TTL)
        return sonuc
