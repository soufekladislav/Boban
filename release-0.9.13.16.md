# Boban 0.9.13.16 – Statistiky + společný výsuvný chat

## Implementováno
- Nová položka **Statistiky** mezi Úkoly a Výsledky v desktopovém a mobilním menu.
- Čtení již uložených snímků GA4 / Search Console; metriky mají období, čas pořízení a popisek původu.
- Přehled stavu existujících konektorů a posledních analytických dat; oddělení nedostupných hodnot od nuly.
- Načítání sedmi dalších GA4 reportů při synchronizaci: kanály, source/medium, země, zařízení, kampaně, události, produkty. Pokud daná kombinace metrik není povolena, chyba je uložena jen pro příslušný report a nedojde k přerušení existující synchronizace.
- Samostatný `manage.py analytics-sync` (GA4, GSC, GTM a PageSpeed), který **nespouští SEO zápisy a operátora**.
- Výsuvný Boban na všech stránkách konkrétního projektu mimo titulní projektový chat (kde je chat již hlavní plochou). Používá shodnou existující konverzaci, historii a endpoint POST; nevzniká druhý chat. Rozepsaný text mezi navigací zůstává v rámci prohlížečové relace.
- Responsivní dvousloupcové panely, na mobilu jeden sloupec. Vizuální standard Poppins, neutrální pozadí, shodné spacing/radius a dostupné štítky.

## Poctivá omezení první fáze
- Statistika *objednávek WooCommerce*, výkonnostní data Merchant/Seznam/Heureka a Pixel/CAPI nejsou nově implementované jako kompletní analytické API reporty; stránka bezpečně zobrazuje jejich stav připojení a dostupnost uložených dat. Není vhodné tvrdit, že připojená služba sama zpřístupňuje obchodní statistiku.
- Chat je nyní dostupný všude, ale **neprovádí zatím samostatné nástrojové analýzy** – to je následující etapa.
- Změny aplikace samotné nezapínají cron v cPanelu. Je nutno nastavit samostatný analytický cron.

## Bezpečné nasazení
1. Zálohuj zdrojový adresář, konfiguraci `.env`, databázi a publikované feedy. Tento ZIP neobsahuje tvoji produkční `.env`, databázi ani vygenerovaná XML.
2. Rozbal aktualizační ZIP do adresáře aplikace, **neodstraňuj** původní nebalené soubory a data. Restartuj Passenger.
3. Otevři projekt → Statistiky a ověř přístup, zobrazení stávajících GA4/GSC dat a všechny karty na mobilu.
4. Otevři např. Úkoly → tlačítko Boban. Pošli neškodný testovací dotaz a ověř, že se zpráva objeví i na hlavní stránce Boban.
5. Na serveru nezávisle přidej pouze **analytický** cron, nejprve ručně ověř jeden běh:

```bash
cd /home2/lauhannq/webbooster.freshcrackers.cz
/home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py analytics-sync
```

Po ověření ve výpisu `crontab -l` přidej (např. pomocí `crontab -e`) řádek:

```cron
15 * * * * cd /home2/lauhannq/webbooster.freshcrackers.cz && /usr/bin/flock -n /home2/lauhannq/webbooster.freshcrackers.cz/.analytics-cron.lock /home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py analytics-sync >> /home2/lauhannq/webbooster-analytics-cron.log 2>&1 # BOBAN_ANALYTICS_SYNC
```

Existující `catalog-sync` nesmí být odstraněn. Synchronizační pravidla v `manage.py` už samostatně respektují intervaly GA4 a GSC (výchozí 12 h), GTM (24 h) a PageSpeed (24 h).

## Ověřeno lokálně
- `python -m py_compile app.py manage.py`
- parsování všech Jinja šablon
- 72 existujících unit testů
- Produkční přístup ke Google/Meta API **nebyl** v tomto testovacím prostředí ověřován.
