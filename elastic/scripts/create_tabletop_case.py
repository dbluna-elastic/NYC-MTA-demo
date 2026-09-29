#!/usr/bin/env python3
"""Open a Security case in Space mta-demo for Scenario 4B tabletop."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SSL_CTX = ssl._create_unverified_context()


def load_dotenv() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)


def env(name: str) -> str:
    load_dotenv()
    return os.environ[name]


def kb(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{env('KIBANA_URL').rstrip('/')}/s/mta-demo{path}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"ApiKey {env('ES_API_KEY')}",
            "kbn-xsrf": "true",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"error": raw[:2000]}


def main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body = {
        "title": f"IDMZ tabletop {today}",
        "description": (
            "Scenario 4B SOC day-in-the-life tabletop.\n\n"
            "L1 triage checklist:\n"
            "1. Modbus write from enterprise subnet\n"
            "2. Vendor VPN from non-allowlisted IP / idle > 5m\n"
            "3. Threat intel match on 198.51.100.99\n"
            "4. Unknown asset on ot-cbtc-7\n"
            "5. Vuln SLA breaches (NATCA Crit 30 / High 45 / Med 60 / Low 180)\n"
            "6. Escalate to OT engineering; document in case notes\n\n"
            "Replay: `python simulator/simulator.py --attack`"
        ),
        "tags": ["mta-demo", "natca", "tabletop", "idmz"],
        "severity": "high",
        "owner": "securitySolution",
        "connector": {"id": "none", "name": "none", "type": ".none", "fields": None},
        "settings": {"syncAlerts": True},
    }
    code, resp = kb("POST", "/api/cases", body)
    print("cases", code, json.dumps(resp)[:800])
    if code in (200, 201):
        case_id = resp.get("id")
        print(f"Case URL: {env('KIBANA_URL')}/s/mta-demo/app/security/cases/{case_id}")
        # Add analyst note
        if case_id:
            note = {
                "comment": (
                    "L1 note: Correlated Modbus write + vendor remote access IOC 198.51.100.99. "
                    "Attack Discovery recommended for IT/OT blast radius. Escalating to OT eng."
                ),
                "owner": "securitySolution",
                "type": "user",
            }
            c2, r2 = kb("POST", f"/api/cases/{case_id}/comments", note)
            print("comment", c2, json.dumps(r2)[:300])
        return
    print("Case API unavailable with this key/privileges — use UI in mta-demo Security → Cases")


if __name__ == "__main__":
    main()
