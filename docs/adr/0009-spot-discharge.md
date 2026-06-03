# ADR 0009: Vybíjení do sítě dle vysoké ceny (v0.7.0)

## Kontext
Doplnit k nákupu (nabíjení levně) i prodej — vybíjet baterii do sítě při
vysoké spotové ceně.

## Rozhodnutí
- Nový typ pravidla `spot_discharge` (params: price_threshold, soc_min,
  discharge_power). Logika: cena > práh a SoC > min → ECO_DISCHARGE.
- Řídicí vrstva: režim `force_discharge` → OperationMode.ECO_DISCHARGE
  (eco_mode_soc = spodní podlaha SoC).
- **Engine přepracován na agregaci podle zařízení**: pro každé zařízení se
  vyhodnotí všechna jeho pravidla a pošle se JEDEN výsledný povel. Nabíjení má
  přednost; pravidla si tak nepřebíjejí režim (nabíjet levně + prodávat draze
  na jedné baterii teď funguje bez konfliktu).
- soc_min chrání baterii (nevybíjet pod podlahu).
- Dashboard rozlišuje nabíjení vs vybíjení do sítě; ruční vybíjení i v Řízení.

## Důsledky
- První „prodejní" VPP chování. Předpoklad: smluvně povolený a kompenzovaný
  export do sítě.
- Rozšiřitelné o další typy pravidel (FCR/aFRR, peak shaving) stejným vzorem.
