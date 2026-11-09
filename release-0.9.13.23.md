# Boban 0.9.13.23 – stabilizace pouze chatu a SEO fronty

## Opraveno
- Příčina prázdného výsuvného chatu: `renderAssistantBubble` a `chatTimeElement` byly definované v samostatném IIFE, zatímco drawer je volal mimo jeho scope. Sdílený bezpečný renderer je nyní explicitně vystaven pro drawer.
- Opraveno okamžité načítání stavu konverzace; odesílání používá stávající projektový endpoint, bez druhé historie.
- `work-queue` nyní rozlišuje **attempted** od dokončení; ukazuje stav fronty před/po a splatné/odložené retry. `work-queue-status` nyní ukazuje konkrétní čekající job ID, počet pokusů a plán dalšího retry (bez payloadů).
- Volitelný instalační skript cronu je explicitní a idempotentní, nic se nezapíná samotným nahráním ZIP.

## Bezpečný postup nasazení
1. Zálohuj původní aplikaci a databázi. Zachovej .env, logy, média a data mimo ZIP.
2. Nahraj balíček přes existující soubory, restartuj Passenger, dej Ctrl+F5.
3. Nejdříve otestuj výsuvný chat na Úkolech a Statistikách; zkontroluj historii a odeslání jedné zprávy.
4. Spusť pouze read-only diagnostiku: `python manage.py work-queue-status`.
5. Před zapnutím cronu zkontroluj čekající *schválené* změny. Pokud je chceš vykonávat, spusť `bash scripts/install_seo_worker_cron.sh`. Tento krok změní crontab a může způsobit zápisy schválených akcí na web. Nezapínej, pokud nechceš publikovat připravené zásahy.
6. Zkontroluj `crontab -l | grep BOBAN_`, potom `tail -n 50 /home2/lauhannq/webbooster-seo-worker.log` a `python manage.py work-queue-status`.
7. Dokončení nevyvozuj z `attempted=3`; zkontroluj přechod stavu daných ID, `run_after`, počet pokusů a konkrétní chybový stav v aplikaci.

## Omezení
- Žádné produkční SSH a databázové testy neproběhly. Cron se nenastavil automaticky.
- Neřeší se nové SEO strategie, AI instrukce, Merchant, GTM ani další funkcionality.
- Výsuvný chat je opraven na základě prokázané JavaScript chyby; vyžaduje ověření na nasazené stránce.
