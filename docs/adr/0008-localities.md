# ADR 0008: Lokality a párování (v0.6.1)

## Kontext
Portfolio roste přes více míst — potřeba seskupit zařízení a uživatele.

## Rozhodnutí
- Entita `localities` (název, adresa, region, poznámka).
- Vazby: lokalita 1:N zařízení (`modules.locality_id`), uživatel M:N lokalita
  (`user_localities`).
- Profil uživatele rozšířen o `phone`, `note` (e-mail/jméno už ve v0.6.0).
- Správa párování z admin stránky Lokality (přiřazení uživatelů i zařízení).
- **Viditelnost dle lokality zatím NENÍ vynucená** — jen struktura; omezení
  (uživatel vidí jen své lokality) přidáme jako další krok po naplnění dat.
- Rebrand zobrazovaného názvu na **TERA EMS**.

## Důsledky
- Připraveno na pozdější scoping přístupu i na multi-site nasazení.
- Mazání lokality: zařízení se odpojí (locality_id=NULL), uživatelské vazby
  se zruší (ON DELETE CASCADE).
