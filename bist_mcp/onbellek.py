"""SQLite tabanli TTL onbellegi.

Kaynak siteleri korumak icin var: gelistirme sirasinda sunucu onlarca kez
yeniden baslatilir; bellekteki onbellek her restart'ta sifirlanip ayni veriyi
tekrar tekrar cekerdi.
"""

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class Onbellek:
    def __init__(self, yol: Path, zaman: Callable[[], float] = time.time) -> None:
        self._zaman = zaman
        self._baglanti = sqlite3.connect(yol, check_same_thread=False)
        self._baglanti.execute(
            "CREATE TABLE IF NOT EXISTS onbellek ("
            "  anahtar TEXT PRIMARY KEY,"
            "  deger   TEXT NOT NULL,"
            "  biten   REAL NOT NULL"
            ")"
        )
        self._baglanti.commit()

    def al(self, anahtar: str) -> Any | None:
        satir = self._baglanti.execute(
            "SELECT deger, biten FROM onbellek WHERE anahtar = ?", (anahtar,)
        ).fetchone()
        if satir is None:
            return None

        deger, biten = satir
        if biten <= self._zaman():
            self._baglanti.execute("DELETE FROM onbellek WHERE anahtar = ?", (anahtar,))
            self._baglanti.commit()
            return None

        return json.loads(deger)

    def yaz(self, anahtar: str, deger: Any, ttl_saniye: int) -> None:
        self._baglanti.execute(
            "INSERT OR REPLACE INTO onbellek (anahtar, deger, biten) VALUES (?, ?, ?)",
            (
                anahtar,
                json.dumps(deger, ensure_ascii=False),
                self._zaman() + ttl_saniye,
            ),
        )
        self._baglanti.commit()

    def kapat(self) -> None:
        self._baglanti.close()
