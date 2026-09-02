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

---

## P0 — Simdi (bir sonraki oturum)

- [ ] **Telegram bildirimlerini baglamak**
  - [ ] `.env`'e `TELEGRAM_BOT_TOKEN` ekle
  - [ ] `finorch get-chat-id` -> `TELEGRAM_CHAT_ID`
  - [ ] `finorch hello` ile test, sonra gercek uyari akisini dogrula
- [ ] **Teknik profil akisini canli test etmek**
  - [ ] `config/analysts.yaml`'a bir `technical` hesap ekle
  - [ ] Grafik agirlikli bir videoda vision (kare okuma) ciktisini dogrula
  - [ ] Trade setup (entry/SL/TP/RR) cikarimini gozden gecir
- [ ] **Uyelere ozel video karari** (Yatirim 101'in 2/3 videosu uyeye ozel)
  - [ ] Karar: cookie ile erisim mi, yoksa yalniz herkese acik icerik mi?
  - [ ] (Secilirse) yt-dlp icin `cookies.txt` destegi + guvenli saklama

## P1 — Yakin vadede

- [ ] **X (Twitter) toplama** — twscrape + burner hesap cookie'leri
  - [ ] Hesap ekleme/rotasyon akisi, rate-limit yonetimi
  - [ ] Gorselli tweet'lerde vision okuma
- [ ] **Web/RSS kaynagi** — belirli bir sitenin videolari/yazilari icin adapter
- [ ] **Scheduler'i olceklemek** — `finorch run` icin makul araliklar, hata dayanikliligi
- [ ] **Dashboard iyilestirmeleri**
  - [ ] Kural/projeksiyon icin filtre + arama
  - [ ] Analist bazli "son gorus" ozeti karti
  - [ ] Uyari gecmisi sayfasi
- [ ] **Maliyet/gozlemlenebilirlik** — LLM token/maliyet logu, islenen video sayaci
- [ ] **Testler** — cikarim parse'i ve pipeline icin birim testleri (kayan noktali JSON vb.)

## P2 — Sonraki fazlar

- [ ] **Faz 2: Canli fiyat + teknik gostergeler**
  - [ ] Fiyat verisi kaynagi (borsa/kripto API)
  - [ ] RSI/MACD vb. hesaplama; cikarilan kurallari fiyat kosuluyla eslestirme
  - [ ] "Kosul olustu" tetikleyicisi -> uyari
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
- [ ] Uyari kanali: yalniz Telegram mi, ileride e-posta/webhook de mi?
- [ ] Uyelere ozel icerik: cekilecek mi? (ToS riski)
- [ ] VPS dagitimi ne zaman? (GitHub -> VPS + Docker)
- [ ] Veri saklama suresi / arsivleme politikasi

## Teknik borc / notlar

- [ ] `data/report.py` gecici bir hizli-ozet betigi; kalici `finorch report` komutuna donusturulebilir.
- [ ] `docker-compose.yml`'de `./src` mount'u gelistirme kolayligi icin; produ imajinda gerek yok.
- [ ] Kurumsal SSL icin `PIP_TRUSTED_HOST` yerine kok sertifika eklemek daha temiz.
- [ ] Windows PowerShell'de docker cikti akisinda "Add-Content stream" gurultusu var (islevsel etkisi yok).
