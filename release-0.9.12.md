# Boban / WebBooster 0.9.12 – Google Merchant Center

**Výchozí verze:** přesný uživatelem dodaný archiv `boban(4).zip` (0.9.11).

## Co bylo doplněno

- Samostatný Merchant modul `merchant_connector.py` používající oficiální Google Merchant API (Accounts v1, Data Sources v1, Issue Resolution v1, Reports v1).
- Google OAuth využívá stávající klientské ID, tajemství a callback WebBoosteru. Merchant požaduje zvláštní scope `https://www.googleapis.com/auth/content`, aniž přepisuje přístup Search Console, GTM nebo GA4.
- Výběr dostupného Merchant účtu a bezpečné ukládání jeho stavu do dosavadní tabulky `integrations`, včetně šifrovaných OAuth tokenů.
- Vyhledání již existujícího datového zdroje se stejnou URL; vytvoření nového zdroje pro **pravidelné stahování schváleného HTTPS XML** jen po výslovném kliknutí a potvrzení.
- Zobrazení posledního zpracování feedu, agregovaných stavů produktů a problémů, denních prokliků, impresí a CTR organických nákupních záznamů za uplynulých 28 dokončených dní.
- Přehled uložených Merchant výsledků také na stránce E-commerce, bez externích API volání při každém zobrazení stránky.
- Oddělené ovládání diagnostiky a čtení statistik na vyžádání, nikoli během importu WooCommerce.
- Nové formuláře jsou chráněné CSRF tokenem a přístupem uživatele k projektu.
- Feedový validátor již netvrdí `identifier_exists=no` jen proto, že v datech chybí GTIN a značka.

## Pořadí nasazení

1. Zálohovat aplikaci a databázi. Nahrát obsah tohoto balíčku jako kompletní aktualizaci zdrojových souborů. Ponechat produkční `.env`, databázi, `generated_feeds/`, logy a serverový cron. Nenahrazovat ani nemažte produkční data nebo adresář s feedy.
2. Restartovat Passenger standardním postupem pro aplikaci, na níž je nasazen WebBooster.
3. V Google Cloud projektu, jehož OAuth používá Boban, povolit Merchant API a ověřit OAuth souhlas s požadovaným scope `https://www.googleapis.com/auth/content`. Stávající callback `GOOGLE_REDIRECT_URI` zůstává stejný.
4. V projektu otevřít **Konektory → Google Merchant Center → Připojit Merchant přes Google**, schválit oprávnění a vybrat účet. Účet musí mít udělený přístup tomuto Google uživateli; samotná Search Console tuto roli neuděluje.
5. Nechat doběhnout import WooCommerce přes existující cron `manage.py catalog-sync`, dokončit výběr kategorií/produktů a v E-commerce **schválit a publikovat XML**. Zkontrolovat, že XML URL veřejně vrací úplný soubor.
6. V Merchant kartě kliknout **Připojit schválený XML feed**. Kód použije existující zdroj s touto URL, jinak vytvoří *jeden* zdroj pro denní stahování. Žádné jednotlivé produkty neposílá duplicitně přes Products API.
7. Kliknout **Načíst stav Google** a **Výkon za 28 dní**. Google může vyhodnocovat produkty až s odstupem; prázdná analytika po prvním připojení není důkazem chyby.

## Co balíček nemění

- Fresh Core, datový model produktů, frontu importu ani cron, historii SEO, GA4, GTM, Search Console nebo účetnictví.
- Neaktivuje PPC ani nezakládá placenou reklamní kampaň.
- Nepřipravuje zdroje Heureka, Zboží.cz nebo Meta; následují po ověření Merchant integrace.
- Neposílá objednávky a osobní data do Google Merchant API.

## Důležité omezení

Merchant účty a domény musejí být správně ověřené a mít doplněnou dopravu/vracení zboží v Merchant Center. Google určuje přijetí a způsobilost jednotlivých produktů. Pouze XML export a HTTP přijetí vytvořeného zdroje **nejsou** schválením produktů.

Merchant report ukazuje kliknutí, zobrazení a CTR produktů, nikoli automaticky objednávky z WooCommerce. Objednávky a tržby je třeba ověřit samostatně z WooCommerce/GA4, aby nedošlo k falešné atribuci.

## Ověření

- Python syntaktická kontrola, 23 Jinja šablon a jednotkové testy (mock Google API).
- Žádné živé přihlášení ani skutečné volání Merchant API se v testovacím prostředí nekonalo, protože nemáme přístup k uživatelskému Merchant účtu a produkční databázi.
- Před ostrým provozem je nutný integrační test připojení účtu, založení/ověření zdroje, vyhodnocení Googlem a kontrola v Merchant UI.
