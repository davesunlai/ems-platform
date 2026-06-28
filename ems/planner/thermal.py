"""Tepelný a sezónní model plánovače (čisté funkce, bez DB).

POZOR — seed hodnoty, ne fakta (brief §10): COP model, hodnota_tepla_leto,
prahy sezóny, příkon a hystereze TČ jsou ZATÍM odhady. Naimplementováno jako
konfig knoby per lokalita; kalibrace ze zimních dat přijde později. Funkce jsou
záměrně jednoduché a vysvětlitelné, ne „přesné".
"""
from __future__ import annotations


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# --- COP tepelného čerpadla vzduch/voda (brief §6) -------------------------
def cop(t_out: float | None, *, a: float = 2.75, b: float = 0.11,
        lo: float = 1.8, hi: float = 4.0) -> float:
    """COP ≈ clamp(a + b·T_venk, lo, hi) pro výstup ~55 °C. Seed model.
    V zimě (nízká T_venk) nižší COP → vyšší el. odběr právě když je FVE málo."""
    if t_out is None:
        t_out = 0.0
    return _clamp(a + b * float(t_out), lo, hi)


# --- Příkon TČ jako modelovaná (NEřízená) zátěž (brief §6) ------------------
def hp_power_kw(t_out: float | None, *, p_max_kw: float = 3.5,
                t_balance: float = 15.0, t_design: float = -15.0,
                t_off: float = 18.0) -> float:
    """Odhad ELEKTRICKÉHO příkonu TČ podle venkovní teploty (seed).

    Lineární náběh poptávky po teple: nad `t_off` netopí (0), pod `t_design`
    plný příkon `p_max_kw`, mezi tím lineárně. Toto je hrubý odhad pro
    `night_reserve` (kdo kryje TČ) — kalibrace z reálné spotřeby TČ přijde
    ze zimních dat. NEvyžaduje COP (p_max_kw už je elektrický příkon).
    """
    if t_out is None:
        return 0.0
    t = float(t_out)
    if t >= t_off:
        return 0.0
    frac = (t_balance - t) / (t_balance - t_design)   # 0 u t_balance, 1 u t_design
    return _clamp(frac, 0.0, 1.0) * p_max_kw


def hp_load_profile(t_out_series, *, tuv_kwh_den: float = 4.0, p_max_kw: float = 3.5,
                    t_balance: float = 15.0, t_design: float = -15.0, t_off: float = 18.0) -> list[float]:
    """Hodinový ELEKTRICKÝ příkon TČ (kW) = TUV (celoroční baseline) + vytápění (sezónní).

    TUV: ohřev teplé vody jede celoročně nezávisle na venkovní teplotě — rozprostřeno
    jako plochý baseline (tuv_kwh_den/24). Vytápění: hp_power_kw(T_venk), v létě ~0.
    Seed model — TUV složku kalibrovat z propadů I2 (master střed) při odběru TUV.
    """
    tuv_kw = max(0.0, float(tuv_kwh_den)) / 24.0
    out = []
    for t in (t_out_series or []):
        heat = hp_power_kw(t, p_max_kw=p_max_kw, t_balance=t_balance, t_design=t_design, t_off=t_off)
        out.append(tuv_kw + heat)
    return out


# --- Hodnota tepla pro spirálu (brief §4, §7) ------------------------------
def heat_value_czk_kwh(season: str, *, hodnota_tepla_leto: float = 2.0) -> float:
    """„Nízký spot" pro spirálu = cena nejlevnější alternativy získat teplo jinak.
    Léto (krb neběží): reohřev ze sítě → kladná hodnota (konfig). Zima (topí krbem):
    alternativa ≈ dřevo zdarma → ≈ 0 → spirála jen v záporném spotu."""
    return 0.0 if season == "winter" else max(0.0, float(hodnota_tepla_leto))


# --- Sezónní auto-přepínání s hysterezí (brief §8) -------------------------
def detect_season(pv_7d_avg_kwh: float | None, *, prah_zima: float, prah_leto: float,
                  current: str = "summer") -> str:
    """Sezóna z rolling 7denního průměru denní výroby FVE (kWh/den), s hysterezí.

    signál < prah_zima → WINTER; signál > prah_leto → SUMMER; mezi prahy drží
    stávající (prah_leto > prah_zima, ať to neflapuje). Bez dat → ponech current.
    """
    if pv_7d_avg_kwh is None:
        return current if current in ("summer", "winter") else "summer"
    s = float(pv_7d_avg_kwh)
    if s < prah_zima:
        return "winter"
    if s > prah_leto:
        return "summer"
    return current if current in ("summer", "winter") else "summer"


def resolve_season(mode: str, pv_7d_avg_kwh: float | None, *, prah_zima: float,
                   prah_leto: float, current: str = "summer") -> str:
    """mode = 'auto' | 'summer' | 'winter'. Ruční přepíná auto-detekci."""
    m = (mode or "auto").lower()
    if m in ("summer", "winter"):
        return m
    return detect_season(pv_7d_avg_kwh, prah_zima=prah_zima, prah_leto=prah_leto, current=current)
