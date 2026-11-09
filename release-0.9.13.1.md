# Boban WebBooster 0.9.13.1 – oprava Google Merchant registrace

## Opravená příčina HTTP 403

Flask-Login User.id je v Bobanovi text (`str`). Callback jednorázové Merchant registrace porovnával `int(pending.admin_id)` přímo s textovým `current_user.id`, což vždy selhalo a vracelo `abort(403)` i platnému superadminovi. Oprava normalizuje obě ID na text před porovnáním. Kontrola superadmin role, OAuth state a doby platnosti zůstává.

## Nasazení

Zálohujte aplikaci. Nahrajte aktualizované soubory ze ZIPu do adresáře WebBoosteru; nepřepisujte `.env`, databázi, vygenerované feedy ani uživatelská data. Restartujte Passenger. Otevřete superadmin konzoli a spusťte nové přihlášení k registraci Merchant API. Původní jednorázový Google callback již znovu nepoužívejte.

## Kontroly

Ověřena syntaxe app.py a provedeny testy registrovaného Merchant API včetně kontroly regresního porovnání identity. Samotné volání Google Merchant API není lokálně možné ověřit bez oprávnění produkčního účtu.
