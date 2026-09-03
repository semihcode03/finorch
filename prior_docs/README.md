# Financial Orchestrator

Analistlerin dijital ikizi. Takip edilen YouTube kanallari, X (Twitter) hesaplari ve web
videolarindaki icerikleri otomatik toplar, transkript cikarir, bir LLM ile yapilandirilmis
finansal goruslere (yon, hedef fiyat, gerekce) donusturur ve dikkat cekici kosullar
olustugunda Telegram'dan haber verir.

> **Faz 1 (tamam):** Icerik toplama + AI sinyal cikarimi + dashboard + Telegram uyarisi.
> **Faz 2 (buyuk olcude tamam):** X entegrasyonu, canli piyasa verisi, fiyat kosulu
> izleme ve kayan piyasa seridi eklendi. Kalani icin bkz. `YAPILACAKLAR.md`.

### Durum (son test)

Uctan uca calisir durumda.

**Icerik hatti** — `@yatirim101` (makro profil) uzerinde dogrulandi:

- 5 herkese acik video islendi (uyelere ozel videolar yt-dlp ile erisilemez, atlanir).
- ~5.400 zaman damgali transkript segmenti, 11 makro kural, 7 projeksiyon cikarildi.
- Analiz `gpt-4o-mini` ile yapildi (maliyet ~birkac cent); dashboard `http://localhost:8000`.

**Piyasa hatti** — canli veriyle dogrulandi:

- Kayan serit 15/15 sembolu cekiyor (BIST, doviz, altin, emtia, kripto, ABD endeksleri).
- Fiyat izlemeleri ve `/watches` grafikleri onbellekten cizilir.

Telegram uyarilari ve X toplama **kod olarak hazir ama canli baglanmadi**: ilki kurumsal
agda engelli, ikincisi burner hesap cookie'si bekliyor (bkz. `YAPILACAKLAR.md` P0).

## Mimari

Servisler `docker-compose` ile ayaga kalkar. Boru hatti adimlari:

```
[ingest]      YouTube (yt-dlp) / X (twscrape) / Web (feed) -> ham icerik + medya
    |
[transcribe]  ses -> metin (faster-whisper, yerel)
    |
[vision]      teknik video kareleri (ffmpeg sahne) + X gorselleri -> gpt-4o-mini ile okuma
    |
[analyze]     profil tipine gore yapilandirilmis cikarim (+ fiyat kosullari)
    |
[market]      yfinance -> canli fiyat + gecmis mumlar (onbellekli)
    |
[conditions]  izlemeleri canli fiyatla karsilastirir, uyari kosullarini kontrol eder
    |
[notify]      Telegram bildirimi
    |
[db]          PostgreSQL + pgvector
```

Tum adimlar tek bir uygulama sureci (`finorch run`) icinde APScheduler ile zamanlanir;
olceklendikce ayri servislere bolunebilir. Piyasa seridi bu dongunun **disinda**, kendi
ve cok daha sik araliginda calisir: icerik toplama dakikalar surerken serit birkac
saniyelik bir fiyat sorgusudur ve birinin digerini bekletmesi anlamsizdir.

Dashboard ayri bir servistir ve **yalnizca okur**; hicbir web istegi sirasinda ag'a
cikilmaz. Grafikler ve serit onbellekten beslenir, onbellegi arka plandaki isler doldurur.

## Analist profil tipleri

Her analistin `type`'i icerigin nasil islenecegini belirler (`config/analysts.yaml`):

| Tip           | Ne cikarilir                                                   | Uyari mantigi                                 |
| ------------- | -------------------------------------------------------------- | --------------------------------------------- |
| `macro`     | Nedensel kurallar ("savas -> altin yukselir") + projeksiyonlar | yeni kural / yeni projeksiyon                 |
| `technical` | Islem kurulumlari (FVG+MSB, entry/SL/TP, RR)                   | yeni kurulum (analistler arasi konsensus YOK) |
| `mixed`     | Her ikisi                                                      | ikisi de                                      |

Gorsel (vision) **secici** calisir: teknik hesaplarin video kareleri + gorselli X postlari
okunur; makro hesaplarda metin yeterli sayilir.

## X (Twitter) entegrasyonu

Bir X hesabinin ana sayfasi karisiktir: kendi analizinin yaninda baskasindan
repost'lar, kisa cevaplar ve alakasiz gorseller bulunur. Boru hatti bunlari ayirir.

**1. Turu ayrilir.** Her gonderi siniflandirilir: `original` (kendi gonderisi),
`quote` (alintilayip yorum katmis), `thread` (kendi zincirinin devami),
`repost` (baskasinin gonderisi), `reply` (baskasina cevap). Amac analistin **kendi**
mantigini ogrenmek oldugu icin repost ve cevaplar varsayilan olarak elenir
(`X_INCLUDE_REPOSTS` / `X_INCLUDE_REPLIES` ile acilir).

**2. Thread'ler birlestirilir.** Analistler uzun analizi tek tweet'e sigdiramaz;
kendine cevap vererek zincir kurar. Bu parcalar ayri ayri islenirse her biri
baglamsiz kalir. Ayni konusmadaki kendi gonderileri tek icerige birlestirilir.

**3. Grafikler ayiklanir.** Gonderiye ekli her gorsel cok-modlu LLM'e sorulur:
"bu bir finansal grafik mi?" Mem, selfie ve haber kupuru analiz metnine
karistirilmaz. Grafik ise enstruman, zaman dilimi ve gorunur fiyat seviyeleri
okunur (`content_media.is_chart / chart_symbol / chart_timeframe`). Tweet gorselleri
tam cozunurlukte (`name=large`) istenir; yoksa fiyat etiketleri okunmaz.

### Hesabi eklemeden once: on inceleme

```bash
finorch x-preview teknik_kullanici --limit 30
finorch x-preview teknik_kullanici --analyze   # cikarimi da dener (LLM maliyeti)
```

Hesabin ne kadarinin kendi analizi oldugunu, kac gonderide grafik bulundugunu ve
tipik icerik uslubunu gosterir. Hicbir sey DB'ye yazilmaz.

## Fiyat izlemeleri (canli takip)

Teknik hesaplar cogu zaman kosullu konusur: *"3.250 uzerinde gunluk kapanis
gorursem alirim"*. Bu ifadeler `price_watches` tablosuna **izleme** olarak yazilir ve
her `finorch watch` calistiginda canli fiyatla karsilastirilir.

| Tetik turu      | Anlami                                   |
| --------------- | ---------------------------------------- |
| `break_above` | seviyenin uzerine cikarsa                |
| `break_below` | seviyenin altina inerse                  |
| `reclaim`     | kaybedilen seviyeyi geri alirsa          |
| `retest`      | seviyeye geri cekilir/test ederse        |
| `range`       | iki fiyat arasindaki banda girerse       |
| `target`      | analistin verdigi fiyat hedefi           |
| `structure`   | sayisal seviye yok, formasyon kosulu var |

**Iki giris yolu var.** Teknik hesaplarda metinden dogrudan kosul cikarilir. Makro
hesaplarda ise fiyat hedefi tasiyan projeksiyonlar (`price_target` dolu olanlar)
ek bir LLM cagrisi yapilmadan `target` izlemesine cevrilir — analistin verdigi hedef
hazir sinyal gibi degerlendirilir.

**Progress Score artik doluyor.** Cubuk, fiyatin tetige ne kadar yaklastigini gosterir:
tetik seviyesine `WATCH_BAND_PCT` (varsayilan %10) uzaklikta 0, seviyenin uzerinde 1.
Kosul saglandiginda durum `triggered` olur ve Telegram uyarisi uretilir.

`structure` turundeki kosullar (orn. "FVG doldurulursa") fiyata bakarak dogrulanamaz;
dashboard'da **Elle takip** basligi altinda ayri listelenir.

### Sembol cozumleme

Analist "gram altin" der, Yahoo Finance `USDTRY=X` bekler. `market/symbols.py`
aradaki cevirmendir: BIST kodlarina `.IS` eklenir (`THYAO` -> `THYAO.IS`), kripto
`-USD`'ye (`bitcoin` -> `BTC-USD`), doviz `=X`'e (`dolar` -> `USDTRY=X`) baglanir.

Dogrudan karsiligi olmayan enstrumanlar **turev** olarak hesaplanir:
gram altin = ons altin (`GC=F`) / 31,1035 x `USDTRY=X`. Cozumlenemeyen enstrumanlar
`unresolved` durumunda kalir ve elle takip listesinde gorunur.

### Grafikler

Dashboard grafikleri **sunucu tarafinda SVG olarak** cizilir; JavaScript grafik
kutuphanesi veya CDN kullanilmaz. Sebep: kurumsal ag CDN'leri engelleyebiliyor
(bkz. Telegram notu) ve dashboard'un "ekstra kurulum gerekmez" ilkesi var.

Fiyat verisi bir web istegi sirasinda **cekilmez**; yalnizca onbellekten okunur.
Onbellegi `finorch watch` doldurur, boylece sayfa acilisi ag'i beklemez.

### Kayan piyasa seridi

Her sayfanin ustunde, Yahoo Finance / Bloomberg HT tarzinda kayan bir bant durur:
BIST endeksleri, doviz, altin, emtia, kripto ve ABD endeksleri; her biri son deger,
gunluk degisim ve bir aylik mini grafikle. Uzerine gelince kayma durur.

Semboller `TICKER_SYMBOLS` ile degistirilebilir (`sembol|etiket` ciftleri); bos
birakilirsa `market/ticker.py`'daki varsayilan liste kullanilir.

Iki katmanli tazeleme vardir:

- **Sunucu:** scheduler `TICKER_REFRESH_MINUTES` (varsayilan 5 dk) araliginda
  kotasyonlari cekip `market_quotes` tablosuna yazar. Bu is boru hattindan ayridir;
  icerik toplama dakikalar surerken serit birkac saniyelik bir fiyat sorgusudur.
  Elle tazelemek icin `finorch ticker`.
- **Tarayici:** `TICKER_POLL_SECONDS` (varsayilan 60 sn) araliginda `/partials/ticker`
  cekilip seridin icerigi degistirilir. Animasyon disardaki kapsayicida oldugu icin
  fiyatlar guncellenirken kayma kesintiye ugramaz. Arka plan sekmesinde istek atilmaz.

Dashboard burada da ag'i beklemez: yalnizca `market_quotes`'tan okur.

## Analist yontem profili

Tek tek cikarimlar analistin ne *dedigini* kaydeder. Yontem profili bir ust
katmandir: bircok icerik birlikte okunup hesabin **nasil dusundugu** modellenir —
hangi ekolu kullaniyor (SMC/ICT, Elliott, klasik TA, temel analiz), hangi
enstrumanlarda calisiyor, riski nasil yonetiyor ve sinyal uslubu ne:

- `hedefli` — net fiyat hedefi/seviye verir
- `kosullu` — "su seviye kirilirsa girerim" der
- `yorumcu` — yon belirtir ama somut seviye vermez

Profil `finorch profile` ile uretilir (yeni icerik geldikce otomatik yenilenir) ve
analist detay sayfasinin ustunde kart olarak gorunur.

## Kaynak toplama felsefesi

Her kaynak icin "birincil + yedek" backend yonlendirmesi hedeflenir (Agent-Reach'ten ilham).
Bir yol kirilinca digerine dusulur. Cekirdek hat programatik ve deterministiktir:

| Kaynak  | Birincil        | Yedek            |
| ------- | --------------- | ---------------- |
| YouTube | yt-dlp          | -                |
| X       | twscrape        | (ileride) Scweet |
| Web/RSS | feedparser/Jina | yt-dlp (video)   |
| Fiyat   | yfinance        | -                |

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
docker compose run --rm app finorch ticker             # piyasa seridini ilk kez doldur
docker compose up -d dashboard                          # http://localhost:8000
docker compose up -d app                                # surekli calisan scheduler (opsiyonel)
```

> `finorch run` (yani `app` servisi) ayaga kalktiginda seridi zaten kendisi tazeler.
> Yukaridaki `finorch ticker` adimi, scheduler'i baslatmadan dashboard'a bakmak
> isteyenler icindir; aksi halde serit "Piyasa verisi bekleniyor" der.

> **Not (kurumsal ag / SSL denetimi):** Ag SSL trafigini kendi sertifikasiyla denetliyorsa
> (`self-signed certificate in certificate chain`) container icindeki `pip` PyPI'ye baglanamaz.
> `Dockerfile` bu durum icin `PIP_TRUSTED_HOST` tanimlar. Kalici cozum kurumsal kok
> sertifikayi `certs/*.crt` altina koymaktir; `Dockerfile` bunu hem OS guven deposuna hem
> `certifi` paketine ekler (httpx/openai/yt-dlp certifi kullanir). `certs/` git'e dahil
> **degildir**; Windows'ta kok sertifikayi disa aktarmak icin:
>
> ```powershell
> New-Item -ItemType Directory -Force -Path certs | Out-Null
> $c = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -like "*<CA adi>*" } | Select-Object -First 1
> $b64 = [Convert]::ToBase64String($c.RawData, 'InsertLineBreaks').Replace("`r`n", "`n")
> $lf = [string][char]10
> [IO.File]::WriteAllText("$PWD\certs\corp-root-ca.crt", "-----BEGIN CERTIFICATE-----$lf$b64$lf-----END CERTIFICATE-----$lf")
> ```
>
> Ardindan `docker compose build app` ile imaji yeniden kurun. Ayrica host'ta 5432 doluysa (yerel Postgres) diye db
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
Ekstra kurulum gerekmez; FastAPI + Jinja2 ile sunucu tarafi HTML olusturulur. Harici
JavaScript kutuphanesi veya CDN yoktur — tek istisna, piyasa seridini periyodik tazeleyen
birkac satirlik gomulu betiktir (bkz. "Kayan piyasa seridi").

**Her sayfada:** ustte kayan piyasa seridi (endeks/doviz/emtia/kripto).

**Sayfalar:**

- `/` — Her analist icin **ayri bir box**; asagi dogru uzar. Box icinde cikarimlar
  **anlik kurallar** (son icerikte soylenenler) ve **onemli kurallar** (birikmis kalici
  mekanizmalar) olarak ikiye ayrilir, ardindan projeksiyonlar gelir.
- `/watches` — **Fiyat izlemeleri**: canli takipteki kosullar yakinliga gore sirali,
  her sembol icin SVG grafik uzerinde analistin verdigi seviyeler kesikli cizgi olarak
  isaretli. Tetiklenenler ustte, elle dogrulanmasi gerekenler ayri bolumde.
- `/analyst/{id}` — Analistin yontem profili + tum icerikleri ve cikarimlari
- `/content/{id}` — Zaman damgali tam transkript + cikarimlar + gorsel aciklamalari
- `/partials/ticker` — Sayfa degil; seridin HTML parcasi. Tarayici periyodik olarak
  bunu cekip serit icerigini tazeler.

**Keskin kosul satirlari:** Her cikarim yorum yerine tek satirlik kesin bir ifade olarak
gosterilir: `EGER <kosul> → <endeks/sektor/hisse> <yon>`. Etkilenen alan biliniyorsa
sektor (orn. "Bankacilik") ve somut hisse kodlari (orn. `GARAN`, `AKBNK`) rozet olarak
satirda yer alir. Projeksiyonlar `EGER bu olursa → su olur` biciminde okunur.

> Sektor/hisse alanlari cikarim promptuna sonradan eklendi. Bu alanlar yalnizca **yeni
> analiz edilen** icerikte dolar; eski kayitlarda bos gorunur.

**Kural siniflandirmasi:** LLM her kurali `key` (zamansiz/yapisal mekanizma) veya `live`
(guncel, tarihli gorus) olarak isaretler. Bu alani tasimayan eski kayitlarda geriye donuk
kural uygulanir: analistin en son icerigindeki kurallar "anlik", oncekiler "onemli" sayilir.

**Progress Score:** Kosulun gerceklesmeye ne kadar yakin oldugunu gosteren cubuk.
`price_watches` satirlarinda canli fiyattan hesaplanir (bkz. "Fiyat izlemeleri").
Makro kural ve projeksiyonlarda hala bos (`—`) gorunur; onlarin skorlanmasi olaya bagli
oldugu icin ayri bir adim gerektirir — bkz. `YAPILACAKLAR.md`.

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

| Komut                   | Aciklama                                                    |
| ----------------------- | ----------------------------------------------------------- |
| `finorch doctor`      | Ortam/baglanti saglik kontrolu                              |
| `finorch db-init`     | Tablolari olusturur; mevcut tablolara eksik kolonlari ekler |
| `finorch sync-config` | analysts.yaml'daki kaynaklari DB'ye yazar                   |
| `finorch get-chat-id` | Telegram chat id'yi getUpdates ile bulur                    |
| `finorch hello`       | Telegram'a test bildirimi gonderir                          |
| `finorch x-preview`   | Bir X hesabini DB'ye yazmadan on inceler                    |
| `finorch ingest`      | Kaynaklari bir kez tarar (tek seferlik)                     |
| `finorch backfill`    | Gecmisi toplu ceker (altyazi varsa; Whisper'siz)            |
| `finorch watch`       | Fiyat kosullarini canli piyasa verisiyle kontrol eder       |
| `finorch profile`     | Analistlerin yontem profilini cikarir                       |
| `finorch ticker`      | Dashboard ustundeki piyasa seridini tazeler                 |
| `finorch run`         | Zamanlanmis surekli calisma (scheduler)                     |
| `finorch dashboard`   | Salt okunur web dashboard'unu baslatir (uvicorn)            |

### Geriye donuk veri (backfill) sinirlari

- **YouTube**: tum arsiv cekilebilir. Backfill'de sadece hazir altyazisi olan videolar
  alinir (Whisper yalniz yeni videolarda calisir; eski arsivi transkript etmek CPU'da cok agirdir).
- **X**: en fazla ~3200 tweet (Twitter'in sert siniri).
- **Web/RSS**: genelde yalniz feed'deki son yazilar; daha eskisi icin siteye ozel scraping gerekir.
- Tum icerik `published_at` + `fetched_at` ile saklanir; tekrar tarama yalniz yeni icerigi ekler.

## Git / baska bir PC'de devam etme

Uzak depo: **https://github.com/semihcode03/finorch** (henuz push tamamlanmadi; bkz. `YAPILACAKLAR.md` P0).

Baska bir makinede kaldigin yerden devam:

```bash
git clone https://github.com/semihcode03/finorch.git
cd finorch
cp .env.example .env                 # sonra degerleri doldur (OPENAI_API_KEY, ...)
cp config/analysts.example.yaml config/analysts.yaml
# ardindan "Hizli baslangic (Docker)" adimlarini izle
```

> `.env`, `config/analysts.yaml`, `data/` ve loglar depoya **dahil degildir** (`.gitignore`).
> Bu yuzden yeni PC'de bu dosyalari tekrar olusturman gerekir.

## Sorun giderme

| Belirti                                                                      | Neden / Cozum                                                                                                                                                                             |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pip ... SSLCertVerificationError: self-signed certificate`                | Kurumsal SSL denetimi.`Dockerfile`'daki `PIP_TRUSTED_HOST` bunu asar; kalici cozum kurumsal kok sertifikayi imaja eklemek.                                                            |
| `Bind for 0.0.0.0:5432 failed: port is already allocated`                  | Host'ta baska bir Postgres var. db host portu`5433`'tedir; gerekirse `docker-compose.yml`'de degistirin.                                                                              |
| `failed to resolve host 'db'`                                              | db container'i ayakta/saglikli degil.`docker compose up -d db` ile baslatip `docker compose ps` ile `healthy` bekleyin.                                                             |
| Dashboard'da`500 Internal Server Error`                                    | Eski Starlette imzasi.`TemplateResponse(request, "x.html", {...})` yeni imzasi kullanilir.                                                                                              |
| `This video is available to this channel's members`                        | Video uyelere ozel; yt-dlp erisemez. Herkese acik videolar islenir.                                                                                                                       |
| `TELEGRAM_CHAT_ID tanimli degil`                                           | Uyari uretilir ama gonderilmez.`finorch get-chat-id` ile id alip `.env`'e yazin.                                                                                                      |
| `self-signed certificate in certificate chain` (calisma aninda, pip degil) | Kurumsal ag TLS'i kendi kok CA'si ile yeniden imzaliyor. Kok sertifikayi`certs/*.crt` altina koyup imaji yeniden kurun; `Dockerfile` sertifikayi OS deposuna ve `certifi`'ye ekler. |
| Telegram'dan HTML**403** donuyor (JSON degil)                          | `api.telegram.org` kurumsal ag politikasi ile engelli (or. Trend Micro Web Security block sayfasi). TLS sorunu **degil**; IT whitelist'i veya ag disi (VPS) dagitim gerekir.      |
| Serit "Piyasa verisi bekleniyor" diyor                                     | `market_quotes` henuz bos.`finorch ticker` calistirin veya `app` servisini (scheduler) baslatin.                                                                                    |
| `No module named 'yfinance'`                                             | Bagimlilik`pyproject.toml`'a eklendi ama imaj eski. `docker compose build app dashboard` ile yeniden kurun (`./src` mount'u yalniz kodu tazeler, paketleri degil).                |

## Guvenlik notlari

- `.env`, `config/analysts.yaml`, `accounts.db` ve `data/` commit edilmez.
- X icin **ana hesabinizi kullanmayin**; ban riski nedeniyle burner hesap kullanin.
- Cookie'ler yalnizca yerel/VPS'te tutulur.

## Yol haritasi (sonraki fazlar)

> Ayrintili ve guncel liste icin `YAPILACAKLAR.md` dosyasina bakin.

- **Faz 1 (tamam):** Icerik toplama + AI cikarim + zaman damgali dashboard + Telegram
- **Faz 2 (buyuk olcude tamam):** X entegrasyonu (repost ayrimi, thread birlestirme,
  grafik okuma), fiyat kosulu izleme, canli fiyat + SVG grafikler, analist yontem profili,
  kayan piyasa seridi. Kalan: makro kurallar icin olay tabanli skorlama, RSI/MACD gibi
  teknik gostergeler, gun ici veri + `/market` ozet sayfasi.
- Faz 3: pgvector ile RAG, analist konsensus/gecmis basari takibi
- Faz 4: Agentic katman (dogal dille "su analistin son gorusunu getir")
