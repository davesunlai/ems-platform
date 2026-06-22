# INFRASTRUKTURA FRANTA — ZÁVAZNÁ PRAVIDLA
_stav 11.6.2026_

1. **Porty 80/443 vlastní výhradně Caddy** (`infra-caddy-1`, `/opt/ems/infra`).

2. **Jediná sdílená síť je `edge`** (vytvořena ručně, mimo compose).
   Každý projekt ji referencuje:
   ```yaml
   networks:
     edge:
       external: true
   ```
   Sítě `caddy_net` a `tipomat_net` byly zrušeny. **Žádná ruční
   `docker network connect`** připojení — vše deklarovat v compose.

3. **Na `edge` patří POUZE aplikační kontejner projektu.**
   DB, redis, workery zůstávají na interní síti projektu.

4. **Routing domén JEN v `/opt/ems/infra/Caddyfile`**, jeden blok na doménu.
   Caddy cílí výhradně **PLNÝMI jmény kontejnerů** (nikdy jmény služeb
   typu `web` — aliasy služeb na `edge` kolidují, viz incident 11.6.).

5. **POZOR — Caddyfile je mountovaný jako jednotlivý soubor:**
   - Připsání (`cat >>`) je bezpečné, stačí `caddy reload`.
   - Přepis přes `sed -i` / `vim` mění inode → kontejner vidí starou
     verzi! Po takové editaci nutný `docker restart infra-caddy-1`.
   - Validace před reloadem:
     `docker exec infra-caddy-1 caddy validate --config /etc/caddy/Caddyfile`

6. **Obsazené host porty:** 8000 (infra-api), 8080 (infra-web),
   5433 (timescaledb), 5434 (plakatovaciplocha_db), 6333-4 (qdrant),
   10200/10300 (piper/whisper). Nové porty jen s prefixem `127.0.0.1:`.

7. **Po `tar -xzf`, který přepíše Caddyfile, NEpomáhá `caddy reload`.**
   `tar` soubor smaže a vytvoří znovu (**nový inode**), takže běžící
   kontejner přes bind-mount vidí pořád **starou** verzi. Po každém
   rozbalení taru je nutný **RESTART Caddy**, ne reload:
   ```bash
   docker compose -f infra/docker-compose.yml restart caddy
   # nebo: docker restart infra-caddy-1
   ```
   `bash scripts/deploy.sh` tento restart dělá automaticky — proto po
   rozbalení taru **nasazuj přes `deploy.sh`** a neřeš ruční reload.
   Reload (`caddy reload`) stačí jen po ručním `cat >>` / `cat >`, které
   inode zachovají.

## AKTUÁLNÍ ROUTING
_(vše přes `edge`, kromě teraems přes `infra_default`)_

| Doména                 | Cíl                       |
|------------------------|---------------------------|
| teraems.com            | infra-web-1:80            |
| tipomat.net            | tipomat_app:8000          |
| narozeniny.eu          | narozeniny-eu:4321        |
| plakatovaciplocha.cz   | plakatovaciplocha_app:80  |

## Externí projekty v Caddy (mimo EMS repo) — fragmenty
Hlavní `infra/Caddyfile` (teraems/tipomat/narozeniny/plakatovaci) je v repu a deploy ho
přepisuje. Projekty MIMO repo (např. `playcup.online`) proto NESMÍ být přímo v něm —
zmizely by po updatu. Místo toho jdou do `/opt/ems/infra/sites/*.caddy`:
- hlavní Caddyfile je `import /etc/caddy/sites/*.caddy` auto-natáhne,
- compose mountuje `./sites:/etc/caddy/sites:ro`,
- deploy/tar tyto fragmenty NIKDY nepřepisuje (jsou vyloučené z balíčku).
Po přidání/změně fragmentu: `docker restart infra-caddy-1`.
