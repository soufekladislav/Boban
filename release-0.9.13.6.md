# Boban / WebBooster 0.9.13.6 — uspořádání Google Merchant a E-commerce

## Princip
- **Konektory:** pouze připojení Google účtu, výběr Merchant účtu, obnovení OAuth. Merchant karta je opět součástí dvousloupcové mřížky se stejným typografickým a barevným standardem jako GA4 a ostatní karty.
- **E-commerce:** krok 1 — katalog Fresh Core; krok 2 — výběr kategorií/produktů, schválení; krok 3 — Google Merchant (dvousloupcové ovládání + přehled výsledků).
- **Google Merchant ovládání:** publikované XML (adresa a počty), znovupublikování schváleného katalogu bez opětovného importu, připojení datového zdroje, ruční načtení aktuálního XML, odkazy na nastavení obchodu a správu připojení.
- **Google Merchant výsledky:** přepínatelné záložky Import, Obchod, Výkon; počet zpracovaných/vytvořených/aktualizovaných položek, diagnostika, účty/datové zdroje, neplacené prokliky/impresní výkon. Chybějící data jsou viditelně označena, žádné výsledky se nevymýšlejí.
- Po vykonání Merchant akcí se uživatel vrací do E-commerce, nikoli do Konektorů.

## Zachováno
- Původní cesty Merchant API, databázové integrace, přihlášení, CSRF, časové limity, kontrola otisku XML, vazby na projekt a zdroj; žádná databázová migrace.
- Synchronizace produktů a variant, pravidla katalogových výjimek, stávající veřejné XML URL, plánovaný cron.
- API operace jsou dál ruční — tato verze nepřidává novou automatickou synchronizaci ani čtení firemních nastavení Merchant API.

## Nasazení
1. Záloha aplikace a databáze.
2. Nahrát soubory z kompletního ZIPu do existující aplikace; **zachovat vlastní `.env`, databázi, publikované XML a cron**.
3. Restartovat Passenger, ověřit zápatí `0.9.13.6`.
4. Zkontrolovat `/projects/1/connectors#merchant-center` a `/projects/1/ecommerce#merchant-platform` (analogicky další projekty).
5. V E-commerce zkontrolovat uložený feed, případně použít **Znovu publikovat schválené XML** a až poté načíst aktuální soubor Googlem; po načtení ověřit stav a výkon.

## Ověření
26 lokálních unit testů, validace Python AST/Jinja, kontrola ZIP struktury. Provozní OAuth/API volání nebylo v lokálním prostředí prováděno.
