# BOBAN — issue register a GitHub Project #11

**Repo Issues:** https://github.com/soufekladislav/Boban/issues  
**Projekt:** https://github.com/users/soufekladislav/projects/11  
**Srovnání PR:** https://github.com/soufekladislav/Boban/pulls  
**Vlastník produktových rozhodnutí:** Fresh Crackers; konkrétní implementační owner se určí při převzetí Issue.

## Zastřešující Issue

- **[#8 – Restart Bobana](https://github.com/soufekladislav/Boban/issues/8)**: obchodní kontrakt, inventura, roadmap, schválení technického postupu.

## P0 – bezpečná a důvěryhodná aplikace

| Issue | Oblast | Doporučené pořadí | Souvislost |
|---|---|---:|---|
| [#9](https://github.com/soufekladislav/Boban/issues/9) | Jeden release, main/desktop/server, rollback | 1 | PR #7; PR #1 řešit samostatně |
| [#14](https://github.com/soufekladislav/Boban/issues/14) | Bezpečnost runtime artefaktů v public git | 1 (paralelně) | `generated_feeds`, lock soubory |
| [#12](https://github.com/soufekladislav/Boban/issues/12) | Admin 500, úkoly, názvy a datumy | 2 | PR #4/#7 |
| [#13](https://github.com/soufekladislav/Boban/issues/13) | Konektory, live health a denní sync | 2 | PR #2 |
| [#11](https://github.com/soufekladislav/Boban/issues/11) | Fresh Core 404 a SEO ověřený zápis | 3 | PR #5 + WP Fresh Core |
| [#10](https://github.com/soufekladislav/Boban/issues/10) | Worker a autonomní bezpečná exekuce | 4 | PR #2/#3; závisí na #9/#11/#12 |
| [#15](https://github.com/soufekladislav/Boban/issues/15) | Feed validita a Pinterest bez duplikace katalogu | 4, vedle workeru | PR #6/#7, provázat Viki |

**P0 není hotové, dokud není potvrzen alespoň jeden reálný end-to-end SEO zápis, fungující administrace, ověřené crony a známá produkční verze.**

## P1 – obchodní výkon

| Issue | Oblast | Hlavní závislost |
|---|---|---|
| [#17](https://github.com/soufekladislav/Boban/issues/17) | Objednávky, poptávky, měření a data | #13 |
| [#16](https://github.com/soufekladislav/Boban/issues/16) | Goal-first plánovač a prioritizace, PR #1 | #10, #17 |
| [#18](https://github.com/soufekladislav/Boban/issues/18) | Výsledek a prokázaný dopad jednotlivé akce | #10, #17 |
| [#19](https://github.com/soufekladislav/Boban/issues/19) | Chat jako přirozené rozhraní | #16, #18 |
| [#20](https://github.com/soufekladislav/Boban/issues/20) | Kontrakty Viki/Linda/Karel | #15, #16 |
| [#21](https://github.com/soufekladislav/Boban/issues/21) | AI Engine náklady a limity | #10, #17 |

## P2 – rozšíření

- [#22 – Google Ads a Sklik PPC](https://github.com/soufekladislav/Boban/issues/22): blokováno P0/P1. Nezavádět reklamní rozpočtové změny, dokud neměříme skutečné výsledky.

## Doporučené nastavení Project #11

1. V GitHub Project #11 zkontrolovat **Settings → Workflows** a nastavit **Auto-add to project** pro nové Issues repozitáře `soufekladislav/Boban`, pokud je funkce u projektu dostupná.
2. Pokud ne, v tabuli zvolit **Add item → Add issue from repository Boban**; vybrat Issues #8–#22.
3. Nastavit **Status**: Inbox, Backlog, Ready, In progress, Review / QA, Blocked, Done.
4. Nastavit **Priority** P0, P1, P2 a **Area** (Release, Worker, Core, Admin, Data, SEO, E-commerce, AI, UX, Integrations, PPC).
5. Všechny položky začít jako **Backlog** kromě #8 (koordinace), #9 a #14 (priorita ke zpracování); žádná Issue se nepovažuje za Done.
6. Limitovat současnou implementaci na **max. 2 Issues**.
7. Při předání používat Issue jako jednotné zadání; konkrétní PR uvést v Issue a po testu doplnit doklad produkční verze.
8. Nespouštět hromadné SEO zápisy a nemergovat PR #7 bez ověření výrobního workflow.

**Současné omezení:** tento účetní GitHub konektor nemá akci pro správu GitHub Projects V2. Issues byly založeny v repozitáři, nikoli automaticky přiřazeny do tabule. Proto to v této dokumentaci výslovně rozlišuji.

## Otevřená PR a jejich osud

| PR | Obsah | Stav k auditu | Předběžné rozhodnutí |
|---|---|---|---|
| [#1](https://github.com/soufekladislav/Boban/pull/1) | Obchodní goal-first | otevřený, samostatný | **Hold**, vyhodnotit v #16 |
| [#2](https://github.com/soufekladislav/Boban/pull/2) | Worker/sync | otevřený, vrstvený | **Hold**, pod #9/#10/#13 |
| [#3](https://github.com/soufekladislav/Boban/pull/3) | Autonomie/ETA | otevřený, vrstvený | **Hold**, pod #10 |
| [#4](https://github.com/soufekladislav/Boban/pull/4) | Úkoly/názvy/daty | otevřený, vrstvený | **Hold**, pod #12 |
| [#5](https://github.com/soufekladislav/Boban/pull/5) | Fresh Core 404 | Draft | **Hold**, pod #11 |
| [#6](https://github.com/soufekladislav/Boban/pull/6) | Pinterest | Draft | **Hold**, pod #15 |
| [#7](https://github.com/soufekladislav/Boban/pull/7) | Konsolidace #2–#6 | Draft, CI success | **Hold**, neobsahuje #1, vyhodnotit v #9 |

**Nezavírat historická PR automaticky.** Po rozhodnutí o kanonickém release a ověření závislostí lze staré PR uzavřít se zdůvodněním a odkazem na výslednou Issue.
