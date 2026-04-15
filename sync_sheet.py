#!/usr/bin/env python3
"""
Озвучки — синхронизация папок → Google Sheets (мультилист).

Каждый лист = отдельная папка на диске со своей структурой.
Дедлайны вводятся прямо в Google Sheets (формат: 20.04 или 20.04.2026).

Запуск: python sync_sheet.py
"""

import json
import os
import re
import time
import sys
import unicodedata
from datetime import date
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "105PyoJYJSMP8Xk9nnZo4MVz7YEvGfGMZKZXJWluOkjA"

BASE = Path(__file__).resolve().parent

COLUMNS = [
    "Название",
    "Перевод",
    "Озвучка",
    "Аудио-монтаж",
    "Визуализация",
    "Видео-монтаж",
    "Готово",
]

SYNC_INTERVAL = 300  # 5 минут

# --- Sheet configs ---
# Each sheet: folder on disk, tab name in Google, ordered project list

SHEET1_ORDER = [
    "Эмпедокл", "Брейгель", "Форсман", "Батлер", "Дом Гитлера",
    "М. Кюри", "Воннегут", "Маркес", "Гендель", "Оппенгеймер",
    "Моби Дик", "Эриксон", "Адам Кадмон", "Элла Фицджеральд",
    "Стендинг", "Вальд", "Пифагор", "С. Кёльт", "Че Гевара",
    "Кафка", "Ричард Бах", "Тэдли", "Спиноза", "Каспар",
]

SHEET2_ORDER = [
    "Альберт Эйнштейн - 1/5", "Пауло Коэльо - 1/2",
    "Ральф Уолдо Эмерсон", "Альберт Эйнштейн - 2/5",
    "Теодор Рузвельт", "Хелен Келлер - 1/2", "Генри Форд - 1/2",
    "Чарльз Кингсли", "Альберт Эйнштейн - 3/5",
    "Альберт Эйнштейн - 4/5", "Борис Пастернак",
    "Генри Уорд Бичер", "Уильям Джеймс", "Далай-лама - 1/3",
    "Аристотель - 1/2", "Пауло Коэльо - 2/2", "Наполеон Хилл",
    "Роберт Фрост", "Уэйн Гретцки", "Майкл Джордан",
    "Амелия Эрхарт", "Джон Леннон", "Чарльз Суиндолл",
    "Пабло Пикассо", "Майя Энджелоу - 1/2", "Фрэнк Синатра",
    "Винсент ван Гог - 1/2", "Аристотель - 2/2",
    "Генри Дэвид Торо", "Эрма Бомбек", "Конфуций - 1/3",
    "Анна Франк", "Далай-лама - 2/3", "Шерил Сэндберг",
    "Мария Кюри", "Лес Браун", "Боб Дилан",
    "Винсент ван Гог - 2/2", "Конфуций - 2/3", "Опра Уинфри",
    "Далай-лама - 3/3", "Майя Энджелоу - 2/2",
    "Элеонора Рузвельт", "Айн Рэнд", "Генри Форд - 2/2",
    "Бенджамин Франклин - 1/2", "Уоррен Баффет",
    "Уильям Шекспир", "Нельсон Мандела",
    "Бенджамин Франклин - 2/2", "Сенека", "Эрнест Хемингуэй",
    "Лао-цзы - 1/2", "Стивен Хокинг",
    "Альберт Эйнштейн - 5/5", "Хелен Келлер - 2/2",
    "Джефф Безос", "Марк Аврелий", "Бертран Рассел",
    "Ричард Бах - 1/2", "Альбер Камю - 1/2", "Элис Уокер",
    "Пико Айер", "Конфуций - 3/3", "Элберт Хаббард",
    "Оскар Уайльд - 1/2", "Фрэнсис Бэкон", "Жан-Жак Руссо",
    "Карл Лагерфельд", "Роберт Кийосаки", "Экхарт Толле",
    "Иоганн Вольфганг Гёте - 1/3", "Лорд Честерфилд",
    "Гарри Трумэн - 1/2", "Гарри Трумэн - 2/2",
    "Артур Шопенгауэр", "Плутарх", "Лев Толстой",
    "Иоганн Вольфганг Гёте - 2/3", "Ошо", "Карл Юнг",
    "Мэри Шелли", "Альбер Камю - 2/2", "Андре Жид",
    "Ричард Бах - 2/2", "Терри Пратчетт", "Джон Милтон",
    "Франклин Рузвельт", "Оскар Уайльд - 2/2",
    "Фридрих Ницше - 1/2", "Джо Диспенза", "Руми",
    "Анаис Нин - 1/2", "Редьярд Киплинг", "Лао-цзы - 2/2",
    "Анаис Нин - 2/2", "Иоганн Вольфганг Гёте - 3/3",
    "Курт Воннегут", "Чарльз Дарвин", "Фридрих Ницше - 2/2",
]

SHEETS = [
    {"tab": "Лист1", "folder": BASE, "order": SHEET1_ORDER},
    {"tab": "Лист2", "folder": BASE / "Лист2", "order": SHEET2_ORDER},
]

# --- Colors ---
GREEN = {"red": 0.72, "green": 0.88, "blue": 0.72}
YELLOW = {"red": 1.0, "green": 0.95, "blue": 0.8}
RED = {"red": 0.96, "green": 0.80, "blue": 0.80}
WHITE = {"red": 1, "green": 1, "blue": 1}
HEADER_BG = {"red": 0.85, "green": 0.92, "blue": 1.0}

# --- Date parsing ---
DATE_RE = re.compile(r"(\d{1,2})\.(\d{2})(?:\.(\d{4}))?")

# --- File parts matching ---
PARTS_PATTERNS = [
    re.compile(r"^(.+?)-(\d+):(\d+)(?:\..+)?$"),
    re.compile(r"^(.+?)\s*\((\d+)-(\d+)\)(?:\..+)?$"),
    re.compile(r"^(.+?)\s*\[(\d+)-(\d+)\](?:\..+)?$"),
]
SIMPLE_RE = re.compile(r"^(.+?)(?:\..+)?$")


def norm(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def to_fs(name: str) -> str:
    """Display name → filesystem name (/ → : on macOS)."""
    return name.replace("/", ":")


def to_display(name: str) -> str:
    """Filesystem name → display name (: → /)."""
    return name.replace(":", "/")


def parse_date_from_cell(cell_value: str) -> str | None:
    if not cell_value or cell_value == "✓":
        return None
    m = DATE_RE.search(cell_value)
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else date.today().year
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def format_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d.%m")
    except ValueError:
        return iso


def is_overdue(iso: str) -> bool:
    try:
        return date.fromisoformat(iso) < date.today()
    except ValueError:
        return False


def load_deadlines() -> dict:
    dl_file = BASE / "deadlines.json"
    if not dl_file.exists():
        return {}
    with open(dl_file, encoding="utf-8") as f:
        return json.load(f)


def save_deadlines(deadlines: dict):
    with open(BASE / "deadlines.json", "w", encoding="utf-8") as f:
        json.dump(deadlines, f, ensure_ascii=False, indent=2)


def get_deadline(deadlines: dict, sheet_tab: str, project: str, col: str) -> str | None:
    return deadlines.get(sheet_tab, {}).get(project, {}).get(col)


def connect():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        import json as _json
        info = _json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(
            BASE / "credentials.json", scopes=scopes,
        )
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def scan_projects(folder: Path, order: list[str]) -> list[str]:
    names_dir = folder / "Название"
    if not names_dir.is_dir():
        return []
    existing_fs = {norm(d.name) for d in names_dir.iterdir() if d.is_dir()}
    ordered = []
    for p in order:
        if norm(to_fs(p)) in existing_fs:
            ordered.append(p)
    for d in names_dir.iterdir():
        display = to_display(d.name)
        if d.is_dir() and norm(to_fs(display)) not in {norm(to_fs(p)) for p in ordered}:
            ordered.append(display)
    return ordered


def check_parts(project: str, column: str, folder: Path) -> tuple[bool, int, int]:
    col_dir = folder / column
    if not col_dir.is_dir():
        return False, 0, 0

    p = norm(to_fs(project))
    found_parts = set()
    total = 0
    has_simple_match = False

    for entry in col_dir.iterdir():
        name = norm(entry.name)
        if name.startswith("."):
            continue

        matched = False
        for pattern in PARTS_PATTERNS:
            m = pattern.match(name)
            if m:
                if norm(m.group(1).strip()) == p:
                    found_parts.add(int(m.group(2)))
                    total = max(total, int(m.group(3)))
                matched = True
                break

        if not matched:
            bare = SIMPLE_RE.match(name)
            if bare and norm(bare.group(1).strip()) == p:
                has_simple_match = True

    if total > 0:
        return len(found_parts) >= total, len(found_parts), total
    if has_simple_match:
        return True, 1, 1
    return False, 0, 0


def read_deadlines_from_sheet(ws) -> dict:
    try:
        all_values = ws.get_all_values()
    except Exception:
        return {}
    if len(all_values) < 2:
        return {}

    header = all_values[0]
    col_map = {i: h for i, h in enumerate(header) if h in COLUMNS[1:]}
    result = {}
    for row in all_values[1:]:
        if not row:
            continue
        project_name = row[0].strip()
        if not project_name:
            continue
        for i, col_name in col_map.items():
            if i < len(row):
                dl = parse_date_from_cell(row[i])
                if dl:
                    result.setdefault(project_name, {})[col_name] = dl
    return result


def sync_sheet(spreadsheet, sheet_cfg, deadlines):
    tab_name = sheet_cfg["tab"]
    folder = sheet_cfg["folder"]
    order = sheet_cfg["order"]

    try:
        ws = spreadsheet.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=200, cols=len(COLUMNS))

    projects = scan_projects(folder, order)
    if not projects:
        return 0, 0

    # Read dates from sheet before overwriting
    sheet_dl = read_deadlines_from_sheet(ws)
    for proj, cols in sheet_dl.items():
        for col, dl in cols.items():
            deadlines.setdefault(tab_name, {}).setdefault(proj, {})[col] = dl

    total_rows = len(projects) + 1
    total_cols = len(COLUMNS)

    header = [COLUMNS]
    rows_data = []
    cell_info = {}

    for project in projects:
        row = [project]
        statuses = {}

        for col in COLUMNS[1:]:
            complete, found, total = check_parts(project, col, folder)
            dl = get_deadline(deadlines, tab_name, project, col)
            statuses[col] = {
                "complete": complete, "found": found,
                "total": total, "deadline": dl,
            }

        all_stages = all(statuses[c]["complete"] for c in COLUMNS[1:-1])
        if all_stages:
            statuses["Готово"] = {"complete": True, "found": 1, "total": 1, "deadline": None}

        for col in COLUMNS[1:]:
            info = statuses[col]
            dl = info["deadline"]
            if info["complete"]:
                row.append("✓")
            elif info["found"] > 0:
                label = f'{info["found"]}/{info["total"]}'
                row.append(f'{label} до {format_date(dl)}' if dl else label)
            elif dl:
                row.append(f'до {format_date(dl)}')
            else:
                row.append("")

        cell_info[project] = statuses
        rows_data.append(row)

    all_data = header + rows_data
    ws.clear()
    ws.update(range_name=f"A1:{chr(64 + total_cols)}{total_rows}", values=all_data)

    formats = [{
        "range": f"A1:{chr(64 + total_cols)}1",
        "format": {
            "textFormat": {"bold": True},
            "backgroundColor": HEADER_BG,
            "horizontalAlignment": "CENTER",
        },
    }]

    done_count = 0
    total_cells = 0

    for row_idx, project in enumerate(projects, start=2):
        for col_idx, col in enumerate(COLUMNS[1:], start=2):
            info = cell_info[project][col]
            dl = info["deadline"]
            total_cells += 1

            if info["complete"]:
                bg = GREEN
                done_count += 1
            elif dl and is_overdue(dl):
                bg = RED
            elif dl:
                bg = YELLOW
            elif info["found"] > 0:
                bg = YELLOW
            else:
                bg = WHITE

            cell = f"{chr(64 + col_idx)}{row_idx}"
            formats.append({
                "range": cell,
                "format": {
                    "backgroundColor": bg,
                    "horizontalAlignment": "CENTER",
                },
            })

    ws.batch_format(formats)
    return done_count, total_cells


def sync_all():
    """Run one full sync cycle. Returns (done, total)."""
    spreadsheet = connect()
    deadlines = load_deadlines()
    total_done = 0
    total_all = 0
    for cfg in SHEETS:
        done, total = sync_sheet(spreadsheet, cfg, deadlines)
        total_done += done
        total_all += total
    save_deadlines(deadlines)
    return total_done, total_all


def main():
    print("Подключение к Google Sheets...")
    spreadsheet = connect()
    print(f"Подключено: {spreadsheet.title}")
    print(f"Листов: {len(SHEETS)}")
    for s in SHEETS:
        print(f"  • {s['tab']} → {s['folder']}")
    print(f"Синхронизация каждые {SYNC_INTERVAL} сек. Ctrl+C для остановки.\n")

    while True:
        try:
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] Синхронизация...", end="")
            deadlines = load_deadlines()
            total_done = 0
            total_all = 0
            for cfg in SHEETS:
                done, total = sync_sheet(spreadsheet, cfg, deadlines)
                total_done += done
                total_all += total
            save_deadlines(deadlines)
            print(f"  Прогресс: {total_done}/{total_all}")
        except gspread.exceptions.APIError as e:
            print(f"\n  Ошибка API: {e}")
        except KeyboardInterrupt:
            print("\nОстановлено.")
            sys.exit(0)
        except Exception as e:
            print(f"\n  Ошибка: {e}")

        try:
            time.sleep(SYNC_INTERVAL)
        except KeyboardInterrupt:
            print("\nОстановлено.")
            sys.exit(0)


if __name__ == "__main__":
    main()
