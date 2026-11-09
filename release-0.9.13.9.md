# Boban 0.9.13.9 – Zboží.cz / Seznam Nákupy (Fénix)

- Nový samostatný XML feed Zboží.cz s povinným namespace, unikátními ID variant, cenou v CZK, URL, obrázkem, popisem a povinným DELIVERY_DATE. Neznámé expedice nejsou vydávány za sklad: `-1`.
- Stejná schválená sada a vyloučení jako Google/Heureka, bez nového Woo importu. Existující feedy jsou beze změn.
- Konektory: API Fénix připojené ověřením API klíče přes POST /user/token a GET /nakupy/feeds. Klíč je uložen šifrovaně; tokeny se neukazují.
- E-commerce: dva boxy pro Zboží.cz – publikace a diagnostika. Stabilní URL souboru. Bez automatické aktivace placené inzerce.
- Cron po dokončení stávajícího katalogového cyklu obnoví také Zboží.cz XML, pokud bylo již aktivováno. Chyba vedlejšího feedu nezastaví Google ani Heureku.
- Provozovnu musí být možné spravovat v účtu Seznamu. Připojení API neznamená automatické vytvoření provozovny nebo registraci jejího feedu.
- Testovat v produkci nejprve URL a ověřit API klíč, bez závazku PPC.
