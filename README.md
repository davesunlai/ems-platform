# TERA EMS

Univerzální energy management napříč energetickým portfoliem — sledování a (postupně) řízení vyrobené a spotřebované elektrické energie. Stavěno modulárně: jádro drží kanonický model, každý typ zdroje se připojuje přes vlastní adaptér.

Tento repozitář začíná **pilotem jedné domácnosti** (FVE 26 kWp, baterie 52 kWh, dvě Goodwe měniče), ale architektura je od začátku připravená na škálování (viz `docs/architecture.md`).

## v0.44.2 — Hlídač sítě u spotřebičů: pole jen pro KLADNÉ kW (type=number min=0), jasnější popis „vypni, když nakupuješ ze sítě > X kW" + pozn., že reaguje na import (nákup), ne na pokles výroby, a při 0 kW se nevypne. Záporná/nulová hodnota se neuloží (= vypnuto) — dřív zápor (-3) hlídač tiše deaktivoval.

## v0.44.1 — (1) Stránka SPOT: stará Goodwe automatika (formulář + seznam pravidel) schována za zatržítko „Zobrazit stará pravidla automatiky (Goodwe)", default skryté (na Solis se nepoužívá, spot vybíjení je v Řízení). (2) Audit povelů: zatržítko „zobrazit čtení stavu (read_controls)" — defaultně se read_controls SKRÝVAJÍ (filtr na serveru, neplýtvá místem), zapnutím se zobrazí.

## v0.44.0 — Spotové auto-vybíjení do sítě (Solis) přímo v ŘÍZENÍ u měniče. Pravidlo per modul: zapnout při spotu ≥ X Kč/MWh, vypnout při spotu < Y (hystereze), výkon v kW, podlaha SoC (nevybíjí pod ni). Kolektor vyhodnocuje každé kolo (živá cena), pouští force_discharge se source='spot'; plánovač i ruční zásah (override 30 min) mají přednost. Akce se zapisují do auditu (spot:auto) s důvodem i hodnotami; stav modulu ukazuje „· spot". Tabulka spot_discharge_rules. Menu „Automatizace" → „SPOT".

## v0.43.11 — Menu „Automatizace" přejmenováno na „SPOT" (stránka se spotovou cenou a pravidly). Route /automation beze změny.

## v0.43.10 — Zámek hlídače sítě je teď VIDĚT: v tabulce spínaných spotřebičů se u uzamčeného výstupu zobrazí „🔒 uzamčeno hlídačem do HH:MM" + tlačítko Odemknout (POST /api/outputs/{id}/unlock → zruší off_lock_until). Dosud byl zámek jen v DB/textu důvodu.

## v0.43.9 — Hlídač sítě (grid_guard) zpřehledněn: ve formuláři spotřebiče popisek „Hlídač sítě … prázdné = vypnuto", placeholder „vyp". Úprava/uložení výstupu nově ruší případný zámek off_lock_until (takže vyprázdnění hlídače = okamžité odemčení, nečeká se na vypršení). Hlídač je aktivní jen když je vyplněné kW i min > 0.

## v0.43.8 — Audit povelů u spotřebičů zaznamenává NAMĚŘENÉ HODNOTY v okamžiku rozhodnutí (params.values) — u SoC triggeru SoC %, prahy sepni/rozepni, čas, denní okno; u přebytku export kW, práh, SoC, spot. Rozklik řádku má novou sekci „Naměřené hodnoty…". Reason u SoC hystereze je teď srozumitelný: „SoC 94 % ≤ 95 % → vypnuto" / „… v pásmu … → beze změny".

## v0.43.7 — Audit povelů: (1) řádek jde ROZKLIKNOUT (▸) – ukáže důvod rozhodnutí + kompletní parametry a výsledek (JSON). (2) U spotřebičů se do auditu ukládá i DŮVOD (reason) a NÁZEV – sloupec „Co se stalo / důvod" tak rovnou píše třeba „mimo denní okno 06:30–13:29". (3) Sloupec Modul ukazuje NÁZEV (z params.name nebo z mapy modulů/výstupů) + pod ním device ID. Hledání funguje i přes název a důvod.

## v0.43.6 — (1) OPRAVA: kolektor dostal v docker-compose eWeLink proměnné (EMS_EWELINK_*) — dosud je měl jen api, proto spínání spotřebičů hlásilo „eWeLink není nakonfigurován". Po nasazení s `up -d collector` engine ohřev sám vypne. (2) Audit povelů: fulltextové hledání (uživatel/modul/akce/parametry/chyba) + stránkování (50/stránku, Novější/Starší).

## v0.43.5 — Audit povelů teď u neúspěšného povelu ukazuje DŮVOD chyby (z result.error) přímo pod „chyba" — např. text chyby z eWeLink. Pomáhá poznat, proč přepnutí spotřebiče selhalo (offline / autorizace / API).

## v0.43.4 — Spínané spotřebiče (SoC): denní okno „od–do" teď bere i MINUTY (HH:MM, např. 19:33) — vstup je typu čas. Podpora okna přes půlnoc (de<ds). Zpětně kompatibilní se starými celými hodinami. Backend porovnává na minuty (Europe/Prague).

## v0.43.3 — Dashboard: sepnuté spínané spotřebiče (eWeLink/kontakt) se teď ukazují v pruhu aktivního řízení pod názvem lokality — vedle „🔻 Vybíjení do sítě" je „🔌 <název> · sepnuto · od <čas>" (tyrkysový pruh). ControlBanners čte i stav výstupů (is_on/on_since) pro danou lokalitu, obnova á 5 s.

## v0.43.2 — Spínané spotřebiče: po sepnutí/rozepnutí (SoC/přebytek, vč. spirály) se notifikace rozešle HNED (jako u vynuceného nabíjení/vybíjení), ne až za 60 s. (Per-uživatel+lokalita kanály z v0.43.1 vyžadují přebudovaný API kontejner — viz pozn. k nasazení.)

## v0.43.1 — Notifikační kanály jsou nově PER UŽIVATEL + LOKALITA (ne globálně). Kanály (✉️ e-mail / 🖥️ prohlížeč / 📱 mobil-připravujeme) se zaškrtávají u každého uživatele přímo v editaci lokality vedle 🔔. Sloupce notify_email/notify_browser/notify_mobile přesunuty na user_localities; notify_users_for_locality i dispatcher čtou per-lokalita kanály. /api/alerts vrací browser_localities → zvoneček vypaluje browser notifikaci jen pro lokality, kde má uživatel zapnutý kanál prohlížeč. Globální volba kanálů odstraněna z Vzhledu i ze zvonečku (ve zvonečku zůstává jen povolení prohlížeče + test). Styl rozhraní (Klasický/Moderní) ve Vzhledu zůstává.

## v0.43.0 — (1) Řízení: zvýrazněný STAV MODULU v hlavičce (barevný odznak Self-Use / ⚡ Nabíjení / 🔻 Vybíjení do sítě / 🌀 Spirála + zdroj ručně/plánovač), aktualizace á 10 s. (2) Notifikace i u „stop" (návrat do Self-Use) — pokryto „cokoli v řízení". (3) Volba kanálů (e-mail / prohlížeč / mobil-připravujeme) je teď i ve Vzhledu (dřív jen pod zvonečkem). (4) Přepínatelný STYL ROZHRANÍ ve Vzhledu: Klasický (výchozí, beze změny) / Moderní (zkouška — měkčí stíny, zaoblení, vzdušnější panely). Styl je třída na <html>, ukládá se do localStorage → okamžité přepnutí bez rebuildu a bez problému s cache.

## v0.42.0 — Spotřebiče (SoC hystereze) rozšířeny o dvě podmínky pro „spirálu přes eWeLink": (1) DENNÍ OKNO – sepni jen mezi zvolenými hodinami (lokální čas), mimo okno vypnuto; (2) HLÍDAČ SÍTĚ – když se ze sítě bere import > X kW (default 0,5) souvisle déle než Y min (default 15), spotřebič se vypne a uzamkne na guard_lock_min (default 120 min), aby neposkakoval. Tím lze: při SoC ≥ 95 % sepnout spirálu, držet do 80 %, jen přes den a jen dokud to netáhne ze sítě. UI v Řízení → Spínané spotřebiče (trigger SoC) má nová pole. Sloupec off_lock_until.

## v0.41.6 — Grafy: výraznější osa X (nulová linka, silnější a kontrastní var(--fg)) a na ose Y vlevo se vždy vypisuje 0 (tučně), ať je zřejmé, kde leží nula. Sjednoceno napříč TimeChart, MultiChart, ForecastChart i SpotCurve (spotová křivka teď začíná od 0 — korektní sloupcový graf).

## v0.41.5 — Oprava popisu výkonu: ruční výkon je na CELÉ ÚLOŽIŠTĚ (obě baterie dohromady), ne na pack. Zrušen chybný ×2 odhad i popisek „kW / pack" v Řízení (label, tlačítka, status hláška „✓ Vybíjet teď (X kW)") a stejně i text v notifikacích/alertech (operační událost: „X kW" místo „X kW/pack").

## v0.41.4 — Oprava „nejde stopnout vybíjení": zapnutý plánovač okamžitě přebíjel ruční Stop (cur=idle != desired=force_discharge → znovu poslal vybíjení). Nově RUČNÍ PŘEBITÍ: po jakémkoli ručním povelu (Stop/Nabíjet/Vybíjet, source=manual) nechá plánovač modul 30 min na pokoji (EMS_MANUAL_OVERRIDE_SEC), pak se zase ujme. Navíc pojistka: zatoulaný keepalive „force_poke" z doby před Stopem se přeskočí, když už modul neforcuje. Nápověda v Řízení upřesněna.

## v0.41.3 — Notifikace: (1) U lokality (editace) přibyl srozumitelný výpis NA CO chodí upozornění (vynucené nabíjení/vybíjení, spirála, sepnutí spotřebiče, výpadky, test) a KTERÝM kanálem (mail / prohlížeč i na jiné kartě / mobil-připravujeme). (2) E-mail u operací chodí HNED — po vynucené operaci se rozeslání spustí okamžitě (ne až za 5 min) a kontrolní tick zrychlen 5 min → 60 s. Pozn.: operační události mají TTL 60 min, takže staré události se po obnově SMTP zpětně nerozesílají.

## v0.41.2 — Oprava odesílání e-mailů ("Connection lost"): u implicitního TLS (port 465) se teď explicitně vypíná start_tls (aiosmtplib jinak zkoušel STARTTLS přes už šifrované spojení → server spojení položil). Přidán timeout a fallback na druhý režim/port (465/ssl ↔ 587/starttls) + auto-odvození režimu z portu. Navíc tlačítko „🔔 Poslat testovací notifikaci" v zvonečku (okamžitá událost + hned rozešle e-mail) a zrychlení obnovy zvonečku 180 s → 30 s, aby browser notifikace přišly rychle.

## v0.41.1 — Notifikace o důležitých OPERACÍCH: nový modul operačních událostí (ems/alerts/db.py, tabulka operational_events). Zaznamenává se vynucené nabíjení/vybíjení/spirála (kolektor) a sepnutí/rozepnutí spínaného spotřebiče (outputs engine). Události se na ~1 h zařadí mezi výstrahy → projeví se v zvonečku ⚠, browser notifikaci i e-mailu (stejný dispatcher + dedup). alerts.collect_for_user/locality teď zahrnují i eventy. Bez změny frontendu (vše jede stávající cestou výstrah).

## v0.41.0 — Notifikace krok 1: volba kanálu per uživatel (e-mail / prohlížeč; mobil připravujeme) + reálné doručování. Do `users` přidány `notify_email`/`notify_browser`, dedup tabulka `notification_log`. Kolektor `tick_notify` (à 5 min) rozesílá nové výstrahy (zatím výpadky) e-mailem opt-in uživatelům lokality (user_localities.notify) přes existující SMTP. Prohlížeč: zvoneček ⚠ při nové výstraze vypálí Notification (když je appka otevřená a kanál povolený), s tlačítkem „Povolit upozornění v prohlížeči". Volba kanálů + povolení je v dropdownu zvonečku. API: PUT /api/auth/me/notify; alerts.collect_for_locality; localities.notify_users_for_locality vrací i kanály.

## v0.40.2 — (1) Souhrn lokality na dashboardu: u „ze sítě"/„do sítě" přibyl OKAMŽITÝ výkon v kW (import/export z grid_w) vedle denní energie, s ikonou stožáru (tower) pro jasnou identifikaci sítě. (2) Řízení (Solis): vyjasněno, že ruční výkon se zadává v kW NA JEDEN battery pack — u 2 packů je celkový výkon ≈ 2× (5 kW/pack → ~10 kW celkem); přidán živý odhad „≈ X kW celkem" a popisky tlačítek. Bez změny backendu (grid_w už API vracelo).

## v0.40.1 — Caddy: externí projekty (mimo EMS repo, např. playcup.online) už nemizí po updatu. Hlavní Caddyfile dostal `import /etc/caddy/sites/*.caddy`, compose mountuje `./sites`, a deploy/tar fragmenty `infra/sites/*.caddy` NIKDY nepřepisuje (vyloučené z balíčku). Doc INFRA-FRANTA aktualizován. (Bez změny aplikace.)

## v0.40.0 — Oprava řízení Solis (vybíjení + jednotky + deadman): (1) PŘÍMÉ VYBÍJENÍ opraveno — výkon vybíjení musí jít do registru 43129 (ne 43136, ten je jen pro nabíjení); set_force teď píše výkon do správného registru podle směru. (2) Jednotka výkonu potvrzena: 43136/43129 = 10 W na jednotku (kW×100); UI v Řízení i banner na dashboardu teď v kW; default ruční výkon 5 kW. (3) Deadman switch: 43135 se po ~5 min sám nuluje → kolektor každé 4 min „přiťukne" aktivní force (tick_force_keepalive + akce force_poke), aby vynucené nabíjení/vybíjení nespadlo. (4) Plánovač teď posílá force s výkonem odvozeným z plánu (battery_kw → registr), vybíjení přes 43129. Zdroj: oficiální Solis Modbus + empirická kalibrace (1000→10kW).

## v0.39.1 — Oprava přesunu zúčtování: tabulka „Zúčtovací období" VRÁCENA na konec dashboardu (pod karty zařízení). Do administrace Lokality přesunuto NASTAVENÍ zúčtovacího období (začátek, délka, limit přetoků, baseline, cenění, e-mail upozornění) jako sekce BillingSettings v editaci lokality. Samostatná stránka /billing zrušena (redirect → /localities), položka v menu odebrána, průvodce upraven.

## v0.39.0 — (1) „Zúčtovací období" přesunuto z dashboardu do administrace Lokality (BillingTable jako sdílená komponenta, per lokalita v editaci). (2) Notifikace vázané na uživatele+lokalitu: do user_localities přidán sloupec `notify`; v editaci lokality má každý přiřazený uživatel zaškrtávátko 🔔 notifikace (uživatel dostává jen z lokalit, kde to má zapnuté). API PUT /admin/localities/{id}/users/{uid}/notify; db.notify_users_for_locality (kdo má dostávat). Doručování (web push do mobilu/prohlížeče) je další krok.

## v0.38.3 — (1) Dashboard: stavové pruhy (např. „Vybíjení do sítě (výkon 1000)") přesunuty z karty zařízení úplně nahoru pod název lokality (ControlBanners pro celou lokalitu, ukáže i modul + zdroj). (2) Řízení: centrální souhrn „🧭 Co ovlivňuje tuto lokalitu" na začátku každé lokality — stav plánovače + aktuální akce, aktivní vynucené zásahy, spotová pravidla (s indikací „přebírá plánovač" + odkaz na Automatizaci) a spínané spotřebiče. Read-only přehled, detailní editace v panelech pod ním.

## v0.38.2 — Spínací výstupy přesunuty do ŘÍZENÍ jako "Spínané spotřebiče" (per lokalita): panel s formulářem (eWeLink/kontakt střídače, spouštěč SoC nebo přebytek/spot) + tabulka se stavem, testem zap/vyp, úpravou a mazáním; lokalita se bere z sekce (bez výběru). Samostatná stránka /outputs i /contact teď přesměrují do Řízení, položka v menu odebrána, průvodce (Tour) aktualizován. Nápověda v Řízení doplněna o spínané spotřebiče.

## v0.38.1 — UX Řízení a graf: (1) rozbalovací NÁPOVĚDA v Řízení polopaticky vysvětlí plánovač/ruční řízení/limity/bezpečnost; (2) načtení stavu z měniče se KEŠUJE per modul (15 min) — při dalším otevření Řízení se nečte znovu ze střídače; hláška "Načtení stavu provedeno" má teď datum a čas (+ "z mezipaměti"); (3) přehledový graf na dashboardu (MultiChart): plovoucí rámeček sleduje kurzor i SVISLE (nahoru/dolů), ne jen vodorovně, aby nezakrýval data.

## v0.38.0 — KROK 6: prediktivní PLÁNOVAČ (greedy MVP). ems/planner: core.plan (self-use + levné nabití + špičkové vybíjení do sítě, rezerva floor), dispatch_schedule, planner_config per lokalita. Panel plánovače v Řízení (zapnout=řídí měnič, povolit vybíjení do sítě, kapacita/SoC/rezerva/limity/horizont). Plán se počítá vždy poradně; řízení opt-in přes frontu (force BEZ syrového výkonu -> na limitech proudu, obejde 43136). Precedence: zapnutý plánovač přebírá řízení, reaktivní spot pravidla se přeskočí + Automatizace ukazuje "⚠ přebírá plánovač". SoC trajektorie v grafu na dashboardu. ADR 0034.

## v0.37.1 — Řízení (Solis) UX: limity/SoC se po otevření AUTOMATICKY načtou živě z měniče (read_controls), ne z DB; "Načíst aktuální z měniče" je teď velké výrazné tlačítko + indikace "čtu…"; u ručního výkonu doplněn popis (syrová hodnota registru); poznámka, že hodnoty jsou živé z měniče.

## v0.37.0 — Řízení přestavěno na strukturu LOKALITA → MODULY. Ruční ovládání (Nabíjet/Vybíjet/Stop) přesunuto z dashboardu jen do Řízení; na dashboardu zůstává jen zvýrazněný stavový pruh. Per modul (Solis) přidáno nastavení LIMITŮ přes frontu: nabíjecí/vybíjecí proud (43012/43013, scale 0.1A — ověřené), SoC backup/force (43024/43030), Self-Use režim (43110), + "Načíst aktuální" (read_controls). Goodwe ovládání zůstává. Per lokalita je místo pro plánovač (krok 6). Adaptér: set_charge/discharge_current, set_soc_backup/force; dispatch + validace rozšířeny. controllable_modules vrací i Solis + lokalitu. 43136 (force power 3f) stále neověřený — testovat opatrně.

## v0.36.0 — (1) OPRAVA zadávání cen: NumField přesunut na úroveň modulu (input se přemountovával -> ztráta fokusu po každé cifře); hodnoty se drží jako text, převod na číslo až při uložení -> jde psát "200" v kuse. (2) Krok 2: sledování aktuálního VYNUCENÉHO STAVU modulu (control_state) — kolektor ho zapisuje po provedení povelu; nápadný PULZUJÍCÍ pruh na dashboardu (⚡ Vynucené nabíjení / 🔻 Vybíjení do sítě / 🌀 Spirála), viditelný i pro ne-ovládací uživatele, s výkonem a časem od. API GET /api/control/states.

## v0.35.0 — Cenový model: versionovaný locality_tariff (valid_from) — fix i spot, dvoutarif VT/NT (NT hodiny), provize z prodeje (~200 Kč/MWh), distribuce VT/NT, přirážka, poplatky, měsíční paušál. Editace cen v Lokalitách. Denní kurz EUR→CZK z ČNB (ems/pricing/fx, cache fx_rate) — pozn. spot je ze zdroje už v CZK, kurz tedy informativní. Graf predikce: pravá osa teď ukazuje REÁLNOU cenu nákupu (Kč/kWh) z tarifu místo syrového spotu. ems/pricing modul (db/fx/cost/routes). ZATÍM BEZ ŘÍZENÍ.

## v0.34.0 — Forecast kroky 4+5: load_forecast (medián hodina-v-týdnu z bilance FVE+síť−baterie, Solis nedává load_power) + NOVÝ GRAF "Predikce 24–48 h" na dashboardu — PV plocha + pásmo nejistoty (levá osa kW), spotřeba, spot (pravá osa Kč/kWh; u pevného tarifu čárkovaně). Graf jen čte cache. API /api/forecast/{id} vrací pv+pásmo, load, spot, pricing_mode. ZATÍM BEZ ŘÍZENÍ (SoC trajektorie/nabíjecí sloupce přijdou s plannerem).

## v0.33.0 — Forecast krok 1: druhý zdroj Forecast.Solar (stejná azimut konvence jako Open-Meteo, žádný přepočet) + průměrování až výsledných řad do source='avg' + PÁSMO NEJISTOTY (pv_w_lo/pv_w_hi = rozptyl zdrojů). Bloky stejné orientace se slučují (1 dotaz/orientaci). Forecast.Solar throttle ~2.5 h (limit 12/hod), při výpadku/limitu fallback na cache nebo jen Open-Meteo. Pojistka v editaci: prázdné "FVE kWp celkem" červeně + Uložit zašedne.

## v0.32.2 — Forecast refresh: konkrétní hláška co schází (kWp vs bloky vs vypnuté) + log kWp/poctu bloku, ať jde příčina rozlišit.

## v0.32.1 — OPRAVA: uložení lat/lon/pv_kwp_total z UI nefungovalo — pole chyběla v Pydantic modelu LocalityUpdate, takže je FastAPI z requestu zahodil ("chybí lat/lon"). Doplněna.

## v0.32.0 — NOVÁ FEATURE: predikce výroby z počasí (čtecí základ). Modul ems/forecast: Open-Meteo provider (global_tilted_irradiance, azimut 0=J/−90=V/+90=Z), PV model P_ac=kWp×GTI/1000×PR×temp_factor se samokalibrací PR proti reálné výrobě, cache tabulky weather_forecast/pv_forecast, konfigurace PV bloků (pv_block: typ normal/bifacial, podíl, směr, sklon). Lokalita: lat/lon/pv_kwp_total + admin v Lokalitách (město fulltextem → geokódování, bloky panelů). API /api/forecast/*. Kolektor přepočítává à 3 h. ZATÍM BEZ ŘÍZENÍ (dispatch/graf/2. zdroj v dalších commitech dle §14). ADR 0033.

## v0.31.22 — OPRAVY: (1) Kč v souhrnu se počítaly za špatný den (server UTC vs pražská půlnoc) -> dnešní spotová cena teď přes stejné pražské okno jako kWh (po půlnoci tedy 0). (2) Výroba v billingu z vlastního denního počítadla měniče (energy_today, max za pražský den), odolné proti výpadkům; fallback integrace pv_power u goodwe.

## v0.31.21 — Billing: Spotřeba se už nepočítá z load_power (Solis ho nedává -> bylo 0), ale z bilance FVE+import−export−Δbaterie (fallback na load_power u goodwe). Vše integrací telemetrie = konzistentní.

## v0.31.20 — Souhrn lokality zpřehledněn: spotřeba „kW / dnešní kWh" (dopočet spotřeby dne z bilance FVE+import−export−Δbaterie), FVE „kW / dnes Σ kWh" pohromadě stejnou barvou, baterie jako ikonka místo textu. aggregate_now vrací cons_today_kwh.

## v0.31.19 — Cenění lokality (spot dle OTE / pevný tarif Kč/kWh) volitelné v Zúčtování. Souhrn lokality: u „ze sítě/do sítě" přibyla cena v Kč. Billing tabulka: sloupce „Cena ze sítě" a „Cena do sítě" (spot z spot_history, nebo tarif). OPRAVA: billing import/export byly prohozené vůči konvenci +import/−export (jako v souhrnu) — sjednoceno.

## v0.31.18 — Souhrn lokality: na konci přibyla dnešní energie ZE sítě (import) a DO sítě (export) — integrace grid_power přes dnešek (mezery > 120 s se nezapočítají). aggregate_now vrací import_kwh/export_kwh. Read-probe doplněn o kandidáty denní energie sítě 33169–33180 (k pozdějšímu ověření z měniče).

## v0.31.17 — Graf „Souhrn lokality": série Spotřeba lokality nově jede z POČÍTANÉ spotřeby (load = Σ FVE + Σ síť − Σ baterie per bucket), takže funguje i bez přímého load_power (Solis 3f). aggregate_history podporuje virtuální metriku „load".

## v0.31.16 — Řízení Solis přes portál (fáze C): povelová FRONTA (control_queue) vyřizovaná kolektorem (drží jediné Modbus spojení) — dispatch force_charge/force_discharge/stop/set_work_mode/write_holding/read_holding. API POST /api/control/{id}/command + GET /api/control/command/{id}. Ovládací panel na dashboardu (gating dle control_enabled + oprávnění control): Nabíjet/Vybíjet teď (syrový výkon — scale ověřujeme), Stop, potvrzení + polling stavu. Výkon 43136 scale zatím syrový.

## v0.31.15 — Souhrn lokality: výrazná aktuální SPOTŘEBA (dopočet z bilance FVE + síť − baterie), přejmenováno „součet" -> „FVE". aggregate_now vrací load_w/grid_w/battery_w.

## v0.31.14 — Řízení (fáze C, krok 1): zápisová vrstva adaptéru Solis — write_holding s ověřením zpětným čtením, set_force(0/1/2 + výkon), set_work_mode; read_holding pro stav. Nový write-probe (ems.adapters.solis.wprobe) pro BEZPEČNÉ ověření řídicích registrů na reálném kuse (čte stav; zápis jen explicitně + potvrzení). ADR 0008. UI/API ovládání až po ověření registrů.

## v0.31.13 — UI: ikony u veličin (teploměr u teploty atd.) v editaci i na dashboardu, veličiny seskupené (FVE / Síť / Měnič / Baterie 1/2) v editaci i dashboardu, nová sekce „Ovládání a konfigurace" se zatržítky (zápisová vrstva = příprava, fáze C; ukládá se do control_enabled). Sdílené definice web/src/metrics.js + komponenta Icon.jsx. control_enabled odfiltrován z konstruktoru adaptéru.

## v0.31.12 — Souhrn lokality „dnes Σ": přednostně bere energy_today z měniče (sám si ho počítá -> odolné proti výpadkům kolektoru), fallback max−min energy_pv_total. Obsahuje i v0.31.11 (fix hidden_metrics).

## v0.31.11 — OPRAVA: display-only param `hidden_metrics` (z volby „Co zobrazovat") se cpal do konstruktoru adaptéru a shazoval připojení každý cyklus (modul neaktivní). Nyní se u všech adaptérů odfiltruje.

## v0.31.10 — Solis: když měnič odmítne blok (neimplementovaný registr v rozsahu), čtení blok automaticky rozpůlí a dojede zbytek — jeden vadný registr neshodí ostatní. Za normálu pořád 5 dotazů/cyklus.

## v0.31.9 — Solis: HROMADNÉ čtení v blocích (5 dotazů/cyklus místo ~20) — řeší pády/neaktivitu při mnoha veličinách (měnič/stick nedával rychlé jednotlivé dotazy). Přidána teplota měniče (33093). Teplota Bat2 přehozena na 34282 (34281 vracelo nesmysl). Teploty znaménkové (s16).

## v0.31.8 — Solis hybrid čte i: dnešní energii, 3f síťová napětí L1/L2/L3, SOH a teplotu obou baterií (vše ověřené registry §9/§10). Katalog v editaci doplněn — 21 veličin (počitadlo zčervená nad limitem 20).

## v0.31.7 — Editace modulu: checklist veličin ve sloupcích (3–4 dle šířky) + kompletní katalog co umíme u daného hybridu/typu sledovat; limit 20 zatržených (počitadlo + text „další za příplatek", přes limit nejde zaškrtnout).

## v0.31.6 — Hybrid baterie per-pack: napětí/proud/výkon zvlášť pro Bat1 i Bat2 (místo matoucího součtového proudu). Editace modulu: checklist „Co zobrazovat" (z reálně měřených veličin) — skryté metriky se neukazují na dashboardu (uloženo v params.hidden_metrics).

## v0.31.5 — Hybrid Solis: SOC obou baterií zvlášť (battery_soc_1/2) vedle průměru; volba „Počet baterií" (Auto/1/2) — auto zahrne pack jen když reálně odpovídá. Registry z probe potvrzeny (PV 33057, síť 33130, pack1 331xx, pack2 342xx).

## v0.31.4 — Stránka Moduly: barevná tečka aktivity (zelená/červená dle čerstvé telemetrie) + sloupec Lokalita (vyplněný, pokud je modul přiřazen). Seznam se obnovuje každých 10 s.

## v0.31.3 — Solis: čtení odolné proti pádu socketu (jeden vadný registr neshodí hybrid/pack2) + diagnostika `python -m ems.adapters.solis.probe`. Dashboard: neaktivní moduly jen když mají lokalitu; výběr lokality fulltextem s pamatováním poslední (hlavně pro adminy).

## v0.31.2 — Nový typ zařízení „hybrid": jeden modul ukáže celý střídač (FVE + síť + energie + baterie agregovaně přes oba packy). Solis emituje vše najednou; device_type už nic neomezuje (souhrn jde dle metrik). Backup/load 3f registry zatím nepotvrzené.

## v0.31.1 — Editace modulu v UI („Upravit": změna IP/portu/názvu přes PATCH) + kolektor reconnectuje modul při změně parametrů za běhu (~10 s, bez restartu). Obsahuje i v0.31.0 (solis adaptér).

## v0.31.0 — Nový čtecí adaptér „solis" (Solis S6-EH3P50K-H, Modbus TCP přes pymodbus): stejná kanonická pole i znaménka jako goodwe (grid otočen, battery_power=U*I), 2 battery packy, registrace ve factory + UI dropdown s popisnými labely. Read-only.

## v0.30.8 — docs/INFRA-FRANTA.md bod 7: po tar -xzf nutný RESTART Caddy (ne reload) kvůli inode; deploy.sh to dělá sám.

## v0.30.7 — Caddyfile všechny 4 domény (teraems.com, tipomat.net, narozeniny.eu, plakatovaciplocha.cz) na jména kontejnerů; pravidla infry uložena v docs/INFRA-FRANTA.md.

## v0.30.6 — Caddy: reverse_proxy na JMÉNO KONTEJNERU (infra-web-1, tipomat_app) — odstraňuje kolizi aliasu „web" na sdílené edge síti; + dynamický re-resolve (refresh 10s). Toto je správná verze místo v0.30.5.

## v0.30.5 — Caddy dynamicky re-resolvuje upstreamy (dynamic a, web i tipomat_app, refresh 10s, resolver 127.0.0.11) — konec 502 po recreate/restartu (stale IP).

## v0.30.4 — Safe-area pro mobilni appku: .topbar padding-top + height calc(58px + env(safe-area-inset-top)), body spodni inset. V prohlizeci beze zmeny (env()=0). Zapeceno v repo styles.css.

## v0.30.3 — Caddy: teraems.com + tipomat.net (reverse_proxy tipomat_app:8000), Caddy na sdílené externí síti „edge". Zapečeno v repu.

## v0.30.2 — EMS čistě jen teraems.com (narozeniny.eu/edge odebráno z repa); privacy.html zachováno.

## v0.30.1 — narozeniny.eu (tipomat) zapečeno do infra/Caddyfile + Caddy připojen na sdílenou externí síť „edge" (přežije deploy, oddělené projekty).

## v0.30.0 — Zásady ochrany soukromí (/privacy.html) pro Google Play.

## v0.29.4 — Ikony: logo zvětšeno na maximum (Chrome favicon, iOS, Android adaptivní v rámci bezpečné zóny) — lépe čitelné v malém.

## v0.29.3 — Splash: „TERA EMS" celé v zelené (značková barva).

## v0.29.2 — Splash: „TERA EMS" jednotně světle (bez zeleného EMS), zelené jen iniciály E·M·S v podtitulu.

## v0.29.1 — Web favicon + manifest (ikona v Chrome/záložce, „přidat na plochu") a splash s rozepsanou zkratkou E·M·S (Energy Management System).

## v0.29.0 — Ikona a splash aplikace (mobile/assets): blesk v oblouku, zelená na tmavém pozadí; z předlohy 1024px se přes @capacitor/assets vygenerují všechna rozlišení pro Android i iOS.

## v0.28.1 — nginx: index.html se necachuje (appka/prohlížeč hned vidí novou verzi po nasazení), hashované assety cachovány natrvalo.

## v0.28.0 — Responzivní design pro mobil: menu se na úzké obrazovce skládá do ☰ (nav + účet), skryté nepodstatné prvky, tabulky se rolují vodorovně, žádné přetékání mimo obrazovku.

## v0.27.0 — Přidán mobilní obal Capacitor ve složce mobile/ (Android + iOS), varianta B: appka načítá živý web teraems.com. Server/web build nedotčen.

## v0.26.1 — Spínací výstupy: vyhledávací (fulltext) rozbalovací pole u Zařízení a Lokality, bez ohledu na diakritiku.

## v0.26.0 — Spínací výstupy: sjednocení kontaktů střídače a eWeLink spínačů; spouštěče SoC hystereze i přebytek/FVE + levný/záporný spot (sepnutí spirály přes eWeLink) s hysterezí a min. dobou sepnutí.

## v0.25.0 — Dashboard: u názvu lokality živý souhrn (součet výkonu FVE kW, baterie %, dnešní výroba kWh).

## v0.24.2 — Řízení/Automatizace nabízí bateriové ovládání jen u měničů s baterií (auto-detekce dle battery_soc); grid-tie GW10K-DT se už nezobrazuje jako řiditelný.

## v0.24.1 — Vzhled: ukládání vlastních motivů pod názvem (knihovna „Moje uložené motivy") a návrat k nim.

## v0.24.0 — Vzhled: přednastavené barevné motivy uložené u uživatele (Půlnoc/Břidlice/Karbon/Oceán/Světlý) + základní editor vlastního motivu.

## v0.23.0 — Automatizace: editace pravidel + hystereze nabíjení (soc_start → soc_max), např. nabíjet jen pod 50 % a dojet do 100 %.

## v0.22.5 — Tlačítko „teď" v ovládání grafů přesunuto vlevo od šipek, aby se při posouvání času šipky neposouvaly pod kurzorem.

## v0.22.4 — Oprava časového pásma spotových slotů: stavějí se v Europe/Prague (ne v UTC kontejneru), takže graf i aktuální slot sedí s reálným časem.

## v0.22.3 — Spotový graf: hover svislá čára s datem, časem a cenou (jako ostatní grafy).

## v0.22.2 — eWeLink: oprava zapínání/vypínání (dvojí JSON kódování) a výpisu zařízení (num=0 místo nefunkčního beginIndex).

## v0.22.1 — eWeLink: výpis zařízení napříč všemi rodinami/domácnostmi + stránkování (dřív se ukazovala jen jedna rodina).

## v0.22.0 — eWeLink přes OAuth2 (tlačítko Připojit, token v DB s auto-obnovou), výpis a on/off ovládání Sonoffů.

## v0.21.0 — HTTPS přes Caddy (Let's Encrypt) pro teraems.com; reverzní proxy na web kontejner. Odemyká OAuth2 pro eWeLink.

## v0.20.1 — Souhrn lokality: klik na popisek skryje/zobrazí řadu (přepočte osu), přidána řada Baterie.

## v0.20.0 — Grafy: hover svislá čára u kurzoru s časem a hodnotou (MultiChart ukáže všechny řady naráz).

## v0.19.1 — deploy.sh na konci restartuje web (nginx), aby po přegenerování api nedržel starou IP (konec opakovaných Bad Gateway).

## v0.19.0 — Oznámení odstávek: hodina běhu (EMS_OUTAGE_HOUR) a opakování ve dnech (EMS_OUTAGE_REMIND_DAYS) v .env; úvodní mail + připomínky až do odstávky (řízeno last_notified); kolektor dostal SMTP.

## v0.18.1 — Admin může u uživatele změnit Jméno (tlačítko ✎ u jména v seznamu uživatelů).

## v0.18.0 — E-mail přiřazeným uživatelům při nové plánované odstávce (edge-trigger na nově zjištěné odstávky, denně i při „Načíst teď").

## v0.17.1 — Pevné DNS (1.1.1.1/8.8.8.8) pro api a collector kontejnery, aby dosáhly na ČEZ (jinak „name resolution" chyba uvnitř kontejneru).

## v0.17.0 — Průvodce systémem: po prvním přihlášení provede klikacími kroky, přepíná stránky a zvýrazňuje menu; znovu spustitelný tlačítkem „Průvodce".

## v0.16.1 — Graf zařízení se po výběru veličiny bez dat neschová celý, ukáže ovládání + hlášku (snazší dostat se k SoC).

## v0.16.0 — Dashboard: klikací dlaždice přepínají metriku grafu (vč. SoC baterie), barva křivky dle veličiny.

## v0.15.3 — Předání EMS_SMTP_FROM_NAME do api kontejneru v docker-compose (jinak se proměnná z .env nedostala dovnitř).

## v0.15.2 — Konfigurovatelné jméno odesílatele e-mailů přes EMS_SMTP_FROM_NAME (výchozí „TERA EMS").

## v0.15.1 — Menu „Kontakt" přejmenováno na „Spínací kontakty"; stránka připravena na další spínané výstupy (eWeLink/Olimex) a spouštěče.

## v0.15.0 — Výstrahy v liště: trojúhelník s počtem výstrah scoped na lokality uživatele, generický agregátor (zatím odstávky), endpoint /api/alerts.

## v0.14.0 — Plánované odstávky distribuce (ČEZ): identifikace u lokality (EAN/elektroměr/adresa, priorita), denní stahování, zobrazení v adminu.

## Stav

- **Monitoring** reálných Goodwe měničů (ET hybrid + DT grid-tie).
- **Identita a RBAC** (v0.2): přihlášení (JWT), role viewer/operator/admin, oprávnění `read`/`control`/`admin`, správa uživatelů.
- **Registr modulů v DB** (v0.3): správa zařízení/modulů z admin UI, živá rekonciliace bez restartu kolektoru, migrace z devices.yaml.
- **Řízení / zápis do měniče** (v0.4): povelový kanál s ověřením (read-back) a auditem, oprávnění `control`. První povel: režim baterie Goodwe ET — vynucené nabíjení / normální režim.
- **Automatizace dle spotové ceny** (v0.5): pravidlo „levný spot → nabíjej", zdroj cen OTE + ruční test, audit automatických povelů, samoopravné edge-triggerem. První VPP chování.
- **Správa hesel** (v0.6): změna vlastního hesla, admin reset, zapomenuté heslo přes e-mail (Forpsi SMTP), profilová pole (e-mail, jméno).
- **Spínání kontaktu dle SOC** (v0.13.0): suchý kontakt (relé) měniče se sepne na horní mezi SOC a rozepne na dolní mezi (hystereze, např. 100/95 %); stránka „Kontakt" s nastavením mezí, zapnutím a ručním testem. Goodwe ET přes load_control_switch.
- **Nula při výpadku dat** (v0.12.4): u výkonových veličin (pv/load/grid) se při mezeře v datech (výpadek spojení se střídačem) vloží nula místo šikmé interpolační spojnice — graf spadne na 0 a po obnově se zvedne.
- **Uvítací a reset e-maily** (v0.12.3): po založení uživatele (s e-mailem) přijde brandovaný uvítací e-mail TERA EMS s odkazem na nastavení hesla; tlačítko „Reset hesla" v adminu pošle uživateli e-mail s odkazem (heslo při tvorbě je nepovinné).
- **Zúčtovací období + přetoky** (v0.12.0–0.12.1): per lokalita nastavení období (start dle ČEZ, délka, limit přetoků); na dashboardu tabulka po měsících (výroba/spotřeba/přetoky/odběr) + součet za období + pruh přetoky vs. limit; po konci období od nuly. V adminu lze doplnit dodávku/odběr před spuštěním měření (přičte se k období). Znaménko sítě: kladné = dodávka.
- **Posun času šipkami + datum** (v0.11.0–0.11.1): grafy (zařízení i souhrn lokality) se posouvají šipkami ◀ ▶ vždy o jeden aktuálně nastavený úsek (délku okna); nad grafem je čitelný popisek datum/čas rozsahu a tlačítko „teď".
- **Souhrnný graf lokality** (v0.10.0): dashboard seskupený podle lokality, souhrnný víceřadý graf — součet výroby FVE + spotřeba lokality + odběr/dodávka do sítě (řady dle dostupných dat), okno 6 h–30 dní.
- **eWeLink/Sonoff (test)** (v0.9.0): připojení na eWeLink cloud, admin výpis zařízení (online, vypínač, příkon). První integrace chytrých zařízení; ovládání a telemetrie navazují.
- **Lokalita a stav na dashboardu** (v0.8.1): u zařízení se zobrazuje lokalita a tečka zelená (aktivní) / červená (neaktivní, žádná čerstvá data); neaktivní zařízení už nevisí na „Načítám".
- **Čtvrthodinová křivka + okno** (v0.8.0): spotová křivka v 15min rozlišení (trh OTE), historie ve `spot_history`, tlačítka +/− pro okno den→30 dní; OTE endpoint čtvrthodinový s fallbackem na hodinový.
- **Grafy s osami a oknem** (v0.7.2): graf výkonu na dashboardu má osy čas/výkon a tlačítka +/− pro zpětné okno 6 h–30 dní (agregace přes time_bucket); spotová křivka má popisky os (hodiny / Kč/MWh).
- **Cenová křivka dnes+zítra** (v0.7.1): vizualizace hodinových spotových cen s vyznačením, kdy by automatika nabíjela/vybíjela; „zpět na živý feed" stáhne cenu okamžitě.
- **Vybíjení do sítě dle ceny** (v0.7): pravidlo „prodávej draze" (ECO_DISCHARGE) vedle „nakupuj levně"; engine agreguje pravidla na zařízení (žádný konflikt), spodní SoC chrání baterii.
- **Lokality a párování** (v0.6.1): správa lokalit, vazba zařízení→lokalita a uživatel↔lokalita (M:N), profil uživatele (telefon, poznámka).
- React SPA frontend (přihlášení, dashboard, řízení, automatizace, lokality, správa modulů a uživatelů, změna hesla).

### Role a oprávnění
- **viewer** — `read`: jen dashboard.
- **operator** — `read` + `control`: dashboard + Řízení.
- **admin** — vše + Moduly + Uživatelé.

### Přihlášení

Při prvním nasazení `deploy.sh` vytvoří admina a vypíše heslo (`admin / <heslo>`).
Role: **viewer** (jen čtení), **operator** (čtení + budoucí řízení), **admin** (vše + správa uživatelů).
Změnit/založit uživatele: web → Uživatelé (jen admin).

## Rychlý start (bez DB, bez VPN)

Rozjede celý sběr v mock režimu (simulovaný měnič) a vypisuje na stdout:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
cp devices.example.yaml devices.yaml   # uprav: adapter: mock
make run-mock
```

## Celý stack (TimescaleDB + API + web)

```bash
cp devices.example.yaml devices.yaml
docker compose -f infra/docker-compose.yml up -d --build
# web:  http://localhost:8080
# API:  http://localhost:8080/api/health   (přes nginx proxy)
```

## Nasazení na Debian stroj (např. 192.168.6.209)

Na čistém Debianu stačí dva skripty:

```bash
# 1) Instalace Dockeru (jednorázově, jako root)
sudo bash scripts/setup-debian.sh
#    pak se odhlas a přihlas, ať se projeví členství ve skupině docker

# 2) Nasazení stacku
bash scripts/deploy.sh
```

`deploy.sh` při prvním běhu vytvoří `devices.yaml` v **mock** režimu (běží hned, bez VPN) a `.env` s náhodným heslem databáze. Po nahození:

- Web: `http://192.168.6.209:8080`
- API zdraví: `http://192.168.6.209:8080/api/health`
- Swagger UI: `http://192.168.6.209:8000/docs`

Služby mají `restart: unless-stopped`, takže se po rebootu stroje samy nahodí.

```bash
docker compose -f infra/docker-compose.yml ps                  # stav
docker compose -f infra/docker-compose.yml logs -f collector   # živé logy sběru
docker compose -f infra/docker-compose.yml down                # zastavit
```

### Upgrade běžícího pilotu na novou verzi

```bash
# rozbal nový tar přes /opt/ems, pak:
cd /opt/ems
docker compose -f infra/docker-compose.yml up -d --build
```

DB volume zůstává; tabulka `users` se vytvoří automaticky při startu API.
Pokud `.env` nemá `EMS_JWT_SECRET`/`EMS_ADMIN_PASSWORD`, doplň je (nebo smaž `.env` a nech `deploy.sh` vygenerovat nové).

## Připojení reálného měniče

1. Zprovozni síťový přístup k domácí síti (zatím OpenVPN, později edge HW — Raspberry).
2. Zjisti lokální IP měničů a ověř komunikaci:
   ```bash
   python scripts/discover.py 192.168.1.10        # UDP 8899
   python scripts/discover.py 192.168.1.10 --port 502   # Modbus TCP (LAN dongle V2)
   ```
3. Sensor ID z výpisu zkontroluj proti `ems/adapters/goodwe/mapping.py` (případně doplň).
4. V `devices.yaml` přepni `adapter: mock` → `goodwe` a doplň `host`.

## Architektura v kostce

```
[zařízení] → adaptér → kanonický model → sink → TimescaleDB → API → web/mobil
```

- **Jádro** (`ems/core`) — kanonický model + rozhraní adaptéru/sinku. Nezná žádný konkrétní protokol.
- **Adaptéry** (`ems/adapters`) — překlad nativního protokolu do modelu. Goodwe (ET i DT) + mock.
- **Sinky** (`ems/sinks`) — kam se zapisuje: stdout (dev), TimescaleDB (provoz). Místo pro pozdější message bus.
- **Kolektor** (`ems/collector`) — pollovací smyčka, odolná vůči chybě jednoho zařízení.
- **API** (`ems/api`) — REST nad uloženou telemetrií.
- **Web** (`web`) — dashboard. Mobil (Android/iOS) přijde později nad stejným API.

## Přidání nového typu zdroje

1. Nový adaptér v `ems/adapters/<typ>/` implementující `TelemetryAdapter` (connect/read/close).
2. Mapování nativních veličin na `Metric` z kanonického modelu.
3. Zaregistruj jméno adaptéru v `ems/collector/config.py:build_adapter`.

Jádro ani úložiště se nemění.

## Struktura

```
ems/
  core/        kanonický model + rozhraní
  adapters/    goodwe (adapter, mapping, mock)
  sinks/       stdout, timescale
  collector/   config + pollovací smyčka
  api/         FastAPI
web/           dashboard
infra/         docker-compose, DB schéma, Dockerfile
scripts/       discover.py
docs/          architektura, ADR, doménový katalog
```

## Licence

MIT (placeholder — uprav dle potřeby).
