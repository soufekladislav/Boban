# BOBAN — projektová dokumentace

**Datum revize:** 2026-11-16  
**Repo:** https://github.com/soufekladislav/Boban  
**GitHub Project:** https://github.com/users/soufekladislav/projects/11

## Jak číst dokumentaci

1. [01 — Obchodní zadání a produktový kontrakt](01-BUSINESS-BRIEF.md): proč Boban existuje, cíle klientů, role agentů a schvalování.
2. [02 — Architektura a workflow](02-ARCHITECTURE-AND-WORKFLOW.md): vrstvy aplikace, konektory, fronty, bezpečný end-to-end cyklus a provoz.
3. [03 — Inventura skutečného stavu](03-STATE-INVENTORY.md): co je v main, co v PR, co není produkčně potvrzeno a co je rizikové.
4. [04 — Roadmap a pravidla řízení](04-ROADMAP-GOVERNANCE.md): P0/P1/P2, standard Issues, Definition of Done, práce s GitHub Project #11.
5. [05 — Issue register a Project #11](05-ISSUES-BOARD.md): konkrétní pracovní backlog, závislosti a evidence všech PR #1–#7.
6. [06 — Inventura existujících funkcí](06-EXISTING-CAPABILITIES.md): 15 realizovaných oblastí s odkazy na nové Issues #24–#38 a testovací kritéria.
7. [Původní architektura](../../architecture.md), [integrace](../../integrations.md), [roadmap 0.7–0.8](../../roadmap-0.7x-0.8.md): historické zdroje; technické detaily je nutné ověřovat v aktuální větvi.
8. [Dokumentace sjednoceného release (PR #7)](https://github.com/soufekladislav/Boban/blob/release/boban-unified-20261116/docs/UNIFIED-DEPLOY-2026-11-16.md): konkrétní dosavadní chyby, verze, deploy.
9. [PR #1 — Goal First](https://github.com/soufekladislav/Boban/pull/1): samostatná obchodní logika, není součástí PR #7.

## Závazný slovník stavu

- **Navrženo** – zapsaný cíl / specifikace, ale bez implementace.
- **Kód existuje** – zdrojové soubory jsou dostupné v určené větvi.
- **Ověřeno CI** – testy prošly na konkrétním SHA.
- **Sloučeno** – změna je součástí `main`.
- **Nasazeno** – je doložený fingerprint souborů a restart běžící aplikace.
- **Provozně ověřeno** – skutečná cesta přes službu a data prošla, včetně neúspěšných scénářů.
- **Obchodně ověřeno** – potvrzená změna zákaznické metriky s popsanými limity atribuce.

Zkratka „hotovo“ je povolená pouze v rámci explicitně pojmenované úrovně. Např. „CI hotovo, produkce neověřena“.

## Vývojová pauza

**Nyní nepřidávat funkce.** Nejdřív P0 provozní akceptace a teprve pak P1 strategie. Konkrétní GitHub Issues jsou závazný pracovní backlog. Nepřeskakovat kontrolu nasazené verze a bezpečnosti externích zápisů.

## Úlohy a Project board

Pro každý důležitý problém je GitHub Issue. Otevřené PR #1–#7 jsou **vývojové artefakty, ne potvrzené výsledky**.

Připojení Issues do Project #11 musí být ověřené v GitHub Projects; aktuálně přístupné konektorové akce umí vytvářet repo Issues, ne spravovat položky Projects V2.
