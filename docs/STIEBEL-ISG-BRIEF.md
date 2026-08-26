# Předávací brief — modul `heat_pump` / adaptér `stiebel_isg` (TERA EMS)

> **Pro nosný chat (má repo + Docker).** Připraveno ve vedlejším chatu. Obsahuje konektivitu, mapu registrů,
> datový model, UI a uzel v diagramu toku. Implementaci dělej ty — vzor je `solis` adaptér (pymodbus, Modbus TCP).

---

## 1. Cíl

Přidat tepelné čerpadlo **Stiebel Eltron** (přes bránu **ISG**, `192.168.6.174:502`) jako nový modul
typu **`heat_pump`** s vlastním adaptérem **`stiebel_isg`** — zatím **jen čtení**. Výstup:

1. **Karta TČ** na dashboardu lokality (stav, teploty, dnešní spotřeba, COP).
2. **Samostatný graf TČ** s historií: teploty + podbarvený běh kompresoru (topení / TUV / odtávání / NHZ).
3. **Elektrická spotřeba TČ za den a za měsíc** (topení a TUV zvlášť + součet), včetně billing detailu.
4. **Uzel „Tepelné čerpadlo" v diagramu ⚡ tok** s odhadem okamžitého výkonu.

---

## 2. Konektivita — POTVRZENO ✅

- `nc -zv 192.168.6.174 502` → **open**. Čistý **Modbus TCP**, `device_id=1`, LAN-direct z franty, bez VPN.
- Lib **pymodbus ≥ 3.13** (stejně jako `solis`): `read_input_registers(addr, count=1, device_id=1)`,
  `read_holding_registers(...)`.
- **Adresy v dokumentaci ISG jsou 1-based → v pymodbus `addr = doc_addr − 1`.**
- Sentinel: `0x8000` (= −32768 jako S16) → registr pro tento typ TČ **nedostupný** → `None`;
  `0x7FFF` → neplatná hodnota → `None`. Teploty jsou **S16** (záporná venkovní teplota!).
- Poll **30 s** (ISG snese 5 s, netřeba). Blokové čtení: 501–540 (40 reg), 2501–2507, 3501–3522, 1501–1510, 5001.

**Doporučený config modulu (UI):** HOST `192.168.6.174`, PORT `502`, adaptér `stiebel_isg`,
transport `modbus_tcp`, `device_id=1`, `hp_nominal_kw=3.5`, `nhz_kw=0` (doplnit, pokud má TČ el. dohřev).

---

## 3. KROK 0 — ověřit mapu na kuse (před implementací)

Mapa níže je z dokumentace *Stiebel Modbus TCP/IP Software-Erweiterung ISG* (WPM3 / WPM3i).
Spusť sweep a porovnej s displejem ISG (http://192.168.6.174):

```python
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient("192.168.6.174", port=502); c.connect()
def rd(doc, fc=4):
    r = (c.read_input_registers if fc == 4 else c.read_holding_registers)(doc-1, count=1, device_id=1)
    v = r.registers[0]; return v-65536 if v >= 32768 else v
for name, a, sc in [("T_venk",507,.1),("T_vystup",512,.1),("T_zpatecka",515,.1),("T_buffer",517,.1),
                    ("T_TUV",521,.1),("T_TUV_set",522,.1),("T_zdroj",536,.1),("hotgas",538,.1)]:
    v = rd(a); print(f"{name:12}", "N/A" if v == -32768 else round(v*sc,1))
st = rd(2501); print(f"status 0x{st:04x} komp={bool(st&64)} top={bool(st&16)} tuv={bool(st&32)} nhz={bool(st&8)} odtav={bool(st&512)}")
print("EVU", rd(2502), "fault", rd(2504), "err", rd(2507))
print("el dnes TUV", rd(3511), "topeni", rd(3514), "| teplo dnes TUV", rd(3501), "topeni", rd(3504))
print("runtime h top/TUV/NHZ", rd(3517), rd(3518), rd(3522), "| rezim", rd(1501,3), "SG", rd(5001))
```

Kritéria: **507 ≈ venkovní teplota, 521 ≈ TUV na displeji, 2501 bit6 = kompresor podle displeje, 3514 ≈ spotřeba
dnes v Servicewelt.** Pokud 536–540 vrací `N/A` → je to WPM3 (ne 3i), pole prostě vynech.

---

## 4. Mapa registrů (baseline, ověřit dle §3)

### Blok 1 — hodnoty systému (FC04, doc 501–540)

| Doc | Veličina | Typ/scale | pole |
|---|---|---|---|
| 507 | Venkovní teplota | S16, 0.1 °C | `t_outdoor` |
| 508 / 509 | HK1 skutečná / set | 0.1 °C | `t_hc1`, `t_hc1_set` |
| 512 | Výstupní teplota TČ | 0.1 °C | `t_flow` |
| 513 | Výstupní teplota NHZ | 0.1 °C | `t_flow_nhz` |
| 515 | Zpátečka | 0.1 °C | `t_return` |
| 517 / 518 | Buffer skutečná / set | 0.1 °C | `t_buffer`, `t_buffer_set` |
| 519 | Tlak topení | 0.01 bar | `p_heating` |
| 520 | Průtok | 0.01 l/min | `flow_lpm` |
| **521 / 522** | **TUV skutečná / set** | 0.1 °C | `t_dhw`, `t_dhw_set` |
| 536 | Teplota zdroje (vzduch) | 0.1 °C | `t_source` |
| 538 | Hot gas | 0.1 °C | `t_hotgas` |
| 539 / 540 | Vysoký / nízký tlak | 0.01 bar | `p_high`, `p_low` |

### Blok 3 — stav (FC04, doc 2501–2507)

| Doc | Veličina | pole |
|---|---|---|
| **2501** | Stavový bitmask (níže) | rozpad do bool polí |
| 2502 | Power-off / blokace EVU (HDO) 0/1 | `evu_blocked` |
| 2504 | Fault status 0/1 | `fault` |
| 2505 | Bus status | `bus_status` |
| 2506 | Odtávání zahájeno | `defrost_initiated` |
| 2507 | Číslo aktivní chyby | `error_code` |

Bity 2501: **b0** čerpadlo HK1 · **b1** HK2 · **b2** zátopový program · **b3** `nhz_on` · **b4** `mode_heating` ·
**b5** `mode_dhw` · **b6** `compressor_on` · **b7** `summer_mode` · **b8** `mode_cooling` · **b9** `defrost` ·
**b10/b11** tichý režim 1/2.

Odvozené pole **`hp_mode`**: `defrost` → `"defrost"`, jinak `compressor_on & mode_dhw` → `"dhw"`,
`compressor_on & mode_heating` → `"heating"`, `mode_cooling` → `"cooling"`, jinak `"idle"`.

### Blok 4 — energie a runtime (FC04, doc 3501–3522)

| Doc | Veličina | pole |
|---|---|---|
| 3501 | Teplo TUV dnes (kWh) | `heat_dhw_today_kwh` |
| 3502 + 3503 | Teplo TUV celkem (kWh + MWh) | `heat_dhw_total_kwh` = 3502 + 1000·3503 |
| 3504 | Teplo topení dnes (kWh) | `heat_heating_today_kwh` |
| 3505 + 3506 | Teplo topení celkem | `heat_heating_total_kwh` |
| 3507 + 3508 | Teplo NHZ topení celkem | `heat_nhz_heating_total_kwh` |
| 3509 + 3510 | Teplo NHZ TUV celkem | `heat_nhz_dhw_total_kwh` |
| **3511** | **El. spotřeba TUV dnes (kWh)** | `el_dhw_today_kwh` |
| 3512 + 3513 | El. spotřeba TUV celkem | `el_dhw_total_kwh` |
| **3514** | **El. spotřeba topení dnes (kWh)** | `el_heating_today_kwh` |
| 3515 + 3516 | El. spotřeba topení celkem | `el_heating_total_kwh` |
| 3517 / 3518 / 3519 | Runtime kompresor topení / TUV / chlazení (h) | `rt_heating_h`, `rt_dhw_h`, `rt_cooling_h` |
| 3520 / 3521 / 3522 | Runtime NHZ1 / NHZ2 / NHZ1+2 (h) | `rt_nhz1_h`, `rt_nhz2_h`, `rt_nhz_h` |

> ⚠️ Čítače jsou **v celých kWh** — nehodí se na okamžitý výkon. „Celkem" skládej vždy **kWh + 1000·MWh**
> (registr kWh přetéká do MWh). Známý komunitní problém: u některých FW jsou 35xx nespolehlivé — proto sanity
> check `el_*_total` musí být monotónní (viz §6).

### Blok 2 — parametry (FC03, doc 1501–1510) — jen čtení

| Doc | Veličina | pole |
|---|---|---|
| 1501 | Provozní režim: 0 nouzový, 1 pohotovost, 2 program, 3 komfort, 4 eco, 5 jen TUV | `operating_mode` |
| 1502 / 1503 | HK1 komfort / eco setpoint (0.1 °C) | `hc1_comfort_set`, `hc1_eco_set` |
| 1509 / 1510 | TUV komfort / eco setpoint (0.1 °C) | `dhw_comfort_set`, `dhw_eco_set` |

### SG Ready (mimo rozsah, jen zaznamenat)

`4001` on/off, `4002`/`4003` vstupy (FC03 zápis), `5001` provozní stav 1–4 (FC04). Budoucí řízení TČ jako
modulovatelný deferrable load — **teď nezapisovat**. Číst jen `5001` → `sg_state`.

---

## 5. Adaptér `stiebel_isg`

- Class `StiebelIsgAdapter` po vzoru `SolisAdapter`: `host`, `port=502`, `device_id=1`.
- Čte bloky hromadně (max 40 reg/request), dekóduje S16 + sentinel, vrací normalizovaný dict z §4
  + `hp_mode`, `power_est_w` (§8).
- Registrace do factory + `stiebel_isg` v dropdownu *ADAPTÉR*; nový device type **`heat_pump`** (přidat
  do enumu typů vedle `generation`/`storage`/`grid_point`; **ne** `load` — má vlastní sémantiku teplo×elektřina).
- Chybové stavy: timeout ISG → modul `offline`, ne crash kolektoru. Když `fault=1` nebo `error_code≠0`
  → alarm (stejný kanál jako ostatní alarmy).

---

## 6. Datový model (TimescaleDB)

**`hp_telemetry`** (hypertable, 30 s): `ts, module_id, t_outdoor, t_flow, t_return, t_buffer, t_dhw, t_dhw_set,
t_source, t_hotgas, p_high, p_low, flow_lpm, compressor_on, hp_mode, nhz_on, defrost, evu_blocked, fault,
error_code, operating_mode, sg_state, el_heating_today_kwh, el_dhw_today_kwh, heat_heating_today_kwh,
heat_dhw_today_kwh, el_heating_total_kwh, el_dhw_total_kwh, heat_heating_total_kwh, heat_dhw_total_kwh,
rt_heating_h, rt_dhw_h, rt_nhz_h, power_est_w`.
Retention/komprese stejná politika jako ostatní telemetrie.

**`hp_runs`** (historie spínání, edge detektor v kolektoru nad `compressor_on` a `nhz_on`):
`id, module_id, mode (heating|dhw|cooling|defrost|nhz), started_at, ended_at, t_outdoor_start,
el_kwh (Δ el_*_total za běh, může být 0 při krátkém běhu), heat_kwh`.
Otevřený běh má `ended_at NULL`. Při restartu kolektoru: běh s `NULL` starší než 6 h uzavřít s `ended_at = poslední ts`.

**Denní/měsíční agregace** — počítat z **`*_total`** čítačů (robustní vůči restartům i výpadku pollingu
přes půlnoc), ne z `*_today`:
```
el_day(d)   = max(el_total | ts∈d) − max(el_total | ts∈d−1)     # per topení, TUV; sum = celkem
el_month(m) = Σ el_day
COP_day     = heat_day / el_day   (jen když el_day > 0; zvlášť topení a TUV)
```
Ideálně **continuous aggregate `hp_daily`** (`day, module_id, el_heating, el_dhw, heat_heating, heat_dhw,
cop_heating, cop_dhw, runtime_min_heating, runtime_min_dhw, n_starts`) — `runtime_min` a `n_starts` z `hp_runs`.
Sanity: pokud `el_total` klesne (reset ISG / nespolehlivý FW) → den označit `suspect=true`, nepočítat záporné.

---

## 7. API + UI

**API** (REST/JWT, stejný styl):
- `GET /api/localities/{id}/heat-pump/state` — poslední snapshot (karta).
- `GET /api/localities/{id}/heat-pump/series?from&to&step` — teploty + stav pro graf.
- `GET /api/localities/{id}/heat-pump/runs?from&to` — historie spínání.
- `GET /api/localities/{id}/heat-pump/daily?from&to` — z `hp_daily` (den i měsíc = klient sečte / `group=month`).

**Karta „Tepelné čerpadlo"** (dashboard lokality, stat-card grid): stav (ikona + `hp_mode`, animace při běhu),
`t_dhw / t_dhw_set`, `t_outdoor`, `t_flow → t_return`, **dnes: el. kWh (topení + TUV), teplo kWh, COP**,
**měsíc: el. kWh**, runtime dnes, poslední start. Červený badge při `fault` / `evu_blocked` / `defrost`.

**Samostatný graf TČ** (nová záložka/stránka „Tepelné čerpadlo", rozsah den/týden/měsíc):
- křivky `t_flow`, `t_return`, `t_buffer`, `t_dhw` (+ `t_dhw_set` čárkovaně), `t_outdoor` na **druhé ose**;
- **podbarvení běhu** z `hp_runs` podle `mode` (heating / dhw / defrost / nhz různé barvy) — stejný vizuál jako
  podbarvení v audit trailu;
- pod grafem sloupce **denní el. spotřeba** (stack topení / TUV) + COP jako bod; přepínač den/měsíc.
- Tabulka historie spínání (start, konec, délka, režim, T_venk, kWh) — stránkovaná.

**Billing detail:** řádek „Tepelné čerpadlo" s kWh/měsíc a podílem na celkové spotřebě lokality.

---

## 8. Uzel v diagramu ⚡ tok

Nový uzel **„Tepelné čerpadlo"** mezi Dům a spotřebiče, vedle spirály (ikona TČ; animovaný tok při
`compressor_on`). ISG **nedává okamžitý výkon ve W** → MVP odhad:
```
power_est_w = (hp_nominal_kw if compressor_on else 0) + (nhz_kw if nhz_on else 0)   [×1000]
```
`hp_nominal_kw` se **samokalibruje**: každý den `hp_nominal_kw = el_day / (runtime_min_day/60)` (EMA přes 7 dní,
clamp 1–8 kW). V diagramu hodnotu zobrazovat s prefixem `~`. Domácí zátěž v diagramu **neodečítat** (TČ je
její součást) — jen ji vizuálně rozdělit: `Dům ostatní = load − power_est_w − spirála`.

> Výhled (mimo tento brief): Shelly Pro 3EM na přívodu TČ → reálný W; adaptér pak `power_est_w` nahradí měřením.

---

## 9. Vazba na stávající logiku

- **`night_reserve`:** místo odhadu runtime TČ z I2 použít `hp_daily.runtime_min_heating` + `el_day`
  (rolling 7 dní, podle T_venk) — přesnější vstup. Zatím **jen zapisovat, dispatch neměnit**.
- **COP model** `clamp(2.75 + 0.11·T, 1.8, 4.0)` → od teď existuje reálné `cop_heating(T_outdoor)` z dat;
  kalibraci udělat až po zimě, teď jen ukládat.
- UVR Fáze 1 (I1–I5) běží dál paralelně — křížová kontrola (I2 vs. `t_buffer`/`t_dhw`).

---


---

## OVĚŘENO — sweep 26. 8. 2026 na kuse (192.168.6.174, WPM3) ✅

Displej: venkovní 19,4 °C · „SKUT TEPLOTA AKUMULACE" 54,0 °C · „VD TOPENÍ DEN" 2,743 kWh.

**Sedí s dokumentací:** 507 T_venk (19,3) · 508 = teplota akumulace (54,0) · 517/518 buffer skut/set (55,0/54,0) ·
519 tlak (5,5) · 2501 bitmask (0x0000 v klidu) · 2502/2504/2507 = 0 · 1501 = 2 (program) · 5001 = 0.

**Odchylky (adaptér mapuje DLE KUSU):**
1. **Energetické páry PROHOZENÉ:** doc-3501/3511 („TUV dnes") = na tomto kuse **TOPENÍ**
   (3511 = 2 ↔ displej 2,743 kWh; 3501 = 11 kWh tepla; COP ≈ 4 při 19 °C sedí). Doc-3504/3514 = TUV (0 — TČ TUV nedělá).
2. **Registry `*_today` jsou v CELÝCH kWh** (2 vs. 2,743) → denní přesnost ±1 kWh.
3. **`*_total` čítače (3502/3503/3505/3506/3512/3513/3515/3516) vracejí 0** — nespolehlivý 35xx FW.
   → Denní agregace z `*_today` (max za den, půlnoční reset), totals jen logovat.
4. **Runtime registry 3517–3522 NEEXISTUJÍ** (IllegalAddress) → runtime + starty výhradně z `hp_runs`.
5. **WPM3 (ne 3i):** 512/513/515/520/521/522/536/538 = N/A; 509/539/540 = IllegalAddress → pole vynechána.
   TUV sekce na kartě není. NHZ nikde → `nhz_kw = 0`.
6. Blok 1502–1510 vrací nesmysly (1509 = −7,0) → ignorován, čte se jen 1501.

**Odpovědi na §11:** (1) WPM3. (2) NHZ není → 0. (3) TUV není na Stiebelu (nádrže + spirála). 
**Zbývá doověřit:** bit6 kompresoru za běhu TČ (sweep proběhl v klidu) — mini-check ráno při běhu.

## 10. Pořadí implementace + verze

1. **v0.64.0** — adaptér `stiebel_isg`, device type `heat_pump`, `hp_telemetry`, UI založení modulu, karta TČ (stav + teploty).
2. **v0.64.1** — `hp_runs` edge detektor, `hp_daily` agregát, den/měsíc kWh + COP na kartě.
3. **v0.64.2** — stránka „Tepelné čerpadlo": graf s podbarvením + tabulka historie + denní sloupce.
4. **v0.64.3** — uzel v diagramu ⚡ tok + samokalibrace `hp_nominal_kw` + billing řádek.

Před 1. krokem **§3 sweep** proti kusu a výsledek zapsat do briefu (sekce „OVĚŘENO", jako u Solisu).
Standard: py_compile + npm build, tarball do `/mnt/user-data/outputs/` se SHA-256, `infra/Caddyfile` mimo tarball.

---

## 11. Otevřené otázky

1. Typ controlleru (WPM3 vs. WPM3i) — ze sweepu (536–540).
2. Má TČ elektrický dohřev (NHZ)? Pokud ano, `nhz_kw` do configu.
3. Je TUV na Stiebelu, nebo jen topení do bufferu (UVR nádrže)? Ovlivní, zda `t_dhw` má smysl na kartě.
4. Přesná ikona TČ v diagramu — držet styl stávajících uzlů.
