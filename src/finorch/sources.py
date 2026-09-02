"""analysts.yaml kaynak yapilandirmasini okuma."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SourceCfg:
    type: str  # youtube | x | web
    ref: str


@dataclass
class AnalystCfg:
    name: str
    language: str = "tr"
    focus: str = ""
    # macro   -> anlati/makro: nedensel kurallar + gelecek projeksiyonlari cikarilir
    # technical -> teknik analiz: kendi icinde islem kurulumlari (FVG/MSB, entry, SL, TP, RR)
    # mixed   -> her ikisi
    profile_type: str = "macro"
    sources: list[SourceCfg] = field(default_factory=list)


@dataclass
class AlertRules:
    new_price_target: bool = True
    stance_change: bool = True
    consensus_enabled: bool = True
    consensus_min_analysts: int = 2
    consensus_window_hours: int = 48


@dataclass
class AnalystsConfig:
    analysts: list[AnalystCfg] = field(default_factory=list)
    alert_rules: AlertRules = field(default_factory=AlertRules)


def load_analysts_config(path: str | Path) -> AnalystsConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Kaynak yapilandirmasi bulunamadi: {path}. "
            "config/analysts.example.yaml dosyasini kopyalayip doldurun."
        )

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    analysts: list[AnalystCfg] = []
    for a in raw.get("analysts", []) or []:
        sources = [
            SourceCfg(type=str(s["type"]).strip(), ref=str(s["ref"]).strip())
            for s in (a.get("sources") or [])
        ]
        analysts.append(
            AnalystCfg(
                name=str(a["name"]).strip(),
                language=str(a.get("language", "tr")).strip(),
                focus=str(a.get("focus", "")).strip(),
                profile_type=str(a.get("type", a.get("profile_type", "macro"))).strip().lower(),
                sources=sources,
            )
        )

    rules_raw = raw.get("alert_rules", {}) or {}
    consensus = rules_raw.get("consensus", {}) or {}
    rules = AlertRules(
        new_price_target=bool(rules_raw.get("new_price_target", True)),
        stance_change=bool(rules_raw.get("stance_change", True)),
        consensus_enabled=bool(consensus.get("enabled", True)),
        consensus_min_analysts=int(consensus.get("min_analysts", 2)),
        consensus_window_hours=int(consensus.get("window_hours", 48)),
    )

    return AnalystsConfig(analysts=analysts, alert_rules=rules)
