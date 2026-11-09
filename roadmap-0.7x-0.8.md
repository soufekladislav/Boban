# Boban – roadmap 0.7.x → 0.8.x

## 0.7.1 – exekuce toho, co už audit umí
Cíl: audit nesmí končit větou „udělej si sám“, pokud jde bezpečnou změnu připravit a provést přes Fresh Core.

Hotovo v tomto buildu:
- společné návrhy title + description + canonical na úrovni stránky,
- ALT obrázků včetně bezpečného write endpointu,
- page-role kontext pro záměrný noindex systémových WooCommerce stránek,
- lepší uzavírání vyřešených findings.

Další typy nálezů zůstávají pouze auditní, dokud nebude bezpečný způsob exekuce: H1, zásah do textu stránky, interní odkazy, redirecty, schema a výkon serveru. Nechceme kvůli „autonomii“ otevřít obecný neomezený zápis do WordPressu.

## 0.7.2 – Search Performance + Google Connector Actions
Cíl: Boban vidí skutečný výkon ve vyhledávání a umí po schválení provést bezpečné změny v podporovaných Google službách.

Hotovo v tomto buildu:
- Google Search Console OAuth s read/write scope, property selection a automatický 12h sync,
- dotazy/fráze, TOP 3/10/20/50, gainers/decliners, nízké CTR, příležitosti 4–20 a kanibalizace,
- URL Inspection a schvalovaný zápis sitemap přes jednotný action workflow,
- Google Analytics 4: Organic Search sessions, users, engagement, key events, revenue a landing pages,
- schvalovaný GA4 write: vytvoření Key Event pouze pokud má vybraná property právo editace,
- jednotná vrstva provider/operation → návrh → editace → schválení → fronta → zápis → ověření,
- mobilní KPI panely jako swipe/auto-rotating carousel; desktopové rozložení zůstává beze změny,
- omezená retence detailních analytických snapshotů, aby 12h synchronizace neplnila DB donekonečna.

Další konektory přesouváme do následujících verzí: PageSpeed/CrUX, GTM, Bing, Seznam/IndexNow, Business Profile a podle typu webu Merchant Center.

## 0.7.3 – plánování a živá aplikace
Cíl: Boban nemusí čekat na ruční spuštění auditu.
- plán kontrol na úrovni projektu,
- diff Fresh Core: nové/změněné/smazané stránky,
- pravidelné crawly v dávkách,
- automatické vytvoření návrhů, ne automatická publikace,
- notifikace „připravil jsem 14 změn, zkontroluj a potvrď“,
- režim Bobana: aktivní / standard / pasivní.

## 0.8.0 – Expert Workflow
Cíl: z nástroje udělat digitálního SEO/performance kolegu.

Vrstva 1 – Manuál SEO specialisty
- cíle a priority podle typu webu,
- technické SEO, indexace, obsah, interní odkazy, image SEO, structured data, lokální SEO, autorita,
- definice „hotovo“ pro každý typ úkolu,
- pravidla, kdy nález není problém (např. noindex košíku),
- zdroje jistoty: fakta z webu / data z konektorů / doporučení / hypotéza.

Vrstva 2 – Kontext webu
Boban klasifikuje každou URL: homepage, kategorie, produkt, služba, článek, landing page, systémová stránka, kontakt, účet atd. Hodnotí ji podle účelu, ne podle univerzálního checklistu.

Vrstva 3 – Goal planner
Uživatel zadává cíl („zvýšit organickou návštěvnost blogu“, „více poptávek“, „prodávat produkt X“). Boban se doptá na chybějící informace a vytvoří plán SEO/PPC práce.

Vrstva 4 – Proaktivní pracovní cyklus
pozorování → interpretace → návrh → příprava práce → kontrola vlastní práce → předložení ke schválení → exekuce → ověření → měření dopadu → další krok.

Vrstva 5 – Projektová paměť a učení
Ne „přetrénování modelu“, ale strukturovaná paměť v DB:
- cíle zákazníka,
- schválené/odmítnuté návrhy a důvody,
- preferovaný tone of voice,
- rozhodnutí o indexaci,
- experimenty a výsledky,
- co už bylo vyřešeno a co se nesmí znovu navrhovat bez nové evidence.

Vrstva 6 – Chat jako hlavní rozhraní
Boban po otevření aplikace řekne, co se změnilo, co připravil, co potřebuje schválit a co doporučuje dál. Odkazy a akční tlačítka vedou přímo na konkrétní úkoly. Analytické obrazovky zůstávají jako sekundární expertní vrstva.

## 0.8.1+ – PPC/performance
Stejný pracovní model rozšířit na placené kampaně:
cíl → data → návrh kampaně → editace → schválení → publikace → spend/conversions/ROAS → optimalizace.
