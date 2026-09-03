# Předávací brief — EMSBOX (edge gateway TERA EMS)

> **Pro nosný chat (má repo + Docker).** Připraveno ve vedlejším chatu. Obsahuje architekturu
> lokálního linuxového boxu, protokol store-and-forward synchronizace, serverové změny (ingest API,
> entita emsbox, alerty per lokalita/zařízení) a provisioning. Implementace serverové části v nosném
> chatu; box-side agent je stejný repo (sdílené adaptéry).

---

## 1. Cíl

**EMSBOX** = malý linuxový počítač u klienta, který:

1. **Čte zařízení lokálně** — primárně **RS485 (Modbus RTU)**, dále Modbus TCP a HTTP na LAN klienta.
2. **Sbírá data i bez internetu** — lokální buffer, výdrž **min. 1 měsíc offline**.
3. Po obnovení spojení **dohraje data** na teraems.com (idempotentně, bez duplicit).
4. Je **lokálně konfigurovatelný přes HTTPS** (síť, sériové porty, párování, diagnostika).
5. TERA EMS eviduje boxy, hlídá jejich dostupnost a posílá **alerty vázané na lokalitu i zařízení**
   (s potlačením bouře alertů, když spadne celý box).

---

## 2. Klíčové architektonické rozhodnutí: sdílený kód

**EMSBOX agent = stejný Python kód jako kolektor na frantovi.** Monorepo `/opt/ems`:

```
/opt/ems/
├── ems/                    # stávající backend
│   └── adapters/           # solis, goodwe, stiebel_isg, uvr_cmi, mock…  ← SDÍLENÉ
├── emsbox/                 # NOVÉ — edge agent
│   ├── agent/              # collector loop + buffer + sync + heartbeat
│   ├── localui/            # FastAPI lokální UI
│   ├── docker-compose.yml  # agent + caddy (lokální HTTPS)
│   └── Dockerfile
└── ...
```

Adaptéry se **nikdy neduplikují** — box importuje `ems.adapters.*`. Nový adaptér na serveru
= automaticky dostupný na boxu (po update image). Do adaptérů přibude transport
**`modbus_rtu`** (pymodbus `ModbusSerialClient`), jinak jsou beze změny — adaptér dostane
client factory podle configu rozhraní.

**Transporty rozhraní (interface config zařízení):**

| transport | parametry |
|---|---|
| `modbus_rtu` | `port` (/dev/ttyUSB0…), `baudrate`, `parity` (N/E/O), `stopbits`, `bytesize`, `device_id` |
| `modbus_tcp` | `host`, `port` (502), `device_id` |
| `http` | `base_url`, `auth`, `poll_s` (CMI apod.) |

Na jedné RS485 sběrnici může viset víc zařízení (různá `device_id`, stejný `port`) — agent
serializuje přístup k portu (jeden lock per /dev/tty*).

---

## 3. Box-side architektura (služby)

Docker Compose na boxu, 2 kontejnery:

1. **`emsbox-agent`** (Python/asyncio):
   - **Collector loop** — čte zařízení dle configu (stejné intervaly jako na serveru, 30 s default).
   - **Buffer** — SQLite (WAL) `buffer.db`: fronta telemetrie čekající na odeslání.
   - **Sync worker** — push batchů na teraems.com (viz §5), heartbeat.
   - **Config cache** — poslední známý config z serveru na disku; box funguje offline s cache.
   - **Local API** — FastAPI pro lokální UI (status, síť, diagnostika, párování).
2. **`caddy`** — lokální HTTPS reverse proxy před local API, `tls internal` (Caddy si vygeneruje
   vlastní lokální CA → prohlížeč jednou potvrdí výjimku). Porty 80→443 redirect.

**mDNS:** avahi na hostu → box dostupný jako **`https://emsbox-<krátké-id>.local`** i bez znalosti IP.
DHCP default, statická IP nastavitelná v lokálním UI.

**Watchdog:** systemd unit `emsbox.service` = `docker compose up -d` + restart policy
`unless-stopped`; hardwarový watchdog Pi zapnout (`dtparam=watchdog=on` + systemd `RuntimeWatchdogSec`).

### Buffer — dimenzování a SD karta

- 5 zařízení à 30 s ≈ 14 400 řádků/den ≈ **5–10 MB/den** → měsíc offline ≈ **150–300 MB**. Pohoda.
- SQLite: WAL, `synchronous=NORMAL`, insert v transakci per poll-cyklus (ne per řádek) → šetří flash.
- Řádek: `id, device_uid, ts (UTC), payload (JSON metrik), sent (bool)`. Po ACK smazat; VACUUM 1×/den.
- **Riziko SD karty:** doporučit industrial SD (např. SanDisk High Endurance) nebo USB SSD.
  Logy journald omezit (`SystemMaxUse=100M`).

### Čas bez internetu (KRITICKÉ)

Bez NTP a bez RTC ujede Pi za měsíc klidně o minuty → rozbité timestampy.
**Hardware RTC DS3231 (I2C, ~100 Kč) je povinná součást boxu.** Setup: `dtoverlay=i2c-rtc,ds3231`,
vypnout fake-hwclock. Agent navíc při syncu posílá `box_time` → server loguje drift a při
driftu > 60 s alert „RTC drift" (baterka RTC umřela).

---

## 4. Provisioning (párování boxu k lokalitě)

1. **teraems UI:** lokalita → „Přidat EMSBOX" → server vygeneruje **párovací kód**
   (8 znaků, platnost 1 h) + zobrazí návod.
2. **Lokální UI boxu** (první boot = wizard): zadat URL serveru (default `https://teraems.com`)
   + párovací kód → box `POST /api/emsbox/pair {code, hw_info}`.
3. Server ověří kód → založí/aktivuje záznam boxu, vrátí **`box_id` + `box_token`**
   (dlouhý náhodný, uložen hashovaný jako u hesel). Box token uloží do `/data/credentials.json` (chmod 600).
4. Box stáhne config (§6) a začne sbírat.

Box **jen pushuje ven** (HTTPS na teraems.com) — žádný inbound port z internetu, žádná VPN nutná.
Re-pair = smazat credentials v lokálním UI (tlačítko „Odpárovat", vyžaduje lokální admin heslo boxu).

---

## 5. Sync protokol (store-and-forward)

### Ingest endpoint (server, NOVÝ)

```
POST /api/ingest/v1/telemetry
Authorization: Bearer <box_token>
{
  "box_id": "...",
  "batch_id": "uuid",              # idempotence
  "box_time": "2026-09-03T10:00:00Z",
  "rows": [
    {"device_uid": "...", "ts": "...", "metrics": {...}},
    ...  # max ~1000 řádků / batch
  ]
}
→ 200 {"ack": "uuid", "accepted": N, "duplicates": M}
```

- **Idempotence dvojitá:** (a) server si pamatuje posledních ~1000 `batch_id` per box (tabulka
  `ingest_batches`, TTL 7 dní) → retry celého batche je no-op; (b) insert telemetrie
  `ON CONFLICT (module_id, ts) DO NOTHING` → duplicitní řádky neškodí.
- **`device_uid`** = stabilní identifikátor modulu přidělený serverem v configu boxu
  (mapuje se na `module_id`); box nikdy nevymýšlí vlastní ID.
- **Pořadí dohrávání:** při backlogu box posílá **1) nejdřív aktuální snapshot** (dashboard hned žije),
  **2) pak backlog po chuncích od nejnovějšího k nejstaršímu** — grafy se plní od přítomnosti dozadu.
  TimescaleDB continuous aggregates zvládají out-of-order zápis (invalidation) — ověřit, že
  refresh policy pokrývá i starší okno (lag min. 35 dní kvůli měsíčnímu výpadku!).
- **Backoff:** při chybě exponenciálně 5 s → 5 min, jitter. Rate: max 1 batch/s (dohrání měsíce
  ≈ 430 batchů ≈ pár minut).

### Heartbeat

```
POST /api/ingest/v1/heartbeat    (à 60 s)
{box_id, box_time, uptime_s, buffer_rows, buffer_oldest_ts, disk_free_mb,
 devices: [{device_uid, last_read_ts, ok: bool, error: "..."}]}
```

Heartbeat nese i **per-device stav čtení** → server ví rozdíl mezi „box offline"
a „box online, ale zařízení X neodpovídá na sběrnici".

### Config pull

```
GET /api/emsbox/{box_id}/config   (ETag; box polluje à 5 min)
→ {devices: [{device_uid, adapter, transport, params, poll_s}], settings: {...}}
```

**Server = zdroj pravdy pro definici zařízení.** V teraems UI se u zařízení nově volí
**„Připojení: přímo / přes EMSBOX <název>"** + parametry rozhraní (viz §2 transporty).
Box si config cachuje na disk a jede s ním offline. Lokální UI boxu zařízení **needituje**
(jen zobrazuje + diagnostika) — jediný zdroj pravdy, žádné konflikty. Lokálně se edituje
jen to, co server vědět nemůže: síť boxu, statická IP, admin heslo lokálního UI.

---

## 6. Serverové změny (implementace v nosném chatu)

### DB schéma

```sql
CREATE TABLE emsbox (
  id SERIAL PRIMARY KEY,
  locality_id INT NOT NULL REFERENCES localities(id),
  name TEXT NOT NULL,
  token_hash TEXT NOT NULL,
  hw_info JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  last_heartbeat TIMESTAMPTZ,
  last_ingest TIMESTAMPTZ,
  buffer_rows INT,
  buffer_oldest_ts TIMESTAMPTZ,
  clock_drift_s REAL,
  status TEXT DEFAULT 'pairing'    -- pairing|online|offline|disabled
);

CREATE TABLE emsbox_pairing_codes (
  code TEXT PRIMARY KEY, locality_id INT, expires_at TIMESTAMPTZ, used BOOLEAN DEFAULT false
);

CREATE TABLE ingest_batches (
  batch_id UUID PRIMARY KEY, box_id INT, received_at TIMESTAMPTZ DEFAULT now()
);

-- devices/modules: nový sloupec
ALTER TABLE modules ADD COLUMN emsbox_id INT REFERENCES emsbox(id);  -- NULL = přímé čtení frantou
ALTER TABLE modules ADD COLUMN transport_params JSONB;               -- rtu/tcp/http parametry
```

Modul s `emsbox_id != NULL` serverový kolektor **přeskakuje** — data přijdou ingestem.

### Alerty — vazba na lokalitu I zařízení

```sql
CREATE TABLE alert_rules (
  id SERIAL PRIMARY KEY,
  locality_id INT NOT NULL,
  scope TEXT NOT NULL,            -- 'locality' | 'emsbox' | 'device'
  target_id INT,                  -- emsbox.id nebo modules.id (NULL při scope=locality)
  kind TEXT NOT NULL,             -- 'offline' | 'fault' | 'rtc_drift' | 'buffer_high' …
  threshold_min INT DEFAULT 15,   -- jak dlouho stale, než alert
  channel TEXT DEFAULT 'email',
  recipients TEXT[],              -- default = e-maily uživatelů lokality
  enabled BOOLEAN DEFAULT true
);

CREATE TABLE alert_events (
  id SERIAL PRIMARY KEY, rule_id INT, opened_at TIMESTAMPTZ, closed_at TIMESTAMPTZ,
  detail JSONB    -- co, od kdy, poslední hodnoty
);
```

**Evaluátor** (background task à 1 min):

- `emsbox offline` = `now - last_heartbeat > threshold` → **jeden** alert za box.
- **Potlačení bouře (klíčový požadavek):** dokud je otevřený `emsbox offline` event, **per-device
  offline alerty zařízení za tímto boxem se NEposílají** (v evaluátoru skip modulů s tímto
  `emsbox_id`). Po návratu boxu se per-device pravidla zase vyhodnocují normálně.
- `device offline` = zařízení stale (přímé: žádná telemetrie; za boxem: heartbeat hlásí `ok=false`)
  → alert jen pro to zařízení.
- **Recovery mail** při `closed_at` („EMSBOX DavidDoma zpět online, dohráno N řádků za období X–Y").
- Anti-flap: hystereze — close až po 2× threshold v pořádku; re-open stejného pravidla
  max 1 mail / 6 h (nastavitelné).
- Odesílání stávajícím SMTP (control@teraems.com / Forpsi).

### API + UI (teraems)

- `POST /api/ingest/v1/telemetry`, `/heartbeat` (auth box tokenem — nový auth dependency,
  mimo uživatelský JWT).
- `POST /api/emsbox/pair` (public + pairing code).
- `GET /api/emsbox/{id}/config` (auth box tokenem).
- CRUD `/api/localities/{id}/emsboxes` (uživatelské, permission stejné jako správa modulů).
- **UI:** karta „EMSBOX" v lokalitě — stav (🟢/🔴), poslední heartbeat, buffer (řádky + stáří
  nejstaršího), drift hodin, verze agenta; tlačítko „Přidat EMSBOX" → párovací kód.
  U modulu volba připojení „přes EMSBOX" + formulář transport parametrů.
  Sekce „Alerty" v lokalitě — tabulka pravidel (scope, cíl, druh, práh, příjemci, on/off).

---

## 7. Hardware (doporučení pilotního kusu)

| Komponenta | Doporučení | Pozn. |
|---|---|---|
| Board | **Raspberry Pi 4 (2–4 GB)** nebo CM4 na carrier boardu | Debian/RPi OS Lite 64bit; dost výkonu na Docker + Python |
| RS485 | **USB-RS485 dongle s FTDI čipem** (ne noname CH340) | stabilní /dev/serial/by-id/… cesta, nezávislá na pořadí USB |
| RTC | **DS3231 modul na I2C** | povinné (měsíc offline) |
| Úložiště | industrial microSD **nebo** USB SSD | endurance |
| Zdroj + krabice | 5V/3A, DIN-rail krabice do rozvaděče | |

RT5350F-OLinuXino (32 MB RAM, OpenWrt) na plný agent **nestačí** — zůstává jen jako případný
hloupý RTU→TCP převodník pro variantu bez boxu. Pi třída je pro EMSBOX minimum.
Pozdější „produktová" varianta: průmyslový box (např. Olimex A64/Teres, NanoPi R5S, nebo
x86 fanless) — architektura je na HW nezávislá (Docker, arm64/amd64 multi-arch image).

---

## 8. Pořadí implementace

1. **Server:** schéma (emsbox, alert_rules, sloupce modules) + ingest API + pair + config endpoint.
2. **Server:** evaluátor alertů + SMTP notifikace + potlačení bouře. UI karta EMSBOX + alerty.
3. **Box:** agent skeleton — config pull, collector loop nad sdílenými adaptéry (`modbus_tcp` první,
   otestovat proti Solisu na LAN), SQLite buffer, sync + heartbeat.
4. **Box:** transport `modbus_rtu` (pymodbus ModbusSerialClient + port lock) + test na reálné 485.
5. **Box:** lokální UI (wizard párování, síť, diagnostika „test čtení") + Caddy `tls internal` + avahi.
6. **Test výpadku:** vytáhnout WAN boxu na hodiny/dny → ověřit dohrání, dedup, alert + recovery mail,
   continuous aggregates nad dohranými daty.
7. Multi-arch build (arm64) + OTA strategie (watchtower nebo `emsbox update` v lokálním UI).

---

## 9. Otevřené otázky (rozhodnout před implementací)

1. **Ovládání přes box** (zápis do měniče při Smart Control) — MVP je read-only sběr.
   Ovládání = zpětný kanál (long-poll/WebSocket z boxu na server). Potvrdit, že MVP = jen čtení?
2. **Co má box dělat offline autonomně?** Jen sbírat (MVP), nebo časem i lokální ochranné
   logiky (soc_min apod.)? Ovlivní to, kolik logiky se přesune do agenta.
3. Pilotní HW kus — Pi 4 ze šuplíku, nebo rovnou koupit cílový průmyslový box?
4. `device_uid` formát — navrhují UUID přidělené serverem při založení modulu (přežije přejmenování).
5. Retence `ingest_batches` a max. velikost batche — návrh 1000 řádků / 7 dní TTL, potvrdit.
