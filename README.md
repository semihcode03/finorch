# Financial Orchestrator

Financial Orchestrator, takip edilen finans analistlerinin YouTube, X ve web iceriklerini
toplayan; transkript, goruntu ve LLM analizi ile yapilandirilmis finansal gorusler ureten
bir arastirma ve izleme uygulamasidir.

Uygulama ayrica canli piyasa fiyatlarini, fiyat kosullarini ve Telegram bildirimlerini
yonetir. Dashboard, FastAPI ve Jinja2 ile sunucu tarafinda olusturulur.

## Ozellikler

- YouTube, X ve RSS/web kaynaklarindan icerik toplama
- Faster-Whisper ile yerel transkript
- OpenAI ile makro, teknik ve karma analiz
- Teknik kosullar icin fiyat izleme ve ilerleme skoru
- yfinance ile canli fiyat, gecmis mum ve kayan piyasa seridi
- Lightweight Charts ile 15/30/60 dakikalik etkilesimli grafikler ve Python indikatorleri
- PostgreSQL + pgvector veri saklama
- Salt okunur web dashboard'u
- Telegram uyarilari
- Analistlerin yontem profili

## Mimari

Tum cekirdek akis tek bir Python uygulamasinda calisir:

```text
ingestion -> transcription -> vision -> analysis -> market/conditions -> notification
                                      |
                                      v
                              PostgreSQL + pgvector
```

Dashboard veritabanindan okur; web istegi sirasinda piyasa verisi cekmez. Arka plan
isleri fiyat ve icerik onbelleklerini doldurur.

## Gereksinimler

- Docker ve Docker Compose (onerilen)
- veya Python 3.11+
- OpenAI API anahtari
- Telegram bot token'i (bildirimler icin)
- X entegrasyonu icin burner hesap cookie'leri

## Hizli baslangic

### Docker ile

```powershell
Copy-Item .env.example .env
Copy-Item config/analysts.example.yaml config/analysts.yaml
# .env ve config/analysts.yaml dosyalarini doldurun

docker compose build app
docker compose up -d db
docker compose run --rm app finorch db-init
docker compose run --rm app finorch sync-config
docker compose run --rm app finorch ticker
docker compose up -d dashboard
```

Dashboard: http://localhost:8000
Etkilesimli grafikler: http://localhost:8000/charts

Surekli scheduler'i de baslatmak icin:

```powershell
docker compose up -d app
```

PostgreSQL host portu `5433`, dashboard portu `8000` olarak ayarlanmistir.

### Lokal Python ile

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
Copy-Item config/analysts.example.yaml config/analysts.yaml
finorch db-init
finorch doctor
finorch dashboard
```

Lokal calismada `.env` icindeki `DATABASE_URL` host'u genellikle `localhost` olmalidir.

## CLI komutlari

| Komut | Aciklama |
| --- | --- |
| `finorch doctor` | Ortam ve servis saglik kontrolu |
| `finorch db-init` | Veritabani ve tablolarin kurulumu |
| `finorch sync-config` | Analist konfigurasyonunu veritabanina aktarir |
| `finorch ingest --limit 5` | Icerikleri tek seferlik toplar ve analiz eder |
| `finorch backfill` | Gecmis icerikleri toplu olarak isler |
| `finorch x-preview <kullanici>` | X hesabini DB'ye yazmadan inceler |
| `finorch watch` | Fiyat kosullarini kontrol eder |
| `finorch ticker` | Piyasa seridini tazeler |
| `finorch profile` | Analist yontem profillerini olusturur |
| `finorch run` | Zamanlanmis surekli calisma |
| `finorch dashboard` | Web dashboard'unu baslatir |
| `finorch get-chat-id` | Telegram chat ID'sini bulur |
| `finorch hello` | Telegram bildirim testi gonderir |

## Konfigurasyon

Gizli ve makineye ozel dosyalar repoya dahil edilmez:

- `.env`
- `config/analysts.yaml`
- `data/`
- `certs/`
- log ve Python cache dosyalari

Ornek ayarlar `.env.example` ve `config/analysts.example.yaml` dosyalarindadir.
X icin ana hesap yerine burner hesap kullanilmalidir. Cookie degerlerini repoya
eklemeyin.

Telegram kurulumu icin botunuza once mesaj gonderin, sonra `finorch get-chat-id`
komutunu calistirip sonucu `.env` icindeki `TELEGRAM_CHAT_ID` alanina yazin.

## Dashboard sayfalari

- `/` analistleri ve cikarimlari gosterir
- `/watches` aktif fiyat izlemelerini ve grafikleri gosterir
- `/charts` intraday mum, hacim, SMA 20, EMA 50, RSI 14 ve fiyat seviyelerini gosterir
- `/analyst/{id}` analist profili ve gecmisini gosterir
- `/content/{id}` transkript, cikarim ve gorsel analizini gosterir

## Gelistirme

Kod `src/finorch` altindadir. Yerel kalite kontrolleri:

```powershell
python -m compileall -q src
ruff check src
pytest
```

Dashboard grafik kutuphanesini guncellemek icin Node.js ile:

```powershell
npm install
npm run vendor:charts
```

Grafik JavaScript'i CDN'den cekilmez; `src/finorch/dashboard/static/vendor` altindan
lokal servis edilir. Ucretsiz test saglayicisinda 15/30 dakika yaklasik 60 gun,
60 dakika yaklasik 2 yil gecmis sunar. Bu sinir saglayiciya gore degisebilir.

Detayli teknik notlar ve sonraki adimlar `prior_docs/README.md` ve
`prior_docs/YAPILACAKLAR.md` dosyalarindadir.

## Guvenlik

API anahtarlarini, X cookie'lerini, Telegram token'larini ve kurumsal sertifikalari
commit etmeyin. Finansal cikarimlar otomatik analiz sonucudur; yatirim tavsiyesi
olarak kullanilmamalidir.
