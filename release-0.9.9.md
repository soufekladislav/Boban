# WebBooster 0.9.9 – Diagnostika a výběr katalogu

- Výchozí stav: plný Boban 0.9.8; nedotýká se Fresh Core ani datové migrace.
- Superadmin → Diagnostika pro podporu → bezpečný manifest (nová samostatná URL). Obsahuje stavy projektových synchronizací, stav plánovače, chyby jako kategorie a počty položek. Žádný zdrojový kód, přístupové klíče, e-mail ani syrové produktové záznamy.
- Pokud SECRET_KEY nemá min. 32 znaků, nastav DIAGNOSTIC_MANIFEST_SECRET na 32+ náhodných znaků. Odkaz lze zneplatnit změnou tohoto tajemství a restartem. Kdo má odkaz, může číst diagnostické počty — sdílej jen důvěryhodné podpoře.
- Kategorie jsou zobrazeny hierarchicky v rolovacím stromu. Produkty a varianty jsou v samostatném rolovacím seznamu vedle; položky z vyloučených kategorií se vůbec nezobrazí. Individuálně vyloučené produkty zůstávají viditelné pro opětovné zahrnutí.
- Zatím **není potvrzena příčina zastavování automatické fronty**: v superadmin manifestu zkontroluj `scheduler.last_seen`, `catalogs[*].workflow.mode`, `workflow.error_kind`, `products.next_page` a `variants.next_page`. Pokud se `last_seen` neposouvá, prověř cron `python manage.py tick` nebo `python manage.py catalog-sync`.
- Manifest je pouze diagnostický; neobsahuje nové přístupové právo k obchodu. Starý `/developer/.../manifest.json` v této verzi vyžaduje přihlášení superadmina, protože obsahuje i zdrojové soubory; pro sdílení používej výhradně nový bezpečný manifest.
- Nasazení: záloha databáze, aplikace a `.env`; nahrát celý balíček, zachovat provozní `.env` a adresář `generated_feeds`, restart Passenger; ověřit Desktop/Mobil a provozní manifest.
- Kontroly: `python -m py_compile app.py feed_workflow.py manage.py`; Jinja syntax a testy před nasazením.
