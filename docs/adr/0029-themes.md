# 0029 – Vzhled / motivy uložené u uživatele

## Stav
Přijato (v0.24.0)

## Kontext
Tmavé UI; uživatel chtěl přednastavené barevné motivy přiřazené k účtu
a základní editaci.

## Rozhodnutí
- Motivy přepínají CSS proměnné na :root (--bg, --panel, --border, --fg,
  --muted, --green/blue/amber). Presety: Půlnoc, Břidlice, Karbon, Oceán, Světlý.
- Volba uložena u uživatele: sloupce users.theme (TEXT) + theme_custom (JSONB).
  GET /api/auth/me vrací theme+custom; PUT /api/auth/me/theme ukládá.
- Frontend: theme.js (presety, applyTheme, applyInitial z localStorage pro
  okamžité použití bez bliknutí), auth provider aplikuje motiv po načtení usera.
- Stránka „Vzhled": výběr presetu + základní editor barev (živý náhled) +
  vlastní motiv (theme="custom").

## Důsledky
- Per-user, drží se i mezi zařízeními. Světlý motiv je „basic" — pár prvků má
  natvrdo tmavé stíny/přechody, doladí se případně později.
