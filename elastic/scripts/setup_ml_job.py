#!/usr/bin/env python3
"""Create ML job + datafeed for track divergence (may stay stopped until history accumulates)."""

from __future__ import annotations

import json
import os
import ssl
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
    cfg = json.loads((ROOT / "elastic/ml_jobs/track_divergence_high_count.json").read_text())
    job_id = cfg["job_id"]
    datafeed = cfg.pop("datafeed_config")
    datafeed_id = f"datafeed-{job_id}"
    datafeed["job_id"] = job_id
    datafeed["datafeed_id"] = datafeed_id

    code, resp = req("PUT", f"/_ml/anomaly_detectors/{job_id}", cfg)
    print("job", code, resp)
    code, resp = req("PUT", f"/_ml/datafeeds/{datafeed_id}", datafeed)
    print("datafeed", code, resp)
    # Open job but do not start datafeed if insufficient history — attempt start
    code, resp = req("POST", f"/_ml/anomaly_detectors/{job_id}/_open")
    print("open", code, resp)
    code, resp = req("POST", f"/_ml/datafeeds/{datafeed_id}/_start", {"start": "now-7d"})
    print("start", code, resp)


if __name__ == "__main__":
    main()
