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

## AKTUÁLNÍ ROUTING
_(vše přes `edge`, kromě teraems přes `infra_default`)_

| Doména                 | Cíl                       |
|------------------------|---------------------------|
| teraems.com            | infra-web-1:80            |
| tipomat.net            | tipomat_app:8000          |
| narozeniny.eu          | narozeniny-eu:4321        |
| plakatovaciplocha.cz   | plakatovaciplocha_app:80  |
