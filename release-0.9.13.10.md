# Boban 0.9.13.10 — oprava ukládání Sklik/Fénix API klíče

## Zjištění
V 0.9.13.9 formulář vyžadoval úspěšné načtení `/nakupy/feeds` **ještě před uložením API klíče**. Tento endpoint závisí na oprávnění k Seznam Nákupy/provozovně, které může zatím chybět, i když je Fénix klíč platný. Skutečná produkční HTTP chyba zatím nebyla doložena; jde o zjištěnou chybu konstrukce.

## Oprava
- Ověření API klíče přes `POST /user/token` a identitu přes `GET /user/me`, nezávisle na existenci provozovny.
- Oddělená kontrola `/nakupy/feeds`. Pokud není dostupná, API klíč se přesto uloží jako ověřený, s bezpečným diagnostickým stavem a bez předstírání připojení feedu.
- Tajný refresh klíč se ukládá šifrovaně před potvrzením úspěchu. Access token se neukládá. Chybové zprávy neobsahují token ani tělo odpovědi API.
- Karta Konektory informuje o stavu: API ověřeno / provozovna a feedy dostupné či nedostupné.
- Kontrola v E-commerce používá stejnou dvoustupňovou diagnostiku.
- Žádné změny ve WooCommerce, Google Merchant, Heureka XML, Zboží XML, katalogu, schématu databáze ani cronu.

## Nasazení
1. Zálohujte aplikaci a databázi.
2. Nahrajte ZIP do stejného kořene aplikace, zachovejte `.env` a vygenerované feedy.
3. Restartujte Passenger.
4. V projektu Adrenaline Race > Konektory > Zboží.cz vložte dříve vytvořený **Fénix** klíč a stiskněte Ověřit a připojit. Není třeba generovat nový klíč.
5. Pokud Boban vypíše chybu ověření klíče (HTTP 401/403), zjistěte přesnou zprávu; pokud vypíše API ověřeno a feedy nedostupné, ověřte přístup k provozovně v Seznam Nákupy.

## Kontrola
`python -m unittest discover -s tests -p 'test_*.py' -q`: **50 passed**. `python -m py_compile app.py zbozi_fenix.py`: OK. Skutečný Fénix API klíč nebyl k dispozici, živé připojení nebylo testováno.
