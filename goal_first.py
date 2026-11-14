"""Goal-first, evidence-aware prioritisation for Boban.

Pure helpers: no API writes, no database access, no claims of completed work.
"""

_PRIORITY_BONUS = {
    "incident": 24, "strategy": 18, "blocker": 16, "approval": 14,
    "growth": 8, "measurement": 5, "performance": 0, "execution": -12,
}


def readiness_items(project_id, strategy, connector_states, snapshots, core_connected, has_real_outcome_records):
    """Request missing proof without confusing OAuth, snapshots and verified sales.

    A connected integration is a stored status, NOT a heartbeat or data proof.
    Missing records do not imply zero sales.
    """
    items = []
    if not core_connected:
        items.append({"priority": 97, "kind": "blocker", "title": "Ověřit Fresh Core",
                      "reason": "Bez funkčního Fresh Core nemohu bezpečně provádět změny webu. Stav připojení ještě není důkaz dostupnosti API.",
                      "owner": "spolu", "needs_user": True, "can_prepare": False,
                      "url": f"/projects/{project_id}/connectors"})
    for provider, label, priority in (("search_console", "Search Console", 89), ("ga4", "GA4", 88)):
        if snapshots.get(provider):
            continue
        stored = connector_states.get(provider) == "connected"
        items.append({"priority": priority, "kind": "blocker",
                      "title": ("Ověřit načtení dat " if stored else "Připojit ") + label,
                      "reason": (f"{label} je vedený jako připojený, ale nemám ani jeden uložený datový výstup. Ověř synchronizaci a případnou chybu." if stored
                                 else f"Chybí ověřitelná data z {label}; připoj zdroj, abych neplánoval jen podle domněnek."),
                      "owner": "spolu", "needs_user": True, "can_prepare": False,
                      "url": f"/projects/{project_id}/connectors"})
    conversion = str(strategy.get("primary_conversion") or "").lower()
    goal = str(strategy.get("business_goal") or "").lower()
    sales_goal = any(term in (conversion + " " + goal) for term in
                     ("purchase", "order", "objedn", "prodej", "nákup", "nakup", "obrat", "tržb", "trzb", "lead", "poptáv", "poptav"))
    if sales_goal and not has_real_outcome_records:
        items.append({"priority": 94, "kind": "blocker", "title": "Doložit skutečné konverze",
                      "reason": "Nemám žádný netestovací záznam skutečné objednávky či poptávky. Neznamená to nula prodejů. Pro vyhodnocení cíle potřebuji ověřený obchodní zdroj a období měření.",
                      "owner": "spolu", "needs_user": True, "can_prepare": False,
                      "url": f"/projects/{project_id}/results"})
    return items


def prioritized_items(items, strategy, limit=5):
    """At most five decisions; goal and known business focus outrank site-wide SEO hygiene."""
    goal = str(strategy.get("business_goal") or "").strip()
    topics = [str(x).lower() for x in (strategy.get("priority_topics") or []) if str(x).strip()]
    ranked = []
    for index, item in enumerate(items):
        kind = str(item.get("kind") or "")
        if not goal and kind not in {"strategy", "blocker", "incident", "approval"}:
            continue
        haystack = " ".join(str(item.get(k) or "") for k in ("title", "reason", "query", "primary_page")).lower()
        focus_bonus = 18 if topics and any(t in haystack for t in topics) else 0
        score = int(item.get("priority") or 0) + _PRIORITY_BONUS.get(kind, 0) + focus_bonus
        ranked.append((-score, index, item))
    ranked.sort()
    seen = set()
    result = []
    for _, _, item in ranked:
        key = (item.get("kind"), item.get("title"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def selected_work(plan):
    """Return only candidates shown in the plan; not permission to publish."""
    if not (plan.get("strategy") or {}).get("business_goal"):
        return set(), set()
    issues, growth = set(), set()
    for item in (plan.get("items") or []):
        if item.get("kind") == "execution" and item.get("can_prepare") and not item.get("needs_user"):
            issues.update(int(x) for x in (item.get("issue_ids") or []) if str(x).isdigit())
        if item.get("kind") == "growth" and item.get("can_prepare") and not item.get("needs_user"):
            growth.add(str(item.get("primary_page") or "").rstrip("/"))
    return issues, growth
