import json
import calendar
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


API_TIMEOUT = 35
MONTH_NAMES = [
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]
REPEAT_OPTIONS = {
    "none": ("Без повтора", None),
    "hour": ("Каждый час", "hour"),
    "day": ("Каждый день", "day"),
    "week": ("Каждую неделю", "week"),
    "month": ("Каждый месяц", "month"),
}
sessions = {}


def load_dotenv():
    env_file = Path(".env")
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()


def get_timezone():
    timezone_name = os.getenv("BOT_TIMEZONE", "Asia/Qyzylorda")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        offset = os.getenv("BOT_UTC_OFFSET", "+05:00")
        sign = -1 if offset.startswith("-") else 1
        hours, minutes = offset.lstrip("+-").split(":", 1)
        return timezone(sign * timedelta(hours=int(hours), minutes=int(minutes)))


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = {
    int(user_id.strip())
    for user_id in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if user_id.strip()
}
DATA_FILE = Path(os.getenv("REMINDERS_FILE", "reminders.json"))
TIMEZONE = get_timezone()
KV_REST_API_URL = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL")
KV_REST_API_TOKEN = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN")
REMINDERS_KEY = os.getenv("REMINDERS_KEY", "otbasy:reminders")
SESSIONS_KEY = os.getenv("SESSIONS_KEY", "otbasy:sessions")


def api(method, data=None):
    if not TOKEN:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in environment variables.")

    encoded = urllib.parse.urlencode(data or {}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        data=encoded,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload)
    return payload["result"]


def kv_enabled():
    return bool(KV_REST_API_URL and KV_REST_API_TOKEN)


def kv_command(command):
    request = urllib.request.Request(
        KV_REST_API_URL.rstrip("/"),
        data=json.dumps(command).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {KV_REST_API_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if "error" in payload and payload["error"]:
        raise RuntimeError(payload["error"])
    return payload.get("result")


def kv_get_json(key, default):
    if not kv_enabled():
        return default
    value = kv_command(["GET", key])
    if not value:
        return default
    return json.loads(value)


def kv_set_json(key, value):
    kv_command(["SET", key, json.dumps(value, ensure_ascii=False)])


def encode_session_value(value):
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, dict):
        return {str(key): encode_session_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [encode_session_value(item) for item in value]
    return value


def decode_session_value(value):
    if isinstance(value, dict):
        if "__datetime__" in value:
            return datetime.fromisoformat(value["__datetime__"])
        return {key: decode_session_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_session_value(item) for item in value]
    return value


def load_reminders():
    if kv_enabled():
        return kv_get_json(REMINDERS_KEY, [])
    if not DATA_FILE.exists():
        return []
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save_reminders(reminders):
    if kv_enabled():
        kv_set_json(REMINDERS_KEY, reminders)
        return
    DATA_FILE.write_text(
        json.dumps(reminders, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_sessions():
    if kv_enabled():
        raw_sessions = kv_get_json(SESSIONS_KEY, {})
    else:
        session_file = Path(os.getenv("SESSIONS_FILE", "sessions.json"))
        if not session_file.exists():
            return {}
        raw_sessions = json.loads(session_file.read_text(encoding="utf-8"))

    return {
        int(user_id): decode_session_value(session)
        for user_id, session in raw_sessions.items()
    }


def save_sessions(value):
    encoded = {
        str(user_id): encode_session_value(session)
        for user_id, session in value.items()
    }
    if kv_enabled():
        kv_set_json(SESSIONS_KEY, encoded)
        return

    session_file = Path(os.getenv("SESSIONS_FILE", "sessions.json"))
    session_file.write_text(
        json.dumps(encoded, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    api("sendMessage", data)


def edit_message(chat_id, message_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    api("editMessageText", data)


def answer_callback(callback_query_id, text=None):
    data = {"callback_query_id": callback_query_id}
    if text:
        data["text"] = text
    api("answerCallbackQuery", data)


def is_allowed(user_id):
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


def next_id(reminders):
    return max((item["id"] for item in reminders), default=0) + 1


def parse_when(text):
    value = text.strip().lower()
    now = datetime.now(TIMEZONE)

    relative = re.fullmatch(r"(?:через\s+)?(\d+)\s*(минут[уы]?|мин|m|час(?:а|ов)?|ч|h|дн(?:я|ей)?|д|d)", value)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        if unit in {"минуту", "минуты", "минут", "мин", "m"}:
            return now + timedelta(minutes=amount)
        if unit in {"час", "часа", "часов", "ч", "h"}:
            return now + timedelta(hours=amount)
        return now + timedelta(days=amount)

    formats = (
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y %H:%M",
        "%d.%m %H:%M",
        "%H:%M",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue

        if fmt == "%H:%M":
            parsed = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
            if parsed <= now:
                parsed += timedelta(days=1)
        elif fmt == "%d.%m %H:%M":
            parsed = parsed.replace(year=now.year)
            parsed = parsed.replace(tzinfo=TIMEZONE)
            if parsed <= now:
                parsed = parsed.replace(year=now.year + 1)
        else:
            parsed = parsed.replace(tzinfo=TIMEZONE)

        return parsed

    return None


def format_when(iso_value):
    return datetime.fromisoformat(iso_value).astimezone(TIMEZONE).strftime("%d.%m.%Y %H:%M")


def repeat_label(value):
    if not value:
        return "Без повтора"
    for label, option_value in REPEAT_OPTIONS.values():
        if option_value == value:
            return label
    return value


def active_reminders(reminders=None):
    reminders = load_reminders() if reminders is None else reminders
    return [
        item
        for item in reminders
        if not item.get("sent") or item.get("repeat")
    ]


def find_active_reminder(reminder_id):
    for index, item in enumerate(load_reminders()):
        if item["id"] == reminder_id and (not item.get("sent") or item.get("repeat")):
            return index, item
    return None, None


def add_month(value):
    month = value.month + 1
    year = value.year
    if month > 12:
        month = 1
        year += 1

    max_day = calendar.monthrange(year, month)[1]
    return value.replace(year=year, month=month, day=min(value.day, max_day))


def next_repeat_time(value, repeat):
    if repeat == "hour":
        return value + timedelta(hours=1)
    if repeat == "day":
        return value + timedelta(days=1)
    if repeat == "week":
        return value + timedelta(weeks=1)
    if repeat == "month":
        return add_month(value)
    return None


def calendar_keyboard(year, month):
    keyboard = [
        [
            {"text": "<", "callback_data": f"cal:prev:{year}:{month}"},
            {"text": f"{MONTH_NAMES[month]} {year}", "callback_data": "cal:noop"},
            {"text": ">", "callback_data": f"cal:next:{year}:{month}"},
        ],
        [
            {"text": "Пн", "callback_data": "cal:noop"},
            {"text": "Вт", "callback_data": "cal:noop"},
            {"text": "Ср", "callback_data": "cal:noop"},
            {"text": "Чт", "callback_data": "cal:noop"},
            {"text": "Пт", "callback_data": "cal:noop"},
            {"text": "Сб", "callback_data": "cal:noop"},
            {"text": "Вс", "callback_data": "cal:noop"},
        ],
    ]

    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append({"text": " ", "callback_data": "cal:noop"})
            else:
                row.append({"text": str(day), "callback_data": f"cal:day:{year}:{month}:{day}"})
        keyboard.append(row)

    return {"inline_keyboard": keyboard}


def time_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "09:00", "callback_data": "time:09:00"},
                {"text": "12:00", "callback_data": "time:12:00"},
                {"text": "15:00", "callback_data": "time:15:00"},
            ],
            [
                {"text": "18:00", "callback_data": "time:18:00"},
                {"text": "21:00", "callback_data": "time:21:00"},
                {"text": "23:00", "callback_data": "time:23:00"},
            ],
            [{"text": "Ввести время текстом", "callback_data": "time:manual"}],
        ]
    }


def repeat_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Без повтора", "callback_data": "repeat:none"}],
            [
                {"text": "Каждый час", "callback_data": "repeat:hour"},
                {"text": "Каждый день", "callback_data": "repeat:day"},
            ],
            [
                {"text": "Каждую неделю", "callback_data": "repeat:week"},
                {"text": "Каждый месяц", "callback_data": "repeat:month"},
            ],
        ]
    }


def list_actions_keyboard(reminders):
    keyboard = []
    for item in sorted(reminders, key=lambda reminder: reminder["when"]):
        reminder_id = item["id"]
        keyboard.append(
            [
                {"text": f"Редактировать #{reminder_id}", "callback_data": f"edit:{reminder_id}"},
                {"text": f"Удалить #{reminder_id}", "callback_data": f"delete:{reminder_id}"},
            ]
        )
    keyboard.append([{"text": "Обновить список", "callback_data": "list:refresh"}])
    return {"inline_keyboard": keyboard}


def edit_menu_keyboard(reminder_id):
    return {
        "inline_keyboard": [
            [{"text": "Изменить текст", "callback_data": f"edit_text:{reminder_id}"}],
            [
                {"text": "Изменить дату", "callback_data": f"edit_date:{reminder_id}"},
                {"text": "Изменить время", "callback_data": f"edit_time:{reminder_id}"},
            ],
            [{"text": "Изменить повтор", "callback_data": f"edit_repeat:{reminder_id}"}],
            [{"text": "Удалить", "callback_data": f"delete:{reminder_id}"}],
            [{"text": "Назад к списку", "callback_data": "list:refresh"}],
        ]
    }


def delete_confirm_keyboard(reminder_id):
    return {
        "inline_keyboard": [
            [
                {"text": "Да, удалить", "callback_data": f"delete_confirm:{reminder_id}"},
                {"text": "Отмена", "callback_data": "list:refresh"},
            ]
        ]
    }


def main_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Создать напоминание", "callback_data": "new_reminder"}],
            [{"text": "Все напоминания", "callback_data": "list:refresh"}],
        ]
    }


def handle_start(chat_id, user_id):
    if not is_allowed(user_id):
        send_message(chat_id, "Доступ закрыт. Ваш Telegram ID: " + str(user_id))
        return
    send_message(
        chat_id,
        "Привет! Я бот для текстовых напоминаний.\n\n"
        "Используйте кнопки ниже, чтобы создать, посмотреть, редактировать или удалить напоминание.\n\n"
        f"Ваш Telegram ID: {user_id}",
        main_keyboard(),
    )


def handle_list(chat_id, user_id):
    reminders = active_reminders()
    if not reminders:
        send_message(chat_id, "Активных напоминаний пока нет.", main_keyboard())
        return

    lines = ["Общий список активных напоминаний:"]
    for item in sorted(reminders, key=lambda reminder: reminder["when"]):
        lines.append(
            f'{item["id"]}. {format_when(item["when"])}'
            f' ({repeat_label(item.get("repeat"))}) - {item["text"]}'
        )
    send_message(chat_id, "\n".join(lines), list_actions_keyboard(reminders))


def show_list(chat_id, message_id=None):
    reminders = active_reminders()
    if not reminders:
        text = "Активных напоминаний пока нет."
        if message_id:
            edit_message(chat_id, message_id, text, main_keyboard())
        else:
            send_message(chat_id, text, main_keyboard())
        return

    lines = ["Общий список активных напоминаний:"]
    for item in sorted(reminders, key=lambda reminder: reminder["when"]):
        lines.append(
            f'{item["id"]}. {format_when(item["when"])}'
            f' ({repeat_label(item.get("repeat"))}) - {item["text"]}'
        )

    text = "\n".join(lines)
    keyboard = list_actions_keyboard(reminders)
    if message_id:
        edit_message(chat_id, message_id, text, keyboard)
    else:
        send_message(chat_id, text, keyboard)


def show_edit_menu(chat_id, reminder_id, message_id=None):
    _, reminder = find_active_reminder(reminder_id)
    if not reminder:
        text = "Не нашел активное напоминание с таким ID."
        if message_id:
            edit_message(chat_id, message_id, text, main_keyboard())
        else:
            send_message(chat_id, text, main_keyboard())
        return

    text = (
        f'Напоминание #{reminder["id"]}\n'
        f'Когда: {format_when(reminder["when"])}\n'
        f'Повтор: {repeat_label(reminder.get("repeat"))}\n'
        f'Текст: {reminder["text"]}'
    )
    keyboard = edit_menu_keyboard(reminder_id)
    if message_id:
        edit_message(chat_id, message_id, text, keyboard)
    else:
        send_message(chat_id, text, keyboard)


def handle_delete(chat_id, user_id, text):
    match = re.fullmatch(r"/delete\s+(\d+)", text.strip())
    if not match:
        send_message(chat_id, "Напишите так: /delete 3")
        return

    reminder_id = int(match.group(1))
    reminders = load_reminders()
    filtered = [
        item
        for item in reminders
        if not (
            item["id"] == reminder_id
            and (not item.get("sent") or item.get("repeat"))
        )
    ]
    if len(filtered) == len(reminders):
        send_message(chat_id, "Не нашел активное напоминание с таким ID.")
        return

    save_reminders(filtered)
    send_message(chat_id, f"Удалил напоминание #{reminder_id}.", main_keyboard())


def start_new_reminder(chat_id, user_id):
    sessions[user_id] = {"step": "text"}
    send_message(chat_id, "Напишите текст напоминания.")


def ask_for_date(chat_id, user_id):
    now = datetime.now(TIMEZONE)
    sessions[user_id]["step"] = "date"
    send_message(chat_id, "Выберите дату напоминания:", calendar_keyboard(now.year, now.month))


def ask_for_time(chat_id, user_id):
    sessions[user_id]["step"] = "time"
    selected_date = sessions[user_id]["date"].strftime("%d.%m.%Y")
    send_message(chat_id, f"Дата: {selected_date}. Теперь выберите время:", time_keyboard())


def ask_for_repeat(chat_id, user_id):
    sessions[user_id]["step"] = "repeat"
    when = sessions[user_id]["when"].strftime("%d.%m.%Y %H:%M")
    send_message(chat_id, f"Когда: {when}. Как повторять?", repeat_keyboard())


def save_new_reminder(chat_id, user_id, repeat):
    session = sessions[user_id]
    if session["when"] <= datetime.now(TIMEZONE):
        if "date" in session:
            session["step"] = "time"
            send_message(chat_id, "Это время уже прошло. Выберите другое время:", time_keyboard())
        else:
            session["step"] = "date"
            send_message(chat_id, "Это время уже прошло. Выберите будущую дату и время.")
        return

    reminders = load_reminders()
    if session.get("mode") == "edit":
        reminder_id = session["reminder_id"]
        for item in reminders:
            if item["id"] == reminder_id:
                item["text"] = session["text"]
                item["when"] = session["when"].isoformat()
                item["repeat"] = repeat
                item["sent"] = False
                item["updated_at"] = datetime.now(TIMEZONE).isoformat()
                save_reminders(reminders)
                sessions.pop(user_id, None)
                send_message(
                    chat_id,
                    f'Обновил напоминание #{reminder_id}.\n'
                    f'Когда: {format_when(item["when"])}\n'
                    f'Повтор: {repeat_label(repeat)}\n'
                    f'Текст: {item["text"]}',
                    main_keyboard(),
                )
                show_list(chat_id)
                return

        sessions.pop(user_id, None)
        send_message(chat_id, "Не нашел это напоминание. Откройте список заново.", main_keyboard())
        return

    reminder = {
        "id": next_id(reminders),
        "user_id": user_id,
        "chat_id": chat_id,
        "text": session["text"],
        "when": session["when"].isoformat(),
        "repeat": repeat,
        "sent": False,
        "created_at": datetime.now(TIMEZONE).isoformat(),
    }
    reminders.append(reminder)
    save_reminders(reminders)
    sessions.pop(user_id, None)
    send_message(
        chat_id,
        f'Готово. Напомню {format_when(reminder["when"])} '
        f'({repeat_label(repeat)}):\n{reminder["text"]}',
        main_keyboard(),
    )


def handle_session(chat_id, user_id, text):
    session = sessions.get(user_id)
    if not session:
        return False

    if session["step"] == "text":
        session["text"] = text.strip()
        ask_for_date(chat_id, user_id)
        return True

    if session["step"] == "edit_text":
        session["text"] = text.strip()
        save_new_reminder(chat_id, user_id, session.get("repeat"))
        return True

    if session["step"] == "date":
        when = parse_when(text)
        if not when:
            send_message(chat_id, "Выберите дату в календаре или напишите дату текстом, например 10.07.2026 18:30.")
            return True
        session["when"] = when
        ask_for_repeat(chat_id, user_id)
        return True

    if session["step"] == "time":
        try:
            parsed_time = datetime.strptime(text.strip(), "%H:%M").time()
        except ValueError:
            send_message(chat_id, "Напишите время в формате 18:30 или нажмите кнопку времени.")
            return True
        date_value = session["date"]
        session["when"] = datetime(
            date_value.year,
            date_value.month,
            date_value.day,
            parsed_time.hour,
            parsed_time.minute,
            tzinfo=TIMEZONE,
        )
        ask_for_repeat(chat_id, user_id)
        return True

    if session["step"] == "repeat":
        normalized = text.strip().lower()
        text_repeats = {
            "без повтора": None,
            "каждый час": "hour",
            "каждый день": "day",
            "каждую неделю": "week",
            "каждый месяц": "month",
        }
        if normalized not in text_repeats:
            send_message(chat_id, "Выберите вариант повтора кнопкой или напишите: каждый день.")
            return True
        save_new_reminder(chat_id, user_id, text_repeats[normalized])
        return True

    when = parse_when(text)
    if not when:
        send_message(chat_id, "Не понял дату. Попробуйте: 2026-07-10 18:30 или через 15 минут.")
        return True

    session["when"] = when
    ask_for_repeat(chat_id, user_id)
    return True


def handle_callback(callback_query):
    callback_id = callback_query["id"]
    message = callback_query["message"]
    chat_id = message["chat"]["id"]
    message_id = message["message_id"]
    user_id = callback_query["from"]["id"]
    data = callback_query.get("data", "")

    if not is_allowed(user_id):
        answer_callback(callback_id, "Доступ закрыт")
        return

    session = sessions.get(user_id)
    if data == "cal:noop":
        answer_callback(callback_id)
        return

    if data.startswith("cal:prev:") or data.startswith("cal:next:"):
        _, direction, year, month = data.split(":")
        year = int(year)
        month = int(month)
        if direction == "prev":
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        else:
            month += 1
            if month == 13:
                month = 1
                year += 1
        edit_message(chat_id, message_id, "Выберите дату напоминания:", calendar_keyboard(year, month))
        answer_callback(callback_id)
        return

    if data == "new_reminder":
        start_new_reminder(chat_id, user_id)
        answer_callback(callback_id)
        return

    if data == "list:refresh":
        show_list(chat_id, message_id)
        answer_callback(callback_id)
        return

    if data.startswith("edit:"):
        _, reminder_id = data.split(":", 1)
        show_edit_menu(chat_id, int(reminder_id), message_id)
        answer_callback(callback_id)
        return

    if data.startswith("delete:"):
        _, reminder_id = data.split(":", 1)
        reminder_id = int(reminder_id)
        _, reminder = find_active_reminder(reminder_id)
        if not reminder:
            edit_message(chat_id, message_id, "Не нашел активное напоминание с таким ID.")
            answer_callback(callback_id)
            return
        edit_message(
            chat_id,
            message_id,
            f'Удалить напоминание #{reminder_id}?\n\n{format_when(reminder["when"])} - {reminder["text"]}',
            delete_confirm_keyboard(reminder_id),
        )
        answer_callback(callback_id)
        return

    if data.startswith("delete_confirm:"):
        _, reminder_id = data.split(":", 1)
        reminder_id = int(reminder_id)
        reminders = load_reminders()
        filtered = [
            item
            for item in reminders
            if not (item["id"] == reminder_id and (not item.get("sent") or item.get("repeat")))
        ]
        save_reminders(filtered)
        answer_callback(callback_id, "Удалено")
        show_list(chat_id, message_id)
        return

    if data.startswith("edit_text:"):
        _, reminder_id = data.split(":", 1)
        reminder_id = int(reminder_id)
        _, reminder = find_active_reminder(reminder_id)
        if not reminder:
            answer_callback(callback_id, "Не нашел напоминание")
            return
        sessions[user_id] = {
            "mode": "edit",
            "step": "edit_text",
            "reminder_id": reminder_id,
            "text": reminder["text"],
            "when": datetime.fromisoformat(reminder["when"]),
            "repeat": reminder.get("repeat"),
        }
        send_message(chat_id, f"Напишите новый текст для напоминания #{reminder_id}.")
        answer_callback(callback_id)
        return

    if data.startswith("edit_date:"):
        _, reminder_id = data.split(":", 1)
        reminder_id = int(reminder_id)
        _, reminder = find_active_reminder(reminder_id)
        if not reminder:
            answer_callback(callback_id, "Не нашел напоминание")
            return
        when = datetime.fromisoformat(reminder["when"])
        sessions[user_id] = {
            "mode": "edit",
            "step": "date",
            "reminder_id": reminder_id,
            "text": reminder["text"],
            "when": when,
            "repeat": reminder.get("repeat"),
        }
        send_message(chat_id, f"Выберите новую дату для напоминания #{reminder_id}:", calendar_keyboard(when.year, when.month))
        answer_callback(callback_id)
        return

    if data.startswith("edit_time:"):
        _, reminder_id = data.split(":", 1)
        reminder_id = int(reminder_id)
        _, reminder = find_active_reminder(reminder_id)
        if not reminder:
            answer_callback(callback_id, "Не нашел напоминание")
            return
        when = datetime.fromisoformat(reminder["when"])
        sessions[user_id] = {
            "mode": "edit",
            "step": "time",
            "reminder_id": reminder_id,
            "text": reminder["text"],
            "date": when,
            "when": when,
            "repeat": reminder.get("repeat"),
        }
        send_message(chat_id, f"Выберите новое время для напоминания #{reminder_id}:", time_keyboard())
        answer_callback(callback_id)
        return

    if data.startswith("edit_repeat:"):
        _, reminder_id = data.split(":", 1)
        reminder_id = int(reminder_id)
        _, reminder = find_active_reminder(reminder_id)
        if not reminder:
            answer_callback(callback_id, "Не нашел напоминание")
            return
        sessions[user_id] = {
            "mode": "edit",
            "step": "repeat",
            "reminder_id": reminder_id,
            "text": reminder["text"],
            "when": datetime.fromisoformat(reminder["when"]),
            "repeat": reminder.get("repeat"),
        }
        send_message(chat_id, f"Выберите новый повтор для напоминания #{reminder_id}:", repeat_keyboard())
        answer_callback(callback_id)
        return

    if not session:
        answer_callback(callback_id, "Начните с /new")
        return

    if data.startswith("cal:day:"):
        _, _, year, month, day = data.split(":")
        session["date"] = datetime(int(year), int(month), int(day), tzinfo=TIMEZONE)
        ask_for_time(chat_id, user_id)
        answer_callback(callback_id, "Дата выбрана")
        return

    if data == "time:manual":
        session["step"] = "time"
        send_message(chat_id, "Напишите время в формате 18:30.")
        answer_callback(callback_id)
        return

    if data.startswith("time:"):
        if "date" not in session:
            answer_callback(callback_id, "Сначала выберите дату")
            return
        _, time_text = data.split(":", 1)
        hour, minute = [int(part) for part in time_text.split(":")]
        date_value = session["date"]
        session["when"] = datetime(
            date_value.year,
            date_value.month,
            date_value.day,
            hour,
            minute,
            tzinfo=TIMEZONE,
        )
        ask_for_repeat(chat_id, user_id)
        answer_callback(callback_id, "Время выбрано")
        return

    if data.startswith("repeat:"):
        _, repeat_key = data.split(":", 1)
        if repeat_key not in REPEAT_OPTIONS:
            answer_callback(callback_id, "Неизвестный повтор")
            return
        save_new_reminder(chat_id, user_id, REPEAT_OPTIONS[repeat_key][1])
        answer_callback(callback_id, "Напоминание создано")
        return

    answer_callback(callback_id)


def handle_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "").strip()

    if not is_allowed(user_id):
        send_message(chat_id, "Доступ закрыт. Ваш Telegram ID: " + str(user_id))
        return

    if handle_session(chat_id, user_id, text):
        return

    if text == "/start":
        handle_start(chat_id, user_id)
    elif text in {"/new", "Создать напоминание"}:
        start_new_reminder(chat_id, user_id)
    elif text in {"/list", "Мои напоминания", "Все напоминания"}:
        handle_list(chat_id, user_id)
    elif text.startswith("/delete"):
        handle_delete(chat_id, user_id, text)
    else:
        send_message(chat_id, "Выберите действие кнопкой ниже.", main_keyboard())


def send_due_reminders():
    reminders = load_reminders()
    now = datetime.now(TIMEZONE)
    changed = False

    for item in reminders:
        if item.get("sent"):
            continue
        if datetime.fromisoformat(item["when"]) > now:
            continue
        send_message(item["chat_id"], "Напоминание:\n" + item["text"], main_keyboard())
        repeat = item.get("repeat")
        if repeat:
            next_when = datetime.fromisoformat(item["when"])
            while next_when <= now:
                next_when = next_repeat_time(next_when, repeat)
            item["when"] = next_when.isoformat()
            item["last_sent_at"] = now.isoformat()
            item["sent"] = False
        else:
            item["sent"] = True
            item["sent_at"] = now.isoformat()
        changed = True

    if changed:
        save_reminders(reminders)


def run():
    offset = 0
    global sessions
    sessions = load_sessions()
    print("Reminder bot is running...")
    while True:
        try:
            send_due_reminders()
            updates = api("getUpdates", {"offset": offset, "timeout": 20})
            for update in updates:
                offset = update["update_id"] + 1
                if "message" in update:
                    handle_message(update["message"])
                elif "callback_query" in update:
                    handle_callback(update["callback_query"])
                save_sessions(sessions)
        except (urllib.error.URLError, TimeoutError) as error:
            print("Network error:", error)
            time.sleep(5)
        except Exception as error:
            print("Error:", error)
            time.sleep(2)


if __name__ == "__main__":
    run()
