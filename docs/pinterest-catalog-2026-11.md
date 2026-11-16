# Pinterest Business – jednoduchý katalogový konektor (2026-11-16)

## Proč tato varianta

Boban už má společný produktový katalog z Fresh Core, synchronizované varianty,
pravidla vyloučení produktů/kategorií a schvalování, které využívá Google,
Heureka, Zboží.cz a Meta. Nový Pinterest adaptér **neimportuje nové produkty**
ani nesbírá OAuth klíče a nijak nemění WooCommerce.

## Konektory → Pinterest

Tento konektor je **feed URL**, nikoliv automatizovaná správa reklamního účtu.
V Pinterest Business se musí první zdroj přidat vlastníkem firemního účtu
a doména obchodu musí být ověřena. Pinterest může přístup ke katalogům
omezit podle země, účtu či pravidel pro obchodníky.

1. V E-commerce dokončit synchronizaci produktů i variant a schválit společný sortiment.
2. V oddílu Pinterest kliknout na **Připravit Pinterest XML**.
3. Zkopírovat URL, začíná `https://webbooster.freshcrackers.cz/catalog/pinterest/`.
   Otestovat v anonymním prohlížeči, že vrací platné RSS XML a nikoliv
   HTML přihlášení, 404 nebo timeout. URL je náhodný veřejný token, nesdílet
   mimo Pinterest a oprávněné obchodní partnery.
4. Ve firemním Pinterest účtu otevřít **Catalogs / Data sources**,
   přidat nový zdroj pomocí veřejné URL, XML RSS, trh **CZ**, jazyk **čeština**,
   výchozí měna podle skutečného feedu (obvykle CZK), naplánovat opakované načítání.
   Země a jazyk zdroje může být po založení nevratný.
5. V Konektorech lze zaškrtnout **URL jsem vložil do Pinterest Business**.
   Tento stav je **výslovné potvrzení uživatele**, nikoli ověřený import.
6. Přijetí, chyby a schválení produktů ověřovat v diagnostice Pinterest Business.
   Pinterest může ověřovat obchod, obrázky, produktové stránky a tag zvlášť.

## Automatická obnova

Jestliže má projekt aktivní existující `catalog_workflow_tick`, po novém
úplném načtení produktů se aktualizuje Google XML a všechny dříve vytvořené
platformové feedy včetně Pinterestu. Samostatný Pinterest cron není potřeba.
Výjimky kategorií a produktů se dědí z centrálního katalogu, bez duplikace.

## Rozlišení stavů

- **XML připraveno** – Boban soubor uložil a lze jej stáhnout.
- **Registrace nahlášena** – uživatel potvrdil vložení URL.
- **Pinterest import potvrdil** – v této fázi Boban nemá automatizovaný API důkaz.
- **Prodej/objednávky** – zatím bez samostatného měření Pinterest konverzí;
  pro budoucí vyhodnocení doplnit značení a analytiku v Bobanovi.

## Co testovat

- Schválení katalogu, první ruční generování a URL 200 XML.
- Druhé generování zachovává stejný token a adresu zdroje.
- Vyloučené produkty nejsou ve feedu; variace mají `item_group_id`.
- `availability` obsahuje Pinterest hodnoty `in stock` / `out of stock`.
- Chyba při generování nepoškodí poslední publikovaný XML.
- Ověřit spuštění serverového katalogového cronu; GitHub samotný nic nenasazuje.

Pro cílový ostrý e-shop Adrenaline Race nezačínat hromadným importem celé
sady, dokud Pinterest nepotvrdí dostupnost obchodních katalogů na daném
firemním účtu a alespoň jeden úspěšný import.
