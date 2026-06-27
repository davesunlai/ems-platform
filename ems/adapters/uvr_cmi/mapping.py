"""Mapa čidel UVR16x2 přes CMI a sentinel filtr. Ověřeno živě na pilotu (UVR-CMI-BRIEF)."""
from ems.core.model import Metric

# Vstup (Number na node 2) -> (metrika, role). I13 v odpovědi chybí → klíčujeme dle Number.
# I3/I2/I1 = MASTER horní/střed/dolní, I4/I5 = SLAVE horní/dolní, I14 = technická místnost (ambient).
DEFAULT_SENSORS: dict[int, tuple] = {
    3:  (Metric.TANK_M_TOP, "tank"),
    2:  (Metric.TANK_M_MID, "tank"),
    1:  (Metric.TANK_M_BOT, "tank"),
    4:  (Metric.TANK_S_TOP, "tank"),
    5:  (Metric.TANK_S_BOT, "tank"),
    14: (Metric.TEMP_AMBIENT, "ambient"),
}

# Mapování názvů metrik (pro volitelnou konfiguraci per lokalita: {"3": "tank_m_top", ...})
_METRIC_BY_NAME = {m.value: m for m in Metric}


def is_bad(unit, val) -> bool:
    """Sentinel: odpojený PT1000 = 9999.9, chyba ozáření = 16383. Nesmí do modelu."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return True
    u = str(unit)
    if u in ("1", "46"):              # teplota °C
        return not (-50.0 <= v <= 200.0)
    if u == "2":                      # ozáření W/m²
        return v >= 16000.0
    return False


def resolve_sensors(sensors) -> dict[int, tuple]:
    """Z konfigurace ({"3":"tank_m_top",...}) udělá {3: (Metric, "tank")}. None → default."""
    if not sensors:
        return DEFAULT_SENSORS
    out = {}
    for k, v in sensors.items():
        try:
            num = int(k)
        except (TypeError, ValueError):
            continue
        name = v if isinstance(v, str) else (v.get("metric") if isinstance(v, dict) else None)
        metric = _METRIC_BY_NAME.get(name)
        if metric is None:
            continue
        role = "ambient" if metric is Metric.TEMP_AMBIENT else "tank"
        out[num] = (metric, role)
    return out or DEFAULT_SENSORS
