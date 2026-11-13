"""
advisor_goal_actions.py
Boban - Advisor Goal Actions (poradenská vrstva nad business_dashboard)

Verze: kompatibilní s Boban 0.9.13.17+
Účel: ze seznamu findings (audit, advisor_memory) vygeneruje prioritizovaný
      seznam konkrétních kroků navázaných na obchodní cíl.

Použití z business_dashboard.py:

    from advisor_goal_actions import suggest_actions_for_goal
    result = suggest_actions_for_goal(
        goal="organic_traffic_growth",
        findings=findings_list,           # list[dict] nebo list[Finding]
        project_context={"business_mode": business_mode},
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Definice cílů
# ---------------------------------------------------------------------------

GOALS: dict[str, dict[str, Any]] = {
    "organic_traffic_growth": {
        "label": "Růst organické návštěvnosti",
        "primary_metric": "organic_sessions",
        "supporting_metrics": [
            "impressions", "average_position", "ctr", "indexed_pages",
        ],
    },
    "conversion_rate": {
        "label": "Zvýšení konverzního poměru",
        "primary_metric": "conversion_rate",
        "supporting_metrics": [
            "add_to_cart_rate", "checkout_completion", "bounce_rate",
        ],
    },
    "lead_volume": {
        "label": "Zvýšení počtu leadů",
        "primary_metric": "leads",
        "supporting_metrics": ["form_completion_rate", "contact_rate"],
    },
    "ppc_roi": {
        "label": "Zlepšení PPC ROI",
        "primary_metric": "roas",
        "supporting_metrics": ["cpc", "ctr", "quality_score", "conversion_rate"],
    },
}


# ---------------------------------------------------------------------------
# Katalog akcí podle typu findingu
# ---------------------------------------------------------------------------

ACTION_CATALOG: dict[str, dict[str, Any]] = {
    "missing_meta_description": {
        "title": "Doplnit meta popisy",
        "why": (
            "Meta popis ovlivňuje CTR ve výsledcích vyhledávání. "
            "Chybějící popis = Google si vymyslí vlastní, obvykle horší."
        ),
        "steps": [
            "Exportovat seznam URL bez meta popisu z auditu.",
            "Pro každou URL napsat popis 140–160 znaků s klíčovým slovem a výzvou k akci.",
            "Nahrát zpět do CMS (WordPress: Yoast / RankMath; Shopify: SEO pole produktu).",
            "Znovu spustit audit a ověřit, že počet chybějících je 0.",
        ],
        "effort": "low",
        "base_impact": 60,
    },
    "missing_title_tag": {
        "title": "Opravit title tagy",
        "why": (
            "Title tag je nejsilnější on-page signál pro relevanci. "
            "Chybějící nebo duplicitní title = slabá pozice."
        ),
        "steps": [
            "Najít URL s prázdným nebo duplicitním title.",
            "Napsat unikátní title 50–60 znaků, klíčové slovo na začátku.",
            "Nahrát do CMS a znovu ověřit.",
        ],
        "effort": "low",
        "base_impact": 70,
    },
    "duplicate_content": {
        "title": "Vyřešit duplicitní obsah",
        "why": "Duplicity tříští rank. Google neví, kterou verzi upřednostnit.",
        "steps": [
            "Identifikovat skupiny URL s >80 % shodným obsahem.",
            "Zvolit kanonickou verzi, ostatní přesměrovat nebo nastavit canonical.",
            "U kategorií s filtrovacími parametry nastavit noindex, follow.",
        ],
        "effort": "medium",
        "base_impact": 65,
    },
    "slow_pages": {
        "title": "Zrychlit načítání stránek",
        "why": (
            "Rychlost je ranking faktor a ovlivňuje bounce rate i konverze."
        ),
        "steps": [
            "Změřit Core Web Vitals (PageSpeed Insights, CrUX).",
            "Identifikovat 5 nejpomalejších šablon.",
            "Optimalizovat obrázky (WebP, lazy-load), omezit JS, zapnout cache.",
            "Znovu změřit a porovnat.",
        ],
        "effort": "medium",
        "base_impact": 55,
    },
    "missing_internal_links": {
        "title": "Doplnit interní prolinkování",
        "why": (
            "Interní odkazy předávají authority a pomáhají Google "
            "pochopit strukturu webu."
        ),
        "steps": [
            "Najít klíčové stránky s málo interními odkazy.",
            "Přidat odkazy z relevantních kategorií a článků.",
            "Použít popisné anchor texty s klíčovým slovem.",
        ],
        "effort": "low",
        "base_impact": 50,
    },
    "thin_content": {
        "title": "Rozšířit tenký obsah",
        "why": (
            "Stránky s málo obsahem mají slabou relevanci a neudrží uživatele."
        ),
        "steps": [
            "Identifikovat stránky s <300 slovy unikátního textu.",
            "Doplnit o specifikace, FAQ, návod k použití, recenze.",
            "Cílit na 500–800 slov u kategorií, 300+ u produktů.",
        ],
        "effort": "medium",
        "base_impact": 55,
    },
    "missing_schema": {
        "title": "Přidat strukturovaná data (Schema.org)",
        "why": "Schema zlepšuje rich snippets v SERP a tím CTR.",
        "steps": [
            "Přidat Product schema u produktů (název, cena, dostupnost, hodnocení).",
            "Přidat BreadcrumbList schema.",
            "Ověřit v Google Rich Results Test.",
        ],
        "effort": "medium",
        "base_impact": 45,
    },
    "not_indexed": {
        "title": "Zajistit indexaci klíčových stránek",
        "why": (
            "Neindexovaná stránka nemůže získat organickou návštěvnost."
        ),
        "steps": [
            "Zkontrolovat Search Console → Pokrytí → vyloučené URL.",
            "Odstranit překážky (robots.txt, noindex, chybějící odkazy).",
            "Odeslat sitemap, požádat o indexaci prioritních URL.",
        ],
        "effort": "low",
        "base_impact": 80,
    },
    "weak_category_pages": {
        "title": "Posílit kategorie",
        "why": (
            "Kategorie nesou nejvíc organických dotazů. "
            "Slabé kategorie = ztracený traffic."
        ),
        "steps": [
            "Přidat 300+ slov unikátního textu nad/pod produkty.",
            "Doplnit FAQ sekci s dotazy ze Search Console.",
            "Zajistit interní odkazy z blogu na kategorii.",
        ],
        "effort": "medium",
        "base_impact": 65,
    },
}


# ---------------------------------------------------------------------------
# Prioritizace podle cíle
# ---------------------------------------------------------------------------

# Jak moc je která akce relevantní pro který cíl (0–100).
GOAL_WEIGHTS: dict[str, dict[str, int]] = {
    "organic_traffic_growth": {
        "not_indexed": 100,
        "missing_title_tag": 95,
        "weak_category_pages": 90,
        "missing_meta_description": 85,
        "duplicate_content": 85,
        "thin_content": 75,
        "slow_pages": 60,
        "missing_internal_links": 60,
        "missing_schema": 40,
    },
    "conversion_rate": {
        "slow_pages": 90,
        "missing_schema": 70,
        "thin_content": 65,
        "missing_meta_description": 40,
    },
    "lead_volume": {
        "missing_meta_description": 80,
        "missing_title_tag": 75,
        "slow_pages": 60,
    },
    "ppc_roi": {
        "slow_pages": 90,
        "missing_schema": 60,
    },
}

SEVERITY_SCORE: dict[str, int] = {
    "critical": 100,
    "high": 85,
    "medium": 60,
    "low": 35,
}


# ---------------------------------------------------------------------------
# Datové struktury
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """Normalizovaný finding z advisor_memory / auditu."""
    code: str
    severity: str = "medium"
    count: int = 1
    page_type: str | None = None
    evidence: str | None = None


@dataclass
class Action:
    action_id: str
    title: str
    why: str
    priority: int
    effort: str
    expected_impact: str
    steps: list[str]
    source_findings: list[str] = field(default_factory=list)
    goal: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Hlavní funkce
# ---------------------------------------------------------------------------

def suggest_actions_for_goal(
    goal: str,
    findings: Iterable[dict[str, Any] | Finding],
    project_context: dict[str, Any] | None = None,
    max_actions: int = 8,
) -> dict[str, Any]:
    """
    Vrátí prioritizovaný seznam poradenských kroků pro daný cíl.

    Parametry:
        goal: klíč z GOALS (např. "organic_traffic_growth")
        findings: seznam dictů nebo Finding objektů z auditu / advisor_memory.
                  Každý musí mít alespoň "code" (např. "missing_meta_description").
        project_context: volitelný dict s "business_mode" ("shop"/"lead"),
                         "domain", "brand" – použije se v lidském textu.
        max_actions: kolik akcí maximálně vrátit (default 8).

    Návrat:
        dict s klíči:
            "goal": lidský název cíle
            "goal_key": klíč cíle
            "actions": seznam Action.to_dict(), seřazeno od nejvyšší priority
            "summary": krátké shrnutí pro uživatele
            "gaps": seznam toho, co chybí k lepší analýze
    """
    if goal not in GOALS:
        raise ValueError(
            f"Neznámý cíl '{goal}'. Použij jeden z: {list(GOALS.keys())}"
        )

    goal_meta = GOALS[goal]
    goal_weights = GOAL_WEIGHTS.get(goal, {})
    context = project_context or {}
    business_mode = context.get("business_mode", "shop")

    # Normalizace findings
    normalized: list[Finding] = []
    for f in findings:
        if isinstance(f, Finding):
            normalized.append(f)
        else:
            normalized.append(
                Finding(
                    code=f.get("code") or f.get("type") or "unknown",
                    severity=(f.get("severity") or "medium").lower(),
                    count=int(f.get("count") or f.get("occurrences") or 1),
                    page_type=f.get("page_type"),
                    evidence=f.get("evidence"),
                )
            )

    if not normalized:
        return {
            "goal": goal_meta["label"],
            "goal_key": goal,
            "actions": [],
            "summary": (
                "Zatím nemám žádná zjištění z auditu. Spusť prosím "
                "audit (SEO check) a pak se vrať – připravím konkrétní kroky."
            ),
            "gaps": ["chybí findings z auditu"],
        }

    # Seskupení findings podle kódu
    grouped: dict[str, list[Finding]] = {}
    for f in normalized:
        grouped.setdefault(f.code, []).append(f)

    actions: list[Action] = []

    for code, items in grouped.items():
        catalog_entry = ACTION_CATALOG.get(code)
        if not catalog_entry:
            continue

        goal_weight = goal_weights.get(code, 0)
        if goal_weight == 0:
            continue  # akce nesouvisí s cílem

        max_severity = max(
            (SEVERITY_SCORE.get(i.severity, 50) for i in items), default=50
        )
        total_count = sum(i.count for i in items)

        raw_priority = (
            catalog_entry["base_impact"] * goal_weight * max_severity
        ) / 10_000
        priority = int(round(raw_priority))

        impact_label = _impact_label(priority, total_count)

        actions.append(
            Action(
                action_id=f"{goal}::{code}",
                title=catalog_entry["title"],
                why=catalog_entry["why"],
                priority=priority,
                effort=catalog_entry["effort"],
                expected_impact=impact_label,
                steps=list(catalog_entry["steps"]),
                source_findings=[f"{code} (×{i.count})" for i in items],
                goal=goal,
            )
        )

    actions.sort(key=lambda a: a.priority, reverse=True)
    actions = actions[:max_actions]

    gaps = _detect_gaps(grouped, goal)
    summary = _build_summary(goal_meta, actions, gaps, business_mode)

    return {
        "goal": goal_meta["label"],
        "goal_key": goal,
        "actions": [a.to_dict() for a in actions],
        "summary": summary,
        "gaps": gaps,
    }


# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

def _impact_label(priority: int, count: int) -> str:
    if priority >= 75:
        level = "vysoký"
    elif priority >= 50:
        level = "střední"
    else:
        level = "nižší"
    if count > 1:
        return f"{level} (týká se {count} výskytů)"
    return level


def _detect_gaps(
    grouped: dict[str, list[Finding]], goal: str
) -> list[str]:
    """Vrátí seznam toho, co chybí k přesnějšímu plánu."""
    gaps: list[str] = []
    if not grouped:
        gaps.append("žádná data z auditu")
    if goal == "organic_traffic_growth":
        if "not_indexed" not in grouped:
            gaps.append("chybí kontrola indexace (Search Console)")
        if "weak_category_pages" not in grouped:
            gaps.append("chybí analýza obsahu kategorií")
    return gaps


def _build_summary(
    goal_meta: dict[str, Any],
    actions: list[Action],
    gaps: list[str],
    business_mode: str,
) -> str:
    if not actions:
        base = (
            f"Pro cíl „{goal_meta['label']}“ zatím nemám konkrétní kroky – "
            f"chybí mi relevantní findings z auditu."
        )
    else:
        top = actions[0]
        base = (
            f"Pro cíl „{goal_meta['label']}“ doporučuji začít akcí "
            f"„{top.title}“ (priorita {top.priority}/100, "
            f"očekávaný dopad {top.expected_impact}). "
            f"Celkem mám {len(actions)} kroků seřazených podle priority."
        )
    if business_mode == "shop":
        base += " Počítám s režimem e-shopu."
    elif business_mode == "lead":
        base += " Počítám s režimem lead-gen."
    if gaps:
        base += " Pro přesnější plán mi chybí: " + ", ".join(gaps) + "."
    return base


# ---------------------------------------------------------------------------
# CLI pro rychlé ověření (nepovinné, ale užitečné)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    demo_findings = [
        {"code": "missing_meta_description", "severity": "high", "count": 42},
        {"code": "not_indexed", "severity": "critical", "count": 8},
        {"code": "weak_category_pages", "severity": "medium", "count": 5},
        {"code": "slow_pages", "severity": "medium", "count": 3},
    ]
    result = suggest_actions_for_goal(
        goal="organic_traffic_growth",
        findings=demo_findings,
        project_context={
            "business_mode": "shop",
            "domain": "adrenalinerace.eu",
        },
    )
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))