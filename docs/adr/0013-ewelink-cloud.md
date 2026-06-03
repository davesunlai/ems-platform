# ADR 0013: eWeLink/Sonoff cloud — test připojení (v0.9.0)

## Kontext
První z integrací chytrých zařízení (postupně i nabíječky, Zigbee, …).
Zvoleno eWeLink/Sonoff cloud napřímo, zatím jako test.

## Rozhodnutí
- Klient eWeLink Cloud API v2: App ID/Secret (dev.ewelink.cc) + login účtem
  (e-mail/heslo) s HMAC-SHA256 podpisem, region-specific endpoint, token cache.
- Konfigurace přes env (EMS_EWELINK_*), tajemství v .env (ne v gitu).
- v0.9.0 = jen test: admin endpoint /api/ewelink/devices + stránka „eWeLink"
  vypíše zařízení (online, stav vypínače, příkon/napětí/proud).
- Telemetrie do kanonického modelu (dashboard) a ovládání on/off + napojení na
  automatizaci (řízení spotřebičů dle ceny/přebytku) = navazující kroky.

## Důsledky
- Cloud API nešlo otestovat z build prostředí — ověřuje se proti reálnému účtu.
- Vzor připraven pro další rodiny adaptérů (HA, OCPP, MQTT/Zigbee).
