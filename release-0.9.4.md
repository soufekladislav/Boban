# Boban 0.9.4 – Smart Workspace

## Obsah
- Pět dynamických karet s kontextovým výběrem podle posledního uživatelského dotazu.
- Jednotná knihovna serverových karet, bez volného AI HTML.
- Superadmin: `/admin#smart-workspace-settings`, aktivace, pořadí a rozšiřitelný registr typů.
- Mobilní vysouvací panel se zatemněním a klávesou Escape.
- AI Engine dostává navigaci do aplikace a seznam dostupných pracovních karet; odpovědi neoznačují plánované katalogy za aktivní.
- Po nové odpovědi se panel obnoví bez reloadu.

## Nasazení
1. Zálohuj aktuální soubory a MariaDB. Nestav na `.env.example`; zachovej své existující `.env` mimo distribuční ZIP.
2. Nasaď soubory do testovací kopie aplikace, ověř Passenger a správnou databázi.
3. Proveď hard reload nebo ověř nové cache-busting parametry CSS/JS.
4. Otevři superadmin konzoli, nastav karty a ověř pět karet na desktopu.
5. Ověř mobilní výsuvný panel, přepínání tématu v chatu a funkční odkazy.
6. Ověř existující schvalování, automatizace, archiv chatů a role Editor/Visitor.

## Omezení
- Není zprovozněn Catalog Engine, Google Merchant API ani PPC.
- Karty používají existující projektové zdroje; neprovádějí nové externí API operace.
- Hlas zůstává diktování a předčítání, nikoli full-duplex hlasový režim.
- Kontroly syntaxe nenahrazují produkční integrační a vizuální testování.
