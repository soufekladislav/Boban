# Boban / WebBooster 0.9.11 – živý katalog + superadmin databáze

Vychází z aktuální uživatelem dodané instalace 0.9.10 (`boban(3).zip`). Kompletní aplikace, bez provozní databáze a bez tajných klíčů.

## Co je změněno

- `GET /projects/<id>/ecommerce/status` – čtecí autorizovaný JSON endpoint pro **reálný** počet uložených produktů a variant, očekávané počty, stav workflow, čas poslední dávky, aktivitu katalogového workeru, výsledek jeho posledního běhu a případné chyby.
- Stránka E-commerce načítá stav automaticky každých **20 sekund**, pouze při aktivní kartě prohlížeče. Čtení tohoto endpointu nespouští import a nesahá na frontu. Po návratu do karty provede kontrolu okamžitě.
- Jeden společný ukazatel progresu produktů a variant; detail dávkování je stále dostupný v technickém panelu.
- Superadmin `GET /admin/database-usage` (pouze autorizovaný admin) vrací po vyžádání velikost lokální DB (MariaDB: odhad data+index podle `information_schema`, SQLite: velikost souboru) a součet JSON dat produktu/varianty po projektech a jejich vlastnících.
- Admin konzole obsahuje tlačítko **Načíst využití databáze**, souhrn a rozbalitelné tabulky projektů a účtů. Bez automatického dotazování při otevření stránky.

## Důležité vymezení

- **Objem produktů podle projektů = pouze uložené JSON payloady v Bobanovi.** Není to kompletní velikost účtu v DB; neobsahuje alokaci indexů, jiné tabulky ani provozní média.
- **Velikost databáze WooCommerce ve WordPressu nelze z Bobana přímo odečíst.** Pro skutečnou velikost jednotlivých vzdálených e-shopů bude nutné později doplnit výslovně autorizovaný diagnostický přehled do Fresh Core.
- Náročnější skupinové součty se počítají jen na kliknutí superadmina, nikoliv při každém obnovení stavu katalogu.
- Žádné DB migrace, změny klíčů, cronu nebo zapisování do WooCommerce v tomto vydání.

## Nasazení

1. Zálohovat aktuální adresář WebBoosteru, `.env` a databázi (včetně generovaných veřejných feedů).
2. Nahradit soubory aplikace obsahem ZIP. **Nenahrazovat `.env`, databázi ani veřejný feed z běžící instalace.**
3. Restartovat Passenger (standardním způsobem, např. `tmp/restart.txt`, pokud jej hosting používá).
4. Na stránce E-commerce sledovat automatickou změnu údajů po cca 20 s; při přepnutí pryč a zpět se stav obnoví.
5. V Admin konzoli kliknout „Načíst využití databáze“. Údaje jsou dostupné pouze superadminovi.
6. Cron `manage.py catalog-sync` zachovat; tento update ho nemění.

## Testy

- Python `py_compile`, JavaScript `node --check`, Jinja parsování 23 šablon.
- SQLite test skutečného čtecího endpointu a databázových agregací přes izolované testovací schéma.
- Zkušební běh proti skutečné MariaDB a vizuální test v produkci neproběhl.
