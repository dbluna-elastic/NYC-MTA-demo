#!/usr/bin/env python3
"""Apply index templates, create data streams, data views, and verify Spaces."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SSL_CTX = ssl._create_unverified_context()

ROOT = Path(__file__).resolve().parents[2]
ELASTIC = ROOT / "elastic"

STREAMS = [
    "logs-mta.subway_trip-default",
    "logs-mta.subway_arrival-default",
    "logs-mta.railroad_trip-default",
    "logs-mta.alert-default",
    "logs-mta.stop_ref-default",
    "logs-mta.idmz-simulated",
    "logs-mta.ot_asset-simulated",
    "logs-mta.vuln_finding-simulated",
    "logs-mta.remote_access-simulated",
    "logs-mta.windows_ad-simulated",
    "logs-mta.netconfig-simulated",
    "logs-mta.wireless-simulated",
    "logs-mta.onboard-simulated",
    "logs-mta.threat_intel-simulated",
    "logs-cef.log-simulated",
    "metrics-mta.ene_status-default",
    "metrics-mta.ot_power-simulated",
    "metrics-mta.ot_dcs-simulated",
    "metrics-mta.ot_pump-simulated",
    "metrics-mta.ene_sensor-simulated",
]


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


def req(method: str, url: str, body: dict | list | None = None, kibana: bool = False) -> tuple[int, Any]:
    data = None
    headers = {
        "Authorization": f"ApiKey {env('ES_API_KEY')}",
        "Content-Type": "application/json",
    }
    if kibana:
        headers["kbn-xsrf"] = "true"
    if body is not None:
        data = json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60, context=SSL_CTX) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"error": raw}
        return e.code, parsed


def put_template(name: str, path: Path) -> None:
    body = json.loads(path.read_text())
    code, resp = req("PUT", f"{env('ES_URL')}/_index_template/{name}", body)
    print(f"template {name}: {code} {resp.get('acknowledged', resp)}")


def ensure_stream(name: str) -> None:
    code, _ = req("GET", f"{env('ES_URL')}/_data_stream/{name}")
    if code == 200:
        print(f"stream exists {name}")
        return
    code, resp = req("PUT", f"{env('ES_URL')}/_data_stream/{name}")
    print(f"stream create {name}: {code} {resp}")


def ensure_data_view(space: str, view_id: str, title: str, name: str) -> None:
    kb = env("KIBANA_URL").rstrip("/")
    code, _ = req("GET", f"{kb}/s/{space}/api/data_views/data_view/{view_id}", kibana=True)
    if code == 200:
        print(f"data view {view_id} exists in {space}")
        return
    body = {
        "data_view": {
            "id": view_id,
            "title": title,
            "name": name,
            "timeFieldName": "@timestamp",
        }
    }
    code, resp = req("POST", f"{kb}/s/{space}/api/data_views/data_view", body, kibana=True)
    print(f"data view {view_id} in {space}: {code} {resp if code >= 400 else 'ok'}")


def main() -> None:
    put_template("mta-logs", ELASTIC / "index_templates" / "mta-logs.json")
    put_template("mta-metrics", ELASTIC / "index_templates" / "mta-metrics.json")
    put_template("mta-cef", ELASTIC / "index_templates" / "mta-cef.json")

    for s in STREAMS:
        ensure_stream(s)

    ensure_data_view("mta-demo", "mta-all", "logs-mta.*,metrics-mta.*,logs-cef.*", "MTA All Demo Data")
    ensure_data_view("mta-demo", "mta-subway", "logs-mta.subway_trip-*", "MTA Subway Trips")
    ensure_data_view("mta-demo", "mta-alerts", "logs-mta.alert-*", "MTA Service Alerts")
    ensure_data_view(
        "mta-demo",
        "mta-security",
        "logs-mta.idmz-*,logs-mta.ot_asset-*,logs-mta.vuln_finding-*,logs-mta.remote_access-*,logs-mta.windows_ad-*,logs-mta.netconfig-*,logs-mta.wireless-*,logs-mta.onboard-*,logs-mta.threat_intel-*,logs-cef.*",
        "MTA Security Simulated",
    )
    ensure_data_view("mta-demo", "mta-vuln", "logs-mta.vuln_finding-*", "MTA Vuln Findings")
    ensure_data_view("mta-demo", "mta-ene", "metrics-mta.ene_status-*", "MTA Elevator Escalator")
    ensure_data_view("mta-demo", "mta-railroad", "logs-mta.railroad_trip-*", "MTA Railroad Trips")

    for space in ("nyct", "lirr", "mnr", "bt"):
        ensure_data_view(space, f"{space}-all", "logs-mta.*,metrics-mta.*", f"{space.upper()} Demo Data")

    print("bootstrap complete")


if __name__ == "__main__":
    main()
