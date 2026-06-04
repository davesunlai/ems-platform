# 0020 – Výstrahy v liště (agregátor)

## Stav
Přijato (v0.15.0)

## Kontext
Plánované odstávky byly vidět jen v kartě lokality. Uživatel potřebuje
upozornění nahoře v liště s počtem výstrah, scoped na své lokality, a s prostorem
pro budoucí typy výstrah.

## Rozhodnutí
- Generický agregátor `ems/alerts/service.collect_for_user(user)` sbírá výstrahy
  napříč zdroji; první zdroj = plánované odstávky. Další zdroje (poruchy, limity,
  offline zařízení) se přidají do `collect_for_user`.
- Scope dle viditelnosti: admin = všechny lokality, ostatní = přiřazené
  (`localities_for_user`, join `user_localities`).
- Endpoint `GET /api/alerts` (perm `read`) → `{count, alerts[]}`; alert nese
  type/severity/locality/title/detail/start/end.
- Frontend: `AlertsBell` v liště — trojúhelník ⚠ s číselným badge a rozbalovací
  seznam; polling 1×/3 min.

## Důsledky
- Bez nové tabulky (čte z `planned_outages`). Rozšiřitelné o další zdroje výstrah.
