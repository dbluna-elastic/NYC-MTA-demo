#!/usr/bin/env python3
"""Backfill station.location onto live subway + E&E docs for Kibana Maps layers 3–4."""

from __future__ import annotations

import json
import os
import re
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


def req(method: str, path: str, body: dict | list | None = None) -> dict:
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
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code} {e.read().decode()[:500]}")


def load_stop_lookup() -> dict[str, dict]:
    """stop_id -> {lat, lon, name} from mta-geo-stations + mta-stop-ref."""
    lookup: dict[str, dict] = {}
    for index in ("mta-geo-stations", "mta-stop-ref"):
        body = {
            "size": 10000,
            "_source": ["stop_id", "stop_name", "location", "station", "transit", "geo"],
            "query": {"match_all": {}},
        }
        # scroll-less; both indices are small
        hits = req("POST", f"/{index}/_search", body).get("hits", {}).get("hits", [])
        for h in hits:
            s = h["_source"]
            sid = s.get("stop_id") or (s.get("transit") or {}).get("stop_id")
            loc = s.get("location") or (s.get("station") or {}).get("location") or (s.get("geo") or {}).get("location")
            name = s.get("stop_name") or (s.get("station") or {}).get("name") or (s.get("transit") or {}).get("stop_name")
            if not sid or not loc:
                continue
            point = {"lat": loc["lat"], "lon": loc["lon"]}
            lookup[sid] = {"location": point, "name": name}
            # also key without N/S/E/W suffix used in GTFS-RT
            base = re.sub(r"[NSEW]$", "", sid)
            lookup.setdefault(base, {"location": point, "name": name})
            if name:
                lookup.setdefault(f"name:{name.lower()}", {"location": point, "name": name})
    print(f"stop lookup entries: {len(lookup)}")
    return lookup


def resolve_stop(lookup: dict[str, dict], stop_id: str | None) -> dict | None:
    if not stop_id:
        return None
    if stop_id in lookup:
        return lookup[stop_id]
    base = re.sub(r"[NSEW]$", "", stop_id)
    return lookup.get(base)


def update_by_query_scripted(index: str, lookup: dict[str, dict], id_field: str) -> None:
    """Not using painless external lookup — update docs via bulk from search."""
    # search docs missing station.location
    body = {
        "size": 5000,
        "query": {
            "bool": {
                "must_not": [{"exists": {"field": "station.location"}}],
            }
        },
        "_source": [id_field, "transit", "equipment"],
    }
    if index.startswith("logs-mta.subway"):
        # optional: only diverted for speed, but backfill all recent is better for map
        pass
    hits = req("POST", f"/{index}/_search", body).get("hits", {}).get("hits", [])
    actions = []
    matched = 0
    for h in hits:
        src = h["_source"]
        transit = src.get("transit") or {}
        loc = None
        name = None
        if id_field == "transit.current_stop_id":
            sid = transit.get("current_stop_id")
            hit = resolve_stop(lookup, sid)
            if hit:
                loc, name = hit["location"], hit.get("name")
        elif id_field == "transit.station_name":
            sname = transit.get("station_name")
            if sname:
                hit = lookup.get(f"name:{sname.lower()}")
                if hit:
                    loc, name = hit["location"], hit.get("name")
        if not loc:
            continue
        matched += 1
        doc = {
            "station": {"location": loc, "name": name or transit.get("station_name")},
            "geo": {"location": loc},
        }
        actions.append(json.dumps({"update": {"_index": h["_index"], "_id": h["_id"]}}))
        actions.append(json.dumps({"doc": doc}))
    if not actions:
        print(f"{index}: no matches to update (scanned {len(hits)})")
        return
    payload = ("\n".join(actions) + "\n").encode()
    request = urllib.request.Request(
        env("ES_URL").rstrip("/") + "/_bulk",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"ApiKey {env('ES_API_KEY')}",
            "Content-Type": "application/x-ndjson",
        },
    )
    with urllib.request.urlopen(request, timeout=180, context=SSL_CTX) as resp:
        result = json.loads(resp.read())
    errors = [i for i in result.get("items", []) if list(i.values())[0].get("error")]
    print(f"{index}: updated {matched}/{len(hits)}, bulk_errors={len(errors)}")


def fix_enrich_and_template() -> None:
    """Ensure subway ingest pipeline enriches current_stop_id → station.location."""
    # enrich policy already on transit.stop_id in mta-stop-ref — also add geo stations index
    # recreate policy matching both stop_id fields from mta-geo-stations (cleaner)
    policy = {
        "match": {
            "indices": "mta-geo-stations",
            "match_field": "stop_id",
            "enrich_fields": ["stop_name", "location"],
        }
    }
    # delete + recreate
    try:
        req("DELETE", "/_enrich/policy/mta-stops")
    except SystemExit:
        pass
    # DELETE may 404
    code_path = env("ES_URL").rstrip("/") + "/_enrich/policy/mta-stops"
    request = urllib.request.Request(
        code_path,
        method="DELETE",
        headers={"Authorization": f"ApiKey {env('ES_API_KEY')}"},
    )
    try:
        urllib.request.urlopen(request, timeout=60, context=SSL_CTX)
    except urllib.error.HTTPError:
        pass

    req("PUT", "/_enrich/policy/mta-stops", policy)
    req("POST", "/_enrich/policy/mta-stops/_execute")
    pipeline = {
        "description": "Enrich subway trip current_stop_id with station geo",
        "processors": [
            {
                "set": {
                    "field": "_tmp.stop_base",
                    "value": "{{{transit.current_stop_id}}}",
                    "ignore_empty_value": True,
                }
            },
            {
                "gsub": {
                    "field": "_tmp.stop_base",
                    "pattern": "[NSEW]$",
                    "replacement": "",
                    "ignore_missing": True,
                }
            },
            {
                "enrich": {
                    "policy_name": "mta-stops",
                    "field": "transit.current_stop_id",
                    "target_field": "_tmp.enrich_exact",
                    "max_matches": 1,
                    "ignore_missing": True,
                }
            },
            {
                "enrich": {
                    "policy_name": "mta-stops",
                    "field": "_tmp.stop_base",
                    "target_field": "_tmp.enrich_base",
                    "max_matches": 1,
                    "ignore_missing": True,
                }
            },
            {
                "set": {
                    "field": "station.location",
                    "copy_from": "_tmp.enrich_exact.location",
                    "ignore_empty_value": True,
                    "override": False,
                }
            },
            {
                "set": {
                    "field": "station.location",
                    "copy_from": "_tmp.enrich_base.location",
                    "ignore_empty_value": True,
                    "override": False,
                }
            },
            {
                "set": {
                    "field": "station.name",
                    "copy_from": "_tmp.enrich_exact.stop_name",
                    "ignore_empty_value": True,
                    "override": False,
                }
            },
            {
                "set": {
                    "field": "station.name",
                    "copy_from": "_tmp.enrich_base.stop_name",
                    "ignore_empty_value": True,
                    "override": False,
                }
            },
            {
                "set": {
                    "field": "geo.location",
                    "copy_from": "station.location",
                    "ignore_empty_value": True,
                }
            },
            {"remove": {"field": ["_tmp"], "ignore_missing": True}},
        ],
    }
    req("PUT", "/_ingest/pipeline/mta-subway-enrich", pipeline)
    print("enrich pipeline updated")


def main() -> None:
    lookup = load_stop_lookup()
    update_by_query_scripted("logs-mta.subway_trip-default", lookup, "transit.current_stop_id")
    update_by_query_scripted("logs-mta.subway_arrival-default", lookup, "transit.current_stop_id")
    update_by_query_scripted("metrics-mta.ene_status-default", lookup, "transit.station_name")
    fix_enrich_and_template()
    # verify
    for label, index, q in [
        ("diverted+geo", "logs-mta.subway_trip-default", {"bool": {"filter": [{"term": {"transit.track_diverted": True}}, {"exists": {"field": "station.location"}}]}}),
        ("ene+geo", "metrics-mta.ene_status-default", {"exists": {"field": "station.location"}}),
    ]:
        c = req("POST", f"/{index}/_count", {"query": q})
        print(label, c.get("count"))


if __name__ == "__main__":
    main()
