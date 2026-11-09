# Boban 0.9.13.14 – Meta Graph API konektor a import existujícího zdroje

## Rozsah
- OAuth přihlášení přes Meta aplikaci (`catalog_management`, `business_management`), ochrana `state`, kontrola oprávnění projektu. Přístupový token šifrován existujícím `SECRET_KEY` (Fernet). Nikdy se nezobrazuje v UI ani v diagnostice.
- Ověření existujícího ID katalogu Meta a seznamu jeho feedů. Automatické párování **pouze** podle URL Bobanova feedu. Pokud nenalezne shodu, umožní vybrat existující zdroj v E-commerce; nic dalšího nevytváří.
- Spuštění načtení veřejného Meta XML přes Graph API (`/{feed_id}/uploads`), čtení posledních uploadů a základní diagnostiky.
- Zachován schválený katalog, veřejná URL Meta XML, ID variant, Google, Heureka a Zboží.cz. Žádný nový import WooCommerce; žádné vytváření druhého Meta katalogu ani placených reklam.

## Konfigurace před použitím
1. V [Meta for Developers](https://developers.facebook.com/apps/) založte nebo vyberte vlastní **Business** aplikaci. Nastavte Facebook Login (Web), zapněte povolenou doménu a **Valid OAuth Redirect URI** přesně na `https://webbooster.freshcrackers.cz/connectors/meta/callback`. Meta může vyžadovat další kontrolu domény, App Review, Business Verification nebo Advanced Access pro cizí účty.
2. Doplňte do produkční `.env` (nikoliv do ZIPu): `META_APP_ID=...`, `META_APP_SECRET=...`, volitelně `META_GRAPH_VERSION=v25.0`. Uložte bezpečně, nevypisujte do logů. Pro více zákazníků používejte schválené přístupové role/permissions.
3. Restart Passenger. V Konektory → Facebook / Meta klikněte na **Připojit Meta účet**, potvrďte oprávnění a vložte ID již existujícího katalogu Adrenaline Race. V E-commerce → Meta klikněte na **Načíst stav**, vyberte jeho existující feed a **Odeslat aktuální XML přes Meta API**.
4. Ověřte v Commerce Manageru stav přijetí, počty nabídek a chyby. API úspěch nahrání neznamená schválení jednotlivých produktů.

## Důležité hranice
- **Meta App ID a Secret nejsou součástí balíčku**. Bez Meta aplikace a autorizace se živé API připojení nedokončí.
- Tato verze **nepřidává Pixel/CAPI, reklamní kampaně ani per-item Catalog Batch API**. Záměrně používá ověřený primární XML feed a spouští jeho nahrání přes Graph API, aby nedocházelo k souběžné správě položek dvěma zdroji.
- Boban se pokusí vyměnit krátkodobý token za dlouhodobý. Meta OAuth token přesto může vypršet nebo být odvolán; aplikace pak vyžádá nové připojení. Pro dlouhodobý SaaS provoz bude vhodná schválená systémová/business integrace s řízenou rotací přístupů.
- Databázové schéma `project_meta_feeds` se rozšiřuje o 5 nullable polí. Záloha před nasazením je nutná. **Neměnit SECRET_KEY**, jinak stávající zašifrované přístupy nepůjdou dešifrovat.
