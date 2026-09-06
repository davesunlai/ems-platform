// Export dat grafů do .xlsx — vždy podle AKTUÁLNÍHO zobrazení (skryté série se neexportují).
import * as XLSX from "xlsx";

export function exportRowsXlsx(filename, rows, sheet = "Data") {
  if (!rows || !rows.length) return;
  const ws = XLSX.utils.json_to_sheet(rows);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, sheet.slice(0, 31));
  const day = new Date().toISOString().slice(0, 10);
  XLSX.writeFile(wb, `${filename}-${day}.xlsx`);
}

// Sloučí víc časových řad do řádků {Čas, <label>: hodnota, ...} podle timestampu.
export function mergeSeriesRows(seriesList) {
  const byT = new Map();
  for (const s of seriesList) {
    for (const p of s.points) {
      const t = new Date(p.t).getTime();
      if (!byT.has(t)) byT.set(t, { _t: t, "Čas": new Date(t).toLocaleString("cs-CZ") });
      byT.get(t)[s.col] = p.v;
    }
  }
  return [...byT.values()].sort((a, b) => a._t - b._t).map(({ _t, ...r }) => r);
}
