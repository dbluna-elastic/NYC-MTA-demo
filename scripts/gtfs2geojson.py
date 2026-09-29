#!/usr/bin/env python3
"""
Convert MTA static GTFS shapes.txt / stops.txt → GeoJSON.

Same approach as NYCPlanning/nyc-gtfs2geojson (gtfs2geojson.lines / .stops):
  - shapes.txt → FeatureCollection of LineStrings (one per shape_id)
  - stops.txt  → FeatureCollection of Points

Also joins shape_id → route_id via trips.txt for styling.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path


def shapes_to_geojson(shapes_csv: str, shape_routes: dict[str, set[str]] | None = None) -> dict:
    """nyc-gtfs2geojson / gtfs2geojson.lines equivalent."""
    by_shape: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    reader = csv.DictReader(io.StringIO(shapes_csv))
    for row in reader:
        sid = row["shape_id"]
        seq = int(float(row["shape_pt_sequence"]))
        lat = float(row["shape_pt_lat"])
        lon = float(row["shape_pt_lon"])
        by_shape[sid].append((seq, lon, lat))  # GeoJSON is [lon, lat]

    features = []
    for sid, pts in by_shape.items():
        pts.sort(key=lambda x: x[0])
        coords = [[lon, lat] for _, lon, lat in pts]
        if len(coords) < 2:
            continue
        routes = sorted(shape_routes.get(sid, set())) if shape_routes else []
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "shape_id": sid,
                    "route_ids": routes,
                    "route_id": routes[0] if routes else None,
                    "agency": "NYCT",
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        )
    return {"type": "FeatureCollection", "features": features}


def stops_to_geojson(stops_csv: str) -> dict:
    """nyc-gtfs2geojson / gtfs2geojson.stops equivalent."""
    reader = csv.DictReader(io.StringIO(stops_csv))
    features = []
    for row in reader:
        try:
            lat = float(row["stop_lat"])
            lon = float(row["stop_lon"])
        except (KeyError, ValueError):
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "stop_id": row.get("stop_id"),
                    "stop_name": row.get("stop_name"),
                    "parent_station": row.get("parent_station") or None,
                    "location_type": row.get("location_type") or "0",
                    "agency": "NYCT",
                },
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
        )
    return {"type": "FeatureCollection", "features": features}


def shape_to_routes(trips_csv: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    reader = csv.DictReader(io.StringIO(trips_csv))
    for row in reader:
        sid = row.get("shape_id") or ""
        rid = row.get("route_id") or ""
        if sid and rid:
            out[sid].add(rid)
    return out


def from_zip(zip_path: Path) -> tuple[dict, dict]:
    with zipfile.ZipFile(zip_path) as zf:
        shapes = zf.read("shapes.txt").decode("utf-8-sig")
        stops = zf.read("stops.txt").decode("utf-8-sig")
        trips = zf.read("trips.txt").decode("utf-8-sig")
    routes = shape_to_routes(trips)
    return shapes_to_geojson(shapes, routes), stops_to_geojson(stops)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gtfs-zip", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, default=Path("geojson/subway"))
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    lines, stops = from_zip(args.gtfs_zip)
    lines_path = args.out_dir / "lines.geojson"
    stops_path = args.out_dir / "stops.geojson"
    lines_path.write_text(json.dumps(lines))
    stops_path.write_text(json.dumps(stops))
    print(f"wrote {lines_path} ({len(lines['features'])} lines)")
    print(f"wrote {stops_path} ({len(stops['features'])} stops)")


if __name__ == "__main__":
    main()
