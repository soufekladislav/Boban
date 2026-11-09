# WebBooster / Boban 0.9.5 — Knowledge + Commerce Read (pilot)

## Rozsah
- Automatický **projektový záznam ověřených SEO zásahů** po úspěšném technickém ověření. Záznam nevyvozuje obchodní dopad a nevzniká z pouhého návrhu či neúspěšného ověření.
- Trvalá databázová SEO knihovna `marketing_knowledge` (globální a projektový obsah), vyhledávání v poradně a kontextový výběr až čtyř článků do AI dialogu včetně URL zdrojů.
- Superadmin může znalosti vytvářet, opravovat, mazat a označit jako sdílené nebo projektové. Neomezené HTML od AI se neukládá; v záznamu jsou pouze textová pole a ověřitelné HTTPS URL.
- Čtecí propojení WooCommerce přes **existující** Fresh Core 0.7.6.1 `GET /commerce/catalog`, samostatný **read/access** klíč šifrovaný v Bobanově DB. Stávající SEO write, accounting a invoice klíče se nemění.
- Na stránce konektorů je možnost ověřit čtecí přístup a zkontrolovat vzorek 20 produktů. Zjištěné problémy jsou orientační a neznamenají, že katalog byl odeslán.
- Verze zůstává na dřívějším UI 0.9.4. Žádný nový redesign.

## Stav integračních funkcí (kontrola zdrojového kódu)
| Funkce | Stav |
|---|---|
| Fresh Core read/SEO write | Již existuje, zachováno |
| Fresh Core `commerce/catalog` | Existuje v dodaném Core 0.7.6.1, Boban má nově čtecí kontrolu |
| Google Search Console | Čtení, sync a některé sitemap operace |
| GA4 | Čtení, synchronizace; příprava nastavení key event, nikoliv kompletní e-commerce implementace |
| GTM | Pouze čtení, scope `tagmanager.readonly`; žádné vytváření tagů ani publikace |
| PageSpeed/CrUX | Vyžaduje API key; pro zahájení katalogů není podmínkou |
| Merchant Center / Zboží.cz / Heureka | **Zatím bez funkčního exportu a bez ověřeného příjmu dat** |
| Google Ads | Zatím žádné Google Ads API řízení kampaní |

## Nasazení
1. Zálohuj databázi a adresář aplikace. Nepřepisuj `.env` ani produkční databázi.
2. Nasaď do testovacího adresáře jako celou aplikaci; na prvním startu se **pouze přidají** tabulky `marketing_knowledge` a `project_core_read`. Stávající DB tabulky neměníme.
3. Zkontroluj administraci → SEO poradna, přidání záznamu a vyhledání z projektu. Zkontroluj, že neadmin nemůže měnit globální knihovnu.
4. Zkontroluj Konektory → Fresh Core Produkty a zadej **Read/Access Key** z Fresh Core; netestuj s write/accounting klíčem.
5. Proveď test na skutečném WooCommerce katalogu. U většího shopu jde zatím jen o vzorek prvních 20 produktů, ne plný synchronizační audit.
6. V chatu ověř dotaz na znalostní téma a přítomnost interního zdroje v AI kontextu. Předchozí projekty, chaty a úkoly mají zůstat zachované.

## Důležité limity
- Boban automaticky ukládá **faktické technicky ověřené zásahy**, nikoliv vlastní neověřené odborné závěry či generované články. Ty zatím schvaluje a vkládá superadmin.
- Neobsahuje full-duplex synchronizaci, webhooks ani produktové feedy pro externí katalogy. To je další samostatná etapa.
- Zdodrojované integrace Site Kit a feedových pluginů nejsou kopírovány; jejich užitečné principy poslouží návrhu vlastních adaptérů při respektování licencí a aktuálních veřejných specifikací.
- Provozní test MariaDB / Flask zde nebylo možné provést, protože v izolovaném prostředí chybějí balíčky ze `requirements.txt`. Python a Jinja syntaktické kontroly prošly.
