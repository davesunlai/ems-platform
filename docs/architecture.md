# Architektura

## Princip
Jádro drží **kanonický model**; každý typ zdroje se připojuje přes **adaptér**,
který překládá nativní protokol do modelu. Přidání nového zdroje = nový modul,
beze změny jádra.

## Datový tok
```
[zařízení] → adaptér → Reading (kanonický) → Sample → sink → TimescaleDB → API → web/mobil
```

## Tři kanály (cíl)
1. **Telemetrie ↑** — sběr měřených dat (tato fáze).
2. **Povely ↓** — autorizované, potvrzované (command → ack → confirm); příští fáze.
3. **Lokální autonomie** — fail-safe a rychlé služby (FCR ~30 s) běží na edge,
   funguje i bez spojení s centrem.

## Tři rodiny rozhraní
- **Přímý protokol (vlastní HW/PLC)** — nízká latence, plné řízení, fail-safe na edge.
  Goodwe ET/DT spadá sem (UDP 8899 / Modbus TCP 502).
- **Cloud API (třetí strana)** — monitoring a pomalé povely, ne pro kritické řízení.
- **Trh / TSO** — spot, podpůrné služby; fyzická realizace přes edge.

## Pilot → škálování
Pilot běží centrálně přes VPN (read-only, jeden server). Cílově:
- edge sběr na Raspberry u domácnosti (store-and-forward při výpadku spojení),
- message bus mezi adaptéry a úložištěm (MQTT/NATS) místo přímého zápisu,
- HA: stateless služby, replikovaná DB, distribuce na více Linux serverů.

Sink jako abstrakce je záměrně připravený tak, aby přímý zápis do DB šel
nahradit publikací na bus bez zásahu do adaptérů.

## Volby technologií (pilot)
- Python 3.11+ / asyncio — adaptéry, kolektor, API; knihovna `goodwe` je v Pythonu.
- TimescaleDB (PostgreSQL) — časové řady i konfigurace, HA-schopné.
- FastAPI — REST API.
- Docker Compose — lokální orchestrace pilotu (cílově Kubernetes).

Sémantiku veličin lze později formalizovat dle IEC CIM (61970/61968).
