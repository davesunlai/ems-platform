# EMS — Doménový katalog (mapa portfolia)

**Verze:** 0.2 (mapa, ne detail) · **Fáze projektu:** funkční analýza · **Režim:** control-ready, nasazení fázované
**Třída systému:** EMS/SCADA + **VPP / agregace flexibility** (technická i tržní rovina)

---

## 1. Účel a status

Tento dokument je **mapa všech typů objektů** napříč mezinárodním energetickým portfoliem — co lze sledovat, co řídit, jak zajistit lokální bezpečnost, čím se připojit a v jaké fázi to nasadit. Není to ještě detailní bodový seznam (point list) jednotlivých zařízení; ten vzniká až ve fázi 2 pro konkrétní moduly.

**Tři klíčová rozhodnutí, ze kterých katalog vychází:**

1. **Monitoring + řízení od začátku**, ale architektura je *control-ready* a ostrý zápis do zařízení se otevírá per-modul až po validaci v read-only režimu.
2. **Mix vlastního HW/PLC a cloud API** → existují dvě rodiny adaptérů s zásadně odlišnými možnostmi řízení (viz §4).
3. **Tržní rovina je součástí systému** — spot + podpůrné služby (FCR/aFRR). Z toho plyne optimalizační engine, předpovědi a rozhraní k trhům/TSO (viz §3.5 a §4).

---

## 2. Kanonický (společný) model

Aby byl systém univerzální, každý objekt — ať FVE nebo nabíječka — mapuje na stejné koncepty:

- **Typ objektu:** zdroj / úložiště / spotřebič / měřicí bod sítě / tržní produkt
- **Měřené body (telemetrie):** veličina, jednotka, časová značka (UTC + lokální TZ), **kvalita dat** (good/uncertain/bad/stale), zdroj
- **Řiditelné body (povely/setpointy):** rozsah, jednotka, režim potvrzování (command → ack → confirm), autorizace
- **Stav:** online/offline, dostupnost, provozní režim, alarmy
- **Metadata:** lokalita, region/stát, vlastník/tenant, časové pásmo, měna, regulatorní/tržní zóna (TSO/DSO)

Doporučení: opřít sémantiku o **IEC CIM (61970/61968)**, ať se nevynalézá vlastní ontologie.

**Společné veličiny napříč vším:** činný výkon P [kW/MW], jalový výkon Q [kVAr], energie [kWh/MWh] (import/export), napětí U, frekvence f, účiník, online stav, dostupnost.

---

## 3. Doménový katalog

Sloupce: **Měřené veličiny** · **Řiditelné parametry** · **Lokální fail-safe** · **Typický protokol** · **Fáze**

### 3.1 Výroba

| Typ | Měřené veličiny | Řiditelné parametry | Lokální fail-safe | Protokol | Fáze |
|---|---|---|---|---|---|
| **FVE** | P, Q, DC výkon, U/I stringů, irradiance, teplota panelů/měniče, kWh, účiník, chyby měniče | P-limit (curtailment), Q / cosφ setpoint, on/off, podpora napětí Q(U) | Při ztrátě spojení udržet poslední bezpečný limit dle pravidel TSO; ochrana měniče | SunSpec/Modbus TCP, IEC 61850; cloud (SolarEdge, Huawei, SMA, Fronius) | **1** |
| **VtE** | P, Q, rychlost a směr větru, otáčky rotoru, pitch, teploty gondoly, vibrace, dostupnost | P-limit/curtailment, Q setpoint, start/stop | Feathering/zastavení řeší turbínový kontrolér autonomně | **IEC 61400-25** (wind), OPC UA, Modbus; cloud SCADA výrobce | **1–2** |
| **Kogenerace (CHP)** | P el., tepelný výkon, spotřeba paliva, stav motoru, provozní hodiny, teploty, emise, účiník | P setpoint, start/stop, modulace výkonu, tepelný setpoint | Lokální PLC ochrana motoru, řízený odstav | Modbus, OPC UA, výrobní PLC (Siemens, Wago); cloud | **2** |
| **Vodní — klasická** (na řece, akumulační) | P, Q, průtok, hladina, otáčky, poloha lopatek, teploty ložisek | P setpoint, start/stop, otáčky | Turbínový regulátor, nouzové uzavření | IEC 61850, IEC 60870-5-104, Modbus | **2–3** |
| **Vodní — přílivová/vlnová** | P, stav, výška vln / fáze přílivu, mechanické parametry | Omezené, dle technologie (často jen on/off) | Mechanická ochrana zařízení | Vlastní/experimentální, OPC UA, Modbus | **3** |

> Pozn.: kogenerace = částečně i akumulace (závisí na palivu — biometan/vodík ano, fosilní ne). V modelu ji vedeme jako zdroj s atributem „palivo".

### 3.2 Akumulace

| Typ | Měřené veličiny | Řiditelné parametry | Lokální fail-safe | Protokol | Fáze |
|---|---|---|---|---|---|
| **BESS (baterie)** | SoC, SoH, P (nabíjení/vybíjení), U/I modulů, teploty článků, počet cyklů, dostupná kapacita, stav PCS, alarmy BMS | P setpoint (± charge/discharge), provozní režim (peak-shaving, FCR, arbitráž), Q setpoint, limity SoC | **BMS** = ochrana (přehřátí, přepětí), odpojení, udržení bezpečného SoC pásma | Modbus, IEC 61850; CAN interně (BMS); cloud API | **1** (vysoká hodnota) |
| **PVE (přečerpávací)** | P (turbína/čerpadlo), hladiny obou nádrží, průtok, režim (čerpání/výroba) | Přepnutí režimu, P setpoint, start/stop | Hydraulické ochrany, řízený přechod režimu | IEC 61850, IEC 60870-5-104 | **2–3** |
| **Vodík** (elektrolyzér + zásobník + palivový článek) | Příkon elektrolyzéru, produkce H₂ [kg/Nm³], tlak, čistota, stav zásobníku, výkon palivového článku, teploty | **P setpoint elektrolyzéru** (= flexibilní zátěž!), start/stop, režim výroba↔spotřeba | Tlakové a ATEX bezpečnostní (vodík!), lokální PLC, řízený odstav | Modbus, OPC UA, PLC | **2–3** |

> Pozn.: elektrolyzér je zároveň **řiditelná zátěž** — cenný nástroj pro balancing. V modelu se chová jako úložiště i jako spotřebič.

### 3.3 Odběr

| Typ | Měřené veličiny | Řiditelné parametry | Lokální fail-safe | Protokol | Fáze |
|---|---|---|---|---|---|
| **Domácnosti** | P odběr, kWh, případně podružná měření, U/f | Zpravidla nic (monitoring); přes HEMS lze spínání / DSM | — | Smart meter (**DLMS/COSEM**), MQTT, cloud | **1** (monitoring) / **3** (řízení) |
| **AC nabíječky (domácí)** | P, energie session, stav konektoru, ID session/uživatel | Max proud/výkon (**smart charging**), start/stop, autorizace | Lokální omezení dle jištění objektu | **OCPP 1.6 / 2.0.1** | **1–2** |
| **DC nabíječky (veřejné)** | P, energie, stav, session, dostupnost konektorů | Výkonové omezení, **load management** mezi stojany, start/stop | Lokální výkonový limit přípojky | **OCPP 2.0.1** | **2** |
| **Výrobny vodíku jako zátěž** | viz §3.2 elektrolyzér z pohledu odběru | P setpoint (řízená flexibilní zátěž) | viz §3.2 | Modbus, OPC UA | **2–3** |

### 3.4 Síť

| Typ | Měřené veličiny | Řiditelné parametry | Lokální fail-safe | Protokol | Fáze |
|---|---|---|---|---|---|
| **Přípojné/měřicí body** | P/Q import/export na rozhraní, U, f, THD, výkonové toky | — (měření rozhraní; klíčové pro netting a fakturaci) | — | IEC 60870-5-104, Modbus, měřidla | **1** |
| **Zátěž sítě / transformátory** | Zatížení transformátorů, teploty, U na úrovních, toky výkonu | Přepínání odboček (OLTC) — pokročilé | Lokální ochrana transformátoru | IEC 61850, IEC 60870-5-104 | **2–3** |

### 3.5 Trh a obchod (nová doména po rozhodnutí o obchodní rovině)

Tržní vrstva nepracuje s fyzikálními veličinami, ale s **produkty, závazky a signály**. Je to samostatná doména, která konzumuje technická data zdola a posílá záměry dolů přes optimalizační engine.

| Objekt / koncept | Co drží | Vstupy | Výstupy / akce | Časová kritičnost |
|---|---|---|---|---|
| **Spotový trh (DA/ID)** | day-ahead a intraday ceny, pozice, gate-closure časy | ceny burzy, předpovědi | nákup/prodej, rozvrhy (schedule) | min–hod |
| **FCR** (frekvenční rezerva) | nasmlouvaný objem, dostupnost | frekvence sítě (lokálně!), aktivace | **plná aktivace ~30 s** → setpoint na BESS | **sekundy — edge** |
| **aFRR/mFRR** (regulační energie) | nasmlouvaný objem, aktivační signál TSO | signál TSO, baseline | aktivace výkonu ~5 min | **minuty** |
| **Předpověď (forecast)** | výroba (počasí), spotřeba, ceny | meteo, historie, kalendář | vstup pro optimalizaci | hod–dny |
| **Optimalizace / dispatch** | alokace portfolia napříč trhy | vše výše + technické limity | setpointy, rozvrhy, nabídky | min |
| **Settlement / fakturace** | naměřené závazky vs. plnění | certifikovaná měření, baseline | reporty, vyúčtování | hod–dny |

**Klíčové důsledky:**

- **FCR/aFRR vyžaduje měření a aktivaci blízko zařízení** — frekvence se vyhodnocuje lokálně, aktivace nesmí čekat na centrum ani cloud. Potvrzuje princip edge fail-safe a control-ready architektury.
- **Prekvalifikace u TSO** — pro podpůrné služby je nutné certifikované měření, definovaná baseline a často vyšší rozlišení telemetrie. To zpětně klade nároky na §2 (kvalita dat, časové značky).
- **Optimalizační engine = mozek systému** — rozhoduje mezi konkurenčními užitími téhož zařízení (BESS pro FCR vs. arbitráž). Bez něj je obchodní rovina jen ruční.
- **Multi-region = multi-trh** — každá tržní zóna má vlastní produkty, gate-closure, settlement i prekvalifikaci. Tržní pravidla je nutné abstrahovat per-region, ne zadrátovat.

---

## 4. Tři rodiny rozhraní

Adaptérová/rozhraní vrstva má tři větve s odlišnými vlastnostmi — jádro o nich neví, mluví jen kanonickým modelem.

| Vlastnost | **Přímý protokol (vlastní HW/PLC)** | **Cloud API (třetí strana)** | **Trh / TSO** |
|---|---|---|---|
| Latence | ms–s | sekundy–desítky s | min (obchod) / s (aktivace) |
| Spolehlivost | vysoká, plně v naší režii | závisí na cizí službě, rate limity | smluvní, certifikovaná |
| Řízení | plné, vč. rychlých služeb (FCR/aFRR) | omezené na to, co API dovolí; pomalé | obousměrné: nabídky ↑, aktivace ↓ |
| Fail-safe | **ano, na edge** | nelze garantovat | aktivace FCR/aFRR řešena na edge |
| Nasazení | edge gateway u zařízení (store-and-forward) | centrální konektor, polling/webhook | centrální konektor per tržní zóna |
| Vhodné pro | BESS, vlastní FVE/CHP, nabíječky, řízení | monitoring cizích instalací, pomalý curtailment | spot, podpůrné služby, transparency data |

**Pravidlo:** rychlé a bezpečnostně kritické řízení → jen přímý protokol + edge. Cloud → monitoring a pomalé povely. Trh → obchodní rovina + aktivační signály, jejichž *fyzická realizace* běží přes edge. Žádné cizí API (ani tržní) nesmí být single point of failure pro bezpečnost.

---

## 5. Co dotáhnout v dalších krocích

1. **Cílové regiony / tržní zóny** — určuje TSO pravidla, produkty podpůrných služeb, settlement, prekvalifikaci a regulatoriku (NIS2, GDPR). **Nejvyšší priorita** — tvaruje celou tržní vrstvu.
2. **Aktéři a use-cases** — dispečer, správce portfolia, obchodník/trader, majitel výrobny, billing, údržba. (krok funkční analýzy č. 2)
3. **Nefunkční požadavky** — cíle latence (FCR ~30 s, aFRR ~5 min), RTO/RPO, úroveň redundance, certifikace.
4. **Optimalizační engine + forecasting** — návrh mozku: jak alokovat portfolio napříč spotem a podpůrnými službami; zdroje předpovědí (meteo, ceny, spotřeba).
5. **Výběr 1–2 typů pro hloubkový bodový list (point list)** jako pilot — kandidáti: **BESS** (nejvyšší hodnota řízení + ideál pro FCR) + **FVE** (nejvíc instalací, jasný protokol).
6. **Cílová architektura** — kanály (telemetrie ↑ / povely ↓ / lokální autonomie + tržní rovina), message bus, time-series + konfigurační DB, optimalizační engine, HA na Linuxu.

---

*Otevřené otázky k doplnění: konkrétní cílové regiony/státy a tržní zóny; zda řešit i plyn jako samostatnou doménu nebo jen okrajově; rozsah a zdroje předpovědí pro optimalizaci.*
