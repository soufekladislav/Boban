# BOBAN — projektové řízení, roadmap a pravidla uzavírání úkolů

**GitHub repository:** https://github.com/soufekladislav/Boban  
**GitHub Project:** https://github.com/users/soufekladislav/projects/11  
**Vytvořeno:** 16. 11. 2026 · **stav:** návrh řízení projektu k odsouhlasení

## 1. Reset vývoje

1. Pozastavit přidávání nových funkcí; žádné nové marketingové platformy ani generické refaktory.
2. Nedělat žádný neověřený merge/deploy. Neaktivovat hromadnou publikaci před produkčním smoke-testem.
3. Zapsat jeden produktový kontrakt a inventuru kódu, CI, dat, konektorů, provozu a pozorovaných problémů.
4. Pracovat pouze přes GitHub Issues a odpovídající PR. PR není Issues backlog.
5. Aktivní WIP: nejvýše dvě implementační Issues současně; ostatní čekají v Backlog/Ready.
6. Po každém řešení aktualizovat provozní stav a dokumentaci, ne další „release pod release“.

## 2. Priority

**P0 — stabilizace**: bezpečný release/rollback, oprava admin 500, skutečná fronta, Fresh Core 404, srozumitelná evidence, kontrola cronů, zdroje pravdy a bezpečnost exportních artefaktů.

**P1 — obchodní hodnota**: sjednocení goal-first plánovače, ověřené objednávky/poptávky, měření změny, přínos úkolů, přirozený dialog a report, rozhraní s Viki/Lindou, evidence nákladů AI.

**P2 — škálování**: plné PPC a další akviziční kanály po spolehlivém měření, expertní automatizace a cílené rozšíření konektorů.

## 3. Fáze s podmínkami přechodu

### Fáze A: Bezpečný základ (P0)
- Schválený produktový a technický kontrakt.
- Jediný průchod `release → main → lokální disk → Passenger → otisk souboru`.
- Samostatné read-only diagnostiky `main`/server, cron heartbeat, konektory, jobs.
- Admin, Konektory, Úkoly a Chat fungují bez 500.
- Jedna schválená SEO změna je bezpečně provedena **a nezávisle ověřena**; chybějící cíl končí jako terminální chyba s vysvětlením.
- Při souběhu nehrozí duplicita, nekonečný retry ani ztráta schválení.
- Katalogové crony jsou oddělené od SEO zápisu.
- Produktové feedy nesmějí obsahovat skryté produkční klíče v git historii bez ochrany.

### Fáze B: Obchodní řízení (P1)
- Každý pilotní projekt má jeden hlavní cíl, měřitelnou definici konverze a baseline.
- Ověřený zdroj konverzí; stav „unknown“ tam, kde chybí.
- Nejvýše pět priorit, každá s důkazem, očekávaným přínosem, cenou, rizikem a další akcí.
- Chat přirozeně vysvětlí, co Boban udělal, potřebuje schválit a co přineslo.
- Po uplynutí dohodnutého období Boban porovná baseline a reálný vývoj, nezaměňuje korelaci za prokázanou příčinu.
- Základní čitelné náklady AI Engine / projektu.

### Fáze C: Rozšíření (P2)
- PPC read-only report, potom návrhy, schvalování, rozpočtové limity a až poté write.
- Řízené agent-to-agent kontrakty (Viki katalog; Linda social; Karel projekt).
- Vyhodnocení přínosu vůči nákladům dřív než další distribuční platformy.

## 4. Doporučené sloupce Project #11

- **Inbox** – přijaté podněty bez rozboru;
- **Backlog** – platné, ale neaktuální;
- **Ready** – jasné zadání, závislosti a kritéria přijetí;
- **In progress** – max. 2 současné Issues;
- **Review / QA** – kód/CI + požadovaný integrační test;
- **Blocked** – konkrétní překážka, vlastník a next step;
- **Done** – dokončený a doložený výsledek.

Doporučená vlastní pole: `Priority (P0/P1/P2)`, `Area`, `Release`, `Owner`, `Evidence`. Stav zůstává samostatně v Project, technická priorita v názvu Issue pro viditelnost bez project fields.

**Pozn.:** GitHub propojení v tomto chatu nepodporuje přímé přidávání položek do GitHub Projects V2. Issues budou založeny v repozitáři; připojení ke Project #11 je samostatný ruční nebo projektový Auto-add krok. Nezaměňovat „Issue založeno“ za „je na tabuli“.

## 5. Formát každé Issue

- Proč to potřebujeme z pohledu klienta.
- Jaký je současný stav a důkaz (soubor, chybový log, PR).
- Konkrétní rozsah a co je mimo rozsah.
- Závislosti.
- Testy/akceptace: minimálně jeden automatický a podle typu jeden produkční smoke test.
- Definition of Done: závazek, reference na PR, CI, otisk nasazeného commitu, doložený výsledek, aktualizované docs.
- Bezpečnost: žádné cizí zápisy bez explicitního souhlasu.

## 6. Release governance

- Každá funkce má **jednu Issue**; změna se vztahuje k jednomu rozsahu.
- Implementace z Issue, krátká větev, PR do main. Žádné 5-vrstvé řetězce PR.
- Jestliže vznikne hromadný release PR, musí mít mapu původu všech dílčích změn a nesmí automaticky sloučit nesouvisející goal-first experiment.
- `APP_VERSION` samo nedokládá skutečně běžící soubory. Nasazení ověřit pomocí odpovídajícího fingerprintu, restartu Passenger a endpoint health.
- Kódové testy samy neověří cPanel cron, credentials, API write ani obchodní přínos.
- U kritického P0 mít rollback a zálohu databáze, konfiguračních tajemství, runtime souborů.
- Zákaz ručního spouštění 100 neověřených starých SEO akcí pro „test workeru“.

## 7. Předběžná rozhodnutí k odsouhlasení

1. Boban je **SEO/akvizice/performance agent**, ne trvalý vlastník katalogů a publikace na sítích.
2. SEO změny se vykonávají automaticky **po schválení** a pouze po vyřešení bezpečnosti workeru.
3. Hlavním vstupem do P1 je potvrzená konverzní metrika, ne další nové konektory.
4. Zmrazit další platformové rozšíření (včetně rozvoje Pinterest API) do dokončení P0.
5. Po ověření vydání PR #7 sjednotit historii, ale neztratit samostatný PR #1; žádné nucené sloučení bez integrace a testů.

## 8. Co nepřepisovat a co netvrdit

Při konsolidaci neodstraňovat `.env`, databázi, tajné klíče, uživatelské projekty, historii úloh/akcí, publikované feedy ani logy. Historické release dokumenty zachovat jako archiv, ale označit jediný aktuální plán.

**Aktuální produkční stav je z GitHubu neznámý.** Uzavření P0 nelze potvrdit bez výsledků z cPanelu/Passenger a skutečných projektových dat.
