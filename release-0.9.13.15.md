# Boban 0.9.13.15 – Meta import diagnostics

Oprava pouze read-only diagnostiky Meta katalogu.

- Poslední 3 uploady nyní vracejí `num_detected_items`, `num_invalid_items`, `num_persisted_items`, `num_deleted_items`, `error_count` a `warning_count`.
- Omezený přehled chyb posledního importu.
- `product_count` z katalogu není zaměňováno za počet položek posledního importu.
- Žádný opakovaný import, žádné změny katalogu ani feedů.
- Žádné tokeny ani App Secret se nevypisují.

Instalace: záloha stávajícího zdrojového kódu a databáze, nahrát aktualizovanou aplikaci, zachovat `.env` a produkční datové soubory, restart Passenger. V E-commerce → Meta kliknout na „Načíst stav přes Meta API“ a rozbalit poslední odpověď. Pokud jsou pole dostupná, porovnat počty detekovaných a uložených položek a chyby.

Poznámka: Meta může některá pole/endpointy omezovat oprávněními nebo verzí API; selhání celého statusu pak vyžaduje úpravu seznamu požadovaných polí.
