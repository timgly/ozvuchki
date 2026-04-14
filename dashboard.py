#!/usr/bin/env python3
"""
Озвучки — локальный веб-дашборд с вкладками.
http://localhost:8420
"""

import http.server
import json
import webbrowser
from pathlib import Path
from sync_sheet import (
    SHEETS, COLUMNS, check_parts, scan_projects, to_fs,
    load_deadlines, get_deadline, format_date, is_overdue, norm,
)

PORT = 8420
BASE = Path(__file__).resolve().parent


def scan(sheet_idx: int) -> dict:
    cfg = SHEETS[sheet_idx]
    folder = cfg["folder"]
    order = cfg["order"]
    tab = cfg["tab"]

    projects = scan_projects(folder, order)
    deadlines = load_deadlines()

    rows = []
    for project in projects:
        cells = {}
        parts_info = {}
        deadlines_info = {}
        for col in COLUMNS[1:]:
            complete, found, total = check_parts(project, col, folder)
            cells[col] = complete
            parts_info[col] = {"found": found, "total": total}
            dl = get_deadline(deadlines, tab, project, col)
            deadlines_info[col] = {
                "date": format_date(dl) if dl else None,
                "overdue": is_overdue(dl) if dl else False,
            } if dl else None

        all_stages = all(cells[c] for c in COLUMNS[1:-1])
        cells["Готово"] = all_stages or cells.get("Готово", False)
        rows.append({
            "name": project,
            "cells": cells,
            "parts": parts_info,
            "deadlines": deadlines_info,
        })

    return {"columns": COLUMNS, "rows": rows, "tab": tab}


HTML = """\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Озвучки — Дашборд</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2a2d3a;
    --text: #e4e6f0;
    --text-dim: #8b8fa3;
    --green: #22c55e;
    --green-bg: #0a2e1a;
    --green-glow: rgba(34, 197, 94, 0.15);
    --yellow: #eab308;
    --yellow-bg: #1c1a0a;
    --red-bg: #1c1012;
    --red-dot: #6b3040;
    --accent: #6366f1;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 32px;
  }
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20px;
  }
  .header h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.3px; }
  .header .status { font-size: 13px; color: var(--text-dim); }
  .header .status .dot {
    display: inline-block; width: 7px; height: 7px;
    border-radius: 50%; background: var(--green);
    margin-right: 5px; animation: pulse 2s infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  .tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 20px;
  }
  .tab {
    padding: 8px 20px;
    border-radius: 8px 8px 0 0;
    background: var(--surface);
    border: 1px solid var(--border);
    border-bottom: none;
    color: var(--text-dim);
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    transition: all 0.2s;
  }
  .tab:hover { color: var(--text); }
  .tab.active {
    background: var(--bg);
    color: var(--accent);
    border-color: var(--accent);
    border-bottom: 2px solid var(--bg);
    margin-bottom: -1px;
  }
  .table-wrap {
    overflow-x: auto;
    border-radius: 0 12px 12px 12px;
    border: 1px solid var(--border);
    background: var(--surface);
    max-height: 80vh;
    overflow-y: auto;
  }
  table { width: 100%; border-collapse: collapse; min-width: 700px; }
  th {
    text-align: left; padding: 14px 18px; font-size: 12px;
    font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;
    color: var(--text-dim); border-bottom: 1px solid var(--border);
    background: var(--surface); position: sticky; top: 0;
    white-space: nowrap; z-index: 1;
  }
  td {
    padding: 10px 16px; border-bottom: 1px solid var(--border);
    font-size: 13px; transition: background 0.3s;
  }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(255,255,255,0.02); }
  .name-cell { font-weight: 500; white-space: nowrap; }
  .status-cell { text-align: center; width: 100px; }
  .chip {
    display: inline-block; padding: 3px 12px;
    border-radius: 20px; font-size: 11px; font-weight: 500;
  }
  .chip.done { background: var(--green-bg); color: var(--green); box-shadow: 0 0 12px var(--green-glow); }
  .chip.pending { background: var(--red-bg); color: var(--red-dot); }
  .chip.partial { background: var(--yellow-bg); color: var(--yellow); }
  .chip.deadline { background: var(--yellow-bg); color: var(--yellow); }
  .chip.overdue { background: #2a1015; color: #f87171; }
  .empty { text-align: center; padding: 60px 20px; color: var(--text-dim); }
  .summary {
    margin-top: 16px; display: flex; gap: 16px;
    font-size: 13px; color: var(--text-dim);
  }
  .summary span { color: var(--text); font-weight: 600; }
</style>
</head>
<body>
<div class="header">
  <h1>Озвучки</h1>
  <div class="status"><span class="dot"></span>Автообновление каждые 3 сек</div>
</div>
<div class="tabs" id="tabs"></div>
<div class="table-wrap" id="root"></div>
<div class="summary" id="summary"></div>

<script>
const TABS = TAB_LIST_PLACEHOLDER;
let currentTab = 0;

function buildTabs() {
  document.getElementById('tabs').innerHTML = TABS.map((t, i) =>
    `<div class="tab ${i===currentTab?'active':''}" onclick="switchTab(${i})">${t}</div>`
  ).join('');
}

function switchTab(i) {
  currentTab = i;
  buildTabs();
  load();
}

async function load() {
  const res = await fetch('/api/status?sheet=' + currentTab);
  const data = await res.json();
  render(data);
}

function render(data) {
  const {columns, rows} = data;
  if (!rows.length) {
    document.getElementById('root').innerHTML =
      '<div class="empty">Нет проектов</div>';
    document.getElementById('summary').innerHTML = '';
    return;
  }
  let html = '<table><thead><tr>';
  columns.forEach(c => html += `<th>${c}</th>`);
  html += '</tr></thead><tbody>';

  let totalCells = 0, doneCells = 0;
  rows.forEach(row => {
    html += '<tr>';
    html += `<td class="name-cell">${row.name}</td>`;
    columns.slice(1).forEach(col => {
      const ok = row.cells[col];
      const p = row.parts && row.parts[col];
      const dl = row.deadlines && row.deadlines[col];
      const found = p ? p.found : 0;
      const total = p ? p.total : 0;
      totalCells++;
      let cls, label;
      if (ok) { cls = 'done'; label = '✓'; doneCells++; }
      else if (dl && dl.overdue && found > 0) { cls = 'overdue'; label = `${found}/${total} ⚠ ${dl.date}`; }
      else if (dl && dl.overdue) { cls = 'overdue'; label = `⚠ ${dl.date}`; }
      else if (found > 0 && dl) { cls = 'partial'; label = `${found}/${total} до ${dl.date}`; }
      else if (found > 0) { cls = 'partial'; label = `${found}/${total}`; }
      else if (dl) { cls = 'deadline'; label = `до ${dl.date}`; }
      else { cls = 'pending'; label = '—'; }
      html += `<td class="status-cell"><span class="chip ${cls}">${label}</span></td>`;
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  document.getElementById('root').innerHTML = html;

  const pct = totalCells ? Math.round(doneCells / totalCells * 100) : 0;
  document.getElementById('summary').innerHTML =
    `Проектов: <span>${rows.length}</span> &nbsp;|&nbsp; Прогресс: <span>${doneCells}/${totalCells}</span> (<span>${pct}%</span>)`;
}

buildTabs();
load();
setInterval(load, 300000);
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/status"):
            idx = 0
            if "sheet=" in self.path:
                try:
                    idx = int(self.path.split("sheet=")[1])
                except ValueError:
                    pass
            idx = max(0, min(idx, len(SHEETS) - 1))
            data = json.dumps(scan(idx), ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(data.encode())
        else:
            tab_names = json.dumps([s["tab"] for s in SHEETS], ensure_ascii=False)
            html = HTML.replace("TAB_LIST_PLACEHOLDER", tab_names)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    server = http.server.HTTPServer(("", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Дашборд запущен: {url}")
    print(f"Листов: {len(SHEETS)}")
    for s in SHEETS:
        print(f"  • {s['tab']} → {s['folder']}")
    print("Ctrl+C для остановки")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
