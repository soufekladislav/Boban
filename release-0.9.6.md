# Boban WebBooster 0.9.6 – Fresh Core sjednocení a produktová data

## Změny
- WooCommerce již není samostatná konektorová karta. Jeho čtení je součástí detailu existujícího Fresh Core připojení.
- Manifest (veřejný export SEO/struktury) zůstává beze změny. Aktuální katalog se načítá chráněným Fresh Core REST API pomocí již existujícího **Fresh Core Access Key**. Pokud ho Boban dosud neuchovával, je potřeba ho jednorázově autorizovat. **Write key ani Accounting key se pro čtení nepoužívá.**
- Čtení produktů používá existující GET `/wp-json/fresh-core/v1/commerce/catalog`, hlavičku `X-Fresh-Core-Key`, stránkování, kontrolu odpovědi a diagnostiku HTTP 401/403.
- Přidána projektová mezipaměť `project_core_products` se zdrojovými atributy a vlastním normalizovaným produktovým modelem. Nevyplněná GTIN/značka a nedostupné varianty se záměrně *nevymýšlejí*.
- Přidána `project_core_sync` pro průběžné stránkování. Jedna manuální dávka načítá nejvýše tři stránky po 100 produktech. Po přerušení lze pokračovat od poslední potvrzené stránky.
- Bez změn stávajících SEO/účetních zápisů, Google OAuth, projektu, historie a úkolů.

## Před nasazením
1. Záloha aplikace i MariaDB; samostatně uchovat `.env` a všechny vlastní provozní soubory.
2. Nasadit do testovací instalace; databázové tabulky se vytvářejí doplňkově při inicializaci.
3. Otevřít Konektory → Fresh Core. Ověřit, že manifest a SEO fungují a rozbalit REST rozhraní.
4. Pokud REST čtení dosud nebylo autorizováno, jednou vložit současný **Fresh Core Access Key** z WP administrace. Není to nový klíč.
5. Kliknout „Pokračovat v načítání produktů“; opakovat do načtení požadovaného katalogu. Nechat vypsat počet uložených produktů a případné chyby.
6. Na kontrolním produktu ověřit cenu, sklad, URL, obrázky a kategorie; u variabilních produktů počítat s chybějícími jednotlivými variantami.

## Co tato verze nedělá
- Nepublikuje produktové feedy do katalogů ani neaktivuje Google Merchant, Heureku, Zboží.cz a Meta.
- Nesynchronizuje automaticky v pozadí. Dávky se nyní spouštějí ručně; automatické zpracování je další etapa.
- Neobsahuje variant-level export, EAN/GTIN a značkové mapování – vyžaduje rozšíření samotného Fresh Core produktového payloadu.
- Nezajišťuje měření skutečných objednávek nebo konverzí.

## Kontroly
- Provedena kontrola Python syntaxe (`py_compile`), kompilace Jinja šablony a integrity ZIP.
- Reálný import Flasku a živé REST volání nemohly být otestovány v tomto prostředí (chybí instalovaná závislost PyMySQL). Ověřit na testovacím hostingu před produkcí.
