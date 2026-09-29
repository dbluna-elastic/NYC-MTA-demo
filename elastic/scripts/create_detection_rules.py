#!/usr/bin/env python3
"""Create Elastic Security detection rules (ES|QL) in Space mta-demo."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

SSL_CTX = ssl._create_unverified_context()

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "elastic" / "rules"


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


def env(name: str) -> str:
    load_dotenv()
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"Missing {name}")
    return v


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
        with urllib.request.urlopen(req, timeout=90, context=SSL_CTX) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"error": raw[:2000]}


RULE_DEFS = [
    (
        "mta-modbus-write",
        "MTA IDMZ: Modbus write from enterprise",
        "unauthorized_system_intrusion",
        "modbus_write_enterprise.esql",
    ),
    (
        "mta-plc-change",
        "MTA OT: PLC logic change outside maintenance",
        "unauthorized_modification",
        "plc_logic_outside_window.esql",
    ),
    (
        "mta-ntp-fallback",
        "MTA OT: Controller fell back to public NTP",
        "unauthorized_communication",
        "ntp_public_fallback.esql",
    ),
    (
        "mta-vendor-remote",
        "MTA: Vendor remote access policy violation",
        "unexpected_remote_logon",
        "vendor_remote_access.esql",
    ),
    (
        "mta-unknown-asset",
        "MTA OT: Unknown asset on network segment",
        "unauthorized_system_intrusion",
        "unknown_asset.esql",
    ),
    (
        "mta-vuln-sla",
        "MTA: Vulnerability past NATCA patch SLA",
        "vuln_sla",
        "vuln_sla_breach.esql",
    ),
    (
        "mta-ti-match",
        "MTA: Threat intel indicator match on remote access",
        "threat_intel",
        "threat_intel_match.esql",
    ),
    (
        "mta-dos",
        "MTA OT: Denial of service pattern",
        "denial_of_service",
        "ot_dos_flood.esql",
    ),
    (
        "mta-shutdown",
        "MTA OT: Unplanned shutdown",
        "unplanned_shutdown",
        "unplanned_shutdown.esql",
    ),
]


def main() -> None:
    for rule_id, name, tag, filename in RULE_DEFS:
        query = (RULES / filename).read_text().strip()
        # strip comment-only preamble lines for query body — keep full file as query
        # Elastic ES|QL rule API
        body = {
            "name": name,
            "description": f"MTA demo detection ({tag}). Simulated data unless noted. NATCA/RFP coverage.",
            "rule_id": rule_id,
            "enabled": True,
            "risk_score": 70,
            "severity": "high",
            "type": "esql",
            "language": "esql",
            "query": query,
            "from": "now-1h",
            "interval": "5m",
            "tags": ["mta-demo", "natca", tag, "simulated"],
            "author": ["mta-observability-demo"],
            "license": "Elastic License v2",
            "meta": {"demo": "mta-observability", "natca_function": tag},
        }
        code, resp = kb("POST", "/api/detection_engine/rules", body)
        if code in (200, 201):
            print(f"created {rule_id}")
            continue
        if code == 409 or (isinstance(resp, dict) and "already exists" in json.dumps(resp).lower()):
            code2, resp2 = kb("PUT", f"/api/detection_engine/rules?rule_id={rule_id}", body)
            print(f"updated {rule_id}: {code2}")
            continue
        # try update by rule_id
        code2, resp2 = kb("PUT", f"/api/detection_engine/rules?rule_id={rule_id}", body)
        print(f"{rule_id}: create={code} update={code2} {resp if code >= 400 else ''} {resp2 if code2 >= 400 else ''}")


if __name__ == "__main__":
    main()
