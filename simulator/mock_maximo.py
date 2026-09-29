#!/usr/bin/env python3
"""Tiny mock Maximo webhook for elevator work-order demo (Scenario 2)."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from datetime import datetime, timezone

ORDERS: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/workorders"):
            self._json(200, {"count": len(ORDERS), "workorders": ORDERS[-50:]})
            return
        self._json(200, {"service": "mock-maximo", "status": "ok"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        order = {
            "id": f"WO-{len(ORDERS)+1:05d}",
            "created": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        ORDERS.append(order)
        print("created", order["id"], flush=True)
        self._json(201, order)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[maximo] {self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8088), Handler).serve_forever()
