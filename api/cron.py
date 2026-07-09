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

    def is_authorized(self):
        secret = os.getenv("CRON_SECRET")
        if not secret:
            return True
        authorization = self.headers.get("Authorization", "")
        header_secret = self.headers.get("X-Cron-Secret", "")
        return authorization == f"Bearer {secret}" or header_secret == secret

    def do_GET(self):
        if not self.is_authorized():
            self.send_json(403, {"ok": False, "error": "forbidden"})
            return

        try:
            bot.send_due_reminders()
            self.send_json(200, {"ok": True})
        except Exception as error:
            self.send_json(500, {"ok": False, "error": str(error)})

    def do_POST(self):
        self.do_GET()
