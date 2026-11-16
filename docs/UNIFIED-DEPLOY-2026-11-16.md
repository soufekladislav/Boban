# Boban – sjednocené nasazení z GitHub Desktop a oprava Pinterestu (16. 11. 2026)

## Co bylo ověřeno z boban(1).zip

1. Obsah ZIPu je (po normalizaci CRLF -> LF) shodný se všemi 14
   kontrolovanými klíčovými soubory větve
   `feature/pinterest-catalog-feed-20261116`.
2. Větev `main` v okamžiku auditu **neměla** úpravy z otevřených PR #2–#6.
   GitHub Desktop přepíná a synchronizuje pouze zvolenou větev; neprovádí
   sám nasazení do Passenger na Exonu.
3. Přiložený `stderr.log` obsahuje opakované 500 na `/admin` dne
   16. 11. 2026 12:41: `TypeError: 'builtin_function_or_method' object is not iterable`
   ve `templates/partials/job_ledger.html`. Opraveno
   `job_monitor.items` -> `job_monitor['items']`, přidán render test.
4. Zazipované shellové crony mají Windows CRLF a na Linuxu selhávají:
   `set: pipefail\\r: invalid option name`. Nové
   `.gitattributes` má `*.sh text eol=lf`. Po nasazení ověřit LF i
   **na serveru**, ne jen ve vzdáleném repozitáři.
5. Katalog Pinterestu v ZIPu není publikovaný. Dosavadní export odmítal
   nekompletní import produktů/variant, i když existovalo starší Google XML.
   Z projektu 3 v ZIPu lze bezpečně převést již vytvořený Google feed
   s 5 604 položkami, nicméně zveřejnit jej smíme **jen** tehdy,
   když aktuální `catalog_workflows.approved=1` a
   `published_revision=revision`.
6. ZIP neobsahuje databázi ani konfiguraci skutečného cPanel cronu.
   Nelze z něj potvrdit aktuální schválení katalogu nebo běh cronu.

## Jednoznačný postup s GitHub Desktop

**Doporučeno po schválení a sloučení tohoto jediného PR do main:**

1. Před nasazením zazálohovat produkční databázi a `.env`, existující
   `generated_feeds/`, `catalog_metadata/` a logy.
2. V GitHub Desktop vybrat repository `Boban` (ověřit
   `Repository → Show in Explorer`, že jde o správný místní adresář).
3. Nahoře `Current Branch → main`. Nezůstávat na
   `feature/pinterest-catalog-feed-20261116`.
4. Kliknout `Fetch origin`, potom `Pull origin`. To aktualizuje
   **lokální disk z online main**. Nemění to server na Exonu.
5. Ověřit, že soubory `app.py`, `pinterest_catalog.py`,
   `templates/partials/job_ledger.html`, `templates/ecommerce.html`
   a `.gitattributes` jsou po stažení ve správném místním adresáři.
   U `scripts/*.sh` musí být konce řádků **LF**.
6. Samostatně nasadit zdrojové soubory na Passenger/Exon a restartovat
   Python aplikaci. **Nezapisovat přes produkční .env, databázi,
   `generated_feeds/`, `catalog_metadata/`, `sync_locks/`,
   `stderr.log` a `worker.log`**. V repozitáři jsou některá
   runtime data historicky sledovaná, takže nepoužívat slepé přepsání
   celého serverového adresáře.
7. V přihlášeném administrátorském účtu otevřít:
   `https://webbooster.freshcrackers.cz/admin/deployment/status`
   Tento JSON nevyužívá šablony administrace. Vrací
   `files` s Git-bloby souborů na serveru a `shell_scripts`
   s LF/CRLF. Porovnat s GitHubem; číslo `APP_VERSION` samo nestačí.
8. Po restartu ověřit `/admin`, Úkoly a E-commerce bez chyby 500.

## Proč nejde sestavit Pinterest XML

Po nové úpravě se u tlačítka **Připravit Pinterest XML** zobrazí
skutečný důvod, proč je nedostupné:
- Sortimentu nebylo uděleno schválení: schválit v E-commerce.
- Neúplný import a neexistující Google XML stejné schválené revize:
  opravit import / dokončit schválený Google export.
- Import není dokončen, ale poslední publikovaný Google feed je
  ze stejné schválené revize: **nově lze přímo převést tento existující
  Google XML do Pinterest RSS**, bez dalšího WooCommerce importu.
- Pokud jde o nevalidní XML, nejsou validní produkty nebo chybí
  soubor na serveru, zobrazí se konkrétní chyba; stávající Pinterest
  feed se atomicky nepřepíše chybným obsahem.

Po vytvoření ověřit HTTP 200 a skutečná XML data na generované
`/catalog/pinterest/{token}.xml`. Katalog se pak zadá jako URL
do Pinterest Business; Boban zatím **nemá API potvrzení od Pinterestu**.

## Důkaz fungující automatizace

GitHub Desktop, průchod Python testů a existující soubor workeru nestačí.
Zkontroluj v cPanelu přímé cron příkazy (nebo opravený LF runner):
- `python manage.py work-queue` každou minutu;
- `python manage.py daily-sync` každých 5 minut (přes denní bránu 05:00);
- `python manage.py connector-heartbeat` každých 15 minut;
- `python manage.py boban-cycle` každých 15 minut.
Příkazy musí použít **Python existujícího virtualenv** a absolutní cestu
k `manage.py`. Příslušné logy a čerstvé dokončené joby potvrzují běh,
nikoli samotná přítomnost souboru.

## Důležité omezení

Tato oprava byla připravena do release větve a otestována, ale
**nemění automaticky online cPanel ani lokální GitHub Desktop**.
Kód na GitHubu, místní disk a běžící Passenger jsou tři samostatná místa.
