# TERA EMS

Univerzální energy management napříč energetickým portfoliem — sledování a (postupně) řízení vyrobené a spotřebované elektrické energie. Stavěno modulárně: jádro drží kanonický model, každý typ zdroje se připojuje přes vlastní adaptér.

Tento repozitář začíná **pilotem jedné domácnosti** (FVE 26 kWp, baterie 52 kWh, dvě Goodwe měniče), ale architektura je od začátku připravená na škálování (viz `docs/architecture.md`).

## v0.20.1 — Souhrn lokality: klik na popisek skryje/zobrazí řadu (přepočte osu), přidána řada Baterie.

## v0.20.0 — Grafy: hover svislá čára u kurzoru s časem a hodnotou (MultiChart ukáže všechny řady naráz).

## v0.19.1 — deploy.sh na konci restartuje web (nginx), aby po přegenerování api nedržel starou IP (konec opakovaných Bad Gateway).

## v0.19.0 — Oznámení odstávek: hodina běhu (EMS_OUTAGE_HOUR) a opakování ve dnech (EMS_OUTAGE_REMIND_DAYS) v .env; úvodní mail + připomínky až do odstávky (řízeno last_notified); kolektor dostal SMTP.

## v0.18.1 — Admin může u uživatele změnit Jméno (tlačítko ✎ u jména v seznamu uživatelů).

## v0.18.0 — E-mail přiřazeným uživatelům při nové plánované odstávce (edge-trigger na nově zjištěné odstávky, denně i při „Načíst teď").

## v0.17.1 — Pevné DNS (1.1.1.1/8.8.8.8) pro api a collector kontejnery, aby dosáhly na ČEZ (jinak „name resolution" chyba uvnitř kontejneru).

## v0.17.0 — Průvodce systémem: po prvním přihlášení provede klikacími kroky, přepíná stránky a zvýrazňuje menu; znovu spustitelný tlačítkem „Průvodce".

## v0.16.1 — Graf zařízení se po výběru veličiny bez dat neschová celý, ukáže ovládání + hlášku (snazší dostat se k SoC).

## v0.16.0 — Dashboard: klikací dlaždice přepínají metriku grafu (vč. SoC baterie), barva křivky dle veličiny.

## v0.15.3 — Předání EMS_SMTP_FROM_NAME do api kontejneru v docker-compose (jinak se proměnná z .env nedostala dovnitř).

## v0.15.2 — Konfigurovatelné jméno odesílatele e-mailů přes EMS_SMTP_FROM_NAME (výchozí „TERA EMS").

## v0.15.1 — Menu „Kontakt" přejmenováno na „Spínací kontakty"; stránka připravena na další spínané výstupy (eWeLink/Olimex) a spouštěče.

## v0.15.0 — Výstrahy v liště: trojúhelník s počtem výstrah scoped na lokality uživatele, generický agregátor (zatím odstávky), endpoint /api/alerts.

## v0.14.0 — Plánované odstávky distribuce (ČEZ): identifikace u lokality (EAN/elektroměr/adresa, priorita), denní stahování, zobrazení v adminu.

## Stav

- **Monitoring** reálných Goodwe měničů (ET hybrid + DT grid-tie).
- **Identita a RBAC** (v0.2): přihlášení (JWT), role viewer/operator/admin, oprávnění `read`/`control`/`admin`, správa uživatelů.
- **Registr modulů v DB** (v0.3): správa zařízení/modulů z admin UI, živá rekonciliace bez restartu kolektoru, migrace z devices.yaml.
- **Řízení / zápis do měniče** (v0.4): povelový kanál s ověřením (read-back) a auditem, oprávnění `control`. První povel: režim baterie Goodwe ET — vynucené nabíjení / normální režim.
- **Automatizace dle spotové ceny** (v0.5): pravidlo „levný spot → nabíjej", zdroj cen OTE + ruční test, audit automatických povelů, samoopravné edge-triggerem. První VPP chování.
- **Správa hesel** (v0.6): změna vlastního hesla, admin reset, zapomenuté heslo přes e-mail (Forpsi SMTP), profilová pole (e-mail, jméno).
- **Spínání kontaktu dle SOC** (v0.13.0): suchý kontakt (relé) měniče se sepne na horní mezi SOC a rozepne na dolní mezi (hystereze, např. 100/95 %); stránka „Kontakt" s nastavením mezí, zapnutím a ručním testem. Goodwe ET přes load_control_switch.
- **Nula při výpadku dat** (v0.12.4): u výkonových veličin (pv/load/grid) se při mezeře v datech (výpadek spojení se střídačem) vloží nula místo šikmé interpolační spojnice — graf spadne na 0 a po obnově se zvedne.
- **Uvítací a reset e-maily** (v0.12.3): po založení uživatele (s e-mailem) přijde brandovaný uvítací e-mail TERA EMS s odkazem na nastavení hesla; tlačítko „Reset hesla" v adminu pošle uživateli e-mail s odkazem (heslo při tvorbě je nepovinné).
- **Zúčtovací období + přetoky** (v0.12.0–0.12.1): per lokalita nastavení období (start dle ČEZ, délka, limit přetoků); na dashboardu tabulka po měsících (výroba/spotřeba/přetoky/odběr) + součet za období + pruh přetoky vs. limit; po konci období od nuly. V adminu lze doplnit dodávku/odběr před spuštěním měření (přičte se k období). Znaménko sítě: kladné = dodávka.
- **Posun času šipkami + datum** (v0.11.0–0.11.1): grafy (zařízení i souhrn lokality) se posouvají šipkami ◀ ▶ vždy o jeden aktuálně nastavený úsek (délku okna); nad grafem je čitelný popisek datum/čas rozsahu a tlačítko „teď".
- **Souhrnný graf lokality** (v0.10.0): dashboard seskupený podle lokality, souhrnný víceřadý graf — součet výroby FVE + spotřeba lokality + odběr/dodávka do sítě (řady dle dostupných dat), okno 6 h–30 dní.
- **eWeLink/Sonoff (test)** (v0.9.0): připojení na eWeLink cloud, admin výpis zařízení (online, vypínač, příkon). První integrace chytrých zařízení; ovládání a telemetrie navazují.
- **Lokalita a stav na dashboardu** (v0.8.1): u zařízení se zobrazuje lokalita a tečka zelená (aktivní) / červená (neaktivní, žádná čerstvá data); neaktivní zařízení už nevisí na „Načítám".
- **Čtvrthodinová křivka + okno** (v0.8.0): spotová křivka v 15min rozlišení (trh OTE), historie ve `spot_history`, tlačítka +/− pro okno den→30 dní; OTE endpoint čtvrthodinový s fallbackem na hodinový.
- **Grafy s osami a oknem** (v0.7.2): graf výkonu na dashboardu má osy čas/výkon a tlačítka +/− pro zpětné okno 6 h–30 dní (agregace přes time_bucket); spotová křivka má popisky os (hodiny / Kč/MWh).
- **Cenová křivka dnes+zítra** (v0.7.1): vizualizace hodinových spotových cen s vyznačením, kdy by automatika nabíjela/vybíjela; „zpět na živý feed" stáhne cenu okamžitě.
- **Vybíjení do sítě dle ceny** (v0.7): pravidlo „prodávej draze" (ECO_DISCHARGE) vedle „nakupuj levně"; engine agreguje pravidla na zařízení (žádný konflikt), spodní SoC chrání baterii.
- **Lokality a párování** (v0.6.1): správa lokalit, vazba zařízení→lokalita a uživatel↔lokalita (M:N), profil uživatele (telefon, poznámka).
- React SPA frontend (přihlášení, dashboard, řízení, automatizace, lokality, správa modulů a uživatelů, změna hesla).

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
