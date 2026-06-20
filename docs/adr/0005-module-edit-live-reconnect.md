# ADR 0005 — Editace modulu v UI + živý reconnect při změně parametrů

## Stav
Přijato (v0.31.1).

## Kontext
Stránka Moduly uměla jen Zapnout/Vypnout/Smazat. Změna IP střídače (nebo
jiných parametrů) tak v UI nešla — musel se modul smazat a založit znovu.
Backend přitom PATCH `params` už podporoval (ModuleUpdate + db.update).
Navíc reconcile v kolektoru detekoval jen NOVÉ a ODEBRANÉ moduly, ne změnu
parametrů u běžícího → změna IP by se neprojevila bez vypnutí/zapnutí.

## Rozhodnutí
1. **UI:** tlačítko „Upravit" v řádku modulu naplní formulář (ID zamčené,
   je to klíč) a uloží přes existující `PATCH /api/admin/modules/{id}`
   (name/adapter/device_type/kind/params). Lze tak změnit host/port i název.
2. **Kolektor:** reconcile nově drží podpis `(adapter, params)` per aktivní
   modul. Při změně podpisu zavře staré spojení a připojí znovu → změna IP
   se projeví do jednoho cyklu (~POLL_INTERVAL, 10 s), bez restartu.

## Pozn.
- Lokalita se mění přes stránku Lokality (attach zařízení k jiné lokalitě
  přepíše `modules.locality_id`) — `ModuleUpdate` ji záměrně neobsahuje.
- Telemetrie je klíčovaná na `device_id` (= id modulu), takže editace IP
  historii zachová (na rozdíl od smazat+založit pod jiným ID).
