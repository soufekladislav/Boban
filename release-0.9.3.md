# Boban / WebBooster 0.9.3 — čistý instalační balíček

Výchozí zdroj: uživatelem dodaný `boban(1).zip` (0.9.2). Nejde o přepis backendu; datové struktury, REST cesty, oprávnění, schvalování a konektory zůstávají zachovány.

## Udělané změny
- `static/app.css`: jedna přehledně naformátovaná sada pravidel místo minifikovaných sekcí. Čitelnost sjednocena *v existujících deklaracích* (minimálně 12px u drobného textu, chat 16px); žádná další koncová override záplata. Zachovány původní breakpointy, barevnost a pořadí pravidel.
- `static/app.js`: oprava chyby, při které se rozbalovací pokračování dlouhé odpovědi okamžitě přepsalo plným HTML.
- `templates/project.html`: odstraněno nadbytečné uzavření HTML elementu v chatu.
- `templates/base.html`: srozumitelná ikona oznámení, nové verze CSS/JS pro odstranění staré cache.
- `app.py`: verze 0.9.3, bez změn obchodní logiky.
- Archiv očištěn od starých release poznámek, logů, `__pycache__`, `tmp`, ukázkových dat a provozních souborů certifikační výzvy.

## Důležité omezení
Úpravy nebyly otestovány proti živé MariaDB ani provoznímu Passenger procesu. Mobilní obrazovky a všechny podstránky je nutné vizuálně ověřit v testovacím nasazení. Vzhledem k mnoha historickým CSS selektorům jde o **první konsolidační build**, nikoli o prokázanou bezchybnou kompletní rekonstrukci všech obrazovek.

## Bezpečné nasazení
1. Zálohuj kompletní webový adresář a databázi, včetně `.env`, který není součástí ZIP.
2. Vytvoř prázdný nový adresář testovací instance. Nepřepisuj neověřeně aktuální produkci.
3. Nahraj obsah ZIP a do testovacího adresáře přenes pouze nezbytné konfigurace a tajné klíče ze zabezpečeného uložiště (`.env`, případné provozní soubory), nikoli staré CSS, šablony nebo cache.
4. Zachovej stejné DB připojení pouze pokud chceš sdílet provozní data; pro bezpečný test preferuj kopii DB. Spusť aplikaci a zkontroluj přihlášení, projekty, chat, cíle, úkoly, admina, konektory a mobil.
5. Teprve po schválení změň cestu aplikace. U Passenger podle existující konfigurace restartuj aplikaci.
6. Pokud dojde k chybě, vrať původní soubory a původní verzi konfigurace. DB schéma tato verze nemění.

**Zachování dat:** Samotné nahrazení instalačních souborů nemaže data uložená v MariaDB. Neodstraňuj však neidentifikované lokální databáze, uploady, tajné klíče nebo provozní složky mimo tento instalační balíček.
