"""Edge detektor běhů TČ + denní agregace.

Běhy: hrana compressor_on False→True otevírá běh, True→False zavírá.
Energie běhu se AKUMULUJE po vzorcích (Σ max(0, Δ el_today)) — robustní vůči
půlnočnímu resetu *_today čítačů (ISG totals jsou na tomto kusu mrtvé).
Průběžný stav běhu se ukládá do hp_runs (acc_* sloupce), takže restart
kolektoru uprostřed běhu o energii nepřijde — otevřený běh se adoptuje.
Osiřelý otevřený běh (TČ mezitím doběhlo) se uzavře posledním známým ts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ems.api.db import get_pool

logger = logging.getLogger(__name__)

_mem: dict[str, dict] = {}   # module_id -> {run_id, prev el/heat čítače}


def _cnt(d: dict) -> tuple[float, float]:
    el = (d.get("el_heating_today_kwh") or 0) + (d.get("el_dhw_today_kwh") or 0)
    heat = (d.get("heat_heating_today_kwh") or 0) + (d.get("heat_dhw_today_kwh") or 0)
    return float(el), float(heat)


async def on_snapshot(module_id: str, d: dict) -> None:
    pool = await get_pool()
    comp = bool(d.get("compressor_on"))
    el, heat = _cnt(d)
    m = _mem.get(module_id)
    async with pool.acquire() as conn:
        if m is None:
            # start kolektoru: adoptuj případný otevřený běh
            row = await conn.fetchrow(
                "SELECT id, started_at, acc_el_kwh, acc_heat_kwh FROM hp_runs "
                "WHERE module_id=$1 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1", module_id)
            if row and comp:
                m = {"run_id": row["id"], "el": el, "heat": heat}
                logger.info("TČ %s: adoptuji otevřený běh #%s", module_id, row["id"])
            else:
                if row:   # osiřelý běh — TČ už neběží, uzavři posledním známým časem
                    last = await conn.fetchval(
                        "SELECT max(ts) FROM hp_telemetry WHERE module_id=$1", module_id)
                    await conn.execute(
                        "UPDATE hp_runs SET ended_at=$2, el_kwh=acc_el_kwh, heat_kwh=acc_heat_kwh WHERE id=$1",
                        row["id"], last or row["started_at"])
                    logger.info("TČ %s: uzavírám osiřelý běh #%s", module_id, row["id"])
                m = {"run_id": None, "el": el, "heat": heat}
            _mem[module_id] = m

        run_id = m.get("run_id")
        if comp and run_id is None:
            # náběh
            rid = await conn.fetchval(
                "INSERT INTO hp_runs (module_id, mode, started_at, t_outdoor_start, acc_el_kwh, acc_heat_kwh) "
                "VALUES ($1, $2, now(), $3, 0, 0) RETURNING id",
                module_id, d.get("hp_mode") or "heating", d.get("t_outdoor"))
            m.update(run_id=rid, el=el, heat=heat)
        elif comp and run_id is not None:
            # běží — akumuluj přírůstky (Δ<0 = půlnoční reset → 0)
            de, dh = max(0.0, el - m["el"]), max(0.0, heat - m["heat"])
            if de or dh:
                await conn.execute(
                    "UPDATE hp_runs SET acc_el_kwh = acc_el_kwh + $2, acc_heat_kwh = acc_heat_kwh + $3 WHERE id=$1",
                    run_id, de, dh)
            m.update(el=el, heat=heat)
        elif not comp and run_id is not None:
            # doběh
            de, dh = max(0.0, el - m["el"]), max(0.0, heat - m["heat"])
            await conn.execute(
                "UPDATE hp_runs SET ended_at=now(), acc_el_kwh=acc_el_kwh+$2, acc_heat_kwh=acc_heat_kwh+$3, "
                "el_kwh=acc_el_kwh+$2, heat_kwh=acc_heat_kwh+$3 WHERE id=$1", run_id, de, dh)
            m.update(run_id=None, el=el, heat=heat)
        else:
            m.update(el=el, heat=heat)
