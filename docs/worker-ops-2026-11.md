# Boban – spolehlivý worker a synchronizace v 05:00 (14. 11. 2026)

## Bezpečné nasazení

1. Předem zálohuj adresář, databázi a produkční `.env`. Nemaž logy ani katalogové soubory.
2. Nahraj soubory z této větve a restartuj Passenger. `daily_sync_state` se vytváří aditivně.
3. Ověř `python manage.py doctor` a `python manage.py work-queue-status`. Pro přesnou cestu k Pythonu v cPanelu použij existující virtualenv, případně nastav `WEBBOOSTER_PYTHON`.
4. Nejdřív vyzkoušej jeden schválený SEO úkol ručním `python manage.py work-queue`. Teprve po ověření zapni minutový cron.
5. V cPanelu přidej samostatný `daily-sync` každých pět minut. Přestože příkaz běží během dne, data stáhne **nejdříve po 05:00 Europe/Prague**, úspěšně pouze jednou za místní den na zdroj.
6. Přidej samostatný read-only příkaz `connector-heartbeat` jednou za 15 minut. Ověřuje dostupnost Fresh Core, Search Console, GA4 a GTM bez stahování statistických sestav. Úspěch či chyba se ukládá odděleně od denních dat.\n7. **Vypni staré duplicitní crony** `tick`, `seo-apply`, `analytics-sync`. Pokud máš samostatný katalogový cron, ponech ho.

Vzorové dva záznamy včetně cest získáš:
```bash
bash scripts/install_seo_worker_cron.sh
```
Tento skript nic do cronu automaticky nezapisuje. Příkazy provádí `scripts/run_boban_cron.sh`.

## Ruční příkazy

```bash
python manage.py work-queue
python manage.py daily-sync --force --project 3 --provider ga4
python manage.py daily-sync --force
python manage.py work-queue-status
python manage.py work-queue-errors 3
```

- `work-queue` pracuje nejvýše se třemi úlohami v jednom průchodu, další zpracuje cron. Používá společný souborový lock `.seo-worker.lock`, takže ruční klikání nespustí víc souběžných zápisů.
- `daily-sync` má samostatný lock `.daily-sync.lock`, tabulku `daily_sync_state` a samostatný výsledek pro každý zdroj. Neúspěšný zdroj může být opakován nejdříve po 45 minutách.
- Ruční operace přes UI vytváří proces na pozadí, nikoliv dlouhý HTTP požadavek. Požadavek na start **není** důkaz dokončení. Stav je vidět v Úkolech nebo Konektorech.
- Worker aktualizuje DB lease právě běžící úlohy každých 10 s. Ostatní úlohy zůstávají `queued`, dokud na ně skutečně nepřijde řada.
- `completed` u technické úlohy neznamená, že je ověřen obchodní dopad. Schvalování SEO zápisů zůstává stejné.

## Co je potřeba ověřit na ostré aplikaci

1. V Úkolech při manuálním startu sleduj ID a stav konkrétního jobu i čas posledního heartbeat.
2. Vyvolej dva souběžné manuální starty: druhý se musí bezpečně vyhnout již běžícímu procesu.
3. Nech proběhnout ranní synchronizaci: GA4/GSC/GTM/Core/PageSpeed ukážou jednotlivé stavy. Jeden nefunkční konektor nesmí blokovat ostatní.
4. Pokud některé API bude hlásit chybu, vyhledej důvod ve `worker.log`, `queue_cron.log`, `daily_cron.log` a v `work-queue-errors`.
5. Bez produkčních logů a skutečného zkušebního zápisu nelze potvrdit, že původní chyba konektoru již neexistuje.

## Omezení a návrat

Souborový `flock` chrání procesy běžící na stejném hostu; pro více serverů by byla nutná databázová distribuovaná synchronizace. Nová struktura je aditivní. Při problému vrať zdrojové soubory ze zálohy, zachovej DB a `.env`; odstraň jen nové cron záznamy a obnov předchozí ověřené plánování.
