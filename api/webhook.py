import json
import os
import sys
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

    def do_GET(self):
        self.send_json(200, {"ok": True, "service": "telegram-webhook"})

    def do_POST(self):
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
