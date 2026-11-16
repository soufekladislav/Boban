# Boban: viditelná práce, data úloh a kontrola pohybu fronty (2026-11-14)

## Problém
Úkoly se označovaly jako „Úkol #ID“; v administraci byly většinou vidět
jen typy workeru. Uživatel nepoznal název změny, zadání, spuštění ani skutečné dokončení.
Fresh AI Engine `completed` potvrzuje odpověď modelu, **nikoli** vykonaný zápis Bobana.

## Nový stav
- **Úkoly projektu:** nahoře tabulka skutečně uložených jobů a dat vytvoření,
  zahájení, posledního heartbeat, dokončení a případného opakování.
  Názvy se berou z provázaného SEO nálezu, popisu schválené akce nebo konkrétní
  growth/AI dávky. Nepřepisují se databázové záznamy.
- **Samotné akční karty:** skutečný název problému místo „Úkol #123“, datum
  návrhu, schválení, provedení a dokončení.
- **Administrace:** stejný seznam napříč projekty, filtr projektu a stavu,
  živá aktualizace po 12 s.
- **Dokončeno za 15 minut:** počet jobů se stavem `completed` a potvrzeným
  `finished_at` v tomto období. Nejde o potvrzení obchodního výsledku ani
  automaticky o ověřenou publikaci na webu.
- **Naposledy dokončeno:** datum z databáze `jobs.finished_at`. Nezaměňuje
  se s časem posledního volání AI ani kontrolním heartbeat procesů.
- **Bezpečný manifest:** jen agregované stavy a provozní časová razítka.
  Žádné názvy úloh, uživatelé, URL, prompt ani klíče.

## Jak ověřit po nasazení
1. Záloha app + databáze + .env, nasazení PR #2, poté #3, potom této nadstavby.
   Změna nepřidává nové DB tabulky; používá existující `jobs`, `actions` a `issues`.
2. Otevřít `/admin#automation` nebo `/admin` – karta „Přehled práce napříč projekty“
   je nad automatizacemi. V Úkolech projektu je stejný monitor s odkazy.
3. U konkrétního schváleného úkolu musí být vidět přechod
   `queued` → `running` → `completed` (nebo `retry/failed`).
   Název musí odpovídat záznamu akce/SEO problému, nikdy pouze internímu ID.
4. Nejprve ověřit `created_at`, po převzetí `started_at`, během zpracování
   `updated_at` a na konci `finished_at`. Chybějící datum se zobrazuje
   jako pomlčka, nevymýšlí se.
5. Zkontrolovat, že se změnil „Dokončeno za 15 min“ a poslední dokončení.
   Pokud ne a běžící úkoly nemají čerstvý heartbeat, zobrazí se výstraha
   místo falešného tvrzení „pracuje“.
6. Pokud je po 10 minutách více čekajících úkolů a žádné potvrzené dokončení,
   ověřit `queue_cron.log`, `worker.log`, `manage.py work-queue-status`.
   Pokud se zpracovávají AI přípravy, běh může trvat déle; ověřit jejich
   skutečný `running` heartbeat. Nespouštět stejný externí zápis ručně
   bez předchozího ověření stavu na cílovém webu.

## Z manifestu 2026-11-14 15:31
Manifest dokládá 1483 historických `jobs`, 1232 `actions`, 15 záznamů
`daily_sync_state` a **0 záznamů `connector_health`**. Neobsahuje skutečné
stavy jednotlivých úloh ani jejich datum dokončení; proto z něj
**nelze** tvrdit, že se fronta zasekla nebo posouvá. Další bezpečný
diagnostický manifest již nabídne agregovaná časová data pro porovnání.
