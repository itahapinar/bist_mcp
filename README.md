# BIST MCP Sunucusu

Borsa İstanbul verisini LLM'lere açan, **18 araçlı** bir
[Model Context Protocol](https://modelcontextprotocol.io) sunucusu.
Claude Desktop gibi herhangi bir MCP istemcisine bağlanır; model hisse fiyatı,
finansal tablo, oran, temettü, KAP bildirimi, teknik analiz ve tarama
sorularını bu araçları çağırarak cevaplar.

Veri kaynakları: **İş Yatırım** (finansal tablolar), **KAP** (bildirimler),
**yfinance** (fiyat, OHLCV, döviz/altın) ve **TCMB EVDS** (makro göstergeler).

## Araçlar

**Hisse (10):** `detayli_analiz` · `hisse_ara` · `anlik_fiyat` · `gecmis_fiyat` · `sirket_profili` ·
`finansal_tablo` · `finansal_oranlar` · `temettu_gecmisi` · `kap_bildirimleri` ·
`kap_bildirim_detay`

**Analiz (6):** `yonlu_hacim` · `teknik_analiz` · `hisse_karsilastir` · `sektor_karsilastirma` ·
`hisse_tarama` · `endeks_verisi`

**Makro (2):** `doviz_altin` · `makro_gosterge`

## Kurulum

Python 3.10+ gerekir.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env    # sonra .env'i doldur
```

Linux / macOS:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

`.env` alanları:

| Alan | Zorunlu | Açıklama |
|---|---|---|
| `EVDS_API_KEY` | Hayır | TCMB EVDS anahtarı. Yalnızca `makro_gosterge` kullanır; boşsa araç bunu söyler, diğer 17 araç etkilenmez. |
| `LOG_LEVEL` | Hayır | Varsayılan `INFO`. |

> `.env`, `*.db` ve `*.log` dosyaları `.gitignore`'da. Gerçek anahtarı
> `.env.example`'a yazma.

## Çalıştırma

Sunucu stdio üzerinden konuşur; elle başlatmak yerine bir MCP istemcisine
bağlanır:

```bash
python -m bist_mcp.sunucu
```

İlk açılışta proje kökünde `onbellek.db`, `gorunum.db` ve `bist-mcp.log`
oluşur.

## Claude Desktop'a bağlama

`claude_desktop_config.json` dosyasına ekle. Yolları kendi klonladığın klasöre
göre değiştir:

```json
{
  "mcpServers": {
    "bist": {
      "command": "C:/yol/bistmcp/.venv/Scripts/python.exe",
      "args": ["-m", "bist_mcp.sunucu"],
      "cwd": "C:/yol/bistmcp",
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": "C:/yol/bistmcp"
      }
    }
  }
}
```

- **`python` yerine mutlak yol kullan.** Windows'ta PATH'teki `python`,
  Microsoft Store'un sahte `python.exe`'sine düşebiliyor ve sunucu
  "Server disconnected" ile anında kapanıyor.
- `cwd` önemli: `.env` ve veritabanları buradan okunur.
- Yapılandırma değişikliği Claude Desktop yeniden başlatılınca geçerli olur.

## Test

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m pytest              # hızlı testler: ağ yok
python -m pytest -m network   # canlı veri kaynağına çıkan testler
```

Windows konsolu cp1252 kullandığı için `PYTHONIOENCODING` gerekir; yoksa
Türkçe karakterler log'a yazılırken `UnicodeEncodeError` verir.

## Veri kuralları

Her kural canlı ölçülmüş bir hataya karşılık gelir ve regresyon testi vardır.
En önemli ikisi:

1. **Oranlar TL bazında hesaplanır, hazır alan okunmaz.** İş Yatırım yalnızca
   finansal tabloları verir; fiyat yfinance'ten gelir. PD/DD ve F/K bu iki
   kaynağın TL rakamlarıyla `hesap.py`'de hesaplanır. yfinance'in
   `priceToBook`, `trailingPE`, `dividendYield` alanları kullanılmaz.
   Gerekçe: THYAO finansallarını USD raporluyor, hissesi TRY işlem görüyor;
   yfinance TL fiyatı USD defter değerine bölüp PD/DD için **18,64** diyor,
   gerçek değer **0,38** (49 kat hata).

2. **Özkaynak stok, net kâr akıştır.** Özkaynak için en güncel bilanço,
   net kâr için son 12 ay (TTM) kullanılır:
   `TTM = geçen yıl yıllık − geçen yıl aynı kümülatif + bu yıl kümülatif`.
   Ölçüldü (BETAE): yıllık rakamlarla PD/DD 9,08 ve F/K 30,32 çıkıyordu;
   doğru değerler **5,59** ve **44,27**.

## Hız sınırları ve önbellek

KAP ve İş Yatırım için **2 istek/sn**. KAP'ta API çağrısından önce
`/tr/bildirim-sorgu`'ya GET ile oturum çerezi alınır; yoksa WAF bağlantıyı
~6 saniyede düşürür.

Önbellek tembeldir: hiçbir şeyi kendiliğinden çekmez, yalnızca sorulduğunda
çeker ve TTL boyunca saklar. Tek istisna tarama tablosudur.

## Tarama tablosu

`hisse_tarama` ve `sektor_karsilastirma` tüm evrenin verisine ihtiyaç duyar.
Her soruda 630 şirketi çekmek mümkün olmadığı için sunucu tabloyu arka planda
iki kademede taze tutar:

| Kademe | Süre | İstek | Ne çeker |
|---|---|---|---|
| Günlük | ~40 sn | 1 | Fiyat + temettü + hacim (tek toplu indirme) |
| Haftalık | ~15 dk | ~1.300 | Üstüne İş Yatırım finansalları + hisse adedi/sektör |

Soru geldiğinde tablo hazırdır ve `hisse_tarama` doğrudan SQLite'tan okur.

- **Likidite filtresi:** `hacim_min` parametresi, son 60 işlem gününün ortalama
  **TL** işlem hacmiyle süzer. Böylece günde birkaç lot işlem gören kabuk
  şirketler listenin başına çıkmaz.
- **Çok düşük F/K bir tuzaktır:** "F/K < 10" sorgusunun başını holdingler,
  GYO'lar ve yatırım ortaklıkları doldurur (ör. bir girişim sermayesi
  ortaklığında F/K 0,21; "kâr" portföy yeniden değerleme kazancı). Satırlar
  gizlenmez, ama araç açıklaması modeli uyarır. İşletme kârlılığı aranıyorsa
  `fk_min=3` gibi bir alt sınır daha anlamlı sonuç verir.

## Tam evren denetimi (630 işlem gören hisse)

| Durum | Sayı |
|---|---|
| Sağlıklı | **566** |
| Kaynakta finansal tablo yok | 21 |
| İki kaynak hisse adedinde ayrışıyor (İş Yatırım seçilir) | 28 |
| Oran olağandışı (uyarı notuyla döner) | 15 |

## Bilinen eksikler

- **`makro_gosterge` şu an çalışmıyor.** Sebep anahtar değil, TCMB'nin API
  değişikliği: `evds2.tcmb.gov.tr` artık `evds3`'e yönlendiriyor ve servis yolu
  JSON yerine HTML döndürüyor. Araç çökmez, durumu açıklayan bir mesaj döner.
  Doğru yol bulununca `bist_mcp/kaynaklar/tcmb.py` içindeki `EVDS_KOK`
  güncellenmeli. Döviz, altın ve emtia `doviz_altin` üzerinden (yfinance,
  anahtarsız) çalışır.
- **Aynı anda birden fazla sunucu süreci çalıştırma.** Her süreç açılışta
  630 hisselik tazeleme yapar; birkaç süreç çakışınca Yahoo
  "Too Many Requests" veriyor.
- **İlk açılışta tarama tablosu ~15 dakikada kurulur.** O bitene kadar
  `hisse_tarama` "Tarama tablosu henuz kurulmadi" hatası döner; diğer 17 araç hemen çalışır.
- **Çeyreklik verisi eksik ~%27 hissede net kâr kümülatif formülden gelir.**
  yfinance bazı şirketlerde Q3'ü hiç vermiyor (ör. ASELS, FROTO, EREGL).
- **Yabancı para raporlayan 4 şirkette (THYAO, TAVHL, ENKAI, DOCO)** net kâr
  kümülatif formülden gelir; ör. TAVHL'in F/K'sı ~%9,5 düşük çıkıyor.

## Uyarı

Bu sunucu yatırım tavsiyesi vermez. Veriler üçüncü taraf kaynaklardan gelir ve
gecikmeli ya da hatalı olabilir.

## Lisans

[MIT](LICENSE)
