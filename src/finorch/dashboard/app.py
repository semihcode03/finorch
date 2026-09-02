"""Dashboard FastAPI uygulamasi - salt okunur mod.

Rotalar:
  GET /              -> analist listesi + ozet sayilar
  GET /analyst/{id}  -> analist videolari + cikarimlar
  GET /content/{id}  -> icerik detayi: transkript + cikarimlar + gorseller
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from finorch.db import (
    Analyst,
    ContentMedia,
    MacroRule,
    Projection,
    RawContent,
    TradeSetup,
    TranscriptSegment,
    get_session,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _fmt_mmss(sec: float | None) -> str:
    """Saniyeyi mm:ss formatina donusturur. None verilirse bos string dondurur."""
    if sec is None:
        return ""
    total = int(sec)
    return f"{total // 60:02d}:{total % 60:02d}"


def _ts_link(url: str, source_type: str, sec: float | None) -> str | None:
    """YouTube icin tiklanabilir &t= URL'i olusturur; diger turlerde None dondurur."""
    if sec is None or source_type != "youtube":
        return None
    return f"{url}&t={int(sec)}s"


def _direction_label(direction: str) -> str:
    """Yon kodunu Turkce etikete cevirir."""
    return {"up": "YUKARI", "down": "ASAGI", "neutral": "YATAY",
             "long": "LONG", "short": "SHORT"}.get(direction, direction.upper())


def create_app() -> FastAPI:
    """FastAPI uygulamasini olusturup dondurur. DB'ye import sirasinda baglanmaz."""
    fastapi_app = FastAPI(
        title="Financial Orchestrator Dashboard",
        docs_url=None,
        redoc_url=None,
    )

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    # Jinja2 global yardimci fonksiyonlar
    templates.env.globals["fmt_mmss"] = _fmt_mmss
    templates.env.globals["ts_link"] = _ts_link
    templates.env.globals["direction_label"] = _direction_label

    # ------------------------------------------------------------------ #
    #  GET /  - ana sayfa                                                  #
    # ------------------------------------------------------------------ #
    @fastapi_app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """Ana sayfa: tum analistler ve ozet istatistikler."""
        rows: list[dict[str, Any]] = []
        with get_session() as session:
            analysts = session.execute(
                select(Analyst).order_by(Analyst.name)
            ).scalars().all()

            for analyst in analysts:
                video_count: int = session.execute(
                    select(func.count())
                    .select_from(RawContent)
                    .where(RawContent.analyst_id == analyst.id)
                ).scalar_one()
                rule_count: int = session.execute(
                    select(func.count())
                    .select_from(MacroRule)
                    .where(MacroRule.analyst_id == analyst.id)
                ).scalar_one()
                proj_count: int = session.execute(
                    select(func.count())
                    .select_from(Projection)
                    .where(Projection.analyst_id == analyst.id)
                ).scalar_one()
                setup_count: int = session.execute(
                    select(func.count())
                    .select_from(TradeSetup)
                    .where(TradeSetup.analyst_id == analyst.id)
                ).scalar_one()

                rows.append({
                    "id": analyst.id,
                    "name": analyst.name,
                    "language": analyst.language,
                    "focus": analyst.focus,
                    "profile_type": analyst.profile_type,
                    "video_count": video_count,
                    "rule_count": rule_count,
                    "proj_count": proj_count,
                    "setup_count": setup_count,
                })

        return templates.TemplateResponse(
            request, "index.html", {"analysts": rows}
        )

    # ------------------------------------------------------------------ #
    #  GET /analyst/{id}  - analist detay                                  #
    # ------------------------------------------------------------------ #
    @fastapi_app.get("/analyst/{analyst_id}", response_class=HTMLResponse)
    async def analyst_detail(request: Request, analyst_id: int) -> HTMLResponse:
        """Analist detay sayfasi: videolar ve her videoya ait cikarimlar."""
        with get_session() as session:
            analyst = session.get(Analyst, analyst_id)
            if analyst is None:
                raise HTTPException(status_code=404, detail="Analist bulunamadi")

            # Videolari yayinlanma tarihine gore sirala; tarih yoksa cekilme tarihine gore
            contents_raw = session.execute(
                select(RawContent)
                .where(RawContent.analyst_id == analyst_id)
                .order_by(
                    RawContent.published_at.desc().nulls_last(),
                    RawContent.fetched_at.desc(),
                )
            ).scalars().all()

            contents: list[dict[str, Any]] = []
            for rc in contents_raw:
                rules = session.execute(
                    select(MacroRule)
                    .where(MacroRule.content_id == rc.id)
                    .order_by(MacroRule.confidence.desc())
                ).scalars().all()
                projections = session.execute(
                    select(Projection)
                    .where(Projection.content_id == rc.id)
                    .order_by(Projection.confidence.desc())
                ).scalars().all()
                setups = session.execute(
                    select(TradeSetup)
                    .where(TradeSetup.content_id == rc.id)
                    .order_by(TradeSetup.confidence.desc())
                ).scalars().all()

                contents.append({
                    "id": rc.id,
                    "title": rc.title or rc.external_id,
                    "url": rc.url,
                    "source_type": rc.source_type,
                    "published_at": rc.published_at,
                    "fetched_at": rc.fetched_at,
                    "analyzed": rc.analyzed,
                    "rules": rules,
                    "projections": projections,
                    "setups": setups,
                })

        return templates.TemplateResponse(
            request,
            "analyst.html",
            {
                "analyst": analyst,
                "contents": contents,
            },
        )

    # ------------------------------------------------------------------ #
    #  GET /content/{id}  - icerik detay                                   #
    # ------------------------------------------------------------------ #
    @fastapi_app.get("/content/{content_id}", response_class=HTMLResponse)
    async def content_detail(request: Request, content_id: int) -> HTMLResponse:
        """Icerik detay sayfasi: zaman damgali transkript + cikarimlar + gorseller."""
        with get_session() as session:
            rc = session.get(RawContent, content_id)
            if rc is None:
                raise HTTPException(status_code=404, detail="Icerik bulunamadi")

            segments = session.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.content_id == content_id)
                .order_by(TranscriptSegment.idx)
            ).scalars().all()
            rules = session.execute(
                select(MacroRule)
                .where(MacroRule.content_id == content_id)
                .order_by(MacroRule.confidence.desc())
            ).scalars().all()
            projections = session.execute(
                select(Projection)
                .where(Projection.content_id == content_id)
                .order_by(Projection.confidence.desc())
            ).scalars().all()
            setups = session.execute(
                select(TradeSetup)
                .where(TradeSetup.content_id == content_id)
                .order_by(TradeSetup.confidence.desc())
            ).scalars().all()
            media_items = session.execute(
                select(ContentMedia)
                .where(ContentMedia.content_id == content_id)
                .order_by(ContentMedia.timestamp_sec)
            ).scalars().all()

        return templates.TemplateResponse(
            request,
            "content.html",
            {
                "content": rc,
                "segments": segments,
                "rules": rules,
                "projections": projections,
                "setups": setups,
                "media_items": media_items,
            },
        )

    return fastapi_app
