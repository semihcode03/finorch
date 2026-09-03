"""Financial Orchestrator komut satiri arayuzu."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from finorch.config import settings
from finorch.logging_setup import setup_logging

app = typer.Typer(help="Financial Orchestrator - analist dijital ikizi (Faz 1)")
console = Console()


@app.callback()
def _main() -> None:
    setup_logging()


@app.command()
def doctor() -> None:
    """Ortam ve baglanti saglik kontrolu."""
    table = Table(title="finorch doctor")
    table.add_column("Bilesen")
    table.add_column("Durum")
    table.add_column("Not")

    # DB
    try:
        from finorch.db.session import ping

        ping()
        table.add_row("PostgreSQL", "[green]OK[/green]", settings.database_url.split("@")[-1])
    except Exception as e:
        table.add_row("PostgreSQL", "[red]HATA[/red]", str(e)[:60])

    # OpenAI
    if settings.openai_api_key:
        table.add_row("OpenAI", "[green]OK[/green]", f"model={settings.openai_model}")
    else:
        table.add_row("OpenAI", "[yellow]EKSIK[/yellow]", "OPENAI_API_KEY yok")

    # Telegram
    if settings.telegram_bot_token and settings.telegram_chat_id:
        table.add_row("Telegram", "[green]OK[/green]", "token + chat_id var")
    elif settings.telegram_bot_token:
        table.add_row("Telegram", "[yellow]KISMI[/yellow]", "chat_id yok (get-chat-id)")
    else:
        table.add_row("Telegram", "[red]EKSIK[/red]", "TELEGRAM_BOT_TOKEN yok")

    # Ingestor backend'leri
    for stype in ("youtube", "x", "web"):
        try:
            from finorch.ingestion import get_ingestor

            ok, note = get_ingestor(stype).healthcheck()
            style = "green" if ok else "yellow"
            table.add_row(f"ingestor:{stype}", f"[{style}]{'OK' if ok else 'UYARI'}[/{style}]", note)
        except Exception as e:
            table.add_row(f"ingestor:{stype}", "[red]HATA[/red]", str(e)[:60])

    console.print(table)


@app.command("db-init")
def db_init() -> None:
    """Veritabani uzantisini (pgvector) ve tablolari olusturur."""
    from finorch.db import init_db

    init_db()
    console.print("[green]Veritabani hazir.[/green]")


@app.command("sync-config")
def sync_config_cmd() -> None:
    """analysts.yaml'daki kaynaklari DB'ye yazar."""
    from finorch.pipeline import sync_config

    sync_config()
    console.print("[green]Kaynak yapilandirmasi senkronlandi.[/green]")


@app.command("get-chat-id")
def get_chat_id() -> None:
    """Telegram chat id'leri getUpdates ile listeler (once botunuza mesaj gonderin)."""
    from finorch.notify import get_chat_ids

    chats = get_chat_ids()
    if not chats:
        console.print(
            "[yellow]Hic mesaj bulunamadi. Once botunuza Telegram'dan bir mesaj gonderin, "
            "sonra tekrar deneyin.[/yellow]"
        )
        return
    table = Table(title="Telegram chat id'leri")
    table.add_column("chat_id")
    table.add_column("tur")
    table.add_column("ad")
    for c in chats:
        table.add_row(c["chat_id"], c["type"], c["title"])
    console.print(table)
    console.print("Bu id'yi .env icindeki TELEGRAM_CHAT_ID'e yazin.")


@app.command()
def hello() -> None:
    """Telegram'a test bildirimi gonderir."""
    from finorch.notify import send_message

    ok = send_message("Merhaba! Financial Orchestrator bildirim testi calisiyor.")
    if ok:
        console.print("[green]Test mesaji gonderildi.[/green]")
    else:
        console.print("[red]Mesaj gonderilemedi. .env Telegram ayarlarini kontrol edin.[/red]")


@app.command()
def ingest(limit: int = typer.Option(5, help="Kaynak basina cekilecek icerik sayisi")) -> None:
    """Kaynaklari bir kez tarar, transkript + analiz + uyari dongusunu calistirir."""
    from finorch.pipeline import (
        run_analysis,
        run_ingestion,
        run_profiles,
        run_transcription,
        run_vision,
        run_watches,
        send_pending_alerts,
    )

    run_ingestion(limit_per_source=limit)
    run_transcription()
    run_vision()
    run_analysis()
    run_watches()
    run_profiles()
    send_pending_alerts()
    console.print("[green]Tek seferlik dongu tamamlandi.[/green]")


@app.command()
def backfill(
    limit: int = typer.Option(
        200, help="Kaynak basina geriye donuk cekilecek maksimum icerik sayisi"
    ),
) -> None:
    """Kaynaklarin gecmisini toplu ceker (ilk kurulumda tum arsivi almak icin).

    Not: X ~3200 tweet ile sinirlidir; YouTube tum videolar (altyazi/transkript
    maliyetine dikkat); RSS genelde sadece son yazilari verir.
    """
    from finorch.pipeline import (
        run_analysis,
        run_ingestion,
        run_profiles,
        run_transcription,
        run_vision,
        send_pending_alerts,
    )

    console.print(f"[cyan]Backfill basliyor (kaynak basina limit={limit})...[/cyan]")
    # captions_only: altyazisi olmayan eski videolar Whisper'a alinmaz
    run_ingestion(limit_per_source=limit, whisper_for_missing=False)
    run_transcription(max_items=limit)
    run_vision(max_items=limit)
    run_analysis(max_items=limit)
    run_profiles(force=True)
    # Gecmis icerikten cikan kosullar toplu uyari yagmuruna donmesin diye
    # backfill'de fiyat kontrolu calistirilmaz; sonra "finorch watch" ile yapilir.
    send_pending_alerts()
    console.print("[green]Backfill tamamlandi.[/green]")


@app.command("x-preview")
def x_preview(
    handle: str = typer.Argument(..., help="X kullanici adi (@ ile veya @ olmadan)"),
    limit: int = typer.Option(20, help="Incelenecek son gonderi sayisi"),
    analyze: bool = typer.Option(
        False, "--analyze", help="Ornek gonderilerde LLM cikarimi da dene (OpenAI maliyeti olusur)"
    ),
) -> None:
    """Bir X hesabini DB'ye yazmadan on inceler.

    Hesabin ne kadarinin kendi analizi, ne kadarinin repost oldugunu; kac gonderide
    grafik bulundugunu ve tipik icerik uslubunu gosterir. Analist listesine eklemeden
    once hesabin takibe deger olup olmadigina karar vermek icin.
    """
    from finorch.ingestion.x import XIngestor, keep_item, skip_reason, stitch_threads

    ingestor = XIngestor()
    ok, note = ingestor.healthcheck()
    if not ok:
        console.print(f"[red]X kaynagi hazir degil:[/red] {note}")
        raise typer.Exit(code=1)

    console.print(f"[cyan]@{handle.lstrip('@')} inceleniyor (son {limit} gonderi)...[/cyan]")
    items = ingestor.collect(handle, limit=limit)
    if not items:
        console.print("[yellow]Hic gonderi cekilemedi. Cookie'ler gecerli mi?[/yellow]")
        raise typer.Exit(code=1)

    # --- tur dagilimi ---
    kinds: dict[str, int] = {}
    for it in items:
        kinds[it.post_kind] = kinds.get(it.post_kind, 0) + 1

    labels = {
        "original": "Kendi gonderisi",
        "thread": "Thread parcasi",
        "quote": "Alintili yorum",
        "repost": "Repost (baskasinin)",
        "reply": "Baskasina cevap",
    }
    dist = Table(title=f"@{handle.lstrip('@')} - icerik dagilimi")
    dist.add_column("Tur")
    dist.add_column("Adet", justify="right")
    dist.add_column("Oran", justify="right")
    for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
        dist.add_row(labels.get(kind, kind), str(count), f"%{count / len(items) * 100:.0f}")
    console.print(dist)

    stitched = stitch_threads(items)
    kept = [it for it in stitched if keep_item(it)]
    with_charts = [it for it in kept if it.media_urls]

    console.print(
        f"\n[bold]{len(items)}[/bold] gonderi -> thread birlestirme sonrasi "
        f"[bold]{len(stitched)}[/bold] icerik -> filtreden gecen "
        f"[bold green]{len(kept)}[/bold green] (gorselli: {len(with_charts)})"
    )

    # --- elenenler ve gerekceleri ---
    dropped = [(it, skip_reason(it)) for it in stitched if not keep_item(it)]
    if dropped:
        reasons: dict[str, int] = {}
        for _, reason in dropped:
            reasons[reason] = reasons.get(reason, 0) + 1
        console.print(
            "[dim]Elenenler: "
            + ", ".join(f"{reason} x{count}" for reason, count in reasons.items())
            + "[/dim]"
        )

    # --- ornek icerikler ---
    sample = Table(title="Analiz edilecek ornekler")
    sample.add_column("Tarih", no_wrap=True)
    sample.add_column("Tur", no_wrap=True)
    sample.add_column("Etkilesim", justify="right", no_wrap=True)
    sample.add_column("Gorsel", justify="right", no_wrap=True)
    sample.add_column("Metin")
    for it in kept[:10]:
        date = it.published_at.strftime("%d.%m.%Y") if it.published_at else "-"
        preview = " ".join(it.text.split())[:90]
        sample.add_row(
            date,
            labels.get(it.post_kind, it.post_kind),
            str(it.engagement),
            str(len(it.media_urls)),
            preview or "[dim](sadece gorsel)[/dim]",
        )
    console.print(sample)

    if not analyze:
        console.print(
            "\n[dim]Cikarimi da gormek icin: "
            f"finorch x-preview {handle} --analyze[/dim]"
        )
        return

    _preview_extraction(kept[:5])


def _preview_extraction(items: list) -> None:
    """On incelemede ornek gonderilerde grafik okuma + kosul cikarimini dener."""
    from finorch.analysis.vision import describe_image
    from finorch.analysis.watch import extract_watches

    console.print("\n[cyan]Ornek gonderilerde cikarim deneniyor...[/cyan]")
    found = 0
    for it in items:
        text = it.text
        charts = 0
        for url in it.media_urls[:2]:
            reading = describe_image(url)
            if reading.is_chart:
                charts += 1
                text = f"{text}\n[Grafikten okunan] {reading.as_text()}"

        watches = extract_watches(text).watches
        if not watches:
            continue
        found += len(watches)
        console.print(f"\n[bold]{' '.join(it.text.split())[:70]}[/bold] (grafik: {charts})")
        for w in watches:
            level = f"{w['trigger_price']:g}" if w["trigger_price"] is not None else "seviye yok"
            console.print(
                f"  → [green]{w['instrument']}[/green] {w['trigger_type']} @ {level} "
                f"[{w['direction']}] {w['structure'] or w['action']}"
            )

    if not found:
        console.print(
            "[yellow]Ornek gonderilerde takip edilebilir fiyat kosulu bulunamadi.[/yellow] "
            "Hesap seviye vermeyen bir yorumcu olabilir; daha fazla gonderi deneyin."
        )


@app.command()
def watch(
    once: bool = typer.Option(True, help="Tek seferlik kontrol (varsayilan)"),
) -> None:
    """Takipteki fiyat kosullarini guncel piyasa verisiyle kontrol eder."""
    from finorch.pipeline import run_watches, send_pending_alerts

    triggered = run_watches()
    sent = send_pending_alerts() if once else 0
    console.print(
        f"[green]Kontrol tamam.[/green] Tetiklenen: {triggered}, gonderilen uyari: {sent}"
    )


@app.command()
def ticker() -> None:
    """Dashboard ustundeki piyasa seridini tazeler (endeks/doviz/emtia/kripto)."""
    from finorch.market.ticker import load_quotes
    from finorch.pipeline import run_ticker

    count = run_ticker()
    if not count:
        console.print(
            "[yellow]Hicbir kotasyon alinamadi.[/yellow] "
            "MARKET_ENABLED / TICKER_ENABLED ayarlarini ve ag erisimini kontrol edin."
        )
        return

    table = Table(title="Piyasa seridi")
    table.add_column("Sembol")
    table.add_column("Deger", justify="right")
    table.add_column("Degisim", justify="right")
    for q in load_quotes():
        pct = q["change_pct"]
        if pct is None:
            change = "—"
        else:
            color = "green" if pct >= 0 else "red"
            change = f"[{color}]{pct:+.2f}%[/{color}]"
        table.add_row(q["label"], f"{q['price']:,.2f}" if q["price"] else "—", change)
    console.print(table)


@app.command()
def profile(
    force: bool = typer.Option(False, "--force", help="Yeni icerik olmasa da yeniden uret"),
) -> None:
    """Analistlerin yontem profillerini (nasil dusunduklerini) cikarir."""
    from finorch.pipeline import run_profiles

    built = run_profiles(force=force)
    if built:
        console.print(f"[green]{built} analist profili guncellendi.[/green]")
    else:
        console.print(
            "[yellow]Guncellenecek profil yok.[/yellow] "
            "Yeni icerik gelmemis olabilir; --force ile zorlayabilirsiniz."
        )


@app.command()
def run() -> None:
    """Zamanlanmis surekli calisma (scheduler)."""
    from finorch.scheduler import start

    start()


@app.command()
def dashboard() -> None:
    """Salt okunur web dashboard'u baslatir (uvicorn)."""
    import uvicorn

    from finorch.dashboard.app import create_app

    console.print(
        f"[cyan]Dashboard baslatiliyor: http://{settings.dashboard_host}:{settings.dashboard_port}[/cyan]"
    )
    uvicorn.run(
        create_app(),
        host=settings.dashboard_host,
        port=settings.dashboard_port,
    )


if __name__ == "__main__":
    app()
