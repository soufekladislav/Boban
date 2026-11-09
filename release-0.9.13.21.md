# Boban 0.9.13.21 – čitelný dialog a čas zpráv

## Opravy
- Vrácený JSON `{"answer":"..."}` se rozbalí na serveru i při vykreslení starších uložených zpráv. Řídicí pole se nevypisují v bublině.
- Výsuvný chat používá stejný bezpečný formátovač textu jako hlavní chat (odstavce, nadpisy, seznamy, odkazy). Nikdy nevkládá syrové HTML z AI.
- Historie, nové zprávy, hlavní chat a archiv zobrazují datum a čas odeslání; u starších záznamů se použije uložený čas serveru. Server používá lokální naivní ISO čas, proto se neprovádí odhad časového pásma.
- Pokyny AI jsou upravené tak, aby prostá vysvětlující otázka nevyvolávala dlouhý SEO plán. Jde o změnu instrukcí, nikoli o náhradu samotného modelu nebo kompletní nástrojový dialog.

## Nasazení
Zálohujte databázi, aplikaci a `.env`. Nahrajte balíček do existující aplikace bez přepisu `.env`, restartujte Passenger a obnovte stránku s vyčištěním cache prohlížeče. Nevyžaduje migraci DB, nový cron, reautorizaci Google ani změnu katalogů.

## Test
1. V pravém panelu se zeptejte „Co znamená Organic Search a Direct?“ – žádná viditelná JSON závorka.
2. Otevřete stejný chat na jiné stránce. Historie musí zachovat formát i časy.
3. Zkontrolujte hlavní chat a archiv.
4. Ověřte, že projekty 1/3 mají fungující synchronizaci; 2/4 mají stále nezávislý `invalid_grant` a neřeší je tento patch.

## Omezení
Produkční Google API ani Passenger nebyly v tomto izolovaném prostředí testovány. UX/stručnost vyžaduje ověření na konkrétním modelu AI Engine.
