# Boban / WebBooster 0.9.8 – Catalog Workflow

Zdroj: přímo z uživatelem nasazené verze `boban(2).zip` (0.9.7). **Bez změny pluginu Fresh Core** a bez zásahu do dosavadních SEO či účetních oprávnění.

## Co přibylo

- `feed_workflow.py` – samostatná deterministická doménová logika pro pozdější převod vlastnictví katalogu na Viki. Nepoužívá AI ani API klíče třetích stran.
- Nové tabulky `catalog_workflows` a `catalog_exclusions` (automaticky vytvořené při startu, obsah dosavadních tabulek se zachová).
- Záložka **E-commerce** – stav importu, návrh výběru kategorií a produktů/variant, manuální schválení, interval, Google XML a validační výpis.
- Režimy `idle`, `running`, `review`, `paused`, `active`; při chybě se uloží informace a další zpracování se pozastaví.
- Plánovač Bobana (`python manage.py tick`) pokračuje v krátkých dávkách a navazuje na poslední stránku; navíc lze vyvolat `python manage.py catalog-sync`.
- Výjimky pro kategorie a konkrétní produkty či varianty jsou v DB a přežijí synchronizaci. Vyloučení kategorie má přednost bez ohledu na ostatní přiřazené kategorie a zahrnuje známé podkategorie.
- Pro publikaci je nutný **kompletní snapshot a explicitní schválení**. Publikovaný feed se přepíše až po úspěšném sestavení nového XML. Není připojeno Merchant API.
- Po schválení se feed obnovuje v nastaveném intervalu z čerstvě načteného celého katalogu. Stávající publikovaný XML zůstává při přerušení či chybě dostupný.

## Instalace

1. Zálohovat databázi, aplikaci a `.env`, zejména stav připojení a existujícího Merchant feedu.
2. Do nového adresáře nahrát kompletní balíček; zachovat produkční `.env` a nastavení Passenger. **Nemažte stávající databázi ani adresář s `generated_feeds` bez jeho zkopírování.** Pokud je adresář konfigurován absolutní cestou v `CATALOG_FEED_DIR`, tu ponechat.
3. Restartovat aplikaci; při startu se vytvoří dvě nové tabulky. Bez migrace/starého smazání.
4. Ověřit stránku E-commerce a stávající katalogové čtecí oprávnění Fresh Core.
5. Kliknout **Spustit / pokračovat automaticky**. Zajistit, že je v cPanel/Passenger provozním prostředí nastaven **opakovaný cron** `python /cesta/k/boban/manage.py tick` nebo `python /cesta/k/boban/manage.py catalog-sync` (např. 1× za minutu). Bez serverového cronu není automatické pokračování funkční. Dávky jsou omezeny stávajícími `COMMERCE_*` parametry.
6. Po načtení celého sortimentu ručně vyloučit nežádoucí kategorie a položky. Zkontrolovat návrh a kliknout **Schválit sortiment a připravit export**. Následující běh plánovače publikuje Google XML.
7. Až po kontrole exportu přidat veřejnou URL do Google Merchant Center jako zdroj dat. Publikace XML **není** schválení produktů Googlem.

## Důležité provozní limity

- Synchronizace je aktuálně **periodický stránkovaný snapshot**, nikoliv přímá událostová synchronizace změn v reálném čase. Při dokončení nového průchodu odstraní zastaralé položky z interní kopie. Požadavky jsou krátké, nicméně skutečnou zátěž PHP/MariaDB je nutné změřit na hostingu.
- Výběr kategorií vychází z kategorií zaznamenaných u načtených produktů. Úplný strom prázdných kategorií vyžaduje později kategorizační endpoint Fresh Core. Související podkategorie se vyřazují, pokud je jejich vztah ve zdroji známý.
- Zatím jde o **jeden společný výběr sortimentu**; specifické výjimky jednotlivých kanálů, Heureka/Zboží/Meta adaptéry a API konektivita jsou další etapy.
- Při chybě se synchronizace **pozastaví** a pokračuje na manuální obnovení; neprovádí automatické neomezené pokusy. Pro plně autonomní opravy chyb je potřeba klasifikace chyb a řízené retry.
- Při změně produktových či kategoriálních pravidel schválení zanikne; dříve publikovaný feed zůstává zachovaný do nového schválení a publikace. Pokud chceš produkty okamžitě stáhnout z veřejného feedu, je třeba zavést nouzové stažení/disable kanálu.
- Feed zatím používá stávající mapper `merchant_export.py`: názvy, URL, popisy, ID/SKU, ceny, sklady, fotografie a část identifikátorů. Data o cenách a skladech pocházejí z WooCommerce přes Fresh Core.
- Migrační princip: `feed_workflow.py` a jeho tabulky se později přesunou do Viki, Boban i Linda budou číst katalogové stavy a přehledy přes Fresh Key. Tato verze ještě žádné Fresh Key katalogové API nevystavuje.

## Ověření při přípravě

- Syntaktické kontroly Pythonu a HTML/Jinja.
- Jednotkové testy persistence a filtrování kategorií, výjimek variant a příkladu generování Google XML.
- Nebylo provedeno živé volání Fresh Core, test s produkční MariaDB, integrace se serverovým cronem ani přijetí XML službou Google Merchant.
