#!/usr/bin/env python3
"""
Озвучки — онлайн Flask-дашборд.
Читает статусы из Google Sheets. Устойчив к холодному старту и сбоям API.
"""

import json
import os
import re
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from sync_sheet import (
    COLUMNS, SHEETS,
    connect, format_date, is_overdue, parse_date_from_cell,
    to_fs,
)

app = Flask(__name__)

_sheet_cache: dict = {}
_cache_lock = threading.Lock()
_bootstrap_lock = threading.Lock()
CACHE_TTL = 300


def _empty_sheet(tab: str) -> dict:
    return {"columns": COLUMNS, "rows": [], "tab": tab}


def _read_one_tab(spreadsheet, i: int, cfg: dict) -> dict:
    """Read one worksheet; retry if sheet should have rows but API returned empty."""
    tab = cfg["tab"]
    expected = len(cfg.get("order") or [])
    need_rows = expected > 15
    last = _empty_sheet(tab)

    for attempt in range(3):
        try:
            ws = spreadsheet.worksheet(tab)
            last = _parse_sheet(ws.get_all_values(), tab)
        except Exception as e:
            print(f"Read error ({tab}) attempt {attempt + 1}: {e}")
            last = _empty_sheet(tab)
        nrows = len(last.get("rows") or [])
        if not need_rows or nrows > 0 or attempt == 2:
            return last
        print(f"Retry read {tab}: 0 rows (expected ~{expected}), attempt {attempt + 1}")
        time.sleep(2.0)
    return last


def _read_all_sheets() -> dict | None:
    """Read all tabs. Returns None if Google connection failed (keep old cache)."""
    try:
        spreadsheet = connect()
    except Exception as e:
        print(f"Connect error: {e}")
        return None

    result: dict = {}
    for i, cfg in enumerate(SHEETS):
        result[i] = _read_one_tab(spreadsheet, i, cfg)
        time.sleep(0.35)
    return result


def _parse_sheet(all_values: list, tab: str) -> dict:
    if len(all_values) < 2:
        return _empty_sheet(tab)

    header = all_values[0]
    col_map = {h: idx for idx, h in enumerate(header) if h in COLUMNS}

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
            deadlines_info[col] = (
                {"date": format_date(dl_iso), "overdue": is_overdue(dl_iso)}
                if dl_iso
                else None
            )

        rows.append({
            "name": project,
            "cells": cells,
            "parts": parts_info,
            "deadlines": deadlines_info,
        })

    return {"columns": COLUMNS, "rows": rows, "tab": tab}


def _cache_fully_populated() -> bool:
    return len(_sheet_cache) >= len(SHEETS) and all(
        i in _sheet_cache for i in range(len(SHEETS))
    )


def refresh_cache() -> None:
    """Fetch from Google Sheets. On failure, keep previous cache if any."""
    global _sheet_cache
    new_data = _read_all_sheets()
    if new_data is None:
        with _cache_lock:
            if not _sheet_cache:
                for i in range(len(SHEETS)):
                    _sheet_cache[i] = _empty_sheet(SHEETS[i]["tab"])
        return
    all_empty = all(not v.get("rows") for v in new_data.values())
    with _cache_lock:
        had_rows = any(len(v.get("rows") or []) > 0 for v in _sheet_cache.values())
        if all_empty and had_rows:
            print("refresh_cache: skip replacing good cache with all-empty read")
            return
        _sheet_cache.update(new_data)


def ensure_cache() -> None:
    """First request / cold worker: load synchronously (no empty flash)."""
    if _cache_fully_populated():
        return
    with _bootstrap_lock:
        if _cache_fully_populated():
            return
        refresh_cache()


def get_cached_data(sheet_idx: int) -> dict:
    ensure_cache()
    with _cache_lock:
        return _sheet_cache.get(sheet_idx) or _empty_sheet(SHEETS[sheet_idx]["tab"])


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
    """Synchronous refresh so UI never reads stale empty during reload."""
    refresh_cache()
    return jsonify({"ok": True})


@app.route("/api/sheets")
def api_sheets():
    return jsonify([s["tab"] for s in SHEETS])


def background_refresh():
    time.sleep(15)
    while True:
        try:
            refresh_cache()
            print(f"[{time.strftime('%H:%M:%S')}] Cache refreshed")
        except Exception as e:
            print(f"Cache refresh error: {e}")
        time.sleep(CACHE_TTL)


threading.Thread(target=background_refresh, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8420))
    app.run(host="0.0.0.0", port=port, debug=False)
