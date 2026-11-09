# Boban WebBooster 0.9.13.24 – stabilizace (úkoly a chat)

Vychází ze skutečné zálohy `boban(7).zip` (nasazená 0.9.13.23). Do zálohy byly doplněny čtyři chybějící zdrojové moduly ze zdrojů předchozího vydání: `advisor_intelligence.py`, `business_dashboard.py`, `commerce_analytics.py`, `sync_reporting.py`. Samotné moduly nejsou funkčně upravované.

## Opravy

- `queue_seo_apply_jobs`: nespouští duplicitní práci nad stejnou akcí, pokud čeká ve stavu `retry`; nepřepisuje `group_id` existujících úloh; hlášení správně rozlišuje zařazení do fronty od prokazatelného dokončení; potvrzení okamžitého startu procesu není důkaz dokončení.
- `actions`: doplňuje poslední chybu uloženou v `actions.last_error`, případně z výsledku posledního chybového/retry jobu. Chyba je vidět v detailu úkolu bez databázového SQL.
- `manage.py work-queue-errors 3`: pouze čtecí výpis selhaných a retry jobů projektu 3, včetně důvodu a čísla akce. Nepouští SEO a nemění databázi.
- Výsuvný chat má bezpečné náhradní vykreslení i při chybě sdíleného rendereru a chrání načítání historie před souběhem. Využívá stejné URL a uloženou konverzaci jako hlavní chat.
- Verze statických souborů změněna pro obnovení cache.

## Nasazení

1. Předem záloha adresáře aplikace, DB a `.env`; neodstraňovat `.env`, feedy, uživatelská data ani produkční logy.
2. Nahrát soubory z balíčku do aplikace, zachovat lokální `.env`. Restartovat Passenger a obnovit stránku bez mezipaměti (Ctrl+F5).
3. Ověřit chat na stránkách Statistiky a Úkoly: načtení historie, odeslání, odpověď, zavření a přechod mezi stránkami.
4. Bez jakékoliv SEO publikace lze na SSH spustit:

```bash
cd /home2/lauhannq/webbooster.freshcrackers.cz
/home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py work-queue-errors 3
```

5. SEO cron ponechat **vypnutý**, dokud nebude známa příčina chyb a nebude bezpečně otestována jedna úloha. Katalogový cron ponechat.

## Omezení / ověření

- 95 dostupných lokálních unit testů prošlo, `node --check` a `compileall` prošly; produkční běh a HTML v reálném prohlížeči nejsou ověřeny.
- Oprava nevysvětluje, která konkrétní chyba způsobila neúspěšné publikování – ta je jen v produkční databázi, již jsme nedostali. Nově ji lze přečíst přímo z aplikace/SSH.
- Opravný balíček **nezapíná SEO cron** a nespouští `work-queue` automaticky.
