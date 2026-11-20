"""Kaynak siteler icin es zamanlilik-guvenli hiz sinirlayici.

Kilitsiz surum ise yaramiyordu: N es zamanli gorev ayni anda "son istekten
beri gecen sure"yi okuyor, ayni sureyi uyuyor ve hep birlikte ates ediyordu.
Olculdu — 20 es zamanli istek 0,50 sn'de tamamlaniyordu, 2 istek/sn ile
olmasi gereken 10 sn yerine.

Kilit, bekleme ve damga guncellemesini atomik yapar: her gorev sirasini
bekler, kendi damgasini basar, kilidi birakir.
"""

import asyncio


class HizSinirlayici:
    def __init__(self, aralik_sn: float) -> None:
        self._aralik = aralik_sn
        self._kilit = asyncio.Lock()
        self._son_istek = 0.0

    async def bekle(self) -> None:
        async with self._kilit:
            simdi = asyncio.get_event_loop().time()
            gecen = simdi - self._son_istek
            if gecen < self._aralik:
                await asyncio.sleep(self._aralik - gecen)
            self._son_istek = asyncio.get_event_loop().time()
