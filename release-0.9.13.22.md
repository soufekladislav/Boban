# Boban 0.9.13.22 – stabilní SEO fronta a společný chat

Základ: plná aplikace 0.9.13.21. Bez migrace databáze. Beze změn oprávnění, katalogových feedů nebo schvalovacích pravidel.

## Zjištění
- Předložený veřejný diagnostický manifest je **zastaralý** (`application_version=0.9.13.14`, generated_at `2026-11-08T15:24:07`). Neprokazuje aktuální stav SEO fronty.
- Na serveru byl z uživatelova výpisu potvrzen pouze minutový cron `catalog-sync`. Ten SEO pracovní frontu nezpracovává.
- V aktuálním kódu SEO úkoly zpracovává `process_seo_apply_jobs`, avšak spuštění z webu je jen best-effort `Popen`. Chybí potvrzená periodická záchranná cesta. Běžný `manage.py tick` spouští také těžké operace (audity, synchronizace, operator, katalogy), což není vhodné spouštět každou minutu bez omezení.

## Změny
1. `manage.py work-queue`: krátký jednotný SEO worker. Obnoví zatuhlé pracovní záznamy, převede starší a osiřelé úlohy, zpracuje **nejvýše 3** úlohy v jednom průchodu. Řeší existující job typy `seo_ai_prepare`, `seo_growth_prepare`, `seo_apply_action`, `seo_verify_action`. Neprovádí nové periodické crawlingy, katalog-sync, GA4/GSC, e-maily ani bez vyžádání nové obchodní plány.
2. `manage.py work-queue-status`: pouze čtecí diagnostika po projektech, typech úloh a stavech; bez payloadů a tokenů.
3. `seo_queue` heartbeat v databázi `workers`; veřejný bezpečný diagnostický manifest obsahuje jeho stav a celkové počty úloh, nikoliv jejich obsah.
4. Stránka **Úkoly** varuje, pokud čekají práce a SEO worker neodesílá aktuální odezvu. Oddělený heartbeat SEO workeru není zaměňován za katalog worker.
5. Výsuvný chat: srozumitelný stav odesílání, bezpečné načtení potvrzené historie, zachování konceptu při selhání, ošetření HTTP odpovědi bez JSON, detekce odhlášení, 90s hranice čekání. Po timeoutu doporučuje zkontrolovat historii před opakováním, aby se operátor nespustil dvakrát. Verze URL statických souborů změněna pro nucené obnovení cache.

## Nasazení
1. **Zálohujte** produkční adresář, DB a `.env`, případně publikované feedy. Rozbalte aktualizační ZIP do stávající aplikace bez přepsání `.env` a persistentních dat. Restartujte Passenger.
2. Ověřte jednorázově v terminálu:
   ```bash
   cd /home2/lauhannq/webbooster.freshcrackers.cz
   /home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py work-queue-status
   ```
3. Pro prvotní test spusťte **jediný omezený cyklus**:
   ```bash
   /usr/bin/flock -n /home2/lauhannq/webbooster.freshcrackers.cz/.seo-worker.lock /home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py work-queue
   ```
   Pozor: tento cyklus **opravdu převezme a vykoná** již schválené SEO zápisové úlohy z fronty. Pokud nemají být publikovány, nejprve je v UI zrušte/odložte.
4. Do `crontab -e` přidejte **jediný nový** cron (existující katalogový ponechte):
   ```cron
   * * * * * cd /home2/lauhannq/webbooster.freshcrackers.cz && /usr/bin/flock -n /home2/lauhannq/webbooster.freshcrackers.cz/.seo-worker.lock /home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py work-queue >> /home2/lauhannq/webbooster-seo-worker.log 2>&1 # BOBAN_SEO_WORKER
   ```
   **Nevkládejte duplicitní SEO cron**, pokud už se po kontrole `crontab -l` objeví. Běžný `tick` není touto aktualizací automaticky plánován.
5. Kontrola:
   ```bash
   /home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py work-queue-status
   tail -n 60 /home2/lauhannq/webbooster-seo-worker.log
   ```
6. V Úkolech založte **jeden návrhový** SEO úkol (nepublikační) a sledujte přechod `queued` -> `completed` / `failed`, chybu a upozornění. Dále otestujte výsuvný chat na Statistikách a na Úkolech, `Ctrl+F5`, jednu zprávu a historii po přechodu mezi stránkami.

## Bezpečnost a hranice
- Ani nový cron, ani výsuvný chat **neznamenají schválení externích změn**. Pravidla existujících typů úloh zůstávají zachována. Job `seo_apply_action` nicméně znamená již dříve zařazenou změnu k publikaci; při spuštění workeru se může skutečně zapsat. Tento worker se proto nesmí testovat bez kontroly fronty.
- Pravidelné objevování nových SEO problémů přes `tick` není tímto cronem zapnuto. Zatím funguje explicitně spouštěný operator a již připravené úlohy.
- Existující `kick_background_worker` zůstává pro rychlou odezvu, cron funguje jako opravdová záchranná cesta. Kombinace používá databázové claimování; cron používá `flock` proti vlastnímu souběhu.
- Pokud úloha opakovaně selže kvůli Fresh Core, právům nebo neplatné URL, worker nevymýšlí opravu; zaznamená chybu/retry a po limitu neúspěch. Bezpečné automatické řešení konkrétních typů chyb je samostatný vývoj.
- Nové ovládání chatu neřeší všechna potenciální selhání externího AI Engine; zobrazí je viditelně a zachová rozepsaný text.
- Zveřejněný diagnostický token doporučujeme po kontrole změnit. Nikdy nesdílejte `.env` ani tokeny Google.

## Testy
93 lokálních testů; Python compile; `node --check static/app.js`. Integrační běh cron + MariaDB + Passenger + Fresh Core vyžaduje ověření na serveru. V izolovaném prostředí není produkční DB ani Google/Fresh Core přístup.
