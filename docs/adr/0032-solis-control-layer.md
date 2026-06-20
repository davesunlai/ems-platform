# ADR 0032 — Solis řídicí (zápisová) vrstva — fáze C, verification-first

## Kontext
Spouštíme ovládání měniče Solis (zápis do holding registrů, FC06). Brief §11
varuje: řídicí registry jsou z 1f/S5 dokumentace, u 3f 50kW modelu se liší dle
FW, scale/sémantika nepotvrzená, část zápisů jde do flash (opotřebení).

## Rozhodnutí
1. Zápis vždy přes `write_holding(addr, value, verify=True)` — ověření zpětným
   čtením (FC03). High-level `set_force(0/1/2, power)` a `set_work_mode(word)`.
2. **Verification-first**: před zapojením do API/UI/automatiky se každý řídicí
   registr ověří `wprobe` nástrojem na reálném kuse (čte aktuální stav; zápis
   jen explicitně `--write` + potvrzení, na malém výkonu).
3. Řídicí registry: 43110 (režim), 43135/43136 (force 0/1/2 + výkon),
   43012/43013 (limity proudu), 43024/43030 (SOC prahy).
4. `control_enabled` (volby v UI) je display/konfig — odfiltrováno z konstruktoru
   adaptéru (jako `hidden_metrics`).

## Důsledky
Bezpečné postupné spuštění. API endpoint + UI ovládací panel až po ověření
registrů probem. Automatizační pravidla (fáze D) až nad ověřeným řízením.
