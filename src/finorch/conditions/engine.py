"""Kosul motoru (Faz 1 - icerik tabanli).

Cikarim tipine gore uyari uretir:
  - macro     : yeni projeksiyon veya yeni nedensel kural
  - technical : yeni islem kurulumu (kendi icinde, analistler arasi konsensus YOK)

Alert'ler dedup_key ile tekillestirilir; gonderim ayri adimda yapilir.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch.db.models import Alert, Analyst, MacroRule, Projection, TradeSetup

logger = logging.getLogger(__name__)


def _add_alert(session: Session, rule: str, asset: str, message: str, dedup_key: str) -> Alert | None:
    if session.scalar(select(Alert).where(Alert.dedup_key == dedup_key)):
        return None
    alert = Alert(rule=rule, asset=asset, message=message, dedup_key=dedup_key)
    session.add(alert)
    session.flush()
    return alert


def _analyst_name(session: Session, analyst_id: int | None) -> str:
    if not analyst_id:
        return "Bilinmeyen analist"
    a = session.get(Analyst, analyst_id)
    return a.name if a else "Bilinmeyen analist"


def evaluate_projection(session: Session, proj: Projection) -> list[Alert]:
    name = _analyst_name(session, proj.analyst_id)
    # Somut kod yoksa hedef olarak sektor kullanilir
    target_name = proj.asset or proj.sector
    target = f", hedef {proj.price_target}" if proj.price_target is not None else ""
    horizon = f" ({proj.horizon})" if proj.horizon else ""
    condition = f"EGER {proj.conditions} -> " if proj.conditions else ""
    msg = (
        f"[Projeksiyon] {name} - {target_name}{horizon}: "
        f"{condition}{proj.scenario}{target}"
    )
    key = f"proj:{proj.id}"
    alert = _add_alert(session, "projection", target_name, msg, key)
    return [alert] if alert else []


def evaluate_macro_rule(session: Session, mr: MacroRule) -> list[Alert]:
    name = _analyst_name(session, mr.analyst_id)
    target_name = mr.effect_asset or mr.effect_sector
    tickers = f" [{mr.effect_tickers}]" if mr.effect_tickers else ""
    msg = (
        f"[Kural] {name}: EGER {mr.condition} -> {target_name}{tickers} "
        f"{mr.effect_direction}. {mr.rationale}"
    )
    key = f"rule:{mr.id}"
    alert = _add_alert(session, "macro_rule", target_name, msg, key)
    return [alert] if alert else []


def evaluate_trade_setup(session: Session, ts: TradeSetup) -> list[Alert]:
    name = _analyst_name(session, ts.analyst_id)
    entry = f" giris {ts.entry}" if ts.entry is not None else ""
    sl = f" SL {ts.stop_loss}" if ts.stop_loss is not None else ""
    tp = f" TP {ts.take_profit}" if ts.take_profit else ""
    rr = f" ({ts.rr}RR)" if ts.rr is not None else ""
    tf = f" [{ts.timeframe}]" if ts.timeframe else ""
    msg = (
        f"[Kurulum] {name} - {ts.instrument}{tf} {ts.direction.upper()}"
        f"{rr}: {ts.setup_conditions}.{entry}{sl}{tp}. {ts.rationale}"
    )
    key = f"setup:{ts.id}"
    alert = _add_alert(session, "trade_setup", ts.instrument, msg, key)
    return [alert] if alert else []
