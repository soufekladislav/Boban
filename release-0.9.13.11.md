# Boban 0.9.13.11 — kvalita XML Seznam Nákupy

## Co se změnilo

- Základem je poslední funkční Boban 0.9.13.10. **Není nutný nový import z WooCommerce.**
- Samostatný generátor `zbozi_export.py` ověřuje unikátní `ITEM_ID` a `PRODUCTNAME` po rozlišení variant pomocí skutečných atributů velikosti, barvy atd. Neodlišitelné duplicitní názvy raději vynechá a nahlásí. Nevymýšlí produktové vlastnosti.
- Kategorie `CATEGORYTEXT` vyhledává v oficiálním číselníku Zboží.cz (https://www.zbozi.cz/static/categories.json), který se uchovává lokálně v cache. Zohledňuje **všechny** WooCommerce kategorie produktu, nejen první. Pouze jednoznačná shoda s číselníkem je označená za ověřenou. Pokud oficiální kategorie neodpovídá, použije původní Woo kategorii a uvede upozornění `unmapped_category_count`. **Plné mapování nelze garantovat bez kontroly konkrétních kategorií.**
- Základní doplňky podle specifikace: `PRODUCT`, `BRAND`, potvrzený `PRODUCTNO` (SKU), unikátní skutečné alternativní obrázky a `EPREL_ID` jen když je zdrojový identifikátor vyplněný. EPREL se nevymýšlí ani nevyžaduje u všech sportovních výrobků.
- Rozlišuje `DELIVERY_DATE` (expedice) a `DELIVERY` (dopravce, cena, volitelná cena dobírky). Přidán formulář **Ověřená doprava** v E-commerce pro jedno potvrzené univerzální doručení platné skutečně pro celý katalog. Pokud se podmínky liší podle produktů, formulář nepoužívat; dopravu řešit individuálním nastavením Seznamu po ověření provozovny. Formulář lze vymazat výběrem „Nezadávat dopravu do XML“.
- Výstup přehledně uvádí počet neověřených kategorií, bezdopravy a vyřazených duplicit.
- Google Merchant, Heureka, Fénix připojení, data katalogu, plánovaný cron ani URL stávajícího Zboží XML se nemění.

## Instalace

1. Zálohovat nasazenou aplikaci a databázi, zachovat `.env` i publikované XML.
2. Nahrát úplný ZIP do adresáře Bobana. Restartovat Passenger. Při startu dojde k přidání volitelného sloupce `shipping_rules_json` do tabulky `project_zbozi_feeds` (bez mazání dat).
3. V Adrenaline Race → E-commerce → Zboží.cz otevřít „Ověřená doprava“. Univerzální dopravu vyplnit jen při skutečně jednotných podmínkách. Jinak nechat prázdné.
4. Kliknout **Znovu připravit XML**; nepouštět nový import Woo. Zkontrolovat zprávy a zejména `unmapped_category_count`, `duplicate_title_count` a `missing_shipping_count`.
5. Po následujícím stažení zdroje Seznamem porovnat Diagnostiku: původně 39 duplicitních názvů, 2 133 nezařazených, 2 172 bez dopravy. Některé rozdíly mohou odrážet stav nedokončené verifikace provozovny a rozsah zpracovaných nabídek.

## Co tato oprava neslibuje

- Není možné automaticky odhadnout reálné ceny dopravy pro všechny velikosti zboží. Dodavatelství Adrenaline Race může vyžadovat pravidla podle druhu výrobku.
- Automatický převod každé WooCommerce kategorie na Zboží.cz nelze zaručit; nejednoznačné kategorie budou potřebovat schválené mapování.
- Zbývající EAN se nesmí vymýšlet a nezavedený dopravce neznamená selhání stažení XML.
- Počty XML nejsou potvrzením zobrazení nabídek či přijatých prokliků.

## Ověření

`python -m unittest discover -s tests -p 'test_*.py' -q`: 61 testů úspěšně. Kontrola syntaxe `app.py`, `zbozi_export.py`, `zbozi_categories.py` a načtení Jinja šablon úspěšná. Produkční přijetí Seznamem ještě nebylo ověřeno.
