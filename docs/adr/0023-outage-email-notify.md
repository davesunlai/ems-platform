# 0023 – E-mail při nové plánované odstávce

## Stav
Přijato (v0.18.0)

## Kontext
Odstávky se zobrazují ve výstrahách, ale uživatel chce být upozorněn e-mailem
hned, jak se nová odstávka objeví v systému — a to uživatelé přiřazení k lokalitě.

## Rozhodnutí
- `refresh_locality` si před upsertem zjistí existující `uid` odstávek lokality,
  po upsertu spočte nově přidané a na ně (edge-trigger) pošle e-mail.
- Příjemci = aktivní uživatelé přiřazení k lokalitě, kteří mají e-mail
  (`users_with_email_for_locality`). HTML šablona `html_mail`, tlačítko vede na EMS.
- Platí pro denní `refresh_all` i ruční „Načíst teď". Opakované načtení už hotové
  odstávky neposílá (suppress přes existující uid).
- Selhání e-mailu jen zaloguje, neshodí stahování.

## Důsledky
- Při úplně prvním načtení lokality přijdou e-maily na všechny aktuálně
  nadcházející odstávky (jsou „nové"). Dál už jen na skutečně nové.
