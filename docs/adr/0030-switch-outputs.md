# 0030 – Spínací výstupy (sjednocení kontaktů a eWeLink + spouštěče)

## Stav
Přijato (v0.26.0)

## Kontext
„Spínací kontakty" uměly jen SOC→suchý kontakt střídače. Bylo třeba sjednotit
cíle (kontakt střídače i eWeLink spínač) a přidat spouštěč přebytek/FVE +
levný/záporný spot (sepnout spirálu přes eWeLink).

## Rozhodnutí
- Nový modul ems/outputs: tabulka switch_outputs (id, name, enabled, locality_id,
  output_kind ['goodwe_contact'|'ewelink'], target, trigger ['soc'|'surplus'], params,
  is_on, on_since, last_decision). Migrace starého contact_config při prázdné tabulce.
- Engine evaluate_outputs (v kolektoru místo evaluate_contacts):
  - soc: hystereze (≥upper sepni, ≤lower rozepni); SoC z lokality nebo z cíle.
  - surplus: telemetrie lokality (přebytek do sítě = kladné grid_power, SoC) + spot;
    sepni když přebytek ≥ práh A SoC ≥ min, NEBO spot ≤ spot_max (levný/záporný).
    Hystereze (drž do poloviny prahu) + minimální doba sepnutí (min_on_min).
  - aktuace: goodwe set_load_switch nebo ewelink.set_switch; stav v DB (edge-trigger).
- Endpointy /api/outputs (CRUD + /{id}/test ruční sepnutí). UI „Spínací výstupy"
  (přejmenováno z „Spínací kontakty", route /outputs i /contact).

## Důsledky
- Existující SOC kontakt se zmigruje do switch_outputs. Bateriový dispečink
  (Automatizace) zůstává oddělený. Sdílení lokalit master/slave je další fáze.
