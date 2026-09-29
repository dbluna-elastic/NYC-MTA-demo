#!/usr/bin/env python3
"""Index GTFS-derived GeoJSON into Elasticsearch for Kibana Maps layers."""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SSL_CTX = ssl._create_unverified_context()


def load_dotenv() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)


def env(name: str) -> str:
    load_dotenv()
    return os.environ[name]


def req(method: str, path: str, body: dict | list | None = None) -> tuple[int, dict | str]:
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
            return e.code, raw


def ensure_indices() -> None:
    lines_body = {
        "mappings": {
            "properties": {
                "shape_id": {"type": "keyword"},
                "route_id": {"type": "keyword"},
                "route_ids": {"type": "keyword"},
                "agency": {"type": "keyword"},
                "labels": {"properties": {"data_source": {"type": "keyword"}, "layer": {"type": "keyword"}}},
                "geometry": {"type": "geo_shape"},
            }
        }
    }
    stops_body = {
        "mappings": {
            "properties": {
                "stop_id": {"type": "keyword"},
                "stop_name": {"type": "keyword"},
                "parent_station": {"type": "keyword"},
                "location_type": {"type": "keyword"},
                "agency": {"type": "keyword"},
                "labels": {"properties": {"data_source": {"type": "keyword"}, "layer": {"type": "keyword"}}},
                "location": {"type": "geo_point"},
                "geometry": {"type": "geo_shape"},
            }
        }
    }
    for name, body in (("mta-geo-lines", lines_body), ("mta-geo-stations", stops_body)):
        code, _ = req("HEAD", f"/{name}")
        if code == 200:
            req("DELETE", f"/{name}")
        code, resp = req("PUT", f"/{name}", body)
        print(f"index {name}: {code}")


def bulk_index(index: str, docs: list[dict]) -> None:
    lines = []
    for d in docs:
        lines.append(json.dumps({"index": {"_index": index}}))
        lines.append(json.dumps(d))
    payload = ("\n".join(lines) + "\n").encode()
    request = urllib.request.Request(
        env("ES_URL").rstrip("/") + "/_bulk",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"ApiKey {env('ES_API_KEY')}",
            "Content-Type": "application/x-ndjson",
        },
    )
    with urllib.request.urlopen(request, timeout=300, context=SSL_CTX) as resp:
        result = json.loads(resp.read())
    errors = [i for i in result.get("items", []) if list(i.values())[0].get("error")]
    print(f"bulk {index}: {len(docs)} docs, errors={len(errors)}")
    if errors:
        print(json.dumps(errors[0])[:400])


def load_lines(path: Path) -> None:
    fc = json.loads(path.read_text())
    docs = []
    for f in fc["features"]:
        props = f.get("properties") or {}
        docs.append(
            {
                "shape_id": props.get("shape_id"),
                "route_id": props.get("route_id"),
                "route_ids": props.get("route_ids") or [],
                "agency": props.get("agency", "NYCT"),
                "labels": {"data_source": "real", "layer": "gtfs_shapes"},
                "geometry": f["geometry"],
            }
        )
    # chunk
    for i in range(0, len(docs), 500):
        bulk_index("mta-geo-lines", docs[i : i + 500])


def load_stops(path: Path) -> None:
    fc = json.loads(path.read_text())
    docs = []
    for f in fc["features"]:
        props = f.get("properties") or {}
        coords = f["geometry"]["coordinates"]  # [lon, lat]
        docs.append(
            {
                "stop_id": props.get("stop_id"),
                "stop_name": props.get("stop_name"),
                "parent_station": props.get("parent_station"),
                "location_type": props.get("location_type"),
                "agency": props.get("agency", "NYCT"),
                "labels": {"data_source": "real", "layer": "gtfs_stops"},
                "location": {"lon": coords[0], "lat": coords[1]},
                "geometry": f["geometry"],
            }
        )
    for i in range(0, len(docs), 500):
        bulk_index("mta-geo-stations", docs[i : i + 500])


def ensure_data_views() -> None:
    kb = env("KIBANA_URL").rstrip("/")
    for view_id, title, name in (
        ("mta-geo-lines", "mta-geo-lines", "MTA GTFS Lines"),
        ("mta-geo-stations", "mta-geo-stations", "MTA GTFS Stations"),
    ):
        body = {
            "data_view": {
                "id": view_id,
                "title": title,
                "name": name,
                "timeFieldName": None,
            }
        }
        # Kibana may require omitting timeFieldName for non-time indices
        data = json.dumps(
            {"data_view": {"id": view_id, "title": title, "name": name}}
        ).encode()
        request = urllib.request.Request(
            f"{kb}/s/mta-demo/api/data_views/data_view",
            data=data,
            method="POST",
            headers={
                "Authorization": f"ApiKey {env('ES_API_KEY')}",
                "kbn-xsrf": "true",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60, context=SSL_CTX) as resp:
                print(f"data view {view_id}: {resp.status}")
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            if e.code in (409, 400) and "already" in raw.lower():
                print(f"data view {view_id}: exists")
            else:
                # try overwrite via saved objects
                print(f"data view {view_id}: {e.code} {raw[:200]}")


def main() -> None:
    lines = ROOT / "geojson" / "subway" / "lines.geojson"
    stops = ROOT / "geojson" / "subway" / "stops.geojson"
    if not lines.exists() or not stops.exists():
        print("Run scripts/gtfs2geojson.py first", file=sys.stderr)
        sys.exit(1)
    ensure_indices()
    load_lines(lines)
    load_stops(stops)
    ensure_data_views()
    print("done")


if __name__ == "__main__":
    main()
