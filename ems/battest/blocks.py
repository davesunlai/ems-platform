"""Bateriové bloky měniče (B1, B2, …): jmenovitá kapacita a popis každého bloku (= bateriový vstup měniče).
Součet bloků = celková kapacita → zapisuje se do planner_config.capacity_kwh lokality, aby zbytek EMS počítal jako dřív.
Bez zadaných bloků se celková kapacita dělí rovnoměrně podle počtu packů, které hlásí měnič."""
from __future__ import annotations

import logging

from ems.api.db import get_pool

logger = logging.getLogger("ems.battest.blocks")

FIELDS = ("name", "capacity_kwh", "modules_count", "module_model", "module_kwh", "cells_per_module", "installed", "note")


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS battery_blocks (
                id SERIAL PRIMARY KEY,
                module_id TEXT NOT NULL,
                idx INTEGER NOT NULL,                 -- 1 = B1 (battery_*_1), 2 = B2 …
                name TEXT,
                capacity_kwh REAL NOT NULL,
                modules_count INTEGER,                -- počet bateriových modulů v bloku
                module_model TEXT,                    -- např. Pylontech H48050
                module_kwh REAL,                      -- jmenovitá kapacita jednoho modulu
                cells_per_module INTEGER,
                installed TEXT,                       -- rok / datum instalace nebo „cca 3 roky“
                note TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (module_id, idx))""")
        await conn.execute("ALTER TABLE battery_blocks ADD COLUMN IF NOT EXISTS curve JSONB")              # [[soc, kWh využitelných], …] z testu
        await conn.execute("ALTER TABLE battery_blocks ADD COLUMN IF NOT EXISTS curve_test_id INTEGER")
        await conn.execute("ALTER TABLE battery_blocks ADD COLUMN IF NOT EXISTS curve_applied_at TIMESTAMPTZ")
        await conn.execute("ALTER TABLE battery_blocks ADD COLUMN IF NOT EXISTS curve_floor_pct REAL")


async def list_blocks(module_id: str) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM battery_blocks WHERE module_id=$1 ORDER BY idx", module_id)
    out = []
    for r in rows:
        d = dict(r); d["updated_at"] = d["updated_at"].isoformat()
        if isinstance(d.get("curve"), str):
            import json; d["curve"] = json.loads(d["curve"])
        if d.get("curve_applied_at"):
            d["curve_applied_at"] = d["curve_applied_at"].isoformat()
        out.append(d)
    return out


async def save_blocks(module_id: str, blocks: list[dict]) -> list[dict]:
    """Nahradí bloky modulu zadaným seznamem (idx 1..n podle pořadí) a propíše součet do plánovače lokality."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            old = {r["idx"]: dict(r) for r in await conn.fetch("SELECT idx, curve, curve_test_id, curve_applied_at, curve_floor_pct FROM battery_blocks WHERE module_id=$1", module_id)}
            await conn.execute("DELETE FROM battery_blocks WHERE module_id=$1", module_id)
            for i, b in enumerate(blocks, start=1):
                cap = float(b.get("capacity_kwh") or 0)
                if cap <= 0 and b.get("modules_count") and b.get("module_kwh"):
                    cap = float(b["modules_count"]) * float(b["module_kwh"])
                await conn.execute(
                    "INSERT INTO battery_blocks (module_id, idx, name, capacity_kwh, modules_count, module_model, module_kwh, cells_per_module, installed, note) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                    module_id, i, (b.get("name") or f"B{i}").strip(), cap,
                    int(b["modules_count"]) if b.get("modules_count") not in (None, "") else None,
                    (b.get("module_model") or None), float(b["module_kwh"]) if b.get("module_kwh") not in (None, "") else None,
                    int(b["cells_per_module"]) if b.get("cells_per_module") not in (None, "") else None,
                    (b.get("installed") or None), (b.get("note") or None))
                if i in old and old[i].get("curve") is not None:      # křivka z testu přežije editaci popisu bloku
                    await conn.execute("UPDATE battery_blocks SET curve=$3, curve_test_id=$4, curve_applied_at=$5, curve_floor_pct=$6 WHERE module_id=$1 AND idx=$2",
                                       module_id, i, old[i]["curve"], old[i]["curve_test_id"], old[i]["curve_applied_at"], old[i]["curve_floor_pct"])
        loc = await conn.fetchval("SELECT locality_id FROM modules WHERE id=$1", module_id)
    out = await list_blocks(module_id)
    total = sum(float(b["capacity_kwh"]) for b in out)
    if loc and total > 0:
        try:
            from ems.planner import db as planner_db
            await planner_db.upsert_config(int(loc), {"capacity_kwh": round(total, 2)})
        except Exception as exc:
            logger.warning("bloky → plánovač capacity_kwh: %s", exc)
    return out


async def blocks_for_test(module_id: str, total_kwh: float, packs: int) -> list[dict]:
    """Bloky pro parametry testu: zadané, nebo rovnoměrně rozdělená celková kapacita podle počtu packů měniče."""
    bl = await list_blocks(module_id)
    if bl:
        return [{"idx": b["idx"], "name": b["name"], "capacity_kwh": float(b["capacity_kwh"]), "modules_count": b.get("modules_count"),
                 "module_model": b.get("module_model"), "installed": b.get("installed"), "note": b.get("note")} for b in bl]
    n = max(1, int(packs or 1))
    return [{"idx": i, "name": f"B{i}", "capacity_kwh": round(total_kwh / n, 3), "derived": True} for i in range(1, n + 1)]


# ---------- křivka SoC → využitelné kWh z testu ----------
def curve_from_rows(rows: list[dict], k: int, floor_pct: float) -> list[list[float]] | None:
    """Z vybíjecí fáze testu: pro každé celé % SoC bloku (BMS) kolik kWh z bloku ještě vyteklo, než ho BMS zastavil.
    rows = minutové řádky vybíjecího okna (battery_soc_k, battery_power_k). Vrací [[soc, kwh], …] vzestupně podle soc."""
    kp, ks = f"battery_power_{k}", f"battery_soc_{k}"
    pts = [r for r in rows if r.get(ks) is not None]
    if len(pts) < 10:
        return None
    # kumulativní vybitá energie a konec = okamžik, kdy blok přestal dávat výkon (po aktivitě), jinak konec okna
    cum = []; e = 0.0; active = False; stop = len(pts)
    for i, r in enumerate(pts):
        p = -(r.get(kp) or 0)
        if p > 500:
            active = True
        elif active and p < 150:
            stop = i; break
        e += max(0.0, p) / 60.0 / 1000.0
        cum.append(e)
    pts = pts[:stop]; cum = cum[:stop]
    if len(pts) < 10 or not cum or cum[-1] <= 0:
        return None
    total = cum[-1]
    first_at = {}                                   # první minuta, kdy SoC klesl na ≤ q
    prev = int(pts[0][ks]) + 1
    for i, r in enumerate(pts):
        s = int(r[ks])
        for q in range(s, prev):                    # úrovně právě překročené směrem dolů
            first_at.setdefault(q, i)
        prev = min(prev, s)
    soc_max = int(pts[0][ks]); soc_end = int(round(pts[-1][ks]))
    out = []
    for s in range(0, 101):
        if s <= soc_end:
            kwh = 0.0
        elif s in first_at:
            kwh = total - cum[first_at[s]]
        elif s > soc_max:
            # nad začátkem vybíjení: lineární extrapolace sklonem horních 10 %
            lo = max(soc_end + 1, soc_max - 10)
            slope = (total - cum[first_at[soc_max]] - (total - cum[first_at[lo]])) / max(1, soc_max - lo) if lo in first_at else 0
            kwh = (total - cum[first_at[soc_max]]) + slope * (s - soc_max)
        else:
            continue
        out.append([s, round(max(0.0, kwh), 3)])
    return out


def kwh_at(curve: list[list[float]], soc: float) -> float | None:
    if not curve or soc is None:
        return None
    lo = None; hi = None
    for s, kwh in curve:
        if s <= soc:
            lo = (s, kwh)
        if s >= soc and hi is None:
            hi = (s, kwh)
    if lo is None:
        return float(curve[0][1])
    if hi is None or hi[0] == lo[0]:
        return float(lo[1])
    f = (soc - lo[0]) / (hi[0] - lo[0])
    return float(lo[1] + f * (hi[1] - lo[1]))


async def apply_test(test: dict, phase_marks: list[dict]) -> list[dict]:
    """Uloží křivky z dokončeného testu do bloků modulu (bloky založí z parametrů testu, pokud nejsou)."""
    from datetime import datetime, timezone
    from .assess import series_cells
    module_id = test["module_id"]; p = test["params"]
    t0 = datetime.fromisoformat(test["started_at"]); t1 = datetime.fromisoformat(test["ended_at"]) if test.get("ended_at") else datetime.now(timezone.utc)
    w = None
    for i, m in enumerate(phase_marks):
        if m["phase"] == "discharge":
            w = (datetime.fromisoformat(m["ts"]), datetime.fromisoformat(phase_marks[i + 1]["ts"]) if i + 1 < len(phase_marks) else t1)
    if not w:
        raise ValueError("Test nemá vybíjecí krok — křivku nelze odvodit.")
    bl = await list_blocks(module_id)
    if not bl:
        packs = [int(b["idx"]) for b in (p.get("blocks") or [])] or [1, 2]
        await save_blocks(module_id, [{"name": b.get("name") or f"B{b['idx']}", "capacity_kwh": b.get("capacity_kwh")} for b in (p.get("blocks") or [{"idx": k, "capacity_kwh": float(p.get("capacity_kwh") or 0) / len(packs)} for k in packs])])
        bl = await list_blocks(module_id)
    rows = await series_cells(module_id, w[0], w[1], [int(b["idx"]) for b in bl])
    floor = float(p.get("floor_pct") or 10)
    pool = await get_pool()
    import json
    done = 0
    async with pool.acquire() as conn:
        for b in bl:
            curve = curve_from_rows(rows, int(b["idx"]), floor)
            if not curve:
                continue
            await conn.execute("UPDATE battery_blocks SET curve=$3::jsonb, curve_test_id=$4, curve_applied_at=now(), curve_floor_pct=$5 WHERE module_id=$1 AND idx=$2",
                               module_id, int(b["idx"]), json.dumps(curve), int(test["id"]), floor)
            done += 1
    if not done:
        raise ValueError("Ve vybíjecím kroku nejsou data po blocích (battery_soc_1/2, battery_power_1/2).")
    return await list_blocks(module_id)


async def clear_curves(module_id: str) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE battery_blocks SET curve=NULL, curve_test_id=NULL, curve_applied_at=NULL, curve_floor_pct=NULL WHERE module_id=$1", module_id)
    return await list_blocks(module_id)


async def energy_now(module_id: str) -> dict | None:
    """Aktuální využitelná energie po blocích podle aplikované křivky (None, když křivka není)."""
    from . import db as bt_db
    bl = [b for b in await list_blocks(module_id) if b.get("curve")]
    if not bl:
        return None
    m = await bt_db.latest_metrics(module_id, [f"battery_soc_{b['idx']}" for b in bl] + ["battery_soc"], 900)
    out = {"module_id": module_id, "test_id": bl[0].get("curve_test_id"), "applied_at": bl[0].get("curve_applied_at"), "floor_pct": bl[0].get("curve_floor_pct"), "blocks": []}
    tot_u = 0.0; tot_n = 0.0; tot_cap = 0.0; tot_full = 0.0
    for b in bl:
        soc = m.get(f"battery_soc_{b['idx']}")
        usable = kwh_at(b["curve"], soc) if soc is not None else None
        full = kwh_at(b["curve"], 100.0)
        nominal = float(b["capacity_kwh"]) if b.get("capacity_kwh") else None
        lin = nominal * max(0.0, (soc - float(b.get("curve_floor_pct") or 0))) / 100.0 if (nominal and soc is not None) else None
        out["blocks"].append({"idx": b["idx"], "name": b["name"], "soc": soc, "kwh_usable": round(usable, 2) if usable is not None else None,
                              "kwh_full": round(full, 2) if full is not None else None, "kwh_nominal_linear": round(lin, 2) if lin is not None else None, "nominal_kwh": nominal})
        if usable is not None:
            tot_u += usable
        if lin is not None:
            tot_n += lin
        if nominal:
            tot_cap += nominal
        if full is not None:
            tot_full += full
    out["total_usable_kwh"] = round(tot_u, 2); out["total_nominal_linear_kwh"] = round(tot_n, 2)
    out["total_full_kwh"] = round(tot_full, 2); out["total_nominal_kwh"] = round(tot_cap, 2); out["soc"] = m.get("battery_soc")
    return out
