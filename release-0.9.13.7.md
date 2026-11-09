# Boban / WebBooster 0.9.13.7 — Heureka.cz: produktové a dostupnostní XML

## Přidáno
- **Konektory → Heureka.cz**: kompaktní karta ve stávající dvousloupcové mřížce. Zde pouze deklarace registrace obchodu na Heurece a potvrzení spolehlivé rychlosti expedice. Nejde o OAuth a Boban nedokáže bez dalšího oprávnění vzdáleně ověřit skutečný stav účtu.
- **E-commerce → Heureka**: vlevo příprava XML a kopírovatelné stabilní adresy, vpravo lokální statistiky exportu a validace. Připraveno z již synchronizovaných dat Bobana; opakovaný plný import není potřeba.
- Produktové XML podle Heureka.cz s `SHOP/SHOPITEM`, unikátním `ITEM_ID`, `PRODUCTNAME`, `DESCRIPTION`, `URL`, `IMGURL`, `PRICE_VAT`, značkou a EAN pokud existují, společným `ITEMGROUP_ID` pro varianty a jejich atributy. Nedeklarujeme neznámé přepravní sazby ani doručovací termíny.
- Dostupnostní XML podle Heureka.cz `item_list/item/@id/stock_quantity`. Jen položky s výslovně doloženým **kladným** počtem kusů a pouze pokud správce potvrdil expedici umožňující doručení nejpozději do 2 dnů od objednávky. Není-li splněno, dostupnostní URL se nezobrazí a server vrací 404 (nepublikujeme falešnou dostupnost). GZip pro dostupnostní URL je podporován při `Accept-Encoding: gzip`.
- Zachován společný schválený výběr kategorií, jednotlivých produktů i variant a ochrana před cenou 0,01 Kč. Vyprodané, nekoupitelné a explicitně virtuální/digitální produkty se do Heureky nezahrnují.
- Stabilní adresy při přegenerování, atomický zápis XML, malá samostatná tabulka `project_heureka_feeds`; cron obnoví Heureka XML při další dokončené periodické katalogové synchronizaci. Případná chyba Heureky **nezastaví Google Merchant**; uloží se do stavu Heureky.

## Co Heureka neumí automaticky bez účtu / další integrace
- Přímé vytvoření / autorizace e-shopu v Heurece ani automatické zadání XML do jejího rozhraní. Pro první použití je třeba přihlásit se na `https://sluzby.heureka.cz/`, registrovat e-shop a vložit produktovou XML URL. V dostupnostním PPC režimu pak vložit i dostupnostní XML URL, **jen pokud Boban označí dostupnost jako připravenou**.
- Počty reálně schválených/naspárovaných produktů, prokliky, objednávky a výkon Heureky **nejsou dosud vzdáleně načítány**. Zobrazené počty představují lokální XML, nikoli úspěšný import Heurekou.
- Úplná Heureka kategoriální taxonomie není automaticky mapována: `<CATEGORYTEXT>` momentálně vychází z názvu kategorie ve WooCommerce. Heureka může produkty spárovat podle dalších údajů; přesné kategoriální mapování je případný další krok.
- Dostupnostní XML se aktualizuje s úspěšným katalogovým cyklem (podle intervalu projektu), nikoli automaticky každých 10 minut. Heureka ho může stahovat každých 10 min pouze v PPC režimu; pro spolehlivé rychlé aktualizace bude v budoucnu potřeba změnový sync Fresh Core/Woo.
- Cena `PRICE_VAT` vychází z ceny, kterou Fresh Core poskytuje. Před spuštěním ověř skutečný daňový režim a finální cenu včetně DPH proti WooCommerce.

## Nasazení
1. Zálohuj soubory aplikace a MariaDB.
2. Nahraj kompletní obsah ZIP verze **0.9.13.7** na stávající instalaci. Zachovej `.env`, databázi, adresář `generated_feeds`, případný vlastní `CATALOG_FEED_DIR` a cron.
3. Restartuj Passenger. Tabulka se vytvoří při inicializaci aplikace. Žádné produktové údaje se nemažou.
4. Otevři **Adrenaline Race → E-commerce → Heureka** a klikni na **Připravit oba feedy**. Boban použije existující schválené produkty a varianty. Zkontroluj počty a XML adresu.
5. V účtu Heureky vlož **produktové XML**. Dostupnostní XML pouze při splnění podmínek a režimu PPC. Stav účtu v Konektorech můžeš potvrdit po reálné registraci.
6. Ověř minimálně jeden běžný a jeden variantní produkt, ceny s DPH, odkazy, stavy skladu a kategoriální zařazení. Nejdříve ověř funkčnost s Heurekou, pak lze zapnout další katalogové kanály.

## Testy
37 lokálních unit testů. Python `compileall`, Jinja kompilace obou upravených šablon. Provozní import Flask aplikace nebyl v tomto izolovaném prostředí dokončen, protože zde chybí `pymysql`; na hostingu jsou závislosti instalované podle předchozího provozu. Skutečné načtení Heurekou a validaci PPC režimu je nutné ověřit po nasazení.

## Reference
- https://sluzby.heureka.cz/napoveda/xml-feed/
- https://sluzby.heureka.cz/napoveda/dostupnostni-feed/
- https://sluzby.heureka.cz/napoveda/registrace-eshopu/
