# WebBooster 0.9.7 – E-commerce + první Google Merchant XML

**Součástí dodávky jsou dva samostatné ZIPy:** Fresh Core 0.7.7 (WordPress) a WebBooster 0.9.7 (Python/Passenger). Nahrát nejprve Fresh Core, potom WebBooster. Obě verze jsou navrženy jako zpětně kompatibilní rozšíření předchozího stavu; provozní nasazení a integraci MariaDB je nutné otestovat.

## Co se změnilo

- Pod **SEO audit** přibyla záložka **E-commerce**. Nabízí stav produktů, variant, obě synchronizace, Google XML export a diagnostiku. Pro ostatní katalogy (Heureka, Zboží.cz, Facebook/Meta) je připraveno místo, ale **jejich připojení není v této verzi implementováno**.
- Fresh Core 0.7.7 doplňuje bezpečný `GET /wp-json/fresh-core/v1/commerce/variations`, stránkovaný po max. 50 variantách. Ve stávajícím `/commerce/catalog` doplňuje značku, GTIN a další katalogová data. Používá **existující** Fresh Core Access Key. Nevytváří další konektor ani klíč.
- Produkty na Fresh Core se stránkují stabilně podle ID. Boban používá standardně 25 položek na stránku, max. 2 stránky na jeden uživatelský požadavek (konfigurovatelné) a po překročení časového rozpočtu nepokračuje na další stránku. Jednotlivý HTTP požadavek stále může doběhnout do svého timeoutu.
- Ukládání dat zůstává v DB Bobana. Samostatně se ukládají varianty a jejich stav synchronizace; při nové autorizaci Core se staré produkty a varianty smažou, aby se nesmíchala data webů.
- Při importu se používá mezislužbový zámek `flock`: **jen jeden současně běžící import na projekt** (Linux/Passenger).
- Google XML tvoří veřejný produktový feed jako samostatný soubor v `CATALOG_FEED_DIR`. Google nic automaticky nenačte ani nepřijme, dokud feed manuálně nepřidáš do Merchant Center. Nejedná se o Merchant API.
- Variabilní produkty se exportují po variantách; samostatný rodičovský produkt se nepřidává. Neúplné položky se vynechají a vypíšou v diagnostice. Chybějící identifikátory se upozorňují a **nevymýšlejí**.

## Nastavení výkonu (volitelné v `.env` Bobana)

```ini
COMMERCE_PAGE_SIZE=25
COMMERCE_BATCH_PAGES=2
COMMERCE_BATCH_SECONDS=9
CATALOG_MAX_EXPORT_ROWS=10000
# Doporučeno: perzistentní adresář mimo složku aplikace, přístupný pro zápis Passenger uživatelem
CATALOG_FEED_DIR=/home/USER/webbooster-catalog-feeds
```

**Pozor**: `CATALOG_FEED_DIR` musí být existující nebo vytvořitelný zapisovatelný adresář. Exportní XML nesmí zmizet při příštím přepsání složky aplikace. Bez nastavení se ukládá do `generated_feeds` uvnitř aplikace a tento adresář je třeba při nasazení zachovat. URL veřejného feedu používá nevypočitatelný token, ale feed má obsahovat jen veřejné produktové údaje.

## Doporučený test – bez zásahu do účetních integrací

1. Zálohuj stávající Boban 0.9.6, databázi MariaDB a Fresh Core 0.7.6.1. Zachovej `.env` a původní klíče. Nenasazuj překrytím bez zálohy.
2. Nejprve aktualizuj WordPress plugin Fresh Core z instalačního ZIP na 0.7.7. Ověř ping, stávající SEO write bridge a účetní endpointy. Načtení `/commerce/variations` vyžaduje existující Access Key.
3. Aktualizuj Boban a restartuj Passenger. Kontroluj logy; nová tabulková schémata se vytvoří při startu aplikace pomocí `ensure_marketing_knowledge()`.
4. V projektu Adrenaline Race otevři **Nástroje → E-commerce**. Pokračuj po malých dávkách zvlášť pro produkty a varianty. Monitoruj během importu CPU, RAM, latenci WordPressu, PHP-FPM/Passenger procesy, velikost DB a MySQL pomalé dotazy. Jestli je zátěž vysoká, sniž `COMMERCE_BATCH_PAGES=1` a `COMMERCE_PAGE_SIZE=10`.
5. Teprve po úplném importu obou částí spusť **Vygenerovat Google XML**. Ověř URL, validační přehled, obrázky, ceny, měnu, značky/GTIN, skladovost a konfiguraci variant. Důležité: pokud je katalog veliký, export v této verzi běží jednorázově v požadavku; limit `CATALOG_MAX_EXPORT_ROWS` jej bezpečně zastaví, ale pro rozsáhlejší katalogy je vhodné později generování přesunout do pracovní fronty.
6. XML nahraj jako plánovaný zdroj v Google Merchant Center až po vlastní kontrole. V Merchant Center je třeba nastavit i dopravu, obchodní informace a další požadavky. Přijetí či zobrazování nelze z lokálního testu garantovat.

## Limity

- **Neproběhlo měření reálné serverové zátěže**, test s produkčním WooCommerce, skutečnou MariaDB, cPanel Passenger ani přijetí feedu Googlem. Prošly syntaktické kontroly a ukázkový XML test.
- Zatím nejde o automatickou synchronizaci na pozadí; požadavky se řídí z E-commerce rozhraní. Automatický plánovač a inkrementální události budou další etapa.
- Stránkování je podle stabilního ID, ale při souběžném mazání/publikování produktů se počet položek může během běhu měnit. Důležitá je závěrečná kontrolní synchronizace.
- XML je první vlastní exportní adaptér a není zárukou schválení všech produktů. U chybějících veřejných údajů Boban produkt vyřadí a podá diagnózu.
- Neřeší Heureka, Zboží.cz ani Meta API; jejich adaptéry naváží na stejný datový model.

## Ověřené testy při přípravě

- `python -m py_compile app.py merchant_export.py` – OK.
- PHP lint změněných zdrojů Fresh Core – OK.
- Parsování Jinja všech 23 šablon – OK.
- Generování ukázkového Google RSS/XML včetně jednoduchého produktu a varianty, XML parser – OK.
- Celý Flask nebylo možné spustit v tomto prostředí, protože chybí knihovny `flask` a `pymysql`; závislosti jsou uvedeny v `requirements.txt`.
