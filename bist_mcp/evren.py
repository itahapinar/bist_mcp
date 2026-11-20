"""Tarama evreni — KAP sirket dizininden turetilir.

Onceki surumde elle yazilmis 100 kodluk bir liste vardi (bist100.py). Iki
sorunu vardi: endeks revizyonlarinda bayatliyordu ve BIST-100 disindaki
hisseler taramada hic gorunmuyordu — deger taramasinin en cok ise yaradigi
yer tam da orasi.

Olculen sayilar: KAP dizini 807 ticker veriyor, bunlarin 630'unda fiyat
verisi var. Kalan 177'si islem gormeyen, kapanmis ya da GARAN'in "TGB"si
gibi ikincil kodlar; toplu indirme onlari zaten dusuruyor, ayrica elemeye
gerek yok.

Maliyet (olculdu): gunluk hafif tazeleme 40 sn, haftalik tam kurulum ~15 dk
(09.09.2026 iki kosu: 15,4 ve 14,6 dakika).
Ikisi de arka planda, kullaniciyi bekletmeden.
"""

# Ikincil/turev kodlar: ayni sirketin ikinci kodu ya da islem gormeyen
# kayitlar. Toplu indirme bunlari zaten dusuruyor; burada listelenmeleri
# yalnizca gereksiz istek atilmasini onlemek icin.
HARIC_KODLAR: frozenset[str] = frozenset()


async def tarama_evreni(kap) -> list[str]:
    """KAP dizinindeki tum ticker'lari doner (fiyat suzmesi toplu indirmede).

    Ayni sirketin birden fazla kodu varsa hepsi listeye girer; fiyat verisi
    olmayanlar toplu indirme asamasinda kendiliginden duser.
    """
    dizin = await kap.sirket_dizini()
    return sorted(kod for kod in dizin if kod not in HARIC_KODLAR)
