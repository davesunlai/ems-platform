"""Export testu baterie: DOCX (protokol s grafy a vyhodnocením) a XLSX (data). Knihovny se importují až při použití."""
from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

from .assess import LEVEL_TXT
from .engine import STEP_NAMES

TZ = ZoneInfo("Europe/Prague")
LEVEL_DOT = {"green": "●", "amber": "●", "red": "●"}
LEVEL_RGB = {"green": (0x3f, 0xb9, 0x50), "amber": (0xd2, 0x99, 0x22), "red": (0xf8, 0x51, 0x49)}
LEVEL_HEX = {"green": "3FB950", "amber": "D29922", "red": "F85149"}


def _dt(s: str | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if not s:
        return "—"
    return datetime.fromisoformat(s).astimezone(TZ).strftime(fmt)


def _f(v, nd=2, unit="") -> str:
    if v is None:
        return "—"
    return f"{float(v):.{nd}f}{(' ' + unit) if unit else ''}".replace(".", ",")


def _block_label(b: dict) -> str:
    s = b.get("name") or f"B{b.get('idx')}"
    bits = []
    if b.get("modules_count") and b.get("module_model"):
        bits.append(f"{b['modules_count']}× {b['module_model']}")
    elif b.get("module_model"):
        bits.append(b["module_model"])
    if b.get("capacity_kwh") is not None:
        bits.append(f"{_f(b['capacity_kwh'], 2)} kWh")
    if b.get("installed"):
        bits.append(f"instalace {b['installed']}")
    return s + (f" ({', '.join(bits)})" if bits else "")


# ---------- grafy ----------
def chart_png(t: dict, cell_rows: list[dict] | None = None) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    ser = t.get("series") or []
    xs = [datetime.fromisoformat(p["ts"]).astimezone(TZ) for p in ser]
    fig, axes = plt.subplots(2 if cell_rows else 1, 1, figsize=(11, 7.2 if cell_rows else 4), sharex=True, dpi=130)
    ax = axes[0] if cell_rows else axes
    ax.set_title(f"Test baterie #{t['id']} — výkon a SoC", fontsize=11)
    PH = {"discharge0": ("#f85149", "1 Předvybití"), "charge": ("#3fb950", "2 Nabíjení"), "hold": ("#d29922", "3 Výdrž"), "discharge": ("#f85149", "4 Vybíjení")}
    marks = t.get("phase_marks") or []
    end = datetime.fromisoformat(t["ended_at"]).astimezone(TZ) if t.get("ended_at") else (xs[-1] if xs else None)
    for i, m in enumerate(marks):
        a = datetime.fromisoformat(m["ts"]).astimezone(TZ)
        b = datetime.fromisoformat(marks[i + 1]["ts"]).astimezone(TZ) if i + 1 < len(marks) else end
        c, lbl = PH.get(m["phase"], ("#888", m["phase"]))
        for a_ in (axes if cell_rows else [ax]):
            a_.axvspan(a, b, color=c, alpha=0.08)
        ax.text(a, 1.01, lbl, fontsize=7, color="#555", va="bottom", ha="left", transform=ax.get_xaxis_transform())
    ax.plot(xs, [(p.get("bat_w") or 0) / 1000 for p in ser], color="#2da44e", lw=1.3, label="výkon baterie (kW)")
    if any(p.get("bat1_w") is not None for p in ser):
        ax.plot(xs, [(p.get("bat1_w") or 0) / 1000 for p in ser], color="#8250df", lw=0.9, label="B1 (kW)")
        ax.plot(xs, [(p.get("bat2_w") or 0) / 1000 for p in ser], color="#1b7c83", lw=0.9, label="B2 (kW)")
    ax.axhline(0, color="#999", lw=0.6)
    ax.set_ylabel("kW  (+ nabíjení / − vybíjení)")
    ax2 = ax.twinx()
    ax2.plot(xs, [p.get("soc") for p in ser], color="#0969da", lw=1.0, ls="--", label="SoC (%)")
    if any(p.get("soc1") is not None for p in ser):
        ax2.plot(xs, [p.get("soc1") for p in ser], color="#8250df", lw=0.8, ls=":", label="SoC B1")
        ax2.plot(xs, [p.get("soc2") for p in ser], color="#1b7c83", lw=0.8, ls=":", label="SoC B2")
    ax2.set_ylim(0, 105); ax2.set_ylabel("SoC %")
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=7, loc="lower left", ncol=3)
    ax.grid(alpha=0.25)
    if cell_rows:
        axc = axes[1]
        axc.set_title("Napětí článků min / max po blocích", fontsize=11)
        cx = [r["ts"].astimezone(TZ) for r in cell_rows]
        for k, col in ((1, "#8250df"), (2, "#1b7c83")):
            if any(r.get(f"battery_cell_vmin_{k}") is not None for r in cell_rows):
                axc.plot(cx, [r.get(f"battery_cell_vmin_{k}") for r in cell_rows], color=col, lw=0.9, label=f"B{k} článek min")
                axc.plot(cx, [r.get(f"battery_cell_vmax_{k}") for r in cell_rows], color=col, lw=0.9, ls="--", label=f"B{k} článek max")
        axc.set_ylabel("V"); axc.legend(fontsize=7, loc="lower left", ncol=4); axc.grid(alpha=0.25)
    (axes[-1] if cell_rows else ax).xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=TZ))
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
    return buf.getvalue()


# ---------- DOCX ----------
def build_docx(ctx: dict) -> bytes:
    """ctx: test (s series/steps/snapshots/phase_marks/result), assess, locality, module, blocks, version, user, chart (png bytes)."""
    from docx import Document
    from docx.shared import Pt, Mm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    t, a, loc, mod = ctx["test"], ctx["assess"], ctx.get("locality") or {}, ctx.get("module") or {}
    p = t["params"]; r = t.get("result") or {}
    doc = Document()
    for s in doc.sections:
        s.left_margin = s.right_margin = Mm(18); s.top_margin = s.bottom_margin = Mm(16)
    st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10)

    def table(rows, header=None, widths=None, size=9):
        tb = doc.add_table(rows=0, cols=len(rows[0]) if rows else len(header)); tb.style = "Table Grid"
        if header:
            cells = tb.add_row().cells
            for c, h in zip(cells, header):
                c.text = ""; run = c.paragraphs[0].add_run(str(h)); run.bold = True; run.font.size = Pt(size)
        for row in rows:
            cells = tb.add_row().cells
            for c, v in zip(cells, row):
                c.text = ""; run = c.paragraphs[0].add_run("" if v is None else str(v)); run.font.size = Pt(size)
                if isinstance(v, tuple):   # (text, level) → barevně
                    c.text = ""; run = c.paragraphs[0].add_run(v[0]); run.font.size = Pt(size); run.bold = True
                    run.font.color.rgb = RGBColor(*LEVEL_RGB[v[1]])
        if widths:
            for row in tb.rows:
                for c, w in zip(row.cells, widths):
                    c.width = Mm(w)
        doc.add_paragraph()
        return tb

    h = doc.add_heading(f"Protokol testu kapacity a kondice baterie č. {t['id']}", level=0)
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT
    doc.add_paragraph(f"TERA EMS v{ctx.get('version', '?')} · vygenerováno {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}"
                      + (f" · {ctx['user']}" if ctx.get("user") else "")).runs[0].font.size = Pt(8.5)

    doc.add_heading("Průvodní označení", level=1)
    table([
        ["Lokalita", f"{loc.get('name', '—')}" + (f", {loc['address']}" if loc.get("address") else "")],
        ["Měnič / modul", f"{mod.get('name') or t['module_id']} ({t['module_id']}, adaptér {mod.get('adapter', '—')})"],
        ["Bateriové bloky", "\n".join(_block_label(b) for b in (p.get("blocks") or [])) or f"celkem {_f(p.get('capacity_kwh'))} kWh (bez rozpisu bloků)"],
        ["Jmenovitá kapacita celkem", _f(p.get("capacity_kwh"), 2, "kWh")],
        ["Zahájení / ukončení", f"{_dt(t['started_at'])} → {_dt(t.get('ended_at'))}"],
        ["Stav", STEP_NAMES.get(t["status"], t["status"]) + (f" — {t['abort_reason']}" if t.get("abort_reason") else "")],
        ["Parametry", f"nabíjení {_f(p.get('p_chg_kw'), 1)} kW · vybíjení {_f(p.get('p_dis_kw'), 1)} kW · výdrž {p.get('hold_min')} min · rozsah {p.get('floor_pct'):g}–{p.get('ceil_pct'):g} %"],
        ["Zadal", t.get("created_by") or "—"],
    ], widths=[45, 125])

    doc.add_heading("Výsledek celku", level=1)
    table([
        ["Nabito (krok 2)", _f(r.get("e_charge_kwh"), 2, "kWh"), "Vybito (krok 4)", _f(r.get("e_discharge_kwh"), 2, "kWh")],
        ["Dobito ve výdrži", _f(r.get("e_hold_kwh"), 2, "kWh"), "Účinnost cyklu", _f(r.get("efficiency_pct"), 1, "%")],
        ["Odhad kapacity", _f(r.get("capacity_est_kwh"), 2, "kWh"), "SoH vs. jmenovitá", _f(r.get("soh_pct"), 1, "%")],
        ["Max. rozdíl SoC bloků", _f(r.get("pack_drift_pct_max"), 1, "%"), "Celkové hodnocení", (LEVEL_TXT[a["level"]], a["level"])],
    ], widths=[42, 43, 42, 43])

    doc.add_heading("Vyhodnocení po blocích", level=1)
    rows = []
    for b in a["blocks"]:
        rows.append([b["name"], _f(b.get("nominal_kwh"), 2), _f(b.get("e_chg_kwh"), 2), _f(b.get("e_dis_kwh"), 2),
                     f"{_f(b.get('soc_dis_from'), 0)} → {_f(b.get('soc_dis_to'), 0)}", _f(b.get("capacity_est_kwh"), 2),
                     _f(b.get("soh_pct"), 1), _f(b.get("efficiency_pct"), 1), (LEVEL_TXT[b["level"]], b["level"])])
    table(rows, header=["blok", "jmen. kWh", "nabito kWh", "vybito kWh", "SoC vybíjení %", "využitelná kWh", "SoH %", "účinnost %", "hodnocení"], size=8.5)
    for b in a["blocks"]:
        doc.add_heading(f"{b['name']} — {LEVEL_TXT[b['level']]}", level=2)
        meta = _block_label({**b, "capacity_kwh": b.get("nominal_kwh")})
        if b.get("note"):
            meta += f" · {b['note']}"
        doc.add_paragraph(meta).runs[0].font.size = Pt(9)
        for f in b["findings"]:
            para = doc.add_paragraph(style="List Bullet")
            run = para.add_run(LEVEL_DOT[f["level"]] + " "); run.font.color.rgb = RGBColor(*LEVEL_RGB[f["level"]]); run.bold = True
            para.add_run(f["text"])
        c = b.get("cells") or {}
        def top(lst):
            return ", ".join(f"{x['txt']} {x['share_pct']:.0f} %" for x in lst[:2]) if lst else "—"
        table([
            ["nejvyšší článek při nabíjení", top(c.get("max_charge", []))],
            ["nejnižší článek při nabíjení", top(c.get("min_charge", []))],
            ["nejnižší článek při vybíjení", top(c.get("min_discharge", []))],
            ["nejvyšší článek při vybíjení", top(c.get("max_discharge", []))],
            ["nejnižší / nejvyšší v klidu", f"{top(c.get('min_rest', []))} / {top(c.get('max_rest', []))}"],
            ["Δ článků nahoře pod zátěží (SoC ≥ 85 %)", f"max {b['delta']['knee_top'].get('max_mv', '—')} mV, medián {b['delta']['knee_top'].get('median_mv', '—')} mV"],
            ["Δ článků dole pod zátěží (SoC ≤ 20 %)", f"max {b['delta']['knee_bottom'].get('max_mv', '—')} mV, medián {b['delta']['knee_bottom'].get('median_mv', '—')} mV"],
            ["Δ na plató (30–80 %) nabíjení / vybíjení", f"medián {b['delta']['plateau_charge'].get('median_mv', '—')} / {b['delta']['plateau_discharge'].get('median_mv', '—')} mV"],
            ["Δ v klidu", f"medián {b['delta']['rest'].get('median_mv', '—')} mV, max {b['delta']['rest'].get('max_mv', '—')} mV"],
        ], widths=[70, 100], size=8.5)
    if a.get("findings"):
        doc.add_heading("Celek", level=2)
        for f in a["findings"]:
            para = doc.add_paragraph(style="List Bullet")
            run = para.add_run(LEVEL_DOT[f["level"]] + " "); run.font.color.rgb = RGBColor(*LEVEL_RGB[f["level"]]); run.bold = True
            para.add_run(f["text"])
    doc.add_paragraph("Metodika: energie na DC straně baterie z výkonu po minutě (battery_power, _1, _2). SoH bloku = vybitá energie ÷ skutečně "
                      "projetý rozsah SoC bloku ÷ jmenovitá kapacita bloku. Čísla článků: pozice podle BMS (článků na modul hlásí BMS). "
                      "Δ = napětí nejvyššího − nejnižšího článku bloku. LFP plató rozdíly článků maskuje, proto rozhodují energie, "
                      "asymetrie bloků a chování v kolenech pod zátěží.").runs[0].font.size = Pt(8)

    if ctx.get("chart"):
        doc.add_heading("Průběh", level=1)
        doc.add_picture(io.BytesIO(ctx["chart"]), width=Mm(172))

    doc.add_heading("Rekapitulace kroků", level=1)
    PHN = {"discharge0": "1 · Předvybití", "charge": "2 · Nabíjení", "hold": "3 · Výdrž", "discharge": "4 · Vybíjení"}
    table([[PHN.get(s["phase"], s["phase"]), f"{_dt(s['t_from'], '%H:%M')}–{_dt(s['t_to'], '%H:%M')}", s["minutes"],
            f"{_f(s.get('soc_from'), 0)} → {_f(s.get('soc_to'), 0)}", _f(s["e_chg_kwh"]), _f(s["e_dis_kwh"]),
            f"{_f(s.get('e1_chg_kwh'))} / {_f(s.get('e1_dis_kwh'))}", f"{_f(s.get('e2_chg_kwh'))} / {_f(s.get('e2_dis_kwh'))}"]
           for s in (t.get("steps") or [])],
          header=["krok", "čas", "min", "SoC %", "příjem kWh", "výdej kWh", "B1 příjem / výdej", "B2 příjem / výdej"], size=8.5)

    doc.add_heading("Snímky po 10 %", level=1)
    def cell(s, k, which):
        v = s.get(f"cell_{which}_{k}"); n = s.get(f"cell_n{which}_{k}"); cpm = s.get(f"cpm_{k}")
        if v is None:
            return "—"
        from .assess import cell_txt
        return f"{float(v):.3f} V" + (f"\n{cell_txt(n, cpm).replace('článek ', 'čl. ')}" if n is not None else "")
    table([[PHN.get(s["phase"], s["phase"]), f"{s['soc_step']} %", _dt(s["ts"], "%H:%M"), _f(s.get("e_phase_kwh")), _f(s.get("e_step_kwh")),
            _f(s.get("minutes_step"), 0), f"{_f(s.get('soc1'), 0)} / {_f(s.get('soc2'), 0)}", f"{_f(s.get('e1_kwh'))} / {_f(s.get('e2_kwh'))}",
            f"min {cell(s, 1, 'vmin')}\nmax {cell(s, 1, 'vmax')}", f"min {cell(s, 2, 'vmin')}\nmax {cell(s, 2, 'vmax')}"]
           for s in (t.get("snapshots") or [])],
          header=["krok", "SoC", "čas", "kWh od zač. kroku", "+kWh/10 %", "min", "SoC B1 / B2", "kWh B1 / B2", "články B1", "články B2"], size=7.5)

    doc.add_heading("Protokol", level=1)
    for row in ctx.get("log") or []:
        para = doc.add_paragraph(f"{_dt(row['ts'], '%d.%m. %H:%M')}  {row['msg']}"); para.runs[0].font.size = Pt(7.5)
        para.paragraph_format.space_after = Pt(0)
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


# ---------- XLSX ----------
def build_xlsx(ctx: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    t, a, loc, mod = ctx["test"], ctx["assess"], ctx.get("locality") or {}, ctx.get("module") or {}
    p = t["params"]; r = t.get("result") or {}
    wb = Workbook()
    bold = Font(bold=True)

    def sheet(title, header, rows, widths=None):
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font = bold; c.fill = PatternFill("solid", fgColor="DDE3EA"); c.alignment = Alignment(wrap_text=True, vertical="top")
        for row in rows:
            ws.append(row)
        for i, w in enumerate(widths or [], start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        return ws

    ws = wb.active; ws.title = "Souhrn"
    def kv(k, v, level=None):
        ws.append([k, v]); ws.cell(ws.max_row, 1).font = bold
        if level:
            ws.cell(ws.max_row, 2).font = Font(bold=True, color=LEVEL_HEX[level])
    ws.append([f"Protokol testu kapacity a kondice baterie č. {t['id']}"]); ws.cell(1, 1).font = Font(bold=True, size=14)
    ws.append([f"TERA EMS v{ctx.get('version', '?')} · vygenerováno {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}"])
    ws.append([])
    kv("Lokalita", f"{loc.get('name', '—')}" + (f", {loc['address']}" if loc.get("address") else ""))
    kv("Měnič / modul", f"{mod.get('name') or t['module_id']} ({t['module_id']})")
    for b in p.get("blocks") or []:
        kv(f"Blok {b.get('name')}", _block_label(b))
    kv("Jmenovitá kapacita celkem (kWh)", p.get("capacity_kwh"))
    kv("Zahájení", _dt(t["started_at"])); kv("Ukončení", _dt(t.get("ended_at")))
    kv("Stav", STEP_NAMES.get(t["status"], t["status"]) + (f" — {t['abort_reason']}" if t.get("abort_reason") else ""))
    kv("Parametry", f"nabíjení {p.get('p_chg_kw')} kW · vybíjení {p.get('p_dis_kw')} kW · výdrž {p.get('hold_min')} min · {p.get('floor_pct'):g}–{p.get('ceil_pct'):g} %")
    kv("Zadal", t.get("created_by") or "—")
    ws.append([])
    kv("Nabito krok 2 (kWh)", r.get("e_charge_kwh")); kv("Dobito ve výdrži (kWh)", r.get("e_hold_kwh")); kv("Vybito krok 4 (kWh)", r.get("e_discharge_kwh"))
    kv("Odhad kapacity (kWh)", r.get("capacity_est_kwh")); kv("SoH (%)", r.get("soh_pct")); kv("Účinnost (%)", r.get("efficiency_pct"))
    kv("Max. rozdíl SoC bloků (%)", r.get("pack_drift_pct_max"))
    kv("Celkové hodnocení", LEVEL_TXT[a["level"]], a["level"])
    ws.append([])
    ws.append(["Vyhodnocení"]); ws.cell(ws.max_row, 1).font = bold
    for b in a["blocks"]:
        ws.append([b["name"], LEVEL_TXT[b["level"]]]); ws.cell(ws.max_row, 2).font = Font(bold=True, color=LEVEL_HEX[b["level"]])
        for f in b["findings"]:
            ws.append(["", f["text"]]); ws.cell(ws.max_row, 2).font = Font(color=LEVEL_HEX[f["level"]])
    for f in a.get("findings") or []:
        ws.append(["celek", f["text"]]); ws.cell(ws.max_row, 2).font = Font(color=LEVEL_HEX[f["level"]])
    ws.column_dimensions["A"].width = 34; ws.column_dimensions["B"].width = 120
    for row in ws.iter_rows():
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")

    sheet("Bloky", ["blok", "jmenovitá kWh", "moduly", "model", "instalace", "nabito kWh", "dobito ve výdrži kWh", "vybito kWh", "SoC vybíjení od", "SoC vybíjení do",
                    "využitelná kWh", "SoH %", "kapacita z nabíjení kWh", "účinnost %", "Δ nahoře max mV", "Δ dole max mV", "Δ plató nab. med mV", "Δ plató vyb. med mV", "Δ klid med mV", "hodnocení", "nálezy"],
          [[b["name"], b.get("nominal_kwh"), b.get("modules_count"), b.get("module_model"), b.get("installed"), b.get("e_chg_kwh"), b.get("e_hold_kwh"), b.get("e_dis_kwh"),
            b.get("soc_dis_from"), b.get("soc_dis_to"), b.get("capacity_est_kwh"), b.get("soh_pct"), b.get("capacity_from_charge_kwh"), b.get("efficiency_pct"),
            b["delta"]["knee_top"].get("max_mv"), b["delta"]["knee_bottom"].get("max_mv"), b["delta"]["plateau_charge"].get("median_mv"),
            b["delta"]["plateau_discharge"].get("median_mv"), b["delta"]["rest"].get("median_mv"), LEVEL_TXT[b["level"]], "\n".join(f["text"] for f in b["findings"])]
           for b in a["blocks"]], widths=[8, 12, 8, 20, 12, 11, 11, 11, 10, 10, 12, 8, 12, 10, 10, 10, 10, 10, 10, 20, 90])

    sheet("Články", ["blok", "role", "článek", "pozice", "podíl minut %", "počet minut"],
          [[b["name"], role, x["cell"], x["txt"], x["share_pct"], x["count"]] for b in a["blocks"]
           for role, key in (("nejvyšší při nabíjení", "max_charge"), ("nejnižší při nabíjení", "min_charge"), ("nejnižší při vybíjení", "min_discharge"),
                             ("nejvyšší při vybíjení", "max_discharge"), ("nejnižší v klidu", "min_rest"), ("nejvyšší v klidu", "max_rest"))
           for x in (b.get("cells") or {}).get(key, [])], widths=[8, 24, 8, 32, 12, 12])

    PHN = {"discharge0": "1 · Předvybití", "charge": "2 · Nabíjení", "hold": "3 · Výdrž", "discharge": "4 · Vybíjení"}
    sheet("Kroky", ["krok", "od", "do", "min", "SoC od", "SoC do", "příjem kWh", "výdej kWh", "B1 příjem", "B1 výdej", "B2 příjem", "B2 výdej"],
          [[PHN.get(s["phase"], s["phase"]), _dt(s["t_from"]), _dt(s["t_to"]), s["minutes"], s.get("soc_from"), s.get("soc_to"), s["e_chg_kwh"], s["e_dis_kwh"],
            s.get("e1_chg_kwh"), s.get("e1_dis_kwh"), s.get("e2_chg_kwh"), s.get("e2_dis_kwh")] for s in (t.get("steps") or [])],
          widths=[14, 16, 16, 6, 7, 7, 11, 11, 10, 10, 10, 10])

    sheet("Snímky", ["krok", "SoC %", "čas", "kWh od začátku kroku", "+kWh / 10 %", "min", "⌀ kW", "SoC B1", "SoC B2", "kWh B1", "kWh B2",
                     "B1 čl. min V", "B1 čl. min č.", "B1 čl. max V", "B1 čl. max č.", "B1 Δ mV", "B2 čl. min V", "B2 čl. min č.", "B2 čl. max V", "B2 čl. max č.", "B2 Δ mV", "síť kW"],
          [[PHN.get(s["phase"], s["phase"]), s["soc_step"], _dt(s["ts"]), s.get("e_phase_kwh"), s.get("e_step_kwh"), s.get("minutes_step"),
            round(float(s["e_step_kwh"]) / (float(s["minutes_step"]) / 60), 2) if s.get("e_step_kwh") and s.get("minutes_step") else None,
            s.get("soc1"), s.get("soc2"), s.get("e1_kwh"), s.get("e2_kwh"),
            s.get("cell_vmin_1"), s.get("cell_nmin_1"), s.get("cell_vmax_1"), s.get("cell_nmax_1"),
            round((s["cell_vmax_1"] - s["cell_vmin_1"]) * 1000) if s.get("cell_vmax_1") is not None and s.get("cell_vmin_1") is not None else None,
            s.get("cell_vmin_2"), s.get("cell_nmin_2"), s.get("cell_vmax_2"), s.get("cell_nmax_2"),
            round((s["cell_vmax_2"] - s["cell_vmin_2"]) * 1000) if s.get("cell_vmax_2") is not None and s.get("cell_vmin_2") is not None else None,
            round(float(s["grid_w"]) / 1000, 2) if s.get("grid_w") is not None else None] for s in (t.get("snapshots") or [])],
          widths=[14, 7, 16, 12, 10, 6, 7, 7, 7, 8, 8, 10, 8, 10, 8, 8, 10, 8, 10, 8, 8, 8])

    cr = {r_["ts"]: r_ for r_ in (ctx.get("cell_rows") or [])}
    def cell_of(ts, key):
        row = cr.get(datetime.fromisoformat(ts))
        return row.get(key) if row else None
    sheet("Průběh", ["čas", "výkon baterie W", "B1 W", "B2 W", "SoC %", "SoC B1", "SoC B2", "síť W", "FVE W",
                     "B1 čl. min V", "B1 čl. max V", "B1 čl. min č.", "B1 čl. max č.", "B2 čl. min V", "B2 čl. max V", "B2 čl. min č.", "B2 čl. max č."],
          [[_dt(s_["ts"]), s_.get("bat_w"), s_.get("bat1_w"), s_.get("bat2_w"), s_.get("soc"), s_.get("soc1"), s_.get("soc2"), s_.get("grid_w"), s_.get("pv_w"),
            cell_of(s_["ts"], "battery_cell_vmin_1"), cell_of(s_["ts"], "battery_cell_vmax_1"), cell_of(s_["ts"], "battery_cell_nmin_1"), cell_of(s_["ts"], "battery_cell_nmax_1"),
            cell_of(s_["ts"], "battery_cell_vmin_2"), cell_of(s_["ts"], "battery_cell_vmax_2"), cell_of(s_["ts"], "battery_cell_nmin_2"), cell_of(s_["ts"], "battery_cell_nmax_2")]
           for s_ in (t.get("series") or [])], widths=[16] + [10] * 16)

    sheet("Protokol", ["čas", "úroveň", "zpráva"], [[_dt(x["ts"]), x.get("level"), x["msg"]] for x in (ctx.get("log") or [])], widths=[16, 8, 120])
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()
