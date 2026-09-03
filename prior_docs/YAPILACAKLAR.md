# Yapilacaklar / Yol Haritasi

> Financial Orchestrator gelistirme plani. Kutucuklari isaretleyerek ilerleriz.
> Oncelik: **P0** = simdi, **P1** = yakin, **P2** = sonra.

## Mevcut durum (tamamlandi)

- [x] Proje iskeleti (Docker + Compose + Postgres/pgvector + CLI)
- [x] YouTube toplama (yt-dlp) + hazir altyazi cikarma
- [x] Yerel transkripsiyon (faster-whisper) altyapisi
- [x] Zaman damgali transkript segmentleri (`transcript_segments`)
- [x] Makro cikarim (kural + projeksiyon) — timestamp + alinti ile
- [x] Teknik cikarim iskeleti (trade setup) — henuz canli test edilmedi
- [x] Vision (ffmpeg kare + gpt-4o-mini) altyapisi — henuz canli test edilmedi
- [x] Salt okunur dashboard (FastAPI + Jinja2), tiklanabilir mm:ss linkleri
- [x] `@yatirim101` uzerinde uctan uca dogrulama (5 video, 11 kural, 7 projeksiyon)
- [x] Dashboard yeniden tasarimi: acik (beyaz) tema, analist basina box, kurallarin
      **onemli / anlik** olarak ikiye ayrilmasi, "EGER x -> y" keskin kosul satirlari
- [x] Cikarima etkilenen **sektor** + **hisse kodu** alanlari eklendi
      (`macro_rules.effect_sector/effect_tickers`, `projections.sector/tickers`)
- [x] Progress Score icin sema ve UI yeri hazir (`progress_score/status/checked_at`)
- [x] **X entegrasyonu**: gonderi turu ayrimi (original/quote/thread/repost/reply),
      repost ve cevap filtresi, thread birlestirme, etkilesim metrikleri,
      tam cozunurluklu gorsel (`name=large`)
- [x] **Grafik ayirma**: vision cikti JSON'a cevrildi; `is_chart` ile mem/selfie
      elenir, `chart_symbol`/`chart_timeframe` okunur, sadece grafikler analize girer
- [x] **Fiyat kosulu izleme** (`price_watches`): "3.250 uzerinde kapanis gorursem
      alirim" -> break_above/break_below/reclaim/retest/range/target/structure
- [x] **Canli piyasa verisi** (yfinance) + sembol cozumleme (BIST `.IS`, kripto `-USD`,
      doviz `=X`) + turev semboller (gram altin = ons/31,1035 x USDTRY)
- [x] **Progress Score dolduruldu** (izlemeler icin): fiyatin tetige yakinligi
- [x] **Dashboard `/watches`**: sunucu tarafi SVG grafik + analistin seviyeleri
- [x] **Analist yontem profili** (`analyst_profiles`): metodoloji, enstrumanlar,
      risk uslubu, sinyal uslubu (hedefli/kosullu/yorumcu)
- [x] `finorch x-preview` ile hesap on incelemesi (DB'ye yazmadan)
- [x] **Kayan piyasa seridi** (`market_quotes` + `/partials/ticker`): BIST/doviz/
      altin/emtia/kripto/ABD endeksleri; sunucuda 5 dk, tarayicida 60 sn tazeleme
- [x] **Turev sembol gecmisi duzeltildi**: altin ve doviz serilerinin tatil takvimi
      ortusmedigi gunlerde kur carpani sessizce `1.0`'a dusuyor, gram altini TL'ye
      cevirmeden USD birakiyordu (degisim `+4732%` gorunuyordu). Artik bilinen son
      kur tasiniyor.

---

## P0 — Simdi (bir sonraki oturum)

- [ ] **GitHub push'u tamamlamak** (yetki bekliyor)
  - Repo: https://github.com/semihcode03/finorch  (remote `origin` ekli)
  - Durum: Lokal git hazir; ilk commit atildi, `.env.example` eklendi, `origin/main` ile
    birlestirildi. Push **403** ile reddedildi.
  - Neden: Bu makinede git **`semihakmese-krsn`** (is hesabi) ile girisli; repo
    **`semihcode03`**'e ait, yazma yetkisi yok.
  - Cozum secenekleri: (a) `semihcode03` icin `repo`/Contents:write yetkili PAT ile push,
    (b) is hesabini repoya collaborator ekle, (c) Credential Manager'da github.com
    kimligini `semihcode03` ile yenile.
  - Not: `.env` ve `.env copy` **commit edilmedi** (gizli); `.gitignore` bunlari disliyor.
- [ ] **Telegram bildirimlerini baglamak** — **kurumsal agda ENGELLI**
  - Tespit: `api.telegram.org` kurumsal ag tarafindan **Trend Micro Web Security** ile
    kategorik olarak engelliyor. Istek Telegram'a hic ulasmiyor; donen sey TLS hatasi degil,
    proxy'nin HTML **403 block sayfasi**. Bu hem container'da hem host'ta gecerli.
  - Cozum secenekleri: (a) IT'den `api.telegram.org` icin whitelist istemek,
    (b) bildirimleri kurumsal ag disinda calistirmak (VPS dagitimi — bkz. P2),
    (c) engellenmeyen alternatif bir kanal (e-posta/webhook) eklemek.
  - [ ] `.env`'e **gercek** `TELEGRAM_BOT_TOKEN` ekle (su an `.env.example`'daki
        `123456789:ABC...` placeholder'i duruyor — @BotFather'dan alinmali)
  - [ ] `finorch get-chat-id` -> `TELEGRAM_CHAT_ID`
  - [ ] `finorch hello` ile test, sonra gercek uyari akisini dogrula
- [ ] **X hesabini canli baglamak** — kod hazir, yalniz kimlik bilgisi eksik
  - [ ] Burner X hesabi ac (ANA HESABI KULLANMA; ban riski)
  - [ ] `X_AUTH_TOKEN` + `X_CT0` cookie'lerini `.env`'e yaz
        (x.com'da F12 -> Application -> Cookies -> x.com)
  - [ ] `finorch x-preview <hesap>` ile on inceleme yap; kendi analizi / repost
        oranina bakip hesabin takibe deger olup olmadigina karar ver
  - [ ] `config/analysts.yaml`'a `type: technical` + `type: x` kaynagi olarak ekle
  - [ ] `finorch sync-config && finorch ingest --limit 20`
  - [ ] Grafikli bir gonderide vision ciktisini dogrula (`is_chart` dogru mu?)
- [ ] **Teknik profil akisini canli test etmek**
  - [ ] Grafik agirlikli bir videoda vision (kare okuma) ciktisini dogrula
  - [ ] Trade setup (entry/SL/TP/RR) cikarimini gozden gecir
- [ ] **Uyelere ozel video karari** (Yatirim 101'in 2/3 videosu uyeye ozel)
  - [ ] Karar: cookie ile erisim mi, yoksa yalniz herkese acik icerik mi?
  - [ ] (Secilirse) yt-dlp icin `cookies.txt` destegi + guvenli saklama

## P1 — Yakin vadede

- [ ] **X hesap havuzu** — tek burner hesap rate-limit'e takilir; birden fazla
      hesap ekleyip rotasyon ve geri cekilme (backoff) mantigi gerekiyor
- [ ] **Fiyat izlemelerini iyilestirme**
  - [ ] Zaman dilimine saygi: "gunluk kapanis ustunde" kosulu su an anlik fiyatla
        kontrol ediliyor; gun ici dokunuslar yanlis tetikleme uretebilir
  - [ ] `structure` kosullarini (FVG/MSB) grafik uzerinden dogrulama
  - [ ] Tetiklendikten sonra takip: hedefe ulasti mi, stop yedi mi?
  - [ ] Cozumlenemeyen enstrumanlar icin elle sembol eslestirme arayuzu
- [ ] **Web/RSS kaynagi** — belirli bir sitenin videolari/yazilari icin adapter
- [ ] **Scheduler'i olceklemek** — `finorch run` icin makul araliklar, hata dayanikliligi
- [ ] **Dashboard iyilestirmeleri**
  - [ ] Kural/projeksiyon icin filtre + arama
  - [ ] Analist bazli "son gorus" ozeti karti
  - [ ] Uyari gecmisi sayfasi
  - [ ] **Piyasa ozeti sayfasi** (`/market`): seritteki sembollerin buyuk grafikleri,
        gun ici (intraday) seri, kazandiran/kaybettiren BIST hisseleri
  - [ ] Serit mini grafikleri su an gunluk kapanislari cizer; gun ici veri
        (`interval=15m`) daha canli bir siluet verir ama ayri bir seri saklamayi gerektirir
- [ ] **Kural tekillestirme (dedup)** — ayni kural birden fazla icerikte tekrar edince
      ayri satir olarak birikiyor (orn. "serbest fonlar kisitlanirsa -> Fon Yonetimi"
      iki kez). Kosul+sektor+yon uzerinden tekillestirip "kac kez tekrarlandi" sayaci
      tutmak hem gurultuyu azaltir hem "onemli kural" siralamasina dogal bir olcut verir.
- [ ] **Maliyet/gozlemlenebilirlik** — LLM token/maliyet logu, islenen video sayaci
- [ ] **Testler** — cikarim parse'i ve pipeline icin birim testleri (kayan noktali JSON vb.)

## P2 — Sonraki fazlar

- [x] **Faz 2: Canli fiyat + Progress Score** — fiyata baglanabilen kisim tamam
  - [x] Fiyat verisi kaynagi: `yfinance`, `market_snapshots` tablosunda onbellek
  - [x] Sembol cozumleme (`market/symbols.py`) + turev semboller (gram altin)
  - [x] Izlemeler icin `progress_score`: fiyatin tetige yakinligi
  - [x] Kosul saglandiginda uyari (`conditions/watch.py` -> mevcut Alert akisi)
- [ ] **Faz 2 kalanlari**
  - [ ] **Makro kural/projeksiyon skorlamasi.** Izlemeler fiyata baglandi ama makro
        kurallar ("faiz duserse bankacilik yukselir") bir OLAYA bagli; fiyat bakarak
        skorlanamaz. Ayri bir `finorch score` adimi gerekiyor: LLM'e kosul metni +
        ilgili sembolun son N gunluk degisimi verilip
        `{score, status: pending|forming|met|invalid}` istenir.
        Bu satirlarda cubuk hala `—` gorunuyor.
  - [ ] Sektor -> ornek ticker sepeti eslemesi (orn. "Bankacilik" -> GARAN.IS,
        AKBNK.IS, YKBNK.IS) ki somut kod verilmemis kurallar da izlenebilsin.
  - [ ] RSI/MACD vb. teknik gostergeler (trade setup'lari degerlendirmek icin)
- [ ] **Faz 3: RAG + hafiza (pgvector)**
  - [ ] Segment/cikarim embedding'leri
  - [ ] Analist bazli gecmis gorus/basari takibi (kim ne dedi, tuttu mu?)
  - [ ] Konsensus mantigi (birden fazla analist ayni yonde)
- [ ] **Faz 4: Agentic katman**
  - [ ] Dogal dille sorgu ("X analistinin altin gorusu ne?")
  - [ ] Otomatik gunluk/haftalik ozet raporu

---

## Acik kararlar (netlestirmemiz gerekenler)

- [ ] Hangi piyasalar oncelik? (BIST hisse, doviz, altin, kripto, tahvil ...)
  - Serit su an bir varsayilan liste ile geliyor (BIST 100/30/Bankacilik, USD/TRY,
    EUR/TRY, gram altin, ons altin/gumus, Brent, BTC, ETH, S&P 500, Nasdaq, DXY, VIX).
    Bu liste bir karar degil, baslangic noktasi: `TICKER_SYMBOLS` ile degistirilebilir.
    Gercekten takip edilen enstrumanlar netlesince varsayilan da guncellenmeli.
- [ ] Uyari kanali: yalniz Telegram mi, ileride e-posta/webhook de mi?
- [ ] Uyelere ozel icerik: cekilecek mi? (ToS riski)
- [ ] VPS dagitimi ne zaman? (GitHub -> VPS + Docker)
- [ ] Veri saklama suresi / arsivleme politikasi

## Teknik borc / notlar

- [ ] `data/report.py` gecici bir hizli-ozet betigi; kalici `finorch report` komutuna donusturulebilir.
- [ ] `docker-compose.yml`'de `./src` mount'u gelistirme kolayligi icin; produ imajinda gerek yok.
- [x] Kurumsal SSL icin kok sertifika imaja eklendi: `certs/*.crt` hem OS guven deposuna
      hem `certifi` paketine yaziliyor (`Dockerfile`). `certs/` git'e dahil degil; Windows
      guven deposundan yeniden uretilebilir. Bundan sonra `PIP_TRUSTED_HOST` kaldirilabilir.
- [ ] Windows PowerShell'de docker cikti akisinda "Add-Content stream" gurultusu var (islevsel etkisi yok).
- Yeni bir Python bagimliligi eklendiginde `docker compose restart` **yetmez**:
  `./src` mount'u yalniz kodu tazeler, paketler imajin icindedir. `docker compose build
  app dashboard` gerekir. (yfinance eklendiginde `No module named 'yfinance'` ile bu
  yasandi.)
- `market_quotes.spark` mini grafik serisini virgullu metin olarak **denormalize** tutar.
  Normalde `market_snapshots`'tan sorgulanirdi; serit her sembol icin tek satirda ve tek
  sorguda cizilmeli oldugundan bilerek boyle birakildi.
