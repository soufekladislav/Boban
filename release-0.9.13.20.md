# Boban WebBooster 0.9.13.20 – projektová paměť a obchodně datový chat, etapa 1

**Základ:** 0.9.13.19. Aktualizace zachovává existující data, katalogy, SEO úkoly, GUI, společný výsuvný chat i přístupy k platformám.

## Dodané změny

1. **Diagnostika `analytics-sync`:** vedle dosavadních počtů vypíše u GA4, GSC a GTM po jednotlivých projektech `NOT_CONNECTED`, `DISABLED`, `SKIPPED` (interval ještě neuplynul), `ERROR` (poslední pokus selhal) nebo `DUE`. Neprovádí další API požadavky jen kvůli diagnostice. Nula synchronizací už není zaměňována za nulu dat. Zvlášť upozorňuje, že nula Merchant reportů potřebuje kontrolu stavu.
2. **Trvalá paměť `advisor_memory`:** přidává průkazné záznamy o aktuálním stavu připojení a potvrzeném obchodním cíli. Každý záznam má zdroj, typ, status a čas platnosti; stav konektoru neznamená výkon. Záznamy se při opakované kontrole neduplikují. Zastaralé záznamy jsou označené `stale` a nesmějí být vydávány za současný stav.
3. **Analytické nástroje chatu:** podle dotazu vybírá z `conversion_reality`, `search_demand`, `channel_readiness`, `landing_opportunities`, `project_overview`. Jde o deterministickou extrakci GA4/GSC/Fresh Core kontextu z již uložených snímků a lokálních tabulek, ne o nezávislé živé API volání na každou zprávu. Dodává zdroje, omezení a první ověřitelné náměty.
4. **Audit analýz `advisor_analysis_runs`:** ukládá zvolený nástroj, dotaz, zdrojové reference a výsledek. `GET /projects/<ID>/advisor/evidence` zpřístupňuje oprávněnému uživateli audit paměti a posledních analýz v JSON, ne veřejně.
5. **Chat:** používá analytický kontext a projektovou paměť společně s dosavadní strategií, znalostní knihovnou a úkoly. Explicitně nesmí vyvozovat prodej z návštěvnosti ani navrhovat prvotní instalaci připojeného katalogu. Pokud Fresh AI Engine selže, ukáže omezenou věcnou odpověď nad uloženými daty namísto vymyšlené rady.
6. **Připravenost na další vývoj:** stávající `operator_plans`, `marketing_knowledge`, evidence úkolů a schvalování jsou zachovány. Zápisy do externích systémů se nerozšiřují.

## Co tato verze zatím nedělá

- Neumí autonomně potvrdit hypotézu jako fakt; chybí systematické porovnání výsledků obchodních experimentů v čase.
- Neprovádí plný nástrojový dialog AI s více po sobě jdoucími datovými dotazy; v jedné zprávě vybere jeden hlavní lokální analytický postup.
- Nevymýšlí chybějící objednávky, poptávky, marže, ceny konkurence, přínos katalogů ani provedené akce.
- Nestahuje objednávky z Woo ani potvrzené poptávky; pro to je potřeba samostatný schválený čtecí konektor.
- Nenahrazuje stabilní plánovač marketingových úkolů a vyhodnocování experimentů. To je další vývojový celek.

## Nasazení

1. Záloha kódu + DB + `.env` + feedů. Nemažte produkční adresář.
2. Aktualizační ZIP nahrajte přes stávající instalační postup, zachovejte `.env`, data a adresáře feedů.
3. Restart Passenger. Nové dvě tabulky se vytvoří idempotentně při startu aplikace; žádné staré tabulky se nemažou.
4. Jednorázově pro kontrolu spusťte:

```bash
cd /home2/lauhannq/webbooster.freshcrackers.cz
/home2/lauhannq/virtualenv/webbooster.freshcrackers.cz/3.11/bin/python manage.py analytics-sync
```

5. V chatu se zeptejte „Co lidé hledají na Adrenaline Race?“ a „Jaké reálné objednávky umíme potvrdit?“; pro kontrolu důkazů otevřete po přihlášení `/projects/3/advisor/evidence`.
6. **Nevytvářejte další cron.** Stávající analytický i katalogový worker zůstávají beze změny.

## Testy

- 91 lokálních unit testů, Python compileall.
- Nebyl proveden test startu celé Flask aplikace, protože izolované prostředí nemá balíček `pymysql`; test na produkční MariaDB a Passenger je nutný po nasazení.
- Žádné živé testy Google OAuth, GA4, Search Console a WooCommerce nebyly provedeny.
