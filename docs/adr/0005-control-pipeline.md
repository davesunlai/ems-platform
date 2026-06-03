# ADR 0005: Povelová rovina (zápis do zařízení)

## Kontext
Fáze C přidává reálný zápis do měničů — nejcitlivější část. Musí být
bezpečná, ověřitelná a auditovatelná.

## Rozhodnutí
- Povely jen přes oprávnění `control` (role operator/admin).
- Vzor command → ack → ověření: po zápisu se přečte stav (`get_operation_mode`)
  a vrátí pro kontrolu.
- Každý povel (úspěch i selhání) se zapisuje do `command_audit`.
- Bounds na parametrech (power_pct 1–100, target_soc 5–100).
- První podporovaný povel: režim baterie ET — vynucené nabíjení (ECO_CHARGE)
  a návrat na normál (GENERAL). Vratné.
- API se k měniči připojuje krátkodobě (connect → set → read-back → close).

## Důsledky
- Řízení je oddělené od telemetrie a od správy modulů.
- Rozšíření o další povely = přidat akci do control vrstvy + endpoint.
- Pozn.: kolektor i control přistupují k měniči přes UDP nezávisle; pro pilot
  akceptovatelné, do budoucna koordinovat přes jeden přístupový bod / edge.
