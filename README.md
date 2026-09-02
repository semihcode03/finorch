# Financial Orchestrator

Analistlerin dijital ikizi. Takip edilen YouTube kanallari, X (Twitter) hesaplari ve web
videolarindaki icerikleri otomatik toplar, transkript cikarir, bir LLM ile yapilandirilmis
finansal goruslere (yon, hedef fiyat, gerekce) donusturur ve dikkat cekici kosullar
olustugunda Telegram'dan haber verir.

> **Faz 1 (bu repo):** Icerik toplama + AI sinyal cikarimi + dashboard + Telegram uyarisi.
> Canli fiyat/teknik analiz sonraki faza birakilmistir.

### Durum (son test)
Uctan uca calisir durumda. `@yatirim101` (makro profil) uzerinde dogrulandi:
- 5 herkese acik video islendi (uyelere ozel videolar yt-dlp ile erisilemez, atlanir).
- ~5.400 zaman damgali transkript segmenti, 11 makro kural, 7 projeksiyon cikarildi.
- Analiz `gpt-4o-mini` ile yapildi (maliyet ~birkac cent); dashboard `http://localhost:8000`.
- Ayrintili gelecek plani icin bkz. `YAPILACAKLAR.md`.

## Mimari

Servisler `docker-compose` ile ayaga kalkar. Boru hatti adimlari:

```
[ingest]      YouTube (yt-dlp) / X (twscrape) / Web (feed) -> ham icerik + medya
    |
[transcribe]  ses -> metin (faster-whisper, yerel)
    |
[vision]      teknik video kareleri (ffmpeg sahne) + X gorselleri -> gpt-4o-mini ile okuma
    |
[analyze]     profil tipine gore yapilandirilmis cikarim
    |
[conditions]  uyari kosullarini kontrol eder
    |
[notify]      Telegram bildirimi
    |
[db]          PostgreSQL + pgvector
```

Faz 1'de tum adimlar tek bir uygulama sureci (`finorch run`) icinde APScheduler ile
zamanlanir; olceklendikce ayri servislere bolunebilir.

## Analist profil tipleri

Her analistin `type`'i icerigin nasil islenecegini belirler (`config/analysts.yaml`):

| Tip         | Ne cikarilir                                              | Uyari mantigi                     |
| ----------- | --------------------------------------------------------- | --------------------------------- |
| `macro`     | Nedensel kurallar ("savas -> altin yukselir") + projeksiyonlar | yeni kural / yeni projeksiyon     |
| `technical` | Islem kurulumlari (FVG+MSB, entry/SL/TP, RR)              | yeni kurulum (analistler arasi konsensus YOK) |
| `mixed`     | Her ikisi                                                 | ikisi de                          |

Gorsel (vision) **secici** calisir: teknik hesaplarin video kareleri + gorselli X postlari
okunur; makro hesaplarda metin yeterli sayilir.

## Kaynak toplama felsefesi

Her kaynak icin "birincil + yedek" backend yonlendirmesi hedeflenir (Agent-Reach'ten ilham).
Bir yol kirilinca digerine dusulur. Cekirdek hat programatik ve deterministiktir:

| Kaynak  | Birincil        | Yedek             |
| ------- | --------------- | ----------------- |
| YouTube | yt-dlp          | -                 |
| X       | twscrape        | (ileride) Scweet  |
| Web/RSS | feedparser/Jina | yt-dlp (video)    |

## Hizli baslangic

### Gereksinimler
- Docker + Docker Compose (onerilen), veya lokal Python 3.11+
- OpenAI API anahtari (gpt-4o-mini, aylik birkac dolar)
- Telegram bot token'i (@BotFather)
- (X icin) burner X hesabi cookie'leri

### Kurulum (Docker)

```bash
cp .env.example .env
# .env dosyasini doldurun (OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, ...)
cp config/analysts.example.yaml config/analysts.yaml
# analysts.yaml'a takip edilecek analistleri ekleyin

docker compose build app                               # bagimliliklari kurar
docker compose up -d db                                # Postgres+pgvector (host portu 5433)
docker compose run --rm app finorch db-init            # tablolar + pgvector
docker compose run --rm app finorch sync-config        # analysts.yaml -> DB
docker compose run --rm app finorch ingest --limit 3   # son N videoyu uctan uca isle
docker compose up -d dashboard                          # http://localhost:8000
docker compose up -d app                                # surekli calisan scheduler (opsiyonel)
```

> **Not (kurumsal ag / SSL denetimi):** Ag SSL trafigini kendi sertifikasiyla denetliyorsa
> (`self-signed certificate in certificate chain`) container icindeki `pip` PyPI'ye baglanamaz.
> `Dockerfile` bu durum icin `PIP_TRUSTED_HOST` tanimlar; kalici cozum kurumsal kok
> sertifikayi imaja eklemektir. Ayrica host'ta 5432 doluysa (yerel Postgres) diye db
> **host portu 5433**'e alinmistir (uygulama ic agda hala `db:5432` kullanir).

### Kurulum (lokal, Docker'siz)

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows PowerShell
pip install -e .
cp .env.example .env         # duzenleyin
# DATABASE_URL'de host'u localhost yapin
finorch db-init
finorch doctor
finorch run
```

## Telegram chat id ogrenme

1. @BotFather ile bir bot olusturun, token'i `.env`'e yazin.
2. Botunuza Telegram'dan bir mesaj gonderin ("merhaba").
3. `finorch get-chat-id` calistirin; cikan id'yi `TELEGRAM_CHAT_ID`'e yazin.
4. `finorch hello` ile test bildirimi gonderin.

## Dashboard

Salt okunur web arayuzu; veritabanindaki analist, video ve cikarim verilerini gosterir.
Ekstra kurulum gerekmez; FastAPI + Jinja2 ile sunucu tarafi HTML olusturulur.

**Sayfalar:**
- `/` — Analist listesi + ozet sayilar (videolar, kurallar, projeksiyonlar, kurulumlar)
- `/analyst/{id}` — Analistin videolari ve her videoya ait cikarimlar
- `/content/{id}` — Zaman damgali tam transkript + cikarimlar + gorsel aciklamalari

**Zaman damgasi linkleri:** YouTube iceriklerde `source_timestamp_sec` alani dolu olan
her cikarim satiri tiklanabilir bir `mm:ss` linki gosterir; linke tiklaninca video o
saniyeden baslar (`https://www.youtube.com/watch?v=ID&t=Xs`).

### Lokal calistirma

```bash
finorch dashboard
# http://localhost:8000 adresini acin
```

Host/port degistirmek icin `.env`'e ekleyin:

```env
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8080
```

### Docker ile calistirma

```bash
docker compose up -d dashboard
# http://localhost:8000 adresini acin
```

Yalnizca dashboard'u ayaga kaldirmak icin:

```bash
docker compose up -d db dashboard
```

## CLI komutlari

| Komut                 | Aciklama                                             |
| --------------------- | ---------------------------------------------------- |
| `finorch doctor`      | Ortam/baglanti saglik kontrolu                       |
| `finorch db-init`     | Veritabani tablolarini olusturur                     |
| `finorch sync-config` | analysts.yaml'daki kaynaklari DB'ye yazar            |
| `finorch get-chat-id` | Telegram chat id'yi getUpdates ile bulur             |
| `finorch hello`       | Telegram'a test bildirimi gonderir                   |
| `finorch ingest`      | Kaynaklari bir kez tarar (tek seferlik)              |
| `finorch backfill`    | Gecmisi toplu ceker (altyazi varsa; Whisper'siz)    |
| `finorch run`         | Zamanlanmis surekli calisma (scheduler)              |
| `finorch dashboard`   | Salt okunur web dashboard'unu baslatir (uvicorn)     |

### Geriye donuk veri (backfill) sinirlari
- **YouTube**: tum arsiv cekilebilir. Backfill'de sadece hazir altyazisi olan videolar
  alinir (Whisper yalniz yeni videolarda calisir; eski arsivi transkript etmek CPU'da cok agirdir).
- **X**: en fazla ~3200 tweet (Twitter'in sert siniri).
- **Web/RSS**: genelde yalniz feed'deki son yazilar; daha eskisi icin siteye ozel scraping gerekir.
- Tum icerik `published_at` + `fetched_at` ile saklanir; tekrar tarama yalniz yeni icerigi ekler.

## Sorun giderme

| Belirti | Neden / Cozum |
| ------- | ------------- |
| `pip ... SSLCertVerificationError: self-signed certificate` | Kurumsal SSL denetimi. `Dockerfile`'daki `PIP_TRUSTED_HOST` bunu asar; kalici cozum kurumsal kok sertifikayi imaja eklemek. |
| `Bind for 0.0.0.0:5432 failed: port is already allocated` | Host'ta baska bir Postgres var. db host portu `5433`'tedir; gerekirse `docker-compose.yml`'de degistirin. |
| `failed to resolve host 'db'` | db container'i ayakta/saglikli degil. `docker compose up -d db` ile baslatip `docker compose ps` ile `healthy` bekleyin. |
| Dashboard'da `500 Internal Server Error` | Eski Starlette imzasi. `TemplateResponse(request, "x.html", {...})` yeni imzasi kullanilir. |
| `This video is available to this channel's members` | Video uyelere ozel; yt-dlp erisemez. Herkese acik videolar islenir. |
| `TELEGRAM_CHAT_ID tanimli degil` | Uyari uretilir ama gonderilmez. `finorch get-chat-id` ile id alip `.env`'e yazin. |

## Guvenlik notlari
- `.env`, `config/analysts.yaml`, `accounts.db` ve `data/` commit edilmez.
- X icin **ana hesabinizi kullanmayin**; ban riski nedeniyle burner hesap kullanin.
- Cookie'ler yalnizca yerel/VPS'te tutulur.

## Yol haritasi (sonraki fazlar)

> Ayrintili ve guncel liste icin `YAPILACAKLAR.md` dosyasina bakin.

- **Faz 1 (tamam):** Icerik toplama + AI cikarim + zaman damgali dashboard + Telegram
- Faz 2: Canli fiyat verisi + teknik gostergeler (RSI/MACD) ve fiyat kosullari
- Faz 3: pgvector ile RAG, analist konsensus/gecmis basari takibi
- Faz 4: Agentic katman (dogal dille "su analistin son gorusunu getir")
