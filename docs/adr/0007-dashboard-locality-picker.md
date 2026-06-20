# ADR 0007 — Dashboard: výběr lokality + skrývání neaktivních modulů + odolnost Solis čtení

## Stav
Přijato (v0.31.3).

## Kontext (z provozu)
- Hybrid/generation Solis modul hlásil „neaktivní" a pack 2 nešel, zatímco
  storage pack 1 fungoval. Příčina: selhání čtení jednoho registru shodilo
  Modbus socket a OTRÁVILO zbytek cyklu → modul, který četl vadný registr
  jako první (systémové FVE/síť u hybridu/generation, nebo pack 2), nedostal
  nic a tvářil se mrtvě.
- Na dashboardu se ukazovaly i neaktivní moduly bez lokality (nepořádek).
- Admin s víc lokalitami chtěl jednu vybrat, ne scrollovat všechny.

## Rozhodnutí
1. **Solis čtení samoopravné:** při výjimce (spadlý socket) `_read_reg`
   reconnectne a JEDNOU zopakuje jen daný registr. Chybová odpověď
   (illegal address) se přeskočí bez reconnectu. Jeden vadný registr už
   neshodí ostatní → hybrid zůstane aktivní aspoň z baterie.
2. **Diagnostika:** `python -m ems.adapters.solis.probe <host>` přečte
   kandidátní registry a vypíše, co na konkrétním kuse odpovídá (kvůli
   opravě adres FVE/síť/energie a pack 2).
3. **Skrývání neaktivních:** `list_devices` vrací neaktivní modul jen když
   je přiřazený k lokalitě (`HAVING active OR locality_id IS NOT NULL`).
4. **Výběr lokality:** má-li uživatel víc lokalit, dashboard ukáže jednu
   s fulltextovým výběrem (SearchSelect); poslední volba se pamatuje
   (localStorage `ems.dash.locality`). Jedna lokalita → bez přepínače.
   (Cíleno hlavně na adminy; per-user scoping zatím není.)

## TODO
- Opravit reálné adresy systémových registrů a pack 2 dle výstupu probe.
- Per-user viditelnost lokalit (až se řeší běžní uživatelé).
