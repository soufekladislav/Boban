# Boban WebBooster 0.9.13.17 — Obchodní statistiky a datová základna

## Obsah změny

**Rozsah:** sběr a bezpečné ukládání dostupných marketingových dat + přepracování stránky Statistiky. Neřeší autonomní plánování, chatové analytické nástroje, zveřejňování změn ani nákladové ceny; existující společný výsuvný chat z verze 0.9.13.16 zůstává zachovaný.

### Čtyři nové datové tabulky (automatická idempotentní migrace)

1. `analytics_sync_runs` – zdroj, období, čas, počet zaznamenaných pozorování, výsledek synchronizace; kompatibilita SQLite/MariaDB.
2. `analytics_observations` – časově a zdrojově označené metriky se strukturovanými dimenzemi a idempotentním unikátním klíčem; oddělení 28denních agregací od denních pozorování.
3. `analytics_business_outcomes` – připravené čtecí úložiště skutečných objednávek/poptávek, stavů a případné atribuce; eviduje `test_record` (true/false/unknown), žádné kontaktní nebo platební údaje zákazníků. **Zatím bez aktivního plnění Woo/CRM!**
4. `analytics_entity_links` – mapování produktů/služeb mezi externími identifikátory a společnou entitou; zatím bez automatického párování.

**Zachováno:** `source_snapshots`, `search_performance`, `metric_points`, celý katalog, konektory a stávající obchodní procesy. Ani jedna původní tabulka se nemaže.

### Automatický sběr

- GA4 – stávající přehledy, kanály, zdroje, země, zařízení, kampaně, nákupní události, produkty + **denní kanálové hodnoty a vstupní stránky**. Historické zdrojové snímky se nyní normalizují do `analytics_observations`.
- Search Console – současné dotazy, stránky, jejich kombinace a denní vývoj; zachovává období, takže dotazy za 28 dní nejsou vydávány za denní data.
- Google Merchant – již existující read-only metoda pro report **neplacených produktových výpisů** (zobrazení/kliknutí). Pravidelný běh nejvýše 1× denně na projekt; po chybě opakování nejdříve za 6 hodin. Výsledek zůstává v konfiguraci konektoru a zapisuje se do `analytics_observations`. Neprovádí fetch produktového XML.
- Meta, Heureka a Seznam – čtení uloženého stavu feedu/konektorů a přímé odkazy. **Výkonnostní API pro tyto platformy ještě nejsou nově zprovozněná.** Počet vygenerovaných nabídek není prodej ani návštěvnost.
- WooCommerce – současný Fresh Core záměrně neposkytuje objednávky; žádný neověřený odhad objednávek, poptávek, opuštěných košíků ani marží. Pro budoucí obchodní výsledky je připravené schéma.

### Stránka Statistiky

- Manažerské KPI: GA4 relace a organická návštěvnost; objednávky a poptávky jen při skutečně dostupném datovém zdroji.
- Pro e-shop: návštěvy → `view_item` → `add_to_cart` → `begin_checkout` → skutečné objednávky; metriky jsou označené jako události, nikoli unikátní zákazníci.
- Pro poptávkový web, pokud má projekt `primary_conversion` např. `lead`, `generate_lead` nebo `form_submit`: návštěva → zájem o služby (zatím neměřeno) → `form_submit` → `generate_lead` → potvrzená poptávka (zatím neměřeno).
- Opuštěné košíky a checkouty jako **neměřeno**, včetně vysvětlení, proč nelze určit jejich počet odečtením nesrovnatelných událostí.
- Kanály/zdroje, klíčové dotazy, produkty, vstupní stránky, katalogové stavy, odkazy do GA4, Search Console, Merchant, Meta, Skliku a Heureky.
- Zachovány styly, Poppins, responzivní layout a globální chat z 0.9.13.16; detaily v rozbalovacích tabulkách, tabulky uvnitř své karty scrollovatelné na mobilu.

## Bezpečné nasazení

1. Zálohuj produkční databázi, aplikaci, `.env`, katalogové feedy a případné připojené soubory. Aktualizační ZIP **neobsahuje `.env` ani živé obchodní údaje**.
2. Rozbal ZIP přes existující instalaci 0.9.13.16, **neodstraňuj** stávající produkční soubory, `.env`, `generated_feeds`, zámky workerů ani data.
3. Restartuj Passenger. Při prvním importu aplikace se idempotentně vytvoří 4 nové tabulky. Jestli už vlastní migrace Bobana používají zvláštní provozní pravidla, testuj nejdříve na kopii databáze.
4. Vyzkoušej návštěvu `Projekty → Statistiky`, kontrolu GA4 a GSC a výsuvný chat z ostatních projektových stránek.
5. Pro převod nejnovějších historických snapshotů GA4 a GSC do nové tabulky (bez API volání) proveď **jednou**:

```bash
cd /home2/lauhannq/webbooster.freshcrackers.cz
/home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py analytics-backfill
```

6. Ověř jeden skutečný read-only běh:

```bash
/home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py analytics-sync
```

7. Ponech stávající `catalog-sync` beze změny. Pokud analytický cron zatím není v crontabu, přidej **jen jeden** nový řádek (předtím `crontab -l`):

```cron
15 * * * * cd /home2/lauhannq/webbooster.freshcrackers.cz && /usr/bin/flock -n /home2/lauhannq/webbooster.freshcrackers.cz/.analytics-cron.lock /home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py analytics-sync >> /home2/lauhannq/webbooster-analytics-cron.log 2>&1 # BOBAN_ANALYTICS_SYNC
```

Souhrnný `manage.py tick` **nezapínej** jako náhradu analytického cronu, pokud nechceš současně spouštět operátora a obsluhu SEO fronty. V této etapě je záměrem pouze čtení.

## Co je potřeba v následné etapě

- Samostatný agregovaný WooCommerce/Fresh Core read-only endpoint pro objednávky a jejich stav, bez osobních údajů. Oddělení testovacích objednávek musí být explicitní a ověřitelné.
- Read-only evidence a kvalifikace poptávek pro firemní weby (např. potvrzené formuláře/CRM).
- Opuštěné košíky: samostatné WooCommerce měření s identitou košíku, časem aktivity a spojnicí na objednávku; bez osobních údajů.
- Rozšíření Meta / Seznam / Heureka výkonnostních API podle existujících oprávnění a obchodních možností.
- Analytické nástroje pro chat a následné doporučování; samostatně až po ověření spolehlivosti dat.

## Lokální kontrola

- `python -m py_compile app.py manage.py commerce_analytics.py` — OK.
- Jinja parser všech stávajících šablon — OK.
- `python -m unittest discover -s tests -q` — 77 testů OK (zahrnuje pět nových testů datového modelu).
- Živá MariaDB a Google/Meta API v tomto prostředí nejsou k dispozici, proto **nebyl** ověřen produkční import ani skutečné objednávky.
