# 0022 – Průvodce systémem (onboarding)

## Stav
Přijato (v0.17.0)

## Kontext
Nový uživatel po prvním přihlášení nemá přehled, kde co je. Chtěli jsme
klikacího průvodce, který provede systémem, a možnost spustit ho znovu.

## Rozhodnutí
- Samostatná komponenta `Tour` (bez externí knihovny). Kroky Další/Zpět/Přeskočit,
  progress proužky. U kroku se appka přepne na danou stránku a zvýrazní položku v menu.
- Kroky filtrované podle role (`has(...)`): prohlížeč vidí méně než admin.
- Auto-spuštění po prvním přihlášení dle `localStorage` klíče `tera_onboarded_v1`
  (per prohlížeč). Dokončení/přeskočení klíč nastaví.
- Tlačítko „Průvodce“ v liště spustí průvodce kdykoli znovu.

## Důsledky
- Bez serverové změny a bez nové závislosti. „Poprvé“ je detekováno per prohlížeč;
  případné serverové sledování (flag u uživatele) lze doplnit později.
