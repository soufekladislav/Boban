# Boban 0.9.13.18 – Statistiky: vizualizace, Merchant API a diagnostika OAuth

## Opraveno

- **Duplicitní Statistiky v levém menu:** odstraněna druhá položka v `templates/base.html` (mobilní navigace zůstává jedna).
- **Manažerská vizualizace:** přidán denní časový graf relací z GA4, grafické vodorovné porovnání marketingových kanálů a zobrazení vyhledávacích dotazů podle impresí. Původní tabulky jsou zachovány v rozbalovacích detailech. Žádná uměle vygenerovaná čísla; chybějící data zobrazí vysvětlení.
- **Merchant API:** opraveno `FROM ProductPerformanceView` na oficiální `FROM product_performance_view`. Ověřeno dle Google Merchant API MCQL. Přístup, account a oprávnění musí být na hostingu nadále platné.
- **Google OAuth diagnostika:** místo samotného HTTP 400 se zobrazuje pouze bezpečný typ chyby (`invalid_grant`, `invalid_client` aj.) a stručné doporučení. Refresh tokeny, klientské tajemství a kompletní HTTP odpověď se nezobrazují.
- **Duplicitní obsah karet platforem:** odstraněno dvojí zobrazení stejného počtu položek a Merchant reportu.
- **Vizuální styl:** zachovány stávající barvy, písmo, karty a hlavní rozložení; grafy fungují bez externí JavaScriptové knihovny. Pro mobily responsivní úpravy.

## Důležité: výklad stavu dat

Výpis `analytics-backfill` = 11021 znamená 11021 materializovaných analytických pozorování, **nikoliv 11021 objednávek**.

`analytics-sync` úspěšně načetl GA4/GSC u projektu 3, ale projekty 1/2/4 měly problémy s obnovením tokenu Google. **Tato aktualizace neopravuje neplatný refresh token**, jen přesněji identifikuje důvod. Pokud bude `invalid_grant`, je obvykle nutné znovu autorizovat příslušný Google konektor u konkrétního projektu; u `invalid_client` zkontrolovat nastavení OAuth klienta. Není vhodné odpojovat funkční projekt 3.

Pokud Merchant report stále hlásí chybu, pošlete první krátký řádek chyby bez tokenů; nezkoušejte opakované importy katalogu. Oprava je pouze pro čtení reportu, nemění feed ani produktová data.

## Nasazení

1. Zálohovat současné soubory, databázi, `.env` a konektory. ZIP obsahuje kompletní soubory aplikace, ale nezahrnuje provozní `.env`.
2. Nahrát do `/home2/lauhannq/webbooster.freshcrackers.cz`, zachovat `.env` a produkční soubory. Restartovat Passenger.
3. Otevřít Statistiky projektu 3 a ověřit jednu položku v menu, graf i mobilní zobrazení. Pokud chybí denní graf, zkontrolovat aktualizaci GA4 snapshotu.
4. Jednorázová, čtecí kontrola:

```bash
cd /home2/lauhannq/webbooster.freshcrackers.cz
/home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py analytics-sync
```

5. U projektů 1/2/4 vyhodnotit bezpečnou chybovou kategorii (např. `invalid_grant`) a znovu autorizovat **jen** dotčené Google konektory. Nevkládat tokeny do chatu.

Původní `catalog-sync` cron nepřepisovat. `analytics-sync` stále provádí čtení, nikoliv změny na e-shopu. Pokud už je analytický cron nasazený, nepřidávat druhý.

## Testy

- 80 lokálních unittestů: OK.
- Kompilace modifikovaných Python souborů: OK.
- Jinja parser šablon `base.html` a `statistics.html`: OK.
- Skutečné Google API odpovědi a produkční grafy nelze z offline prostředí ověřit; vyžaduje nasazení a ověření.
