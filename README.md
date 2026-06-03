# EMS Platform

Univerzální energy management napříč energetickým portfoliem — sledování a (postupně) řízení vyrobené a spotřebované elektrické energie. Stavěno modulárně: jádro drží kanonický model, každý typ zdroje se připojuje přes vlastní adaptér.

Tento repozitář začíná **pilotem jedné domácnosti** (FVE 26 kWp, baterie 52 kWh, dvě Goodwe měniče), ale architektura je od začátku připravená na škálování (viz `docs/architecture.md`).

## Stav

- **Monitoring** reálných Goodwe měničů (ET hybrid + DT grid-tie).
- **Identita a RBAC** (v0.2): přihlášení (JWT), role viewer/operator/admin, oprávnění `read`/`control`/`admin`, správa uživatelů.
- **Registr modulů v DB** (v0.3): správa zařízení/modulů z admin UI, živá rekonciliace bez restartu kolektoru, migrace z devices.yaml.
- **Řízení / zápis do měniče** (v0.4): povelový kanál s ověřením (read-back) a auditem, oprávnění `control`. První povel: režim baterie Goodwe ET — vynucené nabíjení / normální režim.
- **Automatizace dle spotové ceny** (v0.5): pravidlo „levný spot → nabíjej", zdroj cen OTE + ruční test, audit automatických povelů, samoopravné edge-triggerem. První VPP chování.
- React SPA frontend (přihlášení, dashboard, řízení, automatizace, správa modulů a uživatelů).

### Role a oprávnění
- **viewer** — `read`: jen dashboard.
- **operator** — `read` + `control`: dashboard + Řízení.
- **admin** — vše + Moduly + Uživatelé.

### Přihlášení

Při prvním nasazení `deploy.sh` vytvoří admina a vypíše heslo (`admin / <heslo>`).
Role: **viewer** (jen čtení), **operator** (čtení + budoucí řízení), **admin** (vše + správa uživatelů).
Změnit/založit uživatele: web → Uživatelé (jen admin).

## Rychlý start (bez DB, bez VPN)

Rozjede celý sběr v mock režimu (simulovaný měnič) a vypisuje na stdout:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
cp devices.example.yaml devices.yaml   # uprav: adapter: mock
make run-mock
```

## Celý stack (TimescaleDB + API + web)

```bash
cp devices.example.yaml devices.yaml
docker compose -f infra/docker-compose.yml up -d --build
# web:  http://localhost:8080
# API:  http://localhost:8080/api/health   (přes nginx proxy)
```

## Nasazení na Debian stroj (např. 192.168.6.209)

Na čistém Debianu stačí dva skripty:

```bash
# 1) Instalace Dockeru (jednorázově, jako root)
sudo bash scripts/setup-debian.sh
#    pak se odhlas a přihlas, ať se projeví členství ve skupině docker

# 2) Nasazení stacku
bash scripts/deploy.sh
```

`deploy.sh` při prvním běhu vytvoří `devices.yaml` v **mock** režimu (běží hned, bez VPN) a `.env` s náhodným heslem databáze. Po nahození:

- Web: `http://192.168.6.209:8080`
- API zdraví: `http://192.168.6.209:8080/api/health`
- Swagger UI: `http://192.168.6.209:8000/docs`

Služby mají `restart: unless-stopped`, takže se po rebootu stroje samy nahodí.

```bash
docker compose -f infra/docker-compose.yml ps                  # stav
docker compose -f infra/docker-compose.yml logs -f collector   # živé logy sběru
docker compose -f infra/docker-compose.yml down                # zastavit
```

### Upgrade běžícího pilotu na novou verzi

```bash
# rozbal nový tar přes /opt/ems, pak:
cd /opt/ems
docker compose -f infra/docker-compose.yml up -d --build
```

DB volume zůstává; tabulka `users` se vytvoří automaticky při startu API.
Pokud `.env` nemá `EMS_JWT_SECRET`/`EMS_ADMIN_PASSWORD`, doplň je (nebo smaž `.env` a nech `deploy.sh` vygenerovat nové).

## Připojení reálného měniče

1. Zprovozni síťový přístup k domácí síti (zatím OpenVPN, později edge HW — Raspberry).
2. Zjisti lokální IP měničů a ověř komunikaci:
   ```bash
   python scripts/discover.py 192.168.1.10        # UDP 8899
   python scripts/discover.py 192.168.1.10 --port 502   # Modbus TCP (LAN dongle V2)
   ```
3. Sensor ID z výpisu zkontroluj proti `ems/adapters/goodwe/mapping.py` (případně doplň).
4. V `devices.yaml` přepni `adapter: mock` → `goodwe` a doplň `host`.

## Architektura v kostce

```
[zařízení] → adaptér → kanonický model → sink → TimescaleDB → API → web/mobil
```

- **Jádro** (`ems/core`) — kanonický model + rozhraní adaptéru/sinku. Nezná žádný konkrétní protokol.
- **Adaptéry** (`ems/adapters`) — překlad nativního protokolu do modelu. Goodwe (ET i DT) + mock.
- **Sinky** (`ems/sinks`) — kam se zapisuje: stdout (dev), TimescaleDB (provoz). Místo pro pozdější message bus.
- **Kolektor** (`ems/collector`) — pollovací smyčka, odolná vůči chybě jednoho zařízení.
- **API** (`ems/api`) — REST nad uloženou telemetrií.
- **Web** (`web`) — dashboard. Mobil (Android/iOS) přijde později nad stejným API.

## Přidání nového typu zdroje

1. Nový adaptér v `ems/adapters/<typ>/` implementující `TelemetryAdapter` (connect/read/close).
2. Mapování nativních veličin na `Metric` z kanonického modelu.
3. Zaregistruj jméno adaptéru v `ems/collector/config.py:build_adapter`.

Jádro ani úložiště se nemění.

## Struktura

```
ems/
  core/        kanonický model + rozhraní
  adapters/    goodwe (adapter, mapping, mock)
  sinks/       stdout, timescale
  collector/   config + pollovací smyčka
  api/         FastAPI
web/           dashboard
infra/         docker-compose, DB schéma, Dockerfile
scripts/       discover.py
docs/          architektura, ADR, doménový katalog
```

## Licence

MIT (placeholder — uprav dle potřeby).
