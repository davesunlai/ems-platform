"""Write-probe řídicích (holding) registrů Solis — BEZPEČNÉ ověření před řízením.

Pustit při ZASTAVENÉM kolektoru (měnič povolí jen jedno Modbus spojení).

Výchozí běh = jen ČTE aktuální hodnoty řídicích registrů (FC03), nic nezapisuje:
    python -m ems.adapters.solis.wprobe 192.168.6.180

Zápis JEDNOHO registru (FC06) + zpětné čtení — jen s explicitním --write a po
potvrzení (testovat na malém výkonu, brief §11 varuje na flash-opotřebení):
    python -m ems.adapters.solis.wprobe 192.168.6.180 --write 43135 0
"""
import sys

from .mapping import CONTROL_REGISTERS


def _connect(host, port=502, unit=1):
    from pymodbus.client import ModbusTcpClient
    c = ModbusTcpClient(host, port=port, timeout=5.0)
    if not c.connect():
        raise SystemExit(f"Nelze se připojit k {host}:{port}")
    print(f"Připojeno k {host}:{port} unit={unit}\n")
    return c


def read_controls(c, unit=1):
    print("--- Aktuální stav řídicích registrů (holding, FC03) ---")
    for label, addr in CONTROL_REGISTERS:
        try:
            rr = c.read_holding_registers(addr, count=1, device_id=unit)
            if rr.isError() or not getattr(rr, "registers", None):
                print(f"  {addr}  {label} = CHYBA ({rr})")
            else:
                v = rr.registers[0]
                print(f"  {addr}  {label} = {v}  (0x{v:04X})")
        except Exception as exc:
            print(f"  {addr}  {label} = výjimka: {exc}")


def write_one(c, addr, value, unit=1):
    print(f"\n--- ZÁPIS registru {addr} = {value} (0x{value:04X}) ---")
    try:
        before = c.read_holding_registers(addr, count=1, device_id=unit)
        b = before.registers[0] if not before.isError() and before.registers else None
        print(f"  před:    {b}")
    except Exception as exc:
        print(f"  před: výjimka {exc}")
    try:
        rr = c.write_register(addr, int(value), device_id=unit)
        if rr.isError():
            print(f"  ZÁPIS SELHAL: {rr}")
            return
        print("  zápis OK")
    except Exception as exc:
        print(f"  ZÁPIS výjimka: {exc}")
        return
    try:
        after = c.read_holding_registers(addr, count=1, device_id=unit)
        a = after.registers[0] if not after.isError() and after.registers else None
        print(f"  po:      {a}  {'✅ sedí' if a == int(value) else '⚠️ liší se (registr možná hodnotu transformuje/ořezává)'}")
    except Exception as exc:
        print(f"  po: výjimka {exc}")


def main(argv):
    if not argv:
        print(__doc__)
        raise SystemExit(2)
    host = argv[0]
    c = _connect(host)
    try:
        read_controls(c)
        if "--write" in argv:
            i = argv.index("--write")
            addr, value = int(argv[i + 1]), int(argv[i + 2])
            print("\n⚠️  Chystáš se ZAPSAT do měniče. Měl by běžet na malém/bezpečném"
                  " výkonu a kolektor být zastavený.")
            ans = input(f"   Opravdu zapsat {addr} = {value}? [napiš 'ano']: ").strip().lower()
            if ans == "ano":
                write_one(c, addr, value)
                print("\n--- Stav po zápisu ---")
                read_controls(c)
            else:
                print("   Zrušeno, nic nezapsáno.")
    finally:
        c.close()


if __name__ == "__main__":
    main(sys.argv[1:])
