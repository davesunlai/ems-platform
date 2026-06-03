# ADR 0007: Správa hesel a e-mail (v0.6.0)

## Kontext
Uživatelé potřebují měnit heslo, řešit zapomenuté heslo a admin resetovat heslo.

## Rozhodnutí
- **Změna vlastního hesla**: ověření starým heslem (POST /auth/change-password),
  + e-mailová notifikace o změně.
- **Zapomenuté heslo**: POST /auth/forgot-password {email} vždy vrací 200
  (neprozrazuje existenci e-mailu); vytvoří token (uloží se jen SHA-256 hash,
  platnost 1 h) a pošle odkaz. POST /auth/reset-password {token, new_password}.
- **Admin reset**: přes PATCH /admin/users/{id} (password).
- E-mail přes SMTP (Forpsi, ai@teraems.com), konfigurace z .env
  (EMS_SMTP_*, EMS_BASE_URL); heslo schránky NIKDY v gitu.
- U uživatele přibyla pole `email`, `full_name`.

## Důsledky
- Reset funguje jen s vyplněným e-mailem u uživatele.
- Tokeny se ukládají hashované; odkaz má omezenou platnost.
- Lokality a párování řeší navazující v0.6.1.
