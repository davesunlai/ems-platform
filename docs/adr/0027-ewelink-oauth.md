# 0027 – eWeLink přes OAuth2

## Stav
Přijato (v0.22.0)

## Kontext
Aplikace z eWeLink developer centra nesmí /v2/user/login (chyba 407).
Nutný OAuth2 authorization-code flow (vyžaduje HTTPS redirect → máme Caddy).

## Rozhodnutí
- Klient přepsán z hesla na OAuth2: build_login_url (přihlašovací stránka eWeLink),
  callback vymění code za access/refresh token, token uložen v DB (ewelink_token),
  access token se automaticky obnovuje přes refresh.
- Redirect URL = {EMS_BASE_URL}/api/ewelink/callback (registrováno v dev.ewelink.cc).
- Endpointy: GET /api/ewelink/auth-url (admin), GET /api/ewelink/callback (bez auth,
  landing z eWeLink), GET /api/ewelink/devices, POST /api/ewelink/switch (control).
- UI: tlačítko „Připojit eWeLink", stav připojení, přepínání on/off u zařízení.
- EMS_EWELINK_EMAIL/PASSWORD už nejsou potřeba.

## Důsledky
- Heslo k eWeLink se neukládá, jen token. Napojení na automatizaci naváže dál.
- Signing token/refresh requestů je citlivý; chyby se propisují s eWeLink kódem/zprávou.
