#!/usr/bin/env python3
"""Create enrich policy + ingest pipeline for stop_id → station geo."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
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


def req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = env("ES_URL").rstrip("/") + path
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"ApiKey {env('ES_API_KEY')}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120, context=SSL_CTX) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"error": raw}


def main() -> None:
    policy = json.loads((ROOT / "elastic/enrich_policies/mta-stops.json").read_text())
    code, resp = req("PUT", "/_enrich/policy/mta-stops", policy)
    print("policy", code, resp)
    code, resp = req("POST", "/_enrich/policy/mta-stops/_execute")
    print("execute", code, resp)
    for _ in range(30):
        code, resp = req("GET", "/_enrich/policy/mta-stops")
        # wait briefly
        time.sleep(1)
        if code == 200:
            break
    pipeline = json.loads((ROOT / "elastic/ingest_pipelines/mta-subway-enrich.json").read_text())
    code, resp = req("PUT", "/_ingest/pipeline/mta-subway-enrich", pipeline)
    print("pipeline", code, resp)
    # attach default pipeline to subway trip stream via component template update
    tmpl = {
        "index_patterns": ["logs-mta.subway_trip-*"],
        "data_stream": {},
        "priority": 600,
        "template": {"settings": {"index.default_pipeline": "mta-subway-enrich"}},
    }
    code, resp = req("PUT", "/_index_template/mta-subway-enrich-pipeline", tmpl)
    print("index template pipeline", code, resp)


if __name__ == "__main__":
    main()
