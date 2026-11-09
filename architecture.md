# Web Booster 0.7.2 – architektura

## Hlavní workflow

`sources -> audit -> findings -> proposal -> user edit -> approval -> execution -> verification -> metrics -> impact`

Boban nikdy nepublikuje AI návrh přímo. Návrh je samostatná pracovní verze, uživatel ji může upravit a publikace proběhne až explicitním schválením přes Fresh Core write bridge.

## SEO audit

Audit je rozdělen na:

1. **Technické SEO**
   - crawl / HTTP stav
   - indexace / noindex
   - canonical
   - renderování a dostupnost
   - později sitemap, redirects, structured data, PageSpeed / CrUX

2. **Obsahové SEO**
   - SEO title
   - meta description
   - H1
   - thin content / duplicity
   - obrázky a ALT; od 0.7.1 + Fresh Core 0.4.4 lze ALT připravit, upravit, schválit, zapsat a ověřit
   - tématická srozumitelnost
   - interní prolinkování

3. **Autorita a odkazy**
   - interní link graph už částečně měří crawler
   - externí backlink autorita se neskóruje bez spolehlivého zdroje
   - později backlink opportunity workflow

## Scoring 0.7

Starý model dával `opportunity=0`, takže velké weby často končily blízko 100/100 navzdory desítkám až stovkám nedostatků.

Nový model:
- penalizuje i opportunities
- seskupuje stejné problémy z Fresh Core a crawleru do score families, aby je nesčítal dvakrát
- používá prevalenci problému vůči počtu SEO URL
- nízké pokrytí crawleru snižuje maximální technické skóre
- externí autoritu neodhaduje

Celkové `SEO preparedness` je nyní kombinace technického a obsahového skóre. Autorita se zobrazuje zvlášť jako `bez dat`, dokud nepřipojíme backlink zdroj.

## Návrhy a revize

`actions.proposed_json` = finální verze připravená k publikaci.

`actions.ai_proposal_json` = původní Bobanův návrh.

`action_revisions` uchovává historii jednotlivých verzí (`boban`, `user`).

## Důkaz a dopad

Po publikaci:
1. Fresh Core potvrdí zápis,
2. crawler ověří výsledné veřejné HTML,
3. Search Console / další analytika později změří reálný dopad.

Projektový přehled ukazuje:
- Co je hotové
- Co to přineslo
- Jasný důkaz
- Co nás čeká

## Budoucí PPC

PPC zůstává samostatný channel nad stejným obecným workflow:

`plan -> proposal -> user edit -> approval -> campaign execution -> cost/conversion metrics -> impact`

## Exekuce 0.7.1

Bezpečný write allow-list nyní pokrývá:
- WordPress SEO metadata: title, description, canonical, noindex, nofollow,
- ALT text WordPress image attachmentu.

Boban slučuje více metadata findings jedné stránky do jednoho koherentního návrhu. H1, obecné změny obsahu, interní odkazy, redirecty a schema zatím nemají obecný write přístup; nejdřív pro ně vytvoříme bezpečné typované operace místo libovolného zápisu do WordPressu.


## v0.7.2 – Connector Action Layer

Úkol už není svázaný pouze s Fresh Core. `actions.provider` určuje cílovou službu (`fresh_core`, `search_console`, `ga4`) a `actions.operation` konkrétní allow-listovanou operaci. Worker volá jednotné `apply_action()` a `verify_action()`.

Aktuální write operace:
- Fresh Core: SEO metadata + image ALT
- Search Console: submit/delete sitemap
- GA4: create Key Event

Žádný konektor nedostává libovolný „raw API“ příkaz z chatu. Boban vytváří pouze allow-listované návrhy, uživatel je může upravit a až schválený úkol jde do durable DB fronty.

`search_performance` ukládá normalizovaný snapshot dotazů z GSC; plný JSON snapshot zůstává v `source_snapshots`.
