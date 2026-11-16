# BOBAN — obchodní zadání a produktový kontrakt (16. 11. 2026)

> **Typ:** návrh k odsouhlasení, nikoliv potvrzení nasazené funkčnosti.  
> **Zdroj:** dosavadní obchodní zadání Fresh Crackers, `architecture.md`, `roadmap-0.7x-0.8.md`, `integrations.md`, aktuální `main` a otevřené PR #1–#7.  
> **Změna procesu:** pozastavit další rozšiřování, nejdřív inventura → stabilizace → měřitelný přínos.

## 1. Jednověté poslání

**Boban je digitální SEO, akviziční a performance specialista, který podle obchodního cíle klienta průběžně vyhodnocuje data, navrhuje prioritní kroky, po schválení je bezpečně vykoná a prokáže jejich skutečný dopad.**

Není to nástroj na maximalizaci interního SEO skóre, generátor reportů nebo obecný AI chatbot. Jeho úspěch se posuzuje podle zákazníkových výsledků a nákladů na jejich získání, nikoliv podle počtu vygenerovaných návrhů.

## 2. Obchodní cíle podle typu projektu

| Typ klienta | Primární výsledek | Podpůrný signál | Co nesmí být zaměňováno |
|---|---|---|---|
| E-shop | Objednávky, tržby, kvalifikovaná návštěvnost, konverzní poměr | Organické návštěvy, produktová viditelnost, zdraví feedů | Kliknutí ≠ objednávka; exportovaný produkt ≠ schválený produkt v kanálu |
| Služby / B2B | Kvalifikované poptávky a jejich hodnota | Relevantní landing pages, Search Console, GA4 | Návštěva kontaktu ≠ platná poptávka |
| Obsah / katalog | Relevantní organická návštěvnost a měřitelné sekundární akce | Indexované a navštěvované stránky, CTR | Imprese ≠ návštěvnost |
| Lokální firma | Relevantní lokální poptávky | Lokální hledání, návštěvy kontaktu, ověřený firemní profil | Obecné SEO skóre ≠ nové zakázky |

**Cílová čísla si nastavuje konkrétní projekt a uživatel.** Nevymýšlíme univerzální růstový slib. Boban musí rozlišovat `nemám data` / `nula potvrzených událostí` / `měření je vadné`.

## 3. Jak klient pozná hodnotu

Boban odpovídá na šest praktických otázek:
1. **Co potřebujeme získat?** Jeden hlavní obchodní cíl, metrika, období a doplňkové priority.
2. **Jak si vedeme teď?** Baseline, čerstvost dat, důvěryhodnost měření, hlavní příležitosti.
3. **Co uděláš a proč?** Konkrétní úkol, zdroj důkazu, očekávaný výsledek a priorita.
4. **Co ode mě potřebuješ?** Pouze schválení změny, doplnění chybějícího důkazu nebo rozhodnutí s obchodním dopadem.
5. **Co právě děláš a kdy to bude?** Čitelný stav úlohy a podložený odhad, případně přiznaná nejistota.
6. **Co to přineslo?** Provedená změna + technické ověření + po odpovídajícím intervalu skutečný výkon a obchodní přínos.

V chatu uživatel zadává cíle a schvaluje rozhodnutí. Přehledy a grafy jsou důkazní/pomocná vrstva, nikoli primární náhrada dialogu.

## 4. Obchodní priority

**P0 – důvěryhodný provoz:** konzistentní verze, bezpečný deploy, funkční administrace, jasná fronta, žádné nekonečné retry nebo skryté publikování, funkční data.

**P1 – skutečný výkon:** definice a evidence cíle; kvalitní baseline; ověřené konverze/objednávky/poptávky; prioritizace podle obchodního potenciálu; ověření dopadu a přehledný dialog.

**P2 – rozšíření kanálů:** PPC Google Ads/Sklik, pokročilá akvizice, další platformy; pouze po měření výkonu a stabilní schvalované exekuci.

## 5. Schvalovací pravidlo

Boban může **autonomně číst, analyzovat, kontrolovat a připravovat návrhy** podle nastavení projektu. Externí zápisy, publikace, změny kampaní, rozpočtů, sledování nebo měření musí projít konkrétním oprávněním a schválením. Po schválení Boban sám zajistí zpracování i bezpečné ověření; uživatel nespouští technický worker.

`AI Engine completed` znamená odpověď modelu, **ne** dokončený SEO zásah nebo konverzi. `HTTP 200` z API není důkaz viditelné změny. Chybějící obchodní data nejsou nula výsledků.

## 6. Hranice dalších Fresh agentů

| Komponenta | Zodpovědnost | Boban smí |
|---|---|---|
| **Viki** | Autoritativní produktový katalog, dodavatelské importy, sklad/ceny/varianty, exporty do Google/Heureka/Zboží/Meta/Pinterest | Číst produktová data, validitu a feed status; řídit akviziční priority, ale nevytvářet druhou katalogovou databázi |
| **Linda** | Plán, publikace a vyhodnocování sociálního obsahu | Navrhovat obchodní záměr a sdílet výkon; nepřebírat autorství sociálního publikování |
| **Fresh Core** | Bezpečná WordPress datová/read-write brána | Číst, vytvářet schválené typované úpravy a zpětně je ověřovat |
| **Fresh AI Engine** | Modelové vyhodnocení, generování a zúčtování | Zadávat úlohy s identitou projektu, měřit náklady a validovat výstupy |
| **Fresh Key** | Identita/token vault a propojení projektů | Přistupovat jen k autorizovaným oprávněním |
| **Karel** | Projektové standardy, dokumentace, změnové řízení a GitHub Issues | Poskytovat rozhodnutí, rizika, důkazy a stav implementace |
| **Ema/Fresh Sales** | Kontakt/CRM a obchodní oslovení podle produktového rozhodnutí | Využívat ověřené obchodní výsledky a stavy, ne duplikovat kontakty bez smluveného kontraktu |

E-commerce exporty, které jsou již v Bobanovi, jsou **přechodná implementace**. Migrace do Viki je zvláštní řízený projekt, nikoliv náhodný refaktor.

## 7. Principy pro každou novou funkci

- Předem jasný uživatelský výsledek a minimálně jedno ověřitelné kritérium přijetí.
- Zdroj pravdy a vlastník dat; žádná paralelní implementace téhož.
- Viditelný stav bez falešných úspěchů a smyšleného ETA.
- U přepisu/odeslání schválení, idempotence, možnost obnovy, audit.
- Testy syntaxe + jednotkové + integrační (když jde o externí API) + produkční smoke test.
- Jeden sledovaný release, jedna produkční verze a rollback; změna není `hotová`, dokud neprojde provozem.
- Bez naměřeného obchodního přínosu nesmí být vývoj nového kanálu vydáván za úspěch.

## 8. Co je výslovně mimo aktuální etapu

Nové PPC publikování, nový katalog, další síť, zásadní redesign, nekontrolovaný obecný WordPress zápis, experimenty bez metrik nebo automatizované rozpočtové zásahy. Tyto práce přijmeme až po P0 a dohodě o P1.

**Otevřené rozhodnutí:** schválit tento produktový kontrakt jako jedinou autoritativní definici Bobana. Dokument není náhradou produkčního auditu.
