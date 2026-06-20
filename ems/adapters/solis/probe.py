"""Živá diagnostika Solis registrů přes Modbus TCP.

Spuštění na frantě (uvnitř kontejneru kolektoru, kde je pymodbus):

    docker compose -f infra/docker-compose.yml exec collector \\
        python -m ems.adapters.solis.probe 192.168.6.180

Přečte kandidátní registry jeden po druhém a vypíše hodnotu nebo chybu,
ať zjistíme, které adresy na konkrétním střídači opravdu odpovídají
(systém FVE/síť/energie + oba battery packy). Pošli mi výstup a podle
něj opravím mapování.
"""
from __future__ import annotations

import sys

from .adapter import SolisAdapter

# (popis, adresa, typ, měřítko) ; adresa None = oddělovač sekce
CANDIDATES = [
    ("--- systém: FVE / AC / energie ---", None, None, None),
    ("PV výkon DC (briefu)  ", 33057, "u32", 1.0),
    ("AC činný výkon (alt)  ", 33049, "u32", 1.0),
    ("AC činný výkon (alt2) ", 33079, "u32", 1.0),
    ("Energie celkem (brief)", 33029, "u32", 1.0),
    ("Energie dnes x0.1     ", 33035, "u16", 0.1),
    ("--- 3f síťová napětí ---", None, None, None),
    ("Síť napětí L1 x0.1    ", 33073, "u16", 0.1),
    ("Síť napětí L2 x0.1    ", 33074, "u16", 0.1),
    ("Síť napětí L3 x0.1    ", 33075, "u16", 0.1),
    ("--- teplota měniče ---", None, None, None),
    ("Teplota měniče 33093  ", 33093, "s16", 0.1),
    ("Teplota měniče (alt)  ", 33094, "s16", 0.1),
    ("--- teploty baterií ---", None, None, None),
    ("Teplota pack1 x0.1    ", 33144, "u16", 0.1),
    ("Teplota pack2 x0.1    ", 34281, "u16", 0.1),
    ("Teplota pack2 (alt)   ", 34282, "u16", 0.1),
    ("--- síť / elektroměr ---", None, None, None),
    ("Síť meter (brief)     ", 33130, "s32", 1.0),
    ("Síť meter (alt)       ", 33126, "s32", 1.0),
    ("Síť meter (alt2)      ", 33263, "s32", 1.0),
    ("--- denní energie sítě (33169-33180, brief, ověřit) ---", None, None, None),
    ("33169 (U16 x0.1?)     ", 33169, "u16", 0.1),
    ("33170 (U16 x0.1?)     ", 33170, "u16", 0.1),
    ("33171 (U16 x0.1?)     ", 33171, "u16", 0.1),
    ("33172 (U16 x0.1?)     ", 33172, "u16", 0.1),
    ("33173 (U16 x0.1?)     ", 33173, "u16", 0.1),
    ("33174 (U16 x0.1?)     ", 33174, "u16", 0.1),
    ("33175 (U16 x0.1?)     ", 33175, "u16", 0.1),
    ("33176 (U16 x0.1?)     ", 33176, "u16", 0.1),
    ("33179 (U16 x0.1?)     ", 33179, "u16", 0.1),
    ("33180 (U16 x0.1?)     ", 33180, "u16", 0.1),
    ("--- baterie pack 1 ---", None, None, None),
    ("SOC pack1 (brief)     ", 33139, "u16", 1.0),
    ("SOH pack1             ", 33140, "u16", 1.0),
    ("Napětí pack1 x0.1     ", 33133, "u16", 0.1),
    ("Proud pack1 x0.1      ", 33134, "s16", 0.1),
    ("Výkon baterie (alt)   ", 33135, "s16", 1.0),
    ("Výkon baterie (alt2)  ", 33149, "u16", 1.0),
    ("--- baterie pack 2 (brief – nesedí?) ---", None, None, None),
    ("SOC pack2 (brief)     ", 34278, "u16", 1.0),
    ("SOH pack2             ", 34279, "u16", 1.0),
    ("Napětí pack2 inv x0.1 ", 34289, "u16", 0.1),
    ("Proud pack2 x0.1      ", 34290, "s16", 0.1),
    ("Napětí pack2 bms x0.01", 34275, "u16", 0.01),
    ("--- baterie pack 2 (kandidáti +/− blok) ---", None, None, None),
    ("SOC pack2 (alt 33169) ", 33169, "u16", 1.0),
    ("SOC pack2 (alt 33159) ", 33159, "u16", 1.0),
]


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.6.180"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 502
    unit = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    a = SolisAdapter(device_id="probe", host=host, port=port, unit=unit)
    a._connect_sync()
    print(f"Připojeno k {host}:{port} unit={unit}\n")
    for desc, addr, rtype, scale in CANDIDATES:
        if addr is None:
            print(f"\n{desc}")
            continue
        try:
            v = a._read_reg((addr, rtype, scale), _retry=True)
            print(f"  {addr}  {desc} = {v}")
        except Exception as exc:
            print(f"  {addr}  {desc} = CHYBA: {exc}")
    try:
        a._client.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
