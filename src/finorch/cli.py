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
        run_transcription,
        run_vision,
        send_pending_alerts,
    )

    run_ingestion(limit_per_source=limit)
    run_transcription()
    run_vision()
    run_analysis()
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
    send_pending_alerts()
    console.print("[green]Backfill tamamlandi.[/green]")


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
