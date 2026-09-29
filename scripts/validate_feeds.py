#!/usr/bin/env python3
"""Phase 0: validate public MTA feed URLs and save samples."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
FEEDS = ROOT / "collector" / "feeds.yaml"


def main() -> int:
    cfg = yaml.safe_load(FEEDS.read_text())
    session = requests.Session()
    session.headers["User-Agent"] = "mta-observability-demo-phase0/1.0"
    results = []
    for section in ("subway", "railroad", "alerts", "ene"):
        for fid, meta in (cfg.get(section) or {}).items():
            url = meta["url"]
            kind = meta["kind"]
            try:
                r = session.get(url, timeout=30)
                ok = r.status_code == 200 and len(r.content) > 0
                out_dir = SAMPLES / section
                out_dir.mkdir(parents=True, exist_ok=True)
                if kind.endswith("json") or kind == "ene_equipments" or kind == "ene_json":
                    path = out_dir / f"{fid}.json"
                    # pretty if json
                    try:
                        path.write_text(json.dumps(r.json(), indent=2)[:200000])
                    except Exception:
                        path.write_bytes(r.content[:200000])
                else:
                    path = out_dir / f"{fid}.pb"
                    path.write_bytes(r.content[:500000])
                results.append((fid, r.status_code, len(r.content), str(path.relative_to(ROOT))))
                print(f"{'OK' if ok else 'FAIL'} {fid} {r.status_code} {len(r.content)}b → {path.name}")
            except Exception as e:
                results.append((fid, "ERR", 0, str(e)))
                print(f"FAIL {fid} {e}")

    # static gtfs head
    try:
        url = cfg["static_gtfs"]["subway"]["url"]
        r = session.get(url, timeout=60, stream=True)
        n = len(r.content)
        (SAMPLES / "gtfs").mkdir(exist_ok=True)
        print(f"{'OK' if r.status_code == 200 else 'FAIL'} static_gtfs {r.status_code} {n}b")
    except Exception as e:
        print(f"FAIL static_gtfs {e}")

    fails = [x for x in results if x[1] != 200]
    print(f"\n{len(results) - len(fails)}/{len(results)} feeds OK")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
