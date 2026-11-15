# SEO zápis proti Fresh Core 0.7.8 – provozní převzetí (2026-11-15)

## Příčina
Boban původně odesílal pouze lokálně uložené `target_id` jako WordPress `post_id`.
Fresh Core při nenalezení nebo blokovaném postu vracel HTTP 404
`fresh_core_seo_post`. Boban tuto chybu bez rozdílu považoval za dočasnou
a vrátil ji do retry fronty; uživatel neviděl smysluplný název ani důvod.

## Nové kontrakty
- Boban pro `update_meta` posílá `post_id` + přesné `target_url` pouze
  na hostitele projektu. Fresh Core 0.7.8 z URL dohledá správný WordPress produkt
  a odmítne každý nejednoznačný nebo cizí cíl. Staré ID se nebere jako
  autorita, pokud je URL uvedena.
- `fresh_core_seo_post`, `fresh_core_seo_url_not_found`,
  `fresh_core_seo_url_invalid` a obdobné trvalé chyby zastaví retry:
  job i akce skončí ve stavu `failed` s konkrétním důvodem, ne ve frontě.
  K novému pokusu dochází až po kontrole a schválení opravované akce.
- Do názvu úkolu se promítne typ skutečné úpravy a označení produktu;
  odůvodnění, očekávaný výsledek i blokující chyba jsou přímo v hlavní kartě.
- Původní `change_id=wb-{id}` zůstává zachováno kvůli idempotenci.

## Nasazení
1. Zálohovat WordPress i Bobanovu databázi.
2. Nahrát `fresh-core.zip` + `update.json` verze 0.7.8 do
   `public_html/wp-content/uploads/fresh-crackers/fresh-core/`
   na **www.freshcrackers.cz**; update.json až po nahrání ZIP.
3. V cílovém WordPressu **adrenalinerace.eu** aktualizovat Fresh Core na 0.7.8.
   Jinak Boban nový parametr `target_url` odešle, ale starý Core jej ignoruje.
4. Boban GitHub PR nasadit v pořadí #2 → #3 → #4 → #5. Všechny jsou
   navázané změny; samotné otevřené PR není nasazená produkční oprava.
5. Ověřit jednu URL např. `https://adrenalinerace.eu/produkt/trec-whey-100-2275-g-3/`
   přes autorizované `GET /wp-json/fresh-core/v1/seo/resolve?url=<urlencoded-url>`.
   Vrácené `id` musí odpovídat skutečnému postu ve WordPressu.
6. V Bobanovi ručně znovu schválit **jeden** dříve chybující úkol;
   ověřit konkrétní `resolved_by_url`, skutečný SEO výsledek a 
   označení `verified`. Nespouštět všechny staré neúspěšné úkoly současně.
7. Zkontrolovat, že při neexistující URL se úkol označí `failed`
   a neprobíhá v kruhu `retry` s HTTP 404. Ostatní dočasné chyby
   (timeout/5xx) zůstávají opakovatelné.
8. V případě správného zápisu ověřit výsledek na veřejné stránce; samotný
   úspěšný POST ani AI Engine `completed` není ověřenou změnou ve vyhledávači.

## Omezení
Na lokálním PHP testu lze ověřit mapování a bezpečnost; skutečný
WooCommerce rewrite, konkrétní produktová ID, oprávnění serveru a běh
WordPress updateru vyžadují následný produkční smoke test.
