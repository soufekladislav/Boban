# Web Booster – integrace a pořadí připojení

## Princip

Konektory dělíme na:

1. **Web / CMS** – Fresh Core, crawler.
2. **Organické vyhledávání** – Google Search Console, Bing Webmaster, Seznam Webmaster/IndexNow.
3. **Chování a konverze** – Google Analytics 4.
4. **Měření / tagy** – Google Tag Manager.
5. **Lokální viditelnost** – Google Business Profile.
6. **PPC** – Google Ads, Sklik; později případně Microsoft Advertising/Meta.

Search Console není závislá na Google Analytics ani Google Tag Manageru. Každý konektor má vlastní účel a lze ho připojit samostatně.

## 1. Fresh Core – aktivní

**Účel:** WordPress struktura, SEO metadata, kontext obsahu a bezpečný write bridge.

- read: statický Connector Manifest
- write: samostatný klíč, explicitně zapnutý ve WordPressu
- Boban nikdy nepotřebuje libovolný SQL/PHP zápis

## 2. Google Search Console – aktivní od 0.3.0; v 0.4.0 se může obnovovat automaticky přes cron

**OAuth scope od 0.7.2:** `https://www.googleapis.com/auth/webmasters` (read/write).

**Data:** clicks, impressions, CTR, average position, queries, pages, query→page kombinace, URL Inspection.

**Write:** submit/delete sitemap. Zápis vždy probíhá přes schvalovaný úkol; Search Console neposkytuje obecné API pro ruční požadavek na indexaci běžné URL.

**Použití:** organický výkon, prioritizace SEO, baseline/dopad změn.

## 3. Google Analytics 4 – aktivní od 0.7.2

**OAuth scopes:** `https://www.googleapis.com/auth/analytics.readonly` + `https://www.googleapis.com/auth/analytics.edit`

**Data:** sessions/users, source/medium, landing pages, events, key events/conversions, revenue podle typu projektu.

**Použití:** zjistit, zda návštěvnost skutečně vede k poptávce/nákupu – ne pouze k impresím a klikům.

**Write:** v 0.7.2 umí Boban po schválení vytvořit GA4 Key Event přes Admin API. Další konfigurační operace budeme přidávat přes stejnou Connector Action Layer.

## 4. Google Tag Manager – další

**První scope:** `https://www.googleapis.com/auth/tagmanager.readonly`

Později podle režimu schvalování lze přidat edit/publish scopes.

**Data/řízení:** účty, kontejnery, workspaces, tags, triggers, variables, Google tag config.

**Použití:** kontrola, zda se konverze opravdu měří; později řízené nasazení měření.

## 5. Google Business Profile – další

**OAuth scope:** `https://www.googleapis.com/auth/business.manage`

**Data:** lokace/profily, performance metrics a search keyword impressions.

**Použití:** lokální SEO – Fresh Develop a další firmy s fyzickým/lokálním působením.

## 6. Bing Webmaster Tools – další

**OAuth:** Bing Webmaster OAuth 2.0.

Pro read-only začít scope `Webmaster.read`; write funkce až později přes `Webmaster.manage`.

**Data:** crawl, index, keyword/rank & traffic stats, backlinks; možnost URL/sitemap submission.

Pozn.: Microsoft ukončil legacy SOAP/POX Bing Webmaster API 31. 8. 2026; nové napojení stavět na aktuálním REST/OAuth rozhraní.

## 7. Seznam Webmaster + IndexNow – další

Seznam Webmaster poskytuje informace o crawl/indexaci a historicky také API pro detailnější data. Přesné současné autentizační rozhraní ověříme při implementaci konektoru.

**IndexNow** lze použít samostatně pro hlášení nových/změněných URL Seznamu a dalším zapojeným vyhledávačům.

**Použití:** české weby, rychlejší oznámení změn URL a kontrola SeznamBot/indexace.


## Backlink data / autorita – plánováno

Od 0.7.0 Web Booster **neodhaduje autoritu číslem bez dat**. Interní prolinkování umí sledovat crawler, ale externí zpětné odkazy vyžadují samostatný zdroj.

Možné vrstvy:
- Bing Webmaster data, pokud budou pro daný účet/API dostupná v potřebném rozsahu,
- specializovaný backlink provider (vybereme až podle ceny, API a pokrytí),
- vlastní evidence link opportunities a získaných odkazů.

**Použití:** referring domains, nové/ztracené odkazy, link opportunities, relevantní oborové zdroje a měření získaných odkazů. Boban nebude vyrábět ani doporučovat link farmy nebo masový nákup odkazů.

## 8. Google Ads – PPC fáze

**OAuth scope:** `https://www.googleapis.com/auth/adwords`

**Data/akce:** účty, campaigns, ad groups, keywords, search terms, spend, clicks, conversions, conversion value, bidding, ads/assets.

**Použití:** plán kampaně → schválení → realizace → náklady → konverze → ROAS → dopad.

Google Ads připojíme až po stabilizaci SEO + konverzního měření, aby Boban neoptimalizoval kampaně bez spolehlivých konverzních dat.

## 9. Sklik – PPC fáze

**Účel:** české PPC a hledanost, náklady, kampaně a výkon.

Před implementací ověříme aktuální API autentizaci a metody Skliku; Web Booster už má obecný `channel=ppc`, takže konektor nebude vyžadovat změnu základního datového modelu.

## Doporučené pořadí

1. Fresh Core + crawler – hotovo.
2. Google Search Console – výkon + write sitemap hotovo v 0.7.2.
3. GA4 – organic výkon + Key Event write hotovo v 0.7.2.
4. GTM – audit a správa měření.
5. PageSpeed / CrUX – reálná rychlost a Core Web Vitals.
6. Bing + Seznam/IndexNow – další vyhledávače.
7. Google Business Profile – lokální SEO tam, kde dává smysl.
8. Merchant Center – pro e-shopy.
9. Google Ads + Sklik – PPC plánování a realizace.
10. Microsoft Advertising / Meta Ads – podle potřeby.
11. Clarity – volitelný UX kontext.

## 10. PageSpeed / Chrome UX Report – technický výkon

**Účel:** Core Web Vitals (LCP, INP, CLS), laboratorní i reálná uživatelská data tam, kde jsou dostupná.

**Použití:** Boban může odlišit čistě SEO nastavení od problémů rychlosti/UX a měřit dopad technických zásahů.

## 11. Google Merchant Center – e-commerce

**Účel:** diagnostika produktového feedu, stav produktů a Shopping plochy. Připojovat jen u e-shopů, kde to dává smysl.

## 12. Microsoft Advertising / Meta Ads – další PPC kanály

Datový model `channel=ppc` je pro ně už připravený. Připojíme je až po stabilizaci konverzního měření, stejně jako Google Ads a Sklik.

## 13. Microsoft Clarity – volitelný UX kontext

Doplňková vrstva pro chování návštěvníků. Není podmínkou SEO ani PPC; zapojíme ji jen tam, kde přidá praktickou hodnotu a bude dostupné vhodné API/export.
