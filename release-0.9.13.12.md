# Boban / WebBooster 0.9.13.12 – Meta Commerce Manager catalog

Základ: 0.9.13.11. Beze změny Google Merchant, Heureka, Zboží.cz a jejich veřejných adres.

## Nově
- `meta_export.py`: samostatný Meta RSS XML 2.0 feed s `g:` atributy ze **stejného schváleného katalogu Bobana**; varianty mají vlastní `id` a sdílené `item_group_id`.
- Validace povinných údajů (cena, URL, obrázek, popis, měna, identifikátory), vyřazení zástupné ceny 0,01 a digitálních nabídek. Žádné umělé značky, GTIN nebo sklady.
- `project_meta_feeds`: oddělený stav publikovaného XML, stabilní URL, počty a diagnostika.
- `E-commerce → Meta`: dva boxy (ovládání a diagnostika) se stejným vizuálním stylem. Výstup vzniká nad lokálně uloženými produkty, **bez opakovaného načtení z WooCommerce**.
- `Konektory → Meta`: evidence ID katalogu a uživatelské potvrzení, že byl feed propojen a první import zkontrolován. **Není zde skutečná Meta OAuth/API autorizace**; bez ní nelze spolehlivě číst stav zpracování ani založit katalog na uživatelově účtu automaticky.
- Veřejný endpoint `/catalog/meta/<token>.xml` a bezpečný atomický zápis; automatické obnovení po úspěšném katalogovém cyklu. Chyba Meta výstupu neblokuje Google ani další platformy.

## Nasazení
1. Zálohujte soubory a databázi; nasadit kompletní ZIP, **zachovat `.env`, externí feedy, databázi, cron**, restartovat Passenger.
2. E-commerce → Meta → „Připravit Meta XML“; zkopírovat zveřejněnou URL.
3. V [Meta Commerce Manager](https://business.facebook.com/commerce/) vybrat nebo vytvořit produktový katalog (ověřit správného vlastníka a přístupová práva), v katalogu otevřít **Zdroje dat → Přidat položky / Datový feed → plánované načítání z URL**, vložit URL XML a nastavit pravidelnou kontrolu.
4. Po prvním načtení ověřit v Meta počty přijatých/odmítnutých položek, identifikátory variant, případné zásady Commerce Policies a ID katalogu; potom lze ID a potvrzení zapsat v Konektorech.
5. Při použití Meta Pixel / Conversions API je pro dynamické reklamy potřeba ověřit shodu `content_ids` se stabilními `id` z feedu. V tomto balíčku se Pixel/CAPI neupravují.

## Omezení
- Integrace zatím **neprovádí přihlášení Facebookem, automatické vytvoření katalogu ani API odeslání**. První propojení datového zdroje je v Commerce Manageru ruční. U Meta se také samostatně schvaluje případné zapnutí obchodu na Facebooku/Instagramu; import katalogu není zárukou obchodní způsobilosti.
- Počty v Bobanovi jsou počty v XML, nikoliv živý stav přijetí platformou. Nejsou zde Meta statistiky nebo prodejní konverze.

## Testy
`python -m unittest discover -s tests -p 'test_*.py'` – 65 testů OK.
Jinja2 – 22 šablon parsováno; Python kompilace OK.
Skutečný první import z Meta nebyl proveden na produkčním účtu a je třeba jej ověřit.
