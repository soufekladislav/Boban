# WebBooster / Boban 0.9.13 — systémová registrace Google Merchant API

## Co je nové
- **Admin konzole → Systémové integrace → Google Merchant API**: formulář pro jednorázovou registraci Cloud projektu pomocí `accounts.developerRegistration.registerGcp`.
- Pouze přihlášený administrátor; POST s CSRF tokenem, výslovné potvrzení účtu a administrátorských oprávnění, OAuth `https://www.googleapis.com/auth/content` se stavovým tokenem a expirací 15 minut.
- Úspěšná registrace se uchová v `system_settings` (Merchant ID, kontaktní e-mail, odpověď `gcpIds`, datum). Žádné API heslo ani uživatelské OAuth tokeny nejsou uloženy v systémovém záznamu registrace.
- Nové připojení Merchant v projektových Konektorech uloží OAuth přihlašovací údaje i tehdy, když `accounts.list` dočasně odmítne požadavek kvůli chybějící registraci. Po registraci lze znovu použít „Připojit Merchant přes Google“.
- Stávající Search Console, GA4, GTM, Fresh Core, katalogové produkty, feedy a cron jsou zachovány.

## Instalace
1. **Zálohuj** aplikaci, produkční `.env`, databázi a `generated_feeds`. Balíček neobsahuje produkční `.env`, databázi, logy ani vygenerované XML.
2. Nahrávej **přes existující aplikaci** a přepiš soubory, neodstraňuj celý adresář. Nemaž `generated_feeds` ani uživatelské datové soubory.
3. Restartuj Passenger (`tmp/restart.txt` se smí obnovit na serveru); cron `manage.py catalog-sync` ponech beze změn.
4. Otevři **Admin konzole → Systémové integrace → Google Merchant API**.
5. Zvol jeden **firemní produkční Merchant účet s ověřeným webem**, u něhož má přímo přihlášený Google uživatel roli **Admin**. Zadej jeho Merchant ID a kontaktní Google e-mail; potvrď volbu. Registrace patří Google Cloud projektu, nikoli Adrenaline Race jako jednotlivému zákazníkovi.
6. Klikni na **Přihlásit Google a registrovat WebBooster**, vyber Google účet s přímou administrátorskou rolí k registračnímu Merchant účtu, odsouhlas `auth/content` a vrať se do aplikace. **Úspěch** musí být potvrzen návratovým záznamem `accounts/.../developerRegistration` a `gcpIds`.
7. V projektu Adrenaline Race otevři **Konektory → Google Merchant Center → Připojit Merchant přes Google**, vyber Merchant účet Adrenaline Race (5073368700) a až poté připoj schválené XML.

## Důležité
- Registrace Cloud projektu je **jednorázová napříč jeho uživateli a spravovanými Merchant účty**; každý zákazník musí i nadále udělit vlastní OAuth souhlas a mít Merchant práva.
- Google může odmítnout registraci podúčtu spravovaného pouze přes nadřazený účet. Pro registrační účet je třeba **přímá** administrátorská role a ověřený web. Název Firemní Merchant účtu v nabídce ostatních účtů toto samo o sobě nezaručuje.
- Záměrně **není automatický výběr či tvrdě předvyplněné Merchant ID**: Google Cloud projekt lze registrovat právě k jednomu Merchant účtu. Správný účet před kliknutím ověř.
- Registrace se nesmí opakovat, pokud byla úspěšně potvrzena. Změnu identity řeš řízeně a nejprve podle Google pravidel `unregisterGcp`.
- Registrace API nezakládá Merchant účet a sama neposílá produktový feed.

## Kontroly
- Kompilace Python 3.11: OK.
- Parsování všech Jinja šablon: OK.
- 11 lokálních unit testů: OK.
- **Živý OAuth, MariaDB a Merchant API nebyly v tomto prostředí ověřeny** — tyto části se musí otestovat na produkčním účtu po nasazení.
