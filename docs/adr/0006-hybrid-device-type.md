# ADR 0006 — Typ zařízení `hybrid` (vše v jednom modulu)

## Stav
Přijato (v0.31.2).

## Kontext
Hybridní střídač (FVE + baterie + síť + backup) se musel skládat z více
modulů (generation + storage pack1 + storage pack2…), což je otravné.
Přitom `device_type` v systému nic neomezuje — souhrn lokality
(`aggregate_now`) i dashboard jdou podle EMITOVANÝCH METRIK, ne podle typu.
U goodwe ET to tak funguje už teď (jeden modul posílá pv+baterie+síť).

## Rozhodnutí
- Nový `DeviceType.HYBRID`. Jeden modul = celý střídač.
- Solis adaptér u `hybrid` emituje vše najednou:
  - systém: `pv_power`, `energy_pv_total`, `grid_power` (otočená polarita),
  - baterie AGREGOVANĚ přes oba packy: `battery_soc` = průměr packů,
    `voltage` = průměr (paralelní HV bus), `current` = součet,
    `battery_power` = součet U*I (znaménko + nabíjení / − vybíjení).
- UI: `hybrid` první v nabídce typů; při volbě adaptéru `solis` se typ
  přednastaví na `hybrid`. Pack-selektor jen pro `storage`.
- goodwe/mock: bez změny (emitují vše bez ohledu na typ).

## Mimo rozsah / TODO
- `load_power` (domácí zátěž) a `backup` výkon: registry pro 3f model
  nepotvrzené (brief §9) -> doplnit po živém dočtení proti 192.168.6.180.
  Backup navíc nemá kanonickou metriku — přidat až s potvrzeným registrem.
- Per-pack detail (samostatné SOC) zůstává přes oddělené `storage` moduly.
