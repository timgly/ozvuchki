#!/usr/bin/env python3
"""
Озвучки — онлайн Flask-дашборд.
Читает статусы из Google Sheets (куда их пишет локальный sync_sheet.py).
Поддерживает загрузку файлов через веб → сразу отмечает в Google Sheets.
"""

import json
import os
import re
import threading
import time
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from sync_sheet import (
    COLUMNS, SHEETS, SPREADSHEET_ID, SYNC_INTERVAL,
    connect, format_date, is_overdue, parse_date_from_cell,
    to_fs, check_parts, scan_projects,
)

app = Flask(__name__)

_sheet_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 60


def _read_sheet_data(sheet_idx: int) -> dict:
    """Read one tab from Google Sheets and parse into dashboard format."""
    cfg = SHEETS[sheet_idx]
    tab = cfg["tab"]
    order = cfg["order"]

    spreadsheet = connect()
    ws = spreadsheet.worksheet(tab)
    all_values = ws.get_all_values()

    if len(all_values) < 2:
        return {"columns": COLUMNS, "rows": [], "tab": tab}

    header = all_values[0]
    col_map = {}
    for i, h in enumerate(header):
        if h in COLUMNS:
            col_map[h] = i

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
            if dl_iso:
                deadlines_info[col] = {
                    "date": format_date(dl_iso),
                    "overdue": is_overdue(dl_iso),
                }
            else:
                deadlines_info[col] = None

        rows.append({
            "name": project,
            "cells": cells,
            "parts": parts_info,
            "deadlines": deadlines_info,
        })

    return {"columns": COLUMNS, "rows": rows, "tab": tab}


def get_cached_data(sheet_idx: int) -> dict:
    """Return cached sheet data, refresh if older than CACHE_TTL seconds."""
    now = time.time()
    with _cache_lock:
        entry = _sheet_cache.get(sheet_idx)
        if entry and now - entry["ts"] < CACHE_TTL:
            return entry["data"]

    data = _read_sheet_data(sheet_idx)
    with _cache_lock:
        _sheet_cache[sheet_idx] = {"data": data, "ts": time.time()}
    return data


def invalidate_cache(sheet_idx: int):
    with _cache_lock:
        _sheet_cache.pop(sheet_idx, None)


@app.route("/")
def index():
    tabs = [s["tab"] for s in SHEETS]
    return render_template("index.html", tabs=json.dumps(tabs, ensure_ascii=False))


@app.route("/api/status")
def api_status():
    idx = request.args.get("sheet", 0, type=int)
    idx = max(0, min(idx, len(SHEETS) - 1))
    try:
        return jsonify(get_cached_data(idx))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload a file → save to server folder → trigger local sync → update sheet."""
    sheet_idx = request.form.get("sheet", 0, type=int)
    project = request.form.get("project", "").strip()
    column = request.form.get("column", "").strip()
    file = request.files.get("file")

    if not project or not column or not file or column not in COLUMNS[1:-1]:
        return jsonify({"error": "Missing project, column, or file"}), 400

    sheet_idx = max(0, min(sheet_idx, len(SHEETS) - 1))
    cfg = SHEETS[sheet_idx]
    folder = cfg["folder"]

    col_dir = folder / column
    col_dir.mkdir(parents=True, exist_ok=True)
    names_dir = folder / "Название" / to_fs(project)
    names_dir.mkdir(parents=True, exist_ok=True)

    safe_project = to_fs(project)
    ext = Path(file.filename).suffix if file.filename else ""
    dest = col_dir / f"{safe_project}{ext}"
    file.save(str(dest))

    try:
        from sync_sheet import sync_all
        sync_all()
        invalidate_cache(sheet_idx)
    except Exception as e:
        print(f"Post-upload sync error: {e}")

    return jsonify({"ok": True, "saved": str(dest.name)})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Force refresh: clear cache so next request reads fresh data from Google Sheets."""
    with _cache_lock:
        _sheet_cache.clear()
    return jsonify({"ok": True})


@app.route("/api/sheets")
def api_sheets():
    return jsonify([s["tab"] for s in SHEETS])


def background_refresh():
    """Periodically refresh the cache so dashboard always has fresh data."""
    time.sleep(10)
    while True:
        for i in range(len(SHEETS)):
            try:
                data = _read_sheet_data(i)
                with _cache_lock:
                    _sheet_cache[i] = {"data": data, "ts": time.time()}
            except Exception as e:
                print(f"Cache refresh error (sheet {i}): {e}")
        time.sleep(CACHE_TTL)


threading.Thread(target=background_refresh, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8420))
    app.run(host="0.0.0.0", port=port, debug=False)
