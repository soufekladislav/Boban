# Boban WebBooster 0.9.13.19 — obchodní statistiky, kvalita dat a trychtýř

## Rozsah

Navazuje přímo na 0.9.13.18, bez změn připojených katalogů, SEO workflow, externích zápisů a společného výsuvného chatu.

1. **Spolehlivost synchronizací:** Statistiky rozlišují aktuální, zastaralá a chybějící data GA4/GSC. Zobrazují poslední neúspěšný analytický job a bezpečné vysvětlení. Starší data jsou jasně historická, nikoli aktuální. Samostatné denní agregace GA4 `daily_totals` předcházejí zkreslení grafu při omezeném počtu řádků s kanály. Dříve uložené přehledy zůstanou fungovat přes původní `daily_channels`.
2. **Obchodní model:** Hlavní obchodní cesta se určí z projektového `primary_conversion`. Režim e-shop / poptávky funguje bez databázové migrace. Sekundární metrika zůstává v přehledu, ale je jasně označena.
3. **Vizuální trychtýř:** Graficky odlišené kroky. Popisky uvádějí skutečnou jednotku (relace, události, ověřené výsledky); nesrovnatelné metriky se nedělí procenty a chybějící data nejsou nuly.
4. **Stránky a vyhledávání:** Společná tabulka URL s počtem vstupních relací GA4 a kliknutí Search Console, orientační klasifikace stránky a zvláštní tabulka skutečných párů vyhledávací dotaz / URL ze Search Console. Nespojuje jednotlivé dotazy s objednávkami.
5. **Kvalita měření:** Stručné indikátory stavu GA4 a Search Console na začátku stránky, informace o chybějícím měření e-commerce a poptávek, srovnání relací s předchozím obdobím (pokud je k dispozici).

## Důležité omezení

Tato verze **neopravuje expirované nebo odvolané Google OAuth refresh tokeny**. U projektů, které hlásí chybu obnovení tokenu, je potřeba opravit autorizaci v Konektorech. Toto není řešitelné úpravou grafu.

Skutečné objednávky z WooCommerce a potvrzené poptávky stále vyžadují čtecí zdroj. Údaje o opuštěných košících vyžadují evidenci relací/košíků, nestačí rozdíl GA4 událostí. Bez dat nelze bezpečně zobrazit konverzní míry mezi kroky.

## Nasazení

1. Zálohovat současné soubory, MariaDB a `.env` mimo aplikační adresář.
2. Nahrát ZIP jako upgrade aplikace a zachovat produkční `.env`, databázi, uploady a feedy. **Neodstraňovat produkční adresář.**
3. Restartovat Python Passenger podle současného postupu hostingu.
4. Spustit v existujícím virtualenvu `python manage.py analytics-sync` a sledovat úspěšnost jednotlivých projektů. Pokud již běží analytický cron, nepřidávat druhý. Původní katalogový cron zachovat.
5. Ve Statistikách zkontrolovat datum GA4/GSC, druh trychtýře, denní graf, URL přehled a chybějící obchodní údaje.
6. U projektů s chybou `Google token refresh HTTP 400` řešit opětovnou autorizaci konkrétního konektoru; nezměnit funkční propojení ostatních projektů.

Nová verze nepřidává databázové tabulky ani nemaže existující historii. Využívá stávající `source_snapshots`, `analytics_observations` a evidenci jobs.

## Testy

- 85 lokálních unit testů; kompilace Pythonu a parsování všech Jinja šablon.
- Lokální smoke test vykreslení obsahu Statistik při chybějících měřeních.
- Neproběhlo produkční testování na webbooster.freshcrackers.cz ani vizuální test v reálném prohlížeči. Ty je nutné provést po nasazení.
