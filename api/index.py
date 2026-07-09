import json
import os
import sys
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parents[1]))

import bot


class handler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def is_cron_authorized(self):
        secret = os.getenv("CRON_SECRET")
        if not secret:
            return True
        authorization = self.headers.get("Authorization", "")
        header_secret = self.headers.get("X-Cron-Secret", "")
        return authorization == f"Bearer {secret}" or header_secret == secret

    def route_name(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if query.get("route", [""])[0] in {"cron", "webhook"}:
            return query["route"][0]
        if parsed.path.startswith("/api/cron"):
            return "cron"
        if parsed.path.startswith("/api/webhook"):
            return "webhook"
        return "webhook"

    def handle_webhook(self):
        secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
        incoming_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret and incoming_secret != secret:
            self.send_json(403, {"ok": False, "error": "forbidden"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)

        try:
            update = json.loads(raw_body.decode("utf-8") or "{}")
            bot.sessions = bot.load_sessions()
            if "message" in update:
                bot.handle_message(update["message"])
            elif "callback_query" in update:
                bot.handle_callback(update["callback_query"])
            bot.save_sessions(bot.sessions)
            self.send_json(200, {"ok": True})
        except Exception as error:
            self.send_json(500, {"ok": False, "error": str(error)})

    def handle_cron(self):
        if not self.is_cron_authorized():
            self.send_json(403, {"ok": False, "error": "forbidden"})
            return

        try:
            bot.send_due_reminders()
            self.send_json(200, {"ok": True})
        except Exception as error:
            self.send_json(500, {"ok": False, "error": str(error)})

    def do_GET(self):
        if self.route_name() == "cron":
            self.handle_cron()
            return
        self.send_json(200, {"ok": True, "service": "telegram-reminder-bot"})

    def do_POST(self):
        if self.route_name() == "cron":
            self.handle_cron()
            return
        self.handle_webhook()
