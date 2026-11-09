# Boban 0.9.13.13 – Meta RSS oprava příliš dlouhého řádku

Opravuje výhradně serializaci Meta RSS v `meta_export.py`. Každý XML element je nyní na samostatném odsazeném řádku; před publikováním se ověřuje limit 5 242 880 bajtů na řádek.

Po nasazení restartujte Passenger a v E-commerce → Meta klikněte na **Znovu připravit Meta XML**. Ve stejném datovém zdroji v Meta Commerce Manageru spusťte **Aktualizovat**. Nevytvářejte druhý katalog ani jinou URL feedu.

Nemění WooCommerce import, identifikátory, obsah položek, Meta účet, Google, Heureku ani Zboží.cz. Tato oprava NEPŘIDÁVÁ Graph/Catalog API autentizaci.
