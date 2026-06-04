# ADR 0017: Uvítací e-mail a admin reset hesla mailem (v0.12.3)

## Rozhodnutí
- send_email rozšířen o HTML (multipart text+html); brandovaná šablona html_mail
  (ems/notify/templates.py).
- Založení uživatele: heslo je nepovinné. Když má uživatel e-mail a je SMTP,
  pošle se uvítací e-mail o TERA EMS s odkazem na nastavení hesla (aktivační
  token, platnost 7 dní). Bez hesla se založí náhodné, uživatel si nastaví své.
- Admin „Reset hesla": dříve ručně zadané heslo → nově POST /admin/users/{id}/
  send-reset pošle uživateli e-mail s odkazem (platnost 1 h). Vyžaduje e-mail
  uživatele a nakonfigurované SMTP.

## Důsledky
- Uživatel si heslo nastavuje sám přes /reset?token=… (existující flow).
