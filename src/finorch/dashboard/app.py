"""Dashboard FastAPI uygulamasi - salt okunur mod.

Rotalar:
  GET /              -> analist listesi + ozet sayilar
  GET /watches       -> canli takipteki fiyat kosullari + grafikler
  GET /analyst/{id}  -> analist videolari + cikarimlar + yontem profili
  GET /content/{id}  -> icerik detayi: transkript + cikarimlar + gorseller
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import func, select

from finorch.config import settings
from finorch.dashboard.chart import Level, render_price_svg, render_sparkline
from finorch.db import (
    Analyst,
    AnalystProfile,
    ContentMedia,
    MacroRule,
    PriceWatch,
    Projection,
    RawContent,
    TradeSetup,
    TranscriptSegment,
    get_session,
)
from finorch.market import get_history
from finorch.market.symbols import display_name
from finorch.market.ticker import load_quotes

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Ana sayfada analist basina gosterilecek satir siniri (fazlasi icin detaya gidilir)
_INDEX_ROW_LIMIT = 6

# Izleme sayfasinda grafik cizilecek en fazla farkli sembol sayisi
_CHART_LIMIT = 16

# Piyasa seridinde "degismedi" sayilan esik (%). Gosterilen ondalikta sifira
# yuvarlanan bir degisim yonlu renk/ok almamali.
_FLAT_PCT = 0.005

_TRIGGER_LABELS = {
    "break_above": "uzerine cikarsa",
    "break_below": "altina inerse",
    "reclaim": "geri alirsa",
    "retest": "test ederse",
    "range": "bandina girerse",
    "target": "hedefi",
    "structure": "formasyon kosulu",
}

_STATUS_LABELS = {
    "watching": "Takipte",
    "triggered": "Tetiklendi",
    "expired": "Suresi doldu",
    "invalid": "Gecersiz",
    "unresolved": "Sembol cozumlenemedi",
}


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


def _split_tickers(raw: str) -> list[str]:
    """"GARAN, AKBNK" -> ["GARAN", "AKBNK"]."""
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def _fmt_price(value: float | None) -> str:
    """Fiyati buyuklugune gore uygun ondalikla yazar (BTC 100000 vs THYAO 285.50)."""
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.0f}".replace(",", ".")
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.4g}"


def _ticker_quotes() -> list[dict[str, Any]]:
    """Kayan serit icin kotasyonlari onbellekten okur ve mini grafiklerini cizer.

    Serit her sayfanin ustunde durdugundan buradaki bir hata tum dashboard'u
    goturmemeli: veri yoksa serit sessizce bos kalir.
    """
    if not (settings.ticker_enabled and settings.market_enabled):
        return []
    try:
        quotes = load_quotes()
    except Exception:
        return []

    for q in quotes:
        q["dir"] = _quote_direction(q["change_pct"])
        q["spark_svg"] = Markup(
            render_sparkline(q["spark"], up={"up": True, "down": False}.get(q["dir"]))
        )
    return quotes


def _quote_direction(change_pct: float | None) -> str:
    """Kotasyonu "up" / "down" / "flat" olarak siniflar.

    Sifira cok yakin degisimler nottur: "-0.00%" yaninda kirmizi bir asagi ok
    gostermek, olmayan bir dususu varmis gibi gosterir.
    """
    if change_pct is None:
        return "flat"
    if abs(change_pct) < _FLAT_PCT:
        return "flat"
    return "up" if change_pct > 0 else "down"


def _content_title(rc: RawContent) -> str:
    """Icerik icin baslik uretir.

    Video basligini kullanir; tweet'lerde baslik olmadigi icin metnin ilk
    satirindan kisa bir ozet cikarilir (yoksa tweet id'si gorunurdu).
    """
    if rc.title:
        return rc.title
    text = " ".join((rc.text or "").split())
    if text:
        return text[:90] + ("…" if len(text) > 90 else "")
    return rc.external_id


def _trigger_text(watch: PriceWatch) -> str:
    """Tetik kosulunu tek satirlik okunur ifadeye cevirir."""
    phrase = _TRIGGER_LABELS.get(watch.trigger_type, watch.trigger_type)
    if watch.trigger_price is None:
        return watch.structure or phrase
    if watch.trigger_type == "range":
        low, high = sorted((watch.trigger_price, watch.trigger_price_2 or watch.trigger_price))
        return f"{_fmt_price(low)} - {_fmt_price(high)} {phrase}"
    return f"{_fmt_price(watch.trigger_price)} {phrase}"


def _effective_class(rule_class: str, content_id: int, latest_content_id: int | None) -> str:
    """Kuralin "live" (anlik) mi "key" (onemli) mi oldugunu belirler.

    LLM sinifladiysa onu kullanir. `rule_class` bos olan eski kayitlarda geriye donuk
    kural: analistin EN SON icerigindeki kurallar "anlik", daha eskiler birikmis
    kural tabani olarak "onemli" sayilir. Boylece iki bolum de dolu kalir.
    """
    if rule_class in {"key", "live"}:
        return rule_class
    return "live" if content_id == latest_content_id else "key"


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
    templates.env.globals["split_tickers"] = _split_tickers
    templates.env.globals["fmt_price"] = _fmt_price
    templates.env.globals["row_limit"] = _INDEX_ROW_LIMIT
    # base.html seridi her sayfada cizer; veriyi sablonun kendisi ceker
    templates.env.globals["ticker_quotes"] = _ticker_quotes
    templates.env.globals["ticker_poll_seconds"] = max(10, settings.ticker_poll_seconds)

    # ------------------------------------------------------------------ #
    #  GET /partials/ticker  - kayan seridin icerigi (tarayici periyodik ceker) #
    # ------------------------------------------------------------------ #
    @fastapi_app.get("/partials/ticker", response_class=HTMLResponse)
    async def ticker_partial(request: Request) -> HTMLResponse:
        """Seridin yalnizca ic gruplarini dondurur.

        Tarayici bunu `.ticker-track` icine yazar; animasyon track uzerinde
        oldugu icin fiyatlar guncellenirken kayma kesintiye ugramaz.
        """
        return templates.TemplateResponse(
            request,
            "_ticker.html",
            {"quotes": _ticker_quotes()},
            headers={"Cache-Control": "no-store"},
        )

    # ------------------------------------------------------------------ #
    #  GET /  - ana sayfa: analist basina bir box                          #
    # ------------------------------------------------------------------ #
    @fastapi_app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """Ana sayfa: her analist icin ayri bir box; onemli + anlik kurallar."""
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
                setup_count: int = session.execute(
                    select(func.count())
                    .select_from(TradeSetup)
                    .where(TradeSetup.analyst_id == analyst.id)
                ).scalar_one()
                watch_count: int = session.execute(
                    select(func.count())
                    .select_from(PriceWatch)
                    .where(
                        PriceWatch.analyst_id == analyst.id,
                        PriceWatch.status == "watching",
                    )
                ).scalar_one()

                latest = session.execute(
                    select(RawContent)
                    .where(RawContent.analyst_id == analyst.id)
                    .order_by(
                        RawContent.published_at.desc().nulls_last(),
                        RawContent.fetched_at.desc(),
                    )
                    .limit(1)
                ).scalars().first()

                # --- kurallar: onemli (key) / anlik (live) olarak ikiye ayrilir ---
                rule_rows = session.execute(
                    select(MacroRule, RawContent.url, RawContent.source_type)
                    .join(RawContent, MacroRule.content_id == RawContent.id)
                    .where(MacroRule.analyst_id == analyst.id)
                    .order_by(MacroRule.confidence.desc(), MacroRule.created_at.desc())
                ).all()

                latest_id = latest.id if latest else None
                key_rules: list[dict[str, Any]] = []
                live_rules: list[dict[str, Any]] = []
                for rule, url, source_type in rule_rows:
                    item = {
                        "condition": rule.condition,
                        "asset": rule.effect_asset,
                        "sector": rule.effect_sector,
                        "tickers": _split_tickers(rule.effect_tickers),
                        "direction": rule.effect_direction,
                        "rationale": rule.rationale,
                        "confidence": rule.confidence,
                        "progress_score": rule.progress_score,
                        "progress_status": rule.progress_status,
                        "content_id": rule.content_id,
                        "ts_url": _ts_link(url, source_type, rule.source_timestamp_sec),
                        "ts_label": _fmt_mmss(rule.source_timestamp_sec),
                    }
                    bucket = _effective_class(rule.rule_class, rule.content_id, latest_id)
                    (live_rules if bucket == "live" else key_rules).append(item)

                # --- projeksiyonlar: "bu olursa -> su olur" ---
                proj_rows = session.execute(
                    select(Projection, RawContent.url, RawContent.source_type)
                    .join(RawContent, Projection.content_id == RawContent.id)
                    .where(Projection.analyst_id == analyst.id)
                    .order_by(Projection.confidence.desc(), Projection.created_at.desc())
                ).all()

                projections = [
                    {
                        "asset": p.asset,
                        "sector": p.sector,
                        "tickers": _split_tickers(p.tickers),
                        "horizon": p.horizon,
                        "if_text": p.conditions,
                        "then_text": p.scenario,
                        "direction": p.direction,
                        "price_target": p.price_target,
                        "confidence": p.confidence,
                        "progress_score": p.progress_score,
                        "progress_status": p.progress_status,
                        "content_id": p.content_id,
                        "ts_url": _ts_link(url, source_type, p.source_timestamp_sec),
                        "ts_label": _fmt_mmss(p.source_timestamp_sec),
                    }
                    for p, url, source_type in proj_rows
                ]

                rows.append({
                    "id": analyst.id,
                    "name": analyst.name,
                    "language": analyst.language,
                    "focus": analyst.focus,
                    "profile_type": analyst.profile_type,
                    "video_count": video_count,
                    "rule_count": len(rule_rows),
                    "proj_count": len(projections),
                    "setup_count": setup_count,
                    "watch_count": watch_count,
                    "latest_title": _content_title(latest) if latest else "",
                    "latest_date": (latest.published_at or latest.fetched_at) if latest else None,
                    "key_rules": key_rules[:_INDEX_ROW_LIMIT],
                    "key_rules_total": len(key_rules),
                    "live_rules": live_rules[:_INDEX_ROW_LIMIT],
                    "live_rules_total": len(live_rules),
                    "projections": projections[:_INDEX_ROW_LIMIT],
                })

        return templates.TemplateResponse(
            request, "index.html", {"analysts": rows}
        )

    # ------------------------------------------------------------------ #
    #  GET /watches  - canli takipteki fiyat kosullari                     #
    # ------------------------------------------------------------------ #
    @fastapi_app.get("/watches", response_class=HTMLResponse)
    async def watches(request: Request) -> HTMLResponse:
        """Fiyat kosullari: takipte olanlar yakinliga gore, tetiklenenler ustte."""
        with get_session() as session:
            rows = session.execute(
                select(PriceWatch, Analyst.name)
                .outerjoin(Analyst, PriceWatch.analyst_id == Analyst.id)
                .order_by(
                    PriceWatch.progress_score.desc().nulls_last(),
                    PriceWatch.created_at.desc(),
                )
            ).all()

            watch_rows = [
                {
                    "id": w.id,
                    "analyst": analyst_name or "Bilinmeyen",
                    "analyst_id": w.analyst_id,
                    "content_id": w.content_id,
                    "instrument": w.instrument,
                    "symbol": w.symbol,
                    "label": display_name(w.symbol) if w.symbol else w.instrument,
                    "direction": w.direction,
                    "trigger_type": w.trigger_type,
                    "trigger_text": _trigger_text(w),
                    "trigger_price": w.trigger_price,
                    "trigger_price_2": w.trigger_price_2,
                    "timeframe": w.timeframe,
                    "structure": w.structure,
                    "action": w.action,
                    "entry": w.entry,
                    "stop_loss": w.stop_loss,
                    "take_profit": w.take_profit,
                    "rr": w.rr,
                    "rationale": w.rationale,
                    "confidence": w.confidence,
                    "quote": w.quote,
                    "status": w.status,
                    "status_label": _STATUS_LABELS.get(w.status, w.status),
                    "last_price": w.last_price,
                    "last_price_text": _fmt_price(w.last_price),
                    "distance_pct": w.distance_pct,
                    "progress_score": w.progress_score,
                    "triggered_at": w.triggered_at,
                    "last_checked_at": w.last_checked_at,
                }
                for w, analyst_name in rows
            ]

        # Grafikler yalnizca onbellekten okunur; bir web istegi ag'i beklemez.
        # Onbellegi "finorch watch" doldurur.
        charts: dict[str, Markup] = {}
        levels_by_symbol: dict[str, list[Level]] = {}
        for row in watch_rows:
            symbol = row["symbol"]
            if not symbol or row["trigger_price"] is None:
                continue
            levels_by_symbol.setdefault(symbol, [])
            if len(levels_by_symbol[symbol]) < 3:
                levels_by_symbol[symbol].append(
                    Level(value=row["trigger_price"], label=_fmt_price(row["trigger_price"]))
                )

        for symbol in list(levels_by_symbol)[:_CHART_LIMIT]:
            history = get_history(symbol, cached_only=True)
            svg = render_price_svg(history, levels=levels_by_symbol[symbol])
            if svg:
                charts[symbol] = Markup(svg)

        buckets = {
            "triggered": [r for r in watch_rows if r["status"] == "triggered"],
            "watching": [r for r in watch_rows if r["status"] == "watching"],
            "manual": [r for r in watch_rows if r["status"] == "unresolved"],
            "closed": [r for r in watch_rows if r["status"] in ("expired", "invalid")],
        }

        return templates.TemplateResponse(
            request,
            "watches.html",
            {"buckets": buckets, "charts": charts, "total": len(watch_rows)},
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

            profile = session.scalar(
                select(AnalystProfile).where(AnalystProfile.analyst_id == analyst_id)
            )

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
                    "title": _content_title(rc),
                    "url": rc.url,
                    "source_type": rc.source_type,
                    "post_kind": rc.post_kind,
                    "engagement": rc.like_count + rc.repost_count + rc.reply_count,
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
                "profile": profile,
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
