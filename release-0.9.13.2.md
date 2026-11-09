# Boban / WebBooster 0.9.13.2 — první import Google Merchant XML

## Proč Google vrátil 404

Datový zdroj (účtu 5073368700) byl úspěšně vytvořen, ale pouhé vytvoření zdroje neznamená, že proběhlo první načtení. Volání `fileUploads.get(.../latest)` před prvním uploadem vrací HTTP 404 `File upload not found`. Nejde o chybu registrace Google Cloud ani samotného XML.

## Změny

- V konektoru již připojeného Merchant zdroje nové tlačítko **Spustit načtení XML**. Používá oficiální `dataSources.fetch`, existující OAuth token a uložené ID zdroje (nevytváří duplicity).
- Bezpečnost: práva k projektu, CSRF, kontrola shody datového zdroje s Merchant účtem, existence aktuální schválené/publikované revize XML a shoda adresy XML.
- Při úspěšném API požadavku uloží čas vyžádání; další ruční pokus je z aplikace blokován po dobu 20 hodin kvůli nízkým kvótám Googlu. Pravidelný naplánovaný fetch v Google Merchant zůstává nezávislý.
- HTTP 404 `File upload not found` z dotazu na poslední import se zobrazí jako **dosud nenačteno / čeká na zpracování**, ne jako fatal error. Ostatní skutečné API chyby se nezamlčují.
- Stav importu se čte přes stávající **Načíst stav Google**.
- Žádné změny databázového schématu, produktu, XML ani cronu.

## Nasazení

1. Zálohujte zdrojové soubory a databázi.
2. Aktualizujte aplikaci obsahem ZIPu v adresáři `/home2/lauhannq/webbooster.freshcrackers.cz`, nepřepisujte produkční `.env`, databázi ani `generated_feeds`.
3. Restartujte Passenger.
4. Adrenaline Race → Konektory → Google Merchant Center → **Spustit načtení XML** (jednou).
5. Po čase klikněte na **Načíst stav Google** a zkontrolujte `processingState` a počty zpracovaných položek.
6. Pokud Google hlásí chybu fetch URL, ověřte, že XML je veřejně dostupné přes HTTPS bez přihlášení a vrací XML (HTTP 200, nikoliv HTML či 403).

## Testy

15 lokálních unit/syntaktických kontrol úspěšných. Skutečný Google import lze ověřit až v produkci po tlačítku fetch.
