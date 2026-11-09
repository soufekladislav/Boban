# Boban 0.9.10 – stabilizace katalogové fronty

## Proč se import zastavil
Manifest 0.9.9: 100/4258 produktů, 50/1946 variant; režim running bez chyby, poslední heartbeat výchozího workeru z předchozího dne. Plánovač nejspíš není spouštěn. Zda dochází k dalším chybám, musí potvrdit nový manifest a logy.

## Změny
- Ovládání Spustit/pokračovat, Pozastavit, Spustit dávku nyní, Založit novou frontu (s potvrzením).
- Start/obnova vyvolá jednorázový proces catalog-sync; spolehlivé pravidelné pokračování vyžaduje cron.
- Nová fronta vyčistí jen pracovní katalogové cache a kurzory. Neodstraňuje vyloučené kategorie ani již publikovaný XML feed.
- Přehled samostatné aktivity catalog workeru v diagnostickém manifestu.
- Chybějící přístup již neponechá workflow falešně ve stavu running.

## Serverový cron (NEZBYTNÉ)
V cPanel Cron Jobs nastav každou minutu příkaz s **absolutními cestami** k Pythonu dané Passenger virtuální instalace a souboru manage.py:
```
* * * * * /ABSOLUTNI/CESTA/K/VENV/bin/python /ABSOLUTNI/CESTA/K/WEBBOOSTER/manage.py catalog-sync >> /ABSOLUTNI/CESTA/K/WEBBOOSTER/catalog-cron.log 2>&1
```
Použij skutečné cesty hostingu; příkaz uvedený výše je šablona, ne hotový provozní příkaz. Pro prvotní test jej spusť přes SSH jednou ručně. Nastav, aby cron neběžel ve více kopiích.

## Ověření
1. Záloha aplikace, .env a MariaDB. Nahraj kompletní ZIP, přenes produkční .env, restartuj Passenger.
2. Klikni Spustit/pokračovat. Po minutě obnov stránku: počet produktů >100 nebo zjevná chyba.
3. V diagnostickém manifestu ověř `scheduler.catalog_worker.last_seen` (nový heartbeat).
4. Není-li změna, ověř `catalog-cron.log`, `worker.log` a správnou cestu k venv.
5. Pozastavit zamezí zahájení nových dávek, ale právě rozpracovaný HTTP požadavek může doběhnout.

**Pozor:** Neprovádí se žádný živý test na serveru. Kontrola PHP/DB/Fresh Core v reálném běhu zbývá.
