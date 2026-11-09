# Boban / WebBooster 0.9.13.5 – oprava HTTP 500 u druhého Merchant feedu

## Zjištěná závada

V `/projects/<id>/merchant/publish` se ověření vybraného Merchant účtu a publikovaného XML provádělo **před `try`**. Pro nový projekt bez schváleného a publikovaného XML vyvolalo `merchant_feed_address()` výjimku `ValueError`, která končila obecnou chybou HTTP 500.

## Oprava

- Kontrola účtu i připraveného XML nyní probíhá uvnitř zachytávání chyb.
- Uživatel se vrátí do Konektorů s konkrétním vysvětlením, že musí nejprve připravit a publikovat XML v E-commerce.
- Nezakládá se žádný prázdný ani duplicitní datový zdroj.
- Nedochází k automatickému opakovanému importu produktů z WooCommerce.
- Merchant účet, OAuth, Adrenaline Race feed, cron a databázové schéma zůstávají beze změny.

## Jak dokončit Fresh Crackers

1. Zazálohuj aplikaci, nasazuj přes aktuální instalaci 0.9.13.4, zachovej `.env`, databázi a katalogové XML; restartuj Passenger.
2. V projektu Fresh Crackers otevři **E-commerce** a ověř, že má katalog synchronizovaný, vybraný, schválený a **publikovaný Google XML** (pokud není, dokonči tyto kroky; nemusíš znovu načítat Adrenaline Race).
3. V **Konektory → Merchant** se ujisti, že je vybraný skutečný Merchant účet pro web Fresh Crackers, pak klikni **Připojit schválený XML feed**.
4. Po úspěšném připojení spusť jeho první načtení a ověř zpracování.

### Poznámka k manifestu

Veřejná diagnostická URL při ověření vracela `application_version: 0.9.12`, generováno 6. 11. 2026 ve 21:21 UTC, zatímco uživatelské screenshoty ukazovaly 0.9.13.4. Tento výstup je zjevně starý / z cache, proto jej nelze považovat za aktuální stav projektu Fresh Crackers.
