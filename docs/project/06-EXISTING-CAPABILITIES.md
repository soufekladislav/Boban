# Boban – mapa existujících funkcí (16. 11. 2026)

Tato příloha je soupis **již implementovaných schopností** v hlavní větvi `main` (auditováno z kódu `app.py` a souvisejících modulů).
Nevytváří nové požadavky ani nenahrazuje P0/P1 Issues. Stav `kód existuje` je doložen, **produkční funkčnost** je zatím potřeba individuálně ověřit.

## Evidence / co opravdu existuje

| Issue | Oblast | Důkaz implementace v main | Pracovní fáze |
|---|---|---|---|
| [#24](https://github.com/soufekladislav/Boban/issues/24) | Projekty, účty, role, Fresh Key | Registrace, projektové a přístupové routes v `app.py` | V kódu → provozní akceptace |
| [#25](https://github.com/soufekladislav/Boban/issues/25) | Fresh Core read a SEO snapshoty | `fetch_core_bundle`, `sync_core` | V kódu → ověřit online |
| [#26](https://github.com/soufekladislav/Boban/issues/26) | SEO crawl, audit, scorecard | `crawler_audit`, `seo_scorecard` | V kódu → test kvality |
| [#27](https://github.com/soufekladislav/Boban/issues/27) | Google Search Console | OAuth, `sync_search_console` | V kódu → otestovat vlastnosti |
| [#28](https://github.com/soufekladislav/Boban/issues/28) | Google Analytics 4 | `ga4_run_report`, `sync_ga4` | V kódu → otestovat GA4 |
| [#29](https://github.com/soufekladislav/Boban/issues/29) | GTM | `gtm_accounts`, `sync_gtm` | V kódu → prověřit |
| [#30](https://github.com/soufekladislav/Boban/issues/30) | PageSpeed / CrUX | `sync_pagespeed_crux` | V kódu → prověřit |
| [#31](https://github.com/soufekladislav/Boban/issues/31) | Fresh AI Engine + chat historie | `call_fresh_ai_engine`, chat routes | V kódu → E2E test |
| [#32](https://github.com/soufekladislav/Boban/issues/32) | Cíle, dashboard, doporučení | `project_goals`, `business_dashboard.py` | V kódu → ověřit baseline |
| [#33](https://github.com/soufekladislav/Boban/issues/33) | Woo katalog / varianty / pravidla | `feed_workflow.py`, `catalog_cached_data` | V kódu → otestovat úplnost |
| [#34](https://github.com/soufekladislav/Boban/issues/34) | Google produktové XML / Merchant | `merchant_export.py`, `merchant_connector.py` | V kódu → ověřit přijetí |
| [#35](https://github.com/soufekladislav/Boban/issues/35) | Heureka + Zboží.cz XML | `heureka_export.py`, `zbozi_export.py` | V kódu → ověřit formáty |
| [#36](https://github.com/soufekladislav/Boban/issues/36) | Meta produktový katalog | `meta_export.py` | V kódu → ověřit import |
| [#37](https://github.com/soufekladislav/Boban/issues/37) | SEO návrhy a schválení | `actions`, `action_revisions` | V kódu → prověřit revize |
| [#38](https://github.com/soufekladislav/Boban/issues/38) | Statistiky a výsledky | `commerce_analytics.py`, `business_dashboard.py` | V kódu → ověřit zdroje |

## Rozlišení od pracovního backlogu

- Issues **#9–#15** nejsou duplicitou: řeší incidenty, stabilitu a provozní důvěryhodnost.
- Issues **#16–#22** řeší budoucí obchodní funkčnost, ne přítomnost pomocného kódu.
- Issues **#24–#38** slouží jako *inventura existujících schopností*. Po individuálním akceptačním testu lze přesunout do `Done`.
- Pinterest je ve vývojové větvi PR #6/#7, **není** v `main`, proto není přidán mezi tyto již implementované schopnosti. Jeho stav řeší #15.
- Automatický worker a jeho novější UI jsou ve vývojových PR, proto ani ty neoznačujeme za hotové.

## Doporučené převedení do Project #11

Projektový limit `In review` je podle snímku nastaven na **5 položek**. Proto nedávat všech 15 najednou do Review. Praktický postup:

1. Zaveď nové Issues #24–#38 do tabule pomocí `Add item` nebo nastaveného Auto-add.
2. V první várce prověř **#24, #25, #26, #27, #31**. Až těchto pět skutečně projde testem, přesuň jednotlivé do `Done`.
3. Druhou várku **#28, #29, #30, #32, #38**, třetí **#33–#37**.
4. Při chybě vrátit položku do `Backlog` / `Blocked` a navázat konkrétní P0 Issue, ne prohlásit za dokončenou.

**Důležité:** GitHub Issue `closed` je odlišné od pole `Status = Done` v GitHub Project #11. Jeden stav neimplikuje druhý.

## Ověřitelnost

Aktuální stav `main` je doložitelný GitHub kódem; není doložena skutečná verze na Passenger/cPanel. Založení Issues nemění produkci ani automatizační crony. Pro uzavření je požadována evidence testu v těle Issue.
