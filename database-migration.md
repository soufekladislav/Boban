# Web Booster – migrace SQLite → MariaDB/MySQL (aktuální pro 0.7.2)

Web Booster umí dva režimy:

- bez `DATABASE_URL` dál používá stávající `webbooster.db` (SQLite),
- s `DATABASE_URL=mysql://...` používá MariaDB/MySQL.

Tím lze aplikaci nejdřív bezpečně aktualizovat a databázi přepnout až po ověřené migraci.

## 1. Záloha

Před migrací zazálohuj:

- `.env`
- `webbooster.db`
- celý aktuální adresář aplikace

Neměň `SECRET_KEY`. Šifrované write keys a OAuth refresh tokeny jsou na něj navázané.

## 2. V cPanelu vytvoř prázdnou databázi

V **MySQL® Databases / MySQL Database Wizard**:

1. vytvoř databázi, např. `lauhannq_webbooster`,
2. vytvoř uživatele, např. `lauhannq_webboosterusr`,
3. přidej uživatele k databázi,
4. dej mu **ALL PRIVILEGES** nad touto databází.

## 3. Nahraj aktuální Web Booster

Nejdřív nech ve `.env` `DATABASE_URL` prázdnou, takže aplikace po restartu stále poběží nad SQLite.

Ve virtualenv:

```bash
cd /home2/lauhannq/webbooster.freshcrackers.cz
pip install -r requirements.txt
```

## 4. Otestuj spojení a migruj data

Do shellu nastav `DATABASE_URL` pouze pro migrační příkaz. Příklad:

```bash
export DATABASE_URL='mysql://DB_USER:DB_PASSWORD@localhost/DB_NAME'
python migrate_sqlite_to_mysql.py --sqlite /home2/lauhannq/webbooster.freshcrackers.cz/webbooster.db
```

Pokud heslo obsahuje `@`, `:`, `/`, `#`, `%` apod., URL-encode ho.

Migrační skript:

- vytvoří cílové tabulky přes aktuální schema,
- odmítne pokračovat, pokud cílové tabulky už obsahují data,
- zachová původní ID,
- přenese účty, heslové hashe, projekty, chat, audity, nálezy, úkoly, GSC snapshoty a šifrované secrets,
- obnoví fingerprinty a SEO skóre,
- porovná počty řádků zdroj/cíl.

Na konci musí být u všech tabulek `OK`.

## 5. Přepni produkční aplikaci

Až migrace projde, přidej do skutečného `.env`:

```env
DATABASE_URL=mysql://DB_USER:DB_PASSWORD@localhost/DB_NAME
```

`DATABASE_PATH=webbooster.db` může zůstat; při nastaveném `DATABASE_URL` se nepoužívá.

Restartuj Passenger aplikaci a otevři:

```text
https://webbooster.freshcrackers.cz/health
```

Očekávej:

```json
"database_backend": "mysql"
```

Pak zkontroluj:

- přihlášení stávajícím účtem,
- oba weby,
- historii chatu,
- SEO nálezy,
- Úkoly / Archiv,
- Konektory.

## 6. SQLite zatím nemaž

Soubor `webbooster.db` nech alespoň několik dní jako rollback zálohu. Pokud by bylo potřeba návrat, odeber `DATABASE_URL` z `.env`, restartuj Passenger a aplikace se znovu přepne na SQLite.

## 7. Automatická synchronizace

Po ověření databáze nastav v cPanelu Cron Job každou minutu jako bezpečnostní síť workeru:

```bash
* * * * * /CESTA/K/VIRTUALENV/bin/python /home2/lauhannq/webbooster.freshcrackers.cz/manage.py tick >> /home2/lauhannq/webbooster.freshcrackers.cz/cron.log 2>&1
```

Použij přesnou cestu k Pythonu z cPanel **Setup Python App**.

`manage.py tick` zpracuje durable frontu, kontroluje Fresh Core manifesty a synchronizuje pouze weby, jejichž manifest se změnil. Schéma 0.7.x navíc automaticky doplní historii revizí návrhů (`action_revisions`).


## 0.7.2

Při startu se bez ruční SQL migrace doplní:
- `actions.provider` (default `fresh_core`)
- `actions.operation`
- nová tabulka `search_performance` pro normalizované Search Console query metriky a trendové porovnání.

Existující úkoly jsou automaticky označeny providerem `fresh_core` a `operation=action_type`.
