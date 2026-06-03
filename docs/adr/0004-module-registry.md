# ADR 0004: Registr modulů v DB + živá rekonciliace

## Kontext
Konfigurace zařízení byla v souboru devices.yaml. Pro správu z UI a více
přispěvatelů je potřeba ji spravovat centrálně a měnit za běhu.

## Rozhodnutí
Moduly se ukládají do DB tabulky `modules` (taxonomie source_read /
source_write / logic). Kolektor čte registr živě a v každém cyklu srovnává
běžící adaptéry s aktivními moduly — změny v admin UI se projeví bez restartu.
devices.yaml slouží už jen jako jednorázový seed při prázdném registru.

## Důsledky
- Přidání/zapnutí/vypnutí modulu z UI je okamžité (do ~1 cyklu).
- Funkční jsou zatím čtecí moduly; zápisové (C) a logické (D) registr nese,
  ale kolektor je zatím nespouští.
