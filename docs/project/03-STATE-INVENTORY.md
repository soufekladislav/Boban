# BOBAN — inventura skutečného stavu k 16. 11. 2026

**Metodika:** „kód existuje“ ≠ „schválený release“ ≠ „nasazeno“ ≠ „produkčně ověřeno“ ≠ „přináší obchodní přínos“. Stav zjištěn z GitHub repozitáře `soufekladislav/Boban`, otevřených PR, existujících release dokumentů a předchozího diagnostického ZIPu. Nejde o nový živý přístup do cPanelu/DB.

## 1. Zdrojové větve / release

- **`main`**: `APP_VERSION = 0.9.13.24`, commit `de19ccc9e00026bc50c42e55fc594d8f1c4c54f5` při této inventuře.
- **PR #1:** `feature/goal-first-boban-20261113` → `main`, otevřený, nezávislý. Obsahuje `goal_first.py` a úpravy priorit podle obchodních cílů. **Není součástí PR #7.**
- **PR #2:** `fix/worker-daily-sync-progress-20261114` → `main`; nové oddělené crony/worker/health.
- **PR #3:** `feature/boban-autonomous-execution-eta-20261114` → větev PR #2; autonomní cyklus a ETA.
- **PR #4:** `fix/visible-task-ledger-20261114` → větev PR #3; názvy, data, přehled.
- **PR #5:** `fix/seo-target-recovery-task-labels-20261115` → větev PR #4; Fresh Core SEO 404 a názvy.
- **PR #6:** `feature/pinterest-catalog-feed-20261116` → větev PR #5; Pinterest feed.
- **PR #7:** `release/boban-unified-20261116` → `main`; konsoliduje **#2–#6 a další opravy**, ale **ne #1**.
- V době kontroly **žádné PR #1–#7 nebylo sloučeno**. CI testy PR #7 prošly; produkční provoz není prokázán.
- GitHub issues ke dni inventury: **0**, pouze PR položky v GitHub Issues API.

## 2. Funkční inventura

| Schopnost | Důkaz implementace | Co je potřeba ještě potvrdit | Stav |
|---|---|---|---|
| Projekty, role, sdílení, Fresh Key | `app.py`, `readme.md`, tabulky projektů a uživatelů | Ostré role, tokeny, správa přístupu | **V main, provoz neověřen** |
| Fresh Core čtení SEO/WordPress | `app.py`, `integrations.md` | Čerstvost dat / aktuální manifest / konkrétní cílové weby | **V main, provoz neověřen** |
| SEO crawl, nálezy, skóre | `app.py`, `architecture.md` | Pokrytí a správná interpretace URL, míra falešných nálezů | **V main, kvalita neověřena** |
| Search Console | OAuth, `sync_search_console`, GSC výkonnost | Oprávnění, poslední úspěšné načtení, zdraví API | **V main, provoz neověřen** |
| Google Analytics 4 | OAuth, `sync_ga4`, konverzní přehledy | E-commerce/poptávky a správná atribuce | **V main, měření neprokázáno** |
| GTM, PageSpeed/CrUX | Synchronizační a konfigurační kód v `app.py` | Živá data a oprávnění jednotlivých projektů | **Částečná implementace** |
| Google Merchant | `merchant_connector.py`, `merchant_export.py` | Vlastní API data, import/diagnostika a schválení produktů | **V main, provoz neověřen** |
| Heureka, Zboží.cz, Meta feedy | Exportéry, e-commerce UI, soubory `generated_feeds/` | Aktuální revize, validita a skutečné přijetí platformami | **V main, publikovaný soubor ≠ přijetí** |
| Pinterest | `pinterest_catalog.py`, UI a dokumentace jen PR #6/#7 | První XML, způsobilý Pinterest Business účet, import | **V PR, neověřeno** |
| AI návrhy a paměť | `call_fresh_ai_engine`, `advisor_intelligence.py`, `engine_runs` | Výsledná kvalita, náklady a vazba na obchodní výsledky | **V main, přínos neověřen** |
| Řízení podle cíle | `project_strategy`, `advisor_goal_actions.py`; `goal_first.py` jen PR #1 | Jeden jednotný model priorit a navázaná exekuce | **Rozděleno mezi main a PR #1** |
| Akce a revize, schválení | `actions`, `action_revisions`, `manage.py` | Jeden end-to-end provedený a ověřený zásah | **Kód v main, P0 neschváleno jako hotové** |
| Fronta a autonomní crony | `manage.py`, `worker_runtime.py`, `sync_schedule.py` v PR #2/#7 | Skutečné cPanel crony, heartbeat, retry, neduplikování | **P0 v PR, produkčně neověřeno** |
| Názvy, čas, důvody úloh | `job_monitor.py`, `execution_overview.py` v PR #3/#4/#7 | Ostré UI a skutečný posun | **P0 v PR, produkčně neověřeno** |
| Fresh Core SEO 404 | `FreshCorePermanentError`, URL payload v PR #5/#7 | Konkrétní cílový WordPress Core a úkol #1178 | **P0 v PR; externí plugin zvlášť** |
| Admin 500 | Jinja `job_monitor.items` → `['items']` v PR #7 | Nasazení/Passenger restart bez 500 | **Oprava v PR, produkčně neověřeno** |
| GitHub Desktop / LF crony | `.gitattributes` v PR #7 | Lokální i serverový LF, crontab konfigurace | **Oprava v PR, server neověřen** |
| PPC Google Ads/Sklik | Popis konektorů a `channel=ppc` | Autorizace, akce, schválení, výdajové limity a prokazatelné konverze | **Budoucí fáze P2, nikoliv hotová autonomie** |
| Obchodní dopad | `commerce_analytics.py`, `business_dashboard.py` | Plný zdroj pravdy pro objednávky/poptávky a příčinná vazba | **Datový základ existuje, důkaz přínosu neúplný** |

## 3. Zjištěné provozní incidenty a omezení

1. **Fresh Core HTTP 404 `fresh_core_seo_post`**: cílový WP post nenalezen / nepovolen. Samotné zavolání AI nic neřeší; oprava je v PR #5/#7, aktualizovaný WordPress plugin musí být nasazen samostatně.
2. **Admin HTTP 500**: chyba `job_monitor.items` na Jinja při skutečném vykreslení, zachycená v předchozím `stderr.log`; oprava v PR #7.
3. **CRLF shell skripty z Windows**: v předchozím ZIPu reprodukovaná chyba `pipefail\r`; `.gitattributes` v PR #7, cPanel nutno ověřit.
4. **Pinterest export**: nekompletní sync blokoval vytvoření RSS; PR #7 navrhuje fallback jen na schválený Google feed stejné revize. Zazipované starší produkty samy nedokazují aktuální stav DB.
5. **Nedůvěryhodný pohyb fronty:** čas poslední AI Engine odpovědi ≠ poslední dokončený SEO úkol. Potřebujeme end-to-end audit `jobs`/API/worker/cron.
6. **Rozpor automatizace:** vydání 0.9.13.24 doporučuje ponechat SEO cron vypnutý; nové PR jej chtějí zapínat. Bez provozního testu nelze automatické publikování považovat za bezpečné.
7. **Obchodní orientace:** PR #1 samostatně od PR #7, nutná integrace až po stabilitě.
8. **Potenciální správa a bezpečnost:** veřejný git repozitář obsahuje historicky soubory `generated_feeds/`, lock a `catalog_metadata/`. Vyžaduje inventuru veřejných feed URL/tokenů, oddělení produkčních artefaktů a strategie náhrady/rotace, ne automatické mazání.

## 4. Závěry o reálné produkci

**Prokazatelné:** obsah aktuálního `main`, přesné větve a změny PR, existující moduly, zapsané testy, předchozí log a artefakty.  
**Neprokazatelné z GitHubu:** co právě běží v Passenger, konfigurace cPanel cronu, aktivační stav Fresh Core na cílových WP webech, live dostupnost konektorů, úplná obchodní konverzní data, skutečné provedení schváleného zápisu.  
**Neznámé:** vnitřní stav GitHub Project #11 (současný GitHub konektor neumožnil tabuli načíst), aktuální produkční restart/otisky souborů.

Než prohlásíme P0 za hotové, musíme všechny tyto nedoložené kroky konkrétně ověřit na cílovém projektu bez hromadného zápisu.
