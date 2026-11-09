# Boban/WebBooster 0.9.13.3 – přesnější pravidla Merchant XML

- Bez nového načtení 4 258 produktů a 1 946 variant: export pracuje s aktuální pracovní kopií MariaDB.
- Při exportu vyloučených kategorií Boban načte pouze **strom kategorií** z veřejného Woo Store API (`/wp-json/wc/store/v1/products/categories`), po stránkách 100 kategorií; záznamy se uloží do soukromé lokální cache.
- Vyloučení rodičovské kategorie platí i pro potomky, i když rodič není přímo přiřazen žádnému produktu. Varianta dědí rozhodnutí rodičovského produktu.
- Při chybě Woo Store API se původní XML nepřepíše – bezpečný režim.
- Ceny 0,01 (placeholder, libovolná měna) se nepovolí v Google XML a objeví se ve validačním reportu. Cena se nikdy nepřepisuje ve WooCommerce ani v Bobanově databázi.
- V E-commerce je u takové ceny upozornění; výsledný report ukazuje zdroj stromu kategorií.
- `app.py`, `feed_workflow.py`, `merchant_export.py`, šablona a ostatní služby zůstávají kompatibilní; žádná SQL migrace.

## Po nasazení
1. Zálohuj aplikaci, nahraj ZIP, nepřepisuj `.env`, databázi, `generated_feeds` ani cron; restartuj Passenger.
2. V E-commerce zkontroluj vyloučené kategorie (zejména eventy) a klikni na **Publikovat XML** (případně dosavadní tlačítko pro sestavení výstupu). Nevol **Restart fronty**.
3. Pokud je výběr označen jako neschválený, nejprve jej schval. Tím se katalog znovu nenačte, pokud je dokončená pracovní kopie zachovaná.
4. Zkontroluj nový počet exportovaných položek a hlášení o validačně vyřazených cenách.
5. Teprve potom v Konektorech spusť **Spustit načtení XML**; stejné URL zdroje zůstane zachováno.

Pozor: systém blokuje 0,01 jako podezřelou placeholder cenu. Skutečnou cenu je nutné doplnit ve WooCommerce a aktualizovat katalogovou kopii při příští běžné synchronizaci; neodhaduje se.
