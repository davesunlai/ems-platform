import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

const KEY = "tera_onboarded_v1";

export function tourSeen() {
  try { return localStorage.getItem(KEY) === "1"; } catch { return true; }
}

export default function Tour({ open, onClose }) {
  const nav = useNavigate();
  const { has } = useAuth();
  const [i, setI] = useState(0);

  const steps = [
    { title: "Vítej v TERA EMS",
      body: "Krátký průvodce tě provede hlavními částmi systému. Můžeš ho kdykoli přeskočit a později znovu spustit tlačítkem „Průvodce“ nahoře v liště." },
    { title: "Dashboard", route: "/",
      body: "Přehled výroby FVE, spotřeby, baterie a sítě v reálném čase. Klikni na libovolnou dlaždici (třeba „Baterie SoC“) a graf se přepne na její průběh. Šipkami ◀ ▶ posouváš čas, tlačítky − / + měníš délku okna." },
    { title: "Výstrahy", route: "/",
      body: "Vpravo nahoře je trojúhelník ⚠ s počtem výstrah – zatím plánované odstávky elektřiny pro tvoje lokality. Po kliknutí uvidíš detaily." },
    has("control") && { title: "Spínací kontakty", route: "/contact",
      body: "Spínané výstupy zařízení podle událostí. Teď suchý kontakt měniče podle stavu nabití (SoC) s hysterezí; postupně přibydou další zařízení a spouštěče." },
    has("admin") && { title: "Automatizace", route: "/automation",
      body: "Pravidla pro nabíjení a vybíjení baterie podle spotové ceny a SoC. Nabíjení má přednost před vybíjením, soc_min chrání baterii." },
    has("admin") && { title: "Zúčtování", route: "/billing",
      body: "Zúčtovací období, měsíční energie a hlídání přetoků do sítě vůči limitu." },
    has("admin") && { title: "Lokality a odstávky", route: "/localities",
      body: "Správa lokalit, přiřazení zařízení a uživatelů. U každé lokality zadáš pro plánované odstávky ČEZ EAN, číslo elektroměru nebo adresu – dotaz použije první vyplněné (EAN → elektroměr → adresa)." },
    has("admin") && { title: "Moduly a Uživatelé", route: "/modules",
      body: "Připojená zařízení (Moduly) a správa uživatelů s rolemi: prohlížeč (čte), operátor (+ řízení), admin (+ správa)." },
    { title: "Hotovo", route: "/change-password",
      body: "Heslo si změníš kdykoli tady. To je vše – průvodce kdykoli spustíš znovu tlačítkem „Průvodce“ nahoře." },
  ].filter(Boolean);

  useEffect(() => { if (open) setI(0); }, [open]);

  useEffect(() => {
    if (!open) return;
    const r = steps[i]?.route;
    if (r) nav(r);
    let el = null;
    if (r) el = document.querySelector(`header .nav a[href="${r}"]`);
    if (el) { el.style.outline = "2px solid var(--blue, #58a6ff)"; el.style.borderRadius = "6px"; el.style.outlineOffset = "2px"; }
    return () => { if (el) { el.style.outline = ""; el.style.outlineOffset = ""; } };
  }, [open, i]); // eslint-disable-line

  if (!open) return null;
  const step = steps[i];
  const last = i === steps.length - 1;
  const finish = () => { try { localStorage.setItem(KEY, "1"); } catch { /* ignore */ } onClose(); };

  return (
    <div onClick={finish}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.55)", zIndex: 100,
        display: "flex", alignItems: "flex-end", justifyContent: "center", padding: 24 }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ width: "min(560px, 96vw)", background: "var(--panel, #1c1c24)",
          border: "1px solid var(--border, #2a2a35)", borderRadius: 14, padding: "20px 22px",
          boxShadow: "0 16px 50px rgba(0,0,0,.5)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <h3 style={{ margin: 0, flex: 1 }}>{step.title}</h3>
          <span className="muted" style={{ fontSize: 12 }}>{i + 1} / {steps.length}</span>
          <button className="linkx" onClick={finish} title="Zavřít" style={{ fontSize: 18 }}>×</button>
        </div>
        <p style={{ fontSize: 14, lineHeight: 1.55, marginTop: 10 }}>{step.body}</p>
        <div style={{ display: "flex", gap: 5, margin: "14px 0 2px" }}>
          {steps.map((_, n) => (
            <span key={n} style={{ height: 6, flex: 1, borderRadius: 3,
              background: n <= i ? "var(--blue, #58a6ff)" : "var(--border, #2a2a35)" }} />
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button className="btn" onClick={finish}>Přeskočit</button>
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={() => setI((x) => Math.max(0, x - 1))} disabled={i === 0}>Zpět</button>
          {last
            ? <button className="btn primary" onClick={finish}>Hotovo</button>
            : <button className="btn primary" onClick={() => setI((x) => Math.min(steps.length - 1, x + 1))}>Další</button>}
        </div>
      </div>
    </div>
  );
}
