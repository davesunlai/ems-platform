// 🖥 Servisní konzole EMSBOXu (xterm ⇄ WS ⇄ agent PTY). Admin-only, auditováno.
import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { getToken } from "../api";

export default function BoxConsole({ box, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const term = new Terminal({ fontSize: 13, cursorBlink: true,
      theme: { background: "#0d1117" } });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(ref.current);
    fit.fit();
    const token = getToken() || "";
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/api/emsboxes/${box.id}/console/ws?token=${encodeURIComponent(token)}`);
    ws.onmessage = (e) => { try { const m = JSON.parse(e.data); if (m.t === "o") term.write(m.d); } catch {} };
    ws.onclose = () => term.write("\r\n\x1b[33m[spojení ukončeno]\x1b[0m\r\n");
    term.onData((d) => { if (ws.readyState === 1) ws.send(JSON.stringify({ t: "i", d })); });
    const sendSize = () => { if (ws.readyState === 1) ws.send(JSON.stringify({ t: "r", c: term.cols, r: term.rows })); };
    ws.onopen = sendSize;
    const onRes = () => { fit.fit(); sendSize(); };
    window.addEventListener("resize", onRes);
    return () => { window.removeEventListener("resize", onRes); try { ws.close(); } catch {} term.dispose(); };
  }, [box.id]);
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 60,
                                    display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()} className="panel"
           style={{ width: "min(940px, 96vw)", height: "min(560px, 85vh)", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 6 }}>
          <b>🖥 Konzole — {box.name || box.id} <span className="muted" style={{ fontSize: 12 }}>(shell kontejneru agenta · síť hosta · nmcli přes D-Bus · auditováno)</span></b>
          <button className="btn" style={{ marginLeft: "auto", padding: "3px 10px" }} onClick={onClose}>zavřít</button>
        </div>
        <div ref={ref} style={{ flex: 1, minHeight: 0 }} />
      </div>
    </div>
  );
}
