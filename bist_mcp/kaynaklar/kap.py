"""KAP (Kamuyu Aydinlatma Platformu) kaynagi.

Sirket dizini, bildirim sorgusu ve bildirim detayi.
"""

import asyncio
import datetime as dt
import http.cookiejar
from dataclasses import dataclass

import httpx

from bist_mcp.hiz_sinir import HizSinirlayici
from bist_mcp.onbellek import Onbellek

# KAP financialType kodlari: banka, sigorta, finansal kiralama/faktoring,
# katilim bankasi. Bunlar BDDK formatinda raporlar -> UFRS_K.
BANKA_TIPLERI = frozenset({"BNK", "SIG", "FFF", "KTL"})

KAP_KOK = "https://www.kap.org.tr"
BILDIRIM_SORGU_SAYFASI = f"{KAP_KOK}/tr/bildirim-sorgu"

# Olculen WAF davranisi: 2 istek/sn ustunde TCP baglantisi ~6 sn'de dusuyor.
ISTEK_ARALIGI_SN = 0.5

# Olculen (2026-09-06): byCriteria 365 gunluk araligi kabul ediyor (THYAO 88,
# MEKAG 98 kayit); 366 gun HTTP 500 donuyor. Daha uzun gecmis istendiginde
# aralik parcalara bolunup birlestirilir.
AZAMI_ARALIK_GUN = 365

DIZIN_TTL = 7 * 24 * 3600  # sirket listesi haftada bir yeter
BILDIRIM_TTL = 300  # 5 dk
DETAY_TTL = 24 * 3600


@dataclass(frozen=True)
class Sirket:
    kod: str
    unvan: str
    mkk_oid: str
    tip: str | None
    # Ayni sirketin borsada islem goren tum kodlari. Birden fazlaysa her
    # kod ayri bir hisse SINIFI demektir (ISATR/ISBTR/ISCTR gibi) ve
    # odenmis sermaye TUM siniflarin toplamidir - tek sinifa atanamaz.
    tum_kodlar: tuple[str, ...] = ()

    @property
    def coklu_sinif(self) -> bool:
        return len(self.tum_kodlar) > 1


def dizin_kur(ham: list[dict]) -> dict[str, Sirket]:
    """KAP sirket listesini ticker -> Sirket sozlugune cevirir.

    `stockCode` alani virgulle ayrilmis birden fazla kod tutabilir; GARAN'in
    degeri "GARAN, TGB". Tam eslesme aramak bankalarin cogunu kaybettirir,
    bu yuzden alan virgulle bolunup her kod ayri anahtar yapilir.
    Olculen sonuc: 757 sirket -> 807 ticker.
    """
    dizin: dict[str, Sirket] = {}

    for kayit in ham:
        ham_kod = (kayit.get("stockCode") or "").strip()
        if not ham_kod or ham_kod == "-":
            continue

        unvan = (kayit.get("kapMemberTitle") or "").strip()
        oid = kayit.get("mkkMemberOid") or ""
        tip = kayit.get("financialType") or None

        kodlar = tuple(k.strip() for k in ham_kod.split(",") if k.strip() and k.strip() != "-")
        for kod in kodlar:
            dizin[kod] = Sirket(
                kod=kod, unvan=unvan, mkk_oid=oid, tip=tip, tum_kodlar=kodlar
            )

    return dizin


def tablo_grubu_sec(tip: str | None) -> str:
    """Sirket tipinden Is Yatirim financialGroup parametresini secer.

    Tip bos olabilir (807 ticker'in 315'i); o durumda XI_29 denenir ve
    bos donerse cagiran taraf yedek_grup() ile digerini dener.
    """
    return "UFRS_K" if tip in BANKA_TIPLERI else "XI_29"


def yedek_grup(grup: str) -> str:
    return "XI_29" if grup == "UFRS_K" else "UFRS_K"


def bildirim_sadelestir(ham: dict) -> dict:
    """Modele gidecek alanlari secer; gerisi baglami sisiriyor."""
    return {
        "tarih": ham.get("publishDate"),
        "konu": ham.get("subject"),
        "ozet": ham.get("summary") or None,
        "sinif": ham.get("disclosureClass"),
        "bildirim_no": ham.get("disclosureIndex"),
        "ek_sayisi": ham.get("attachmentCount", 0),
    }


def tarih_pencereleri(
    baslangic: dt.date, bitis: dt.date, azami_gun: int = AZAMI_ARALIK_GUN
) -> list[tuple[dt.date, dt.date]]:
    """Araligi KAP'in kabul ettigi uzunlukta, ustuste binmeyen parcalara boler."""
    pencereler: list[tuple[dt.date, dt.date]] = []
    parca_bas = baslangic
    while parca_bas <= bitis:
        parca_bitis = min(parca_bas + dt.timedelta(days=azami_gun), bitis)
        pencereler.append((parca_bas, parca_bitis))
        parca_bas = parca_bitis + dt.timedelta(days=1)
    return pencereler


def _yayin_zamani(kayit: dict) -> dt.datetime:
    ham = (kayit.get("publishDate") or "").strip()
    for bicim in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(ham, bicim)
        except ValueError:
            continue
    return dt.datetime.min


def tekillestir(ham: list[dict]) -> list[dict]:
    """Parcali sorgulardan gelen kayitlari birlestirir: tekil, yeniden eskiye."""
    gorulen: dict[str, dict] = {}
    for kayit in ham:
        gorulen.setdefault(str(kayit.get("disclosureIndex")), kayit)
    return sorted(gorulen.values(), key=_yayin_zamani, reverse=True)


class KapIstemci:
    def __init__(self, onbellek: Onbellek) -> None:
        self._onbellek = onbellek
        self._kilit = asyncio.Lock()
        self._sinirlayici = HizSinirlayici(ISTEK_ARALIGI_SN)
        # Cerez kavanozu ISTEMCILER ARASI paylasilir. Her cagri kendi
        # AsyncClient'ini acip kapatiyor; cerez istemcide kalsaydi ilk
        # cagriyla birlikte cope giderdi. Ham CookieJar sart: httpx
        # `Cookies` nesnesini KOPYALIYOR (0.28.1), ham kavanozu SARIYOR.
        self._cerezler = http.cookiejar.CookieJar()
        # Isinma icin AYRI kilit: `_kilit` sirket dizini cekimini tutuyor,
        # onu paylasmak alakasiz iki isi birbirine baglardi.
        self._oturum_kilidi = asyncio.Lock()

    def _istemci(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(follow_redirects=True, cookies=self._cerezler)

    async def _bekle(self) -> None:
        """2 istek/sn tavanini uygular (es zamanlilik-guvenli)."""
        await self._sinirlayici.bekle()

    async def _oturum(self, istemci: httpx.AsyncClient) -> None:
        """API cagrisindan once cerez alir; yoksa WAF baglantiyi dusuruyor.

        Isinma bir kez yeter ama kararin dayanagi BAYRAK DEGIL CEREZIN
        KENDISI: bayrak ilk cagridan sonra True kaliyor, cerez ise o
        cagrinin istemcisiyle birlikte oluyordu. Sonraki her istek KAP'a
        cerezsiz gidiyordu (canli logda goruldu, 09.09.2026 17:31).

        KONTROL KILIT ICINDE: kilitsiz "bak sonra yap" es zamanli cagrilarda
        iki isinma uretiyordu -- olculdu (canli log 09.09.2026 17:29:03,139
        ve 17:29:04,212; aradaki 1,07 sn hiz sinirlayicinin araligi). Ajan
        ayni turdaki arac cagrilarini asyncio.gather ile calistirdigi icin
        her soguk baslangicta tekrarlanabilir. Kilit HizSinirlayici'nin
        desenini izler: kilitle, isi yap, birak.
        """
        async with self._oturum_kilidi:
            if len(self._cerezler):
                return
            await self._bekle()
            await istemci.get(BILDIRIM_SORGU_SAYFASI, timeout=30.0)

    async def _ham_sirket_listesi_getir(self) -> list[dict]:
        async with self._istemci() as istemci:
            await self._bekle()
            yanit = await istemci.get(
                f"{KAP_KOK}/tr/api/company/items/IGS/A",
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                timeout=40.0,
            )
            yanit.raise_for_status()
            return yanit.json()

    async def sirket_dizini(self) -> dict[str, Sirket]:
        async with self._kilit:
            ham = self._onbellek.al("kap:sirket_listesi")
            if ham is None:
                ham = await self._ham_sirket_listesi_getir()
                self._onbellek.yaz("kap:sirket_listesi", ham, DIZIN_TTL)
            return dizin_kur(ham)

    async def bildirimler(self, kod: str, gun: int = 90) -> list[dict]:
        anahtar = f"kap:bildirim:{kod.upper()}:{gun}"
        onbellekli = self._onbellek.al(anahtar)
        if onbellekli is not None:
            return onbellekli

        dizin = await self.sirket_dizini()
        sirket = dizin.get(kod.strip().upper())
        if sirket is None:
            return []

        bitis = dt.date.today()
        baslangic = bitis - dt.timedelta(days=gun)

        ham: list[dict] = []
        async with self._istemci() as istemci:
            await self._oturum(istemci)
            for parca_bas, parca_bitis in tarih_pencereleri(baslangic, bitis):
                ham.extend(
                    await self._ham_bildirimler(
                        istemci, sirket.mkk_oid, parca_bas, parca_bitis
                    )
                )

        sonuc = [bildirim_sadelestir(x) for x in tekillestir(ham)]
        self._onbellek.yaz(anahtar, sonuc, BILDIRIM_TTL)
        return sonuc

    async def _ham_bildirimler(
        self,
        istemci: httpx.AsyncClient,
        mkk_oid: str,
        baslangic: dt.date,
        bitis: dt.date,
    ) -> list[dict]:
        await self._bekle()
        yanit = await istemci.post(
            f"{KAP_KOK}/tr/api/disclosure/members/byCriteria",
            json={
                "fromDate": str(baslangic),
                "toDate": str(bitis),
                "mkkMemberOidList": [mkk_oid],
                "subjectList": [],
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": BILDIRIM_SORGU_SAYFASI,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=45.0,
        )
        yanit.raise_for_status()
        return yanit.json()

    async def bildirim_detay(self, bildirim_no: str) -> dict:
        anahtar = f"kap:detay:{bildirim_no}"
        onbellekli = self._onbellek.al(anahtar)
        if onbellekli is not None:
            return onbellekli

        async with self._istemci() as istemci:
            await self._oturum(istemci)
            await self._bekle()
            yanit = await istemci.get(
                f"{KAP_KOK}/tr/api/notification/attachment-detail/{bildirim_no}",
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": f"{KAP_KOK}/tr/Bildirim/{bildirim_no}",
                    "Accept": "application/json",
                },
                timeout=40.0,
            )
            yanit.raise_for_status()
            sonuc = yanit.json()

        self._onbellek.yaz(anahtar, sonuc, DETAY_TTL)
        return sonuc
