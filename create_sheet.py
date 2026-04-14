import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
gc = gspread.authorize(creds)

sh = gc.create("Озвучки")

ws = sh.sheet1
ws.update("A1:H1", [[
    "Название",
    "Перевод-1",
    "Перевод-2",
    "Озвучка",
    "Монтаж аудио",
    "Визуальная генерация",
    "Монтаж видео",
    "Готово",
]])

ws.format("A1:H1", {
    "textFormat": {"bold": True},
    "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0},
    "horizontalAlignment": "CENTER",
})

ws.set_basic_filter()

sh.share("", perm_type="anyone", role="writer")

print(f"Таблица создана: {sh.url}")
print(f"Сервисный аккаунт: {creds.service_account_email}")
print("Доступ: открыт для всех (по ссылке, с правом редактирования)")
