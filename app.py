#!/usr/bin/env python3
"""
Озвучки — онлайн Flask-дашборд.
Читает статусы из Google Sheets (куда их пишет локальный sync_sheet.py).
"""

import json
import os
import re
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from sync_sheet import (
    COLUMNS, SHEETS, SYNC_INTERVAL,
    connect, format_date, is_overdue, parse_date_from_cell,
    to_fs,
)

app = Flask(__name__)

_sheet_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 300


def _read_all_sheets() -> dict:
    """Read ALL tabs in one connection (1 connect instead of 3)."""
    result = {}
    try:
        spreadsheet = connect()
        for i, cfg in enumerate(SHEETS):
            tab = cfg["tab"]
            try:
                ws = spreadsheet.worksheet(tab)
                all_values = ws.get_all_values()
                result[i] = _parse_sheet(all_values, tab)
            except Exception as e:
                print(f"Read error ({tab}): {e}")
                result[i] = {"columns": COLUMNS, "rows": [], "tab": tab}
    except Exception as e:
        print(f"Connect error: {e}")
    return result


def _parse_sheet(all_values: list, tab: str) -> dict:
    if len(all_values) < 2:
        return {"columns": COLUMNS, "rows": [], "tab": tab}

    header = all_values[0]
    col_map = {h: i for i, h in enumerate(header) if h in COLUMNS}

    rows = []
    for row_data in all_values[1:]:
        if not row_data or not row_data[0].strip():
            continue
        project = row_data[0].strip()

        cells = {}
        parts_info = {}
        deadlines_info = {}

        for col in COLUMNS[1:]:
            idx = col_map.get(col)
            cell_val = row_data[idx].strip() if idx is not None and idx < len(row_data) else ""

            done = cell_val == "✓"
            found, total = 0, 0
            dl_iso = None

            if not done and cell_val:
                parts_m = re.match(r"(\d+)/(\d+)", cell_val)
                if parts_m:
                    found, total = int(parts_m.group(1)), int(parts_m.group(2))
                dl_iso = parse_date_from_cell(cell_val)

            cells[col] = done
            parts_info[col] = {"found": found, "total": total}
            deadlines_info[col] = {
                "date": format_date(dl_iso),
                "overdue": is_overdue(dl_iso),
            } if dl_iso else None

        rows.append({
            "name": project,
            "cells": cells,
            "parts": parts_info,
            "deadlines": deadlines_info,
        })

    return {"columns": COLUMNS, "rows": rows, "tab": tab}


def get_cached_data(sheet_idx: int) -> dict:
    with _cache_lock:
        entry = _sheet_cache.get(sheet_idx)
        if entry:
            return entry
    return {"columns": COLUMNS, "rows": [], "tab": SHEETS[sheet_idx]["tab"]}


def refresh_cache():
    data = _read_all_sheets()
    with _cache_lock:
        _sheet_cache.update(data)


@app.route("/")
def index():
    tabs = [s["tab"] for s in SHEETS]
    return render_template("index.html", tabs=json.dumps(tabs, ensure_ascii=False))


@app.route("/api/status")
def api_status():
    idx = request.args.get("sheet", 0, type=int)
    idx = max(0, min(idx, len(SHEETS) - 1))
    return jsonify(get_cached_data(idx))


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
    (folder / "Название" / to_fs(project)).mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix if file.filename else ""
    dest = col_dir / f"{to_fs(project)}{ext}"
    file.save(str(dest))

    try:
        from sync_sheet import sync_all
        sync_all()
        refresh_cache()
    except Exception as e:
        print(f"Post-upload sync error: {e}")

    return jsonify({"ok": True, "saved": str(dest.name)})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    threading.Thread(target=refresh_cache, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/sheets")
def api_sheets():
    return jsonify([s["tab"] for s in SHEETS])


def background_refresh():
    refresh_cache()
    while True:
        time.sleep(CACHE_TTL)
        try:
            refresh_cache()
            print(f"[{time.strftime('%H:%M:%S')}] Cache refreshed")
        except Exception as e:
            print(f"Cache refresh error: {e}")


threading.Thread(target=background_refresh, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8420))
    app.run(host="0.0.0.0", port=port, debug=False)
