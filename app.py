#!/usr/bin/env python3
"""
Озвучки — онлайн Flask-дашборд с загрузкой файлов и Google Sheets синхронизацией.
"""

import json
import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from sync_sheet import (
    BASE, COLUMNS, SHEETS, SYNC_INTERVAL,
    check_parts, scan_projects, sync_all,
    load_deadlines, get_deadline, format_date, is_overdue, to_fs,
)

app = Flask(__name__)


def get_scan_data(sheet_idx: int) -> dict:
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


@app.route("/")
def index():
    tabs = [s["tab"] for s in SHEETS]
    return render_template("index.html", tabs=json.dumps(tabs, ensure_ascii=False))


@app.route("/api/status")
def api_status():
    idx = request.args.get("sheet", 0, type=int)
    idx = max(0, min(idx, len(SHEETS) - 1))
    return jsonify(get_scan_data(idx))


@app.route("/api/upload", methods=["POST"])
def api_upload():
    sheet_idx = request.form.get("sheet", 0, type=int)
    project = request.form.get("project", "").strip()
    column = request.form.get("column", "").strip()
    file = request.files.get("file")

    if not project or not column or not file or column not in COLUMNS[1:-1]:
        return jsonify({"error": "Missing project, column, or file"}), 400

    sheet_idx = max(0, min(sheet_idx, len(SHEETS) - 1))
    folder = SHEETS[sheet_idx]["folder"]

    col_dir = folder / column
    col_dir.mkdir(parents=True, exist_ok=True)

    safe_project = to_fs(project)
    ext = Path(file.filename).suffix if file.filename else ""
    dest = col_dir / f"{safe_project}{ext}"
    file.save(str(dest))

    return jsonify({"ok": True, "saved": str(dest.name)})


@app.route("/api/sheets")
def api_sheets():
    return jsonify([s["tab"] for s in SHEETS])


def background_sync():
    """Background thread: sync to Google Sheets every SYNC_INTERVAL seconds."""
    time.sleep(5)
    while True:
        try:
            done, total = sync_all()
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] Sync: {done}/{total}")
        except Exception as e:
            print(f"Sync error: {e}")
        time.sleep(SYNC_INTERVAL)


def start_background_sync():
    t = threading.Thread(target=background_sync, daemon=True)
    t.start()


start_background_sync()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8420))
    app.run(host="0.0.0.0", port=port, debug=False)
