# Boban / Web Booster 0.8.5 — Fresh Key zdarma

Sdílení lidí, jejich Boban role a lokální přístup zůstávají autoritativně v Bobanovi. Fresh Key pouze spojuje stejný projekt s dalšími Fresh aplikacemi.

- Fresh Key / účet AI Enginu lze připravit automaticky z Bobana; nevyžaduje kredit.
- Projekt se do Fresh Key neposílá automaticky při otevření dashboardu. Odeslání je vždy výslovná akce **Odeslat do Fresh Key**.
- Vedle ní je **Spravovat propojení** do AI Enginu.
- Role: Vlastník / Správce / Editor / Čtenář. Člen týmu / Klient / Agentura je samostatný vztah.
- Vlastník/Správce může spravovat sdílení a Fresh Key i bez Boban AI kreditů; samotná AI práce Bobana se řídí produktovým oprávněním.
- `project_invitations` ukládá pozvánky pro e-maily bez lokálního Boban účtu.

Aditivní DB změny jsou v `sql-0.8.5-project-roles.sql`. Produkční `.env` zachovej.

## Oprava 0.8.5
Na MySQL se nyní při startu explicitně doplní `relationship` do již existujících tabulek `project_members` a `project_invitations`. Tím se opravuje Server Error na kartě Propojení po upgradu z 0.8.2/0.8.3.


## Verze 0.9.13.17
Viz RELEASE-0.9.13.17.md. Nové datové tabulky: analytics_sync_runs, analytics_observations, analytics_business_outcomes, analytics_entity_links.
