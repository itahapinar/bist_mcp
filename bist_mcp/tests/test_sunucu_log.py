"""Sunucunun kendi loglari hicbir yere ulasmiyordu.

Kullanicinin gordugu hata (09.09.2026 03:49): tam tarama baslatildi, botun
terminalinde "Anlik gorunum tam kuruluyor" satiri gorunmedi ve
`borsa-ajan.log`'da `bist_mcp` gecen TEK SATIR yok (olculdu: grep -c -> 0).

Iki ayri sebep:

1. `logging.basicConfig` root logger'da ZATEN handler varsa HICBIR SEY
   YAPMAZ. Olculdu:
       import ONCESI root handler: []
       import SONRASI root handler: [<RichHandler>]   <- yfinance kuruyor
       basicConfig SONRASI       : [<RichHandler>]    <- no-op
   Yani sunucunun kendi bicimi hic uygulanmiyordu. `force=True` sart.

2. Sunucu bir ALT SUREC; stderr'i botun terminaline karisiyor ve kalici
   kayit birakmiyor. Tam tarama ~15 dakika suruyor, kullanicinin durumu
   sonradan gorebilmesi gerekiyor -> kendi dosyasina da yazar.
"""

import logging

import pytest

from bist_mcp.sunucu import LOG_DOSYASI, log_kur


@pytest.fixture(autouse=True)
def _log_durumunu_koru():
    kok = logging.getLogger()
    eski_handlerlar, eski_seviye = list(kok.handlers), kok.level
    yield
    for h in list(kok.handlers):
        kok.removeHandler(h)
        if h not in eski_handlerlar:
            h.close()
    for h in eski_handlerlar:
        kok.addHandler(h)
    kok.setLevel(eski_seviye)


def test_var_olan_handler_degistirilir(tmp_path):
    """REGRESYON: basicConfig sessizce no-op oluyordu."""
    kok = logging.getLogger()
    engel = logging.NullHandler()
    kok.addHandler(engel)
    log_kur(tmp_path / "s.log")
    assert engel not in kok.handlers, "eski handler kaldi, basicConfig yine no-op"


def test_dosyaya_yazar(tmp_path):
    yol = tmp_path / "s.log"
    log_kur(yol)
    logging.getLogger("bist_mcp").info("Anlik gorunum tam kuruluyor")
    for h in logging.getLogger().handlers:
        h.flush()
    assert yol.exists(), "log dosyasi olusmadi"
    assert "Anlik gorunum tam kuruluyor" in yol.read_text(encoding="utf-8")


def test_kendi_bicimi_uygulanir(tmp_path):
    """Rich bicimi degil, sunucunun kendi bicimi: zaman + seviye + ad."""
    yol = tmp_path / "s.log"
    log_kur(yol)
    logging.getLogger("bist_mcp").info("deneme")
    for h in logging.getLogger().handlers:
        h.flush()
    satir = yol.read_text(encoding="utf-8").strip()
    assert "INFO" in satir and "bist_mcp" in satir


def test_stderr_de_korunur(tmp_path):
    """Dosya eklendi diye terminal ciktisi kaybolmamali."""
    log_kur(tmp_path / "s.log")
    akislar = [
        getattr(h, "stream", None)
        for h in logging.getLogger().handlers
        if isinstance(h, logging.StreamHandler)
    ]
    assert any(a is not None for a in akislar), "konsol handler yok"


def test_INFO_seviyesi(tmp_path):
    log_kur(tmp_path / "s.log")
    assert logging.getLogger().level <= logging.INFO


def test_varsayilan_dosya_proje_kokunde():
    assert LOG_DOSYASI.name == "bist-mcp.log"
