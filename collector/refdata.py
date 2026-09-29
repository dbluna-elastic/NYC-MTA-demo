#!/usr/bin/env python3
"""Load static GTFS stops and data.ny.gov reference data into Elasticsearch."""

from __future__ import annotations

import csv
import io
import logging
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from elasticsearch import Elasticsearch, helpers

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("mta-refdata")


def env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        raise SystemExit(f"Missing required env var: {name}")
    return val


def ensure_ref_index(es: Elasticsearch) -> None:
    """Reference data uses a regular index (not a data stream) so enrich can match on _id updates."""
    name = "mta-stop-ref"
    if es.indices.exists(index=name):
        return
    es.indices.create(
        index=name,
        mappings={
            "properties": {
                "@timestamp": {"type": "date"},
                "transit": {
                    "properties": {
                        "stop_id": {"type": "keyword"},
                        "stop_name": {"type": "keyword"},
                        "parent_station": {"type": "keyword"},
                        "station_name": {"type": "keyword"},
                        "borough": {"type": "keyword"},
                        "ada": {"type": "keyword"},
                        "lines": {"type": "keyword"},
                    }
                },
                "station": {
                    "properties": {
                        "name": {"type": "keyword"},
                        "location": {"type": "geo_point"},
                        "ada": {"type": "keyword"},
                        "borough": {"type": "keyword"},
                    }
                },
                "geo": {"properties": {"location": {"type": "geo_point"}}},
                "labels": {
                    "properties": {
                        "data_source": {"type": "keyword"},
                        "agency": {"type": "keyword"},
                    }
                },
            }
        },
    )


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    es = Elasticsearch(
        env("ES_URL"),
        api_key=env("ES_API_KEY"),
        request_timeout=120,
        verify_certs=False,
        ssl_show_warn=False,
    )
    ensure_ref_index(es)
    with open(ROOT / "feeds.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    actions: list[dict[str, Any]] = []
    ingested = datetime.now(timezone.utc).isoformat()

    # Static GTFS stops
    gtfs_url = cfg["static_gtfs"]["subway"]["url"]
    LOG.info("downloading static GTFS %s", gtfs_url)
    zbytes = requests.get(gtfs_url, timeout=120).content
    with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
        with zf.open("stops.txt") as sf:
            reader = csv.DictReader(io.TextIOWrapper(sf, encoding="utf-8"))
            for row in reader:
                stop_id = row.get("stop_id")
                if not stop_id:
                    continue
                try:
                    lat = float(row["stop_lat"])
                    lon = float(row["stop_lon"])
                except (KeyError, ValueError):
                    continue
                doc = {
                    "@timestamp": ingested,
                    "event": {"ingested": ingested, "dataset": "mta.stop_ref"},
                    "labels": {"data_source": "real", "agency": "NYCT"},
                    "transit": {
                        "stop_id": stop_id,
                        "stop_name": row.get("stop_name"),
                        "parent_station": row.get("parent_station"),
                        "location_type": row.get("location_type"),
                    },
                    "station": {
                        "name": row.get("stop_name"),
                        "location": {"lat": lat, "lon": lon},
                    },
                    "geo": {"location": {"lat": lat, "lon": lon}},
                }
                actions.append(
                    {
                        "_op_type": "index",
                        "_index": "mta-stop-ref",
                        "_id": stop_id,
                        "_source": doc,
                    }
                )

    # Socrata stations ADA
    stations_url = cfg["refdata"]["stations"]["url"] + "?$limit=50000"
    LOG.info("loading stations %s", stations_url)
    stations = requests.get(stations_url, timeout=120).json()
    for row in stations:
        gtfs_stop = row.get("gtfs_stop_id") or row.get("station_id")
        if not gtfs_stop:
            continue
        doc = {
            "@timestamp": ingested,
            "event": {"ingested": ingested, "dataset": "mta.station_ada"},
            "labels": {"data_source": "real", "agency": "NYCT"},
            "transit": {
                "stop_id": gtfs_stop,
                "station_name": row.get("stop_name") or row.get("station_name"),
                "borough": row.get("borough"),
                "ada": row.get("ada") or row.get("ada_accessible"),
                "lines": row.get("daytime_routes") or row.get("line"),
            },
            "station": {
                "name": row.get("stop_name") or row.get("station_name"),
                "ada": row.get("ada") or row.get("ada_accessible"),
                "borough": row.get("borough"),
            },
        }
        if row.get("gtfs_latitude") and row.get("gtfs_longitude"):
            try:
                loc = {"lat": float(row["gtfs_latitude"]), "lon": float(row["gtfs_longitude"])}
                doc["station"]["location"] = loc
                doc["geo"] = {"location": loc}
            except ValueError:
                pass
        actions.append(
            {
                "_op_type": "index",
                "_index": "mta-stop-ref",
                "_id": f"ada-{gtfs_stop}",
                "_source": doc,
            }
        )

    ok, errors = helpers.bulk(es, actions, raise_on_error=False, request_timeout=300)
    LOG.info("indexed %s ref docs (%s errors)", ok, len(errors) if errors else 0)


if __name__ == "__main__":
    main()
