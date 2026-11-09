# Boban 0.9.13.4 – opětovný import opraveného Merchant XML

- Opraveno pevné 20hodinové omezení ručního načtení, které bránilo odeslat nový opravený feed po úspěšném importu.
- Boban porovnává SHA-256 publikovaného XML s XML při posledním ručním požadavku; u starších požadavků bez uloženého hash používá datum poslední publikace proti datu posledního načtení.
- Nový XML obsah lze načíst po dokončení předchozího importu; stejné XML zůstává chráněné 20hodinovým intervalem. Min. 60 sekund mezi požadavky.
- Nezměněné URL datového zdroje; žádný nový Merchant zdroj; žádné načítání produktů; žádná migrace DB.
- Přehled stavu importu je čitelný a surový JSON je až v technických podrobnostech.
- Postup: v E-commerce publikovat opravené XML z již uložených produktů; zkontrolovat vyloučené závody a počet položek; v Konektorech znovu vyžádat načtení. Nezřizovat nový zdroj.
- První import 5712 položek má stav SUCCEEDED (soubor načten, nikoli produkty schválené). Po opravě musí počet nebo obsah odpovídat opravě kategorií a nulových cen.
