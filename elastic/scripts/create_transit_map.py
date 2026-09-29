#!/usr/bin/env python3
"""Create/fix MTA transit map using layer types that work on this Kibana 9.5 cluster.

Declutter approach: one lines layer colored by route_id (MTA palette), not 29 layers.
Basemap must be type EMS_VECTOR_TILE (not EMS_TMS).
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SSL_CTX = ssl._create_unverified_context()
MAP_ID = "mta-transit-network"
SPACE = "mta-demo"

# Official MTA subway line colors (NYCT brand)
MTA_ROUTE_COLORS: dict[str, str] = {
    "1": "#EE352E",
    "2": "#EE352E",
    "3": "#EE352E",
    "4": "#00933C",
    "5": "#00933C",
    "6": "#00933C",
    "6X": "#00933C",
    "7": "#B933AD",
    "7X": "#B933AD",
    "A": "#0039A6",
    "C": "#0039A6",
    "E": "#0039A6",
    "B": "#FF6319",
    "D": "#FF6319",
    "F": "#FF6319",
    "FX": "#FF6319",
    "M": "#FF6319",
    "G": "#6CBE45",
    "J": "#996633",
    "Z": "#996633",
    "L": "#A7A9AC",
    "N": "#FCCC0A",
    "Q": "#FCCC0A",
    "R": "#FCCC0A",
    "W": "#FCCC0A",
    "S": "#808183",
    "FS": "#808183",
    "GS": "#808183",
    "H": "#808183",
    "SI": "#0039A6",
}


def load_dotenv() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)


def env(name: str) -> str:
    load_dotenv()
    return os.environ[name]


def kb(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{env('KIBANA_URL').rstrip('/')}/s/{SPACE}{path}"
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


def ensure_dv(view_id: str, title: str, name: str, time_field: str | None = "@timestamp") -> None:
    code, _ = kb("GET", f"/api/data_views/data_view/{view_id}")
    if code == 200:
        return
    dv: dict = {"id": view_id, "title": title, "name": name}
    if time_field:
        dv["timeFieldName"] = time_field
    kb("POST", "/api/data_views/data_view", {"data_view": dv})


def categorical_color(field_name: str) -> dict:
    """DYNAMIC CATEGORICAL color by route field with official MTA palette."""
    return {
        "type": "DYNAMIC",
        "options": {
            "type": "CATEGORICAL",
            "field": {"name": field_name, "origin": "source"},
            "useCustomColorPalette": True,
            "customColorPalette": [{"stop": k, "color": v} for k, v in MTA_ROUTE_COLORS.items()],
            "otherCategoryColor": "#666666",
            "fieldMetaOptions": {"isEnabled": False, "size": 50},
        },
    }


def vector_style_static(*, line: str, fill: str, size: int = 6, line_width: int = 2) -> dict:
    return {
        "type": "GEOJSON_VECTOR",
        "properties": {
            "symbolizeAs": {"options": {"value": "icon"}},
            "fillColor": {"type": "STATIC", "options": {"color": fill}},
            "lineColor": {"type": "STATIC", "options": {"color": line}},
            "lineWidth": {"type": "STATIC", "options": {"size": line_width}},
            "iconSize": {"type": "STATIC", "options": {"size": size}},
            "iconOrientation": {"type": "STATIC", "options": {"orientation": 0}},
            "labelColor": {"type": "STATIC", "options": {"color": "#000000"}},
            "labelSize": {"type": "STATIC", "options": {"size": 14}},
            "labelBorderColor": {"type": "STATIC", "options": {"color": "#FFFFFF"}},
            "labelBorderSize": {"options": {"size": "SMALL"}},
            "labelText": {"type": "STATIC", "options": {"value": ""}},
            "icon": {"type": "STATIC", "options": {"value": "marker"}},
        },
    }


def lines_style_by_route() -> dict:
    """Single GTFS lines layer — MTA colors by route_id (declutter vs per-line layers)."""
    return {
        "type": "GEOJSON_VECTOR",
        "properties": {
            "symbolizeAs": {"options": {"value": "icon"}},
            "fillColor": categorical_color("route_id"),
            "lineColor": categorical_color("route_id"),
            "lineWidth": {"type": "STATIC", "options": {"size": 2}},
            "iconSize": {"type": "STATIC", "options": {"size": 1}},
            "iconOrientation": {"type": "STATIC", "options": {"orientation": 0}},
            "labelColor": {"type": "STATIC", "options": {"color": "#000000"}},
            "labelSize": {"type": "STATIC", "options": {"size": 14}},
            "labelBorderColor": {"type": "STATIC", "options": {"color": "#FFFFFF"}},
            "labelBorderSize": {"options": {"size": "SMALL"}},
            "labelText": {"type": "STATIC", "options": {"value": ""}},
            "icon": {"type": "STATIC", "options": {"value": "marker"}},
        },
    }


def diverted_style_by_route() -> dict:
    """Problem markers inherit line identity via transit.route_id colors."""
    return {
        "type": "GEOJSON_VECTOR",
        "properties": {
            "symbolizeAs": {"options": {"value": "icon"}},
            "fillColor": categorical_color("transit.route_id"),
            "lineColor": {"type": "STATIC", "options": {"color": "#111111"}},
            "lineWidth": {"type": "STATIC", "options": {"size": 1}},
            "iconSize": {"type": "STATIC", "options": {"size": 10}},
            "iconOrientation": {"type": "STATIC", "options": {"orientation": 0}},
            "labelColor": {"type": "STATIC", "options": {"color": "#000000"}},
            "labelSize": {"type": "STATIC", "options": {"size": 14}},
            "labelBorderColor": {"type": "STATIC", "options": {"color": "#FFFFFF"}},
            "labelBorderSize": {"options": {"size": "SMALL"}},
            "labelText": {"type": "STATIC", "options": {"value": ""}},
            "icon": {"type": "STATIC", "options": {"value": "marker"}},
        },
    }


def ems_basemap() -> dict:
    return {
        "locale": "autoselect",
        "sourceDescriptor": {
            "type": "EMS_TMS",
            "isAutoSelect": True,
            "lightModeDefault": "road_map_desaturated_v9",
        },
        "id": "mta-basemap-ems",
        "minZoom": 0,
        "maxZoom": 24,
        "alpha": 1,
        "visible": True,
        "style": {"type": "EMS_VECTOR_TILE", "color": ""},
        "includeInFitToBounds": False,
        "type": "EMS_VECTOR_TILE",
    }


def docs_layer(
    *,
    layer_id: str,
    ref_name: str,
    label: str,
    geo_field: str,
    tooltip: list[str],
    style: dict,
    alpha: float = 1.0,
    apply_global_time: bool = False,
    kuery: str | None = None,
) -> dict:
    source: dict = {
        "type": "ES_SEARCH",
        "id": layer_id,
        "applyGlobalQuery": True,
        "applyGlobalTime": apply_global_time,
        "applyForceRefresh": True,
        "filterByMapBounds": True,
        "geoField": geo_field,
        "tooltipProperties": tooltip,
        "sortField": "",
        "sortOrder": "desc",
        "topHitsSize": 1,
        "indexPatternRefName": ref_name,
    }
    if kuery:
        source["query"] = {"query": kuery, "language": "kuery"}
    return {
        "sourceDescriptor": source,
        "id": layer_id,
        "label": label,
        "minZoom": 0,
        "maxZoom": 24,
        "alpha": alpha,
        "visible": True,
        "style": style,
        "includeInFitToBounds": True,
        "type": "GEOJSON_VECTOR",
    }


def main() -> None:
    ensure_dv("mta-geo-lines", "mta-geo-lines", "MTA GTFS Lines", time_field=None)
    ensure_dv("mta-geo-stations", "mta-geo-stations", "MTA GTFS Stations", time_field=None)
    ensure_dv("mta-subway", "logs-mta.subway_trip-*", "MTA Subway Trips")
    ensure_dv("mta-ene", "metrics-mta.ene_status-*", "MTA Elevator Escalator")

    layer_list = [
        ems_basemap(),
        docs_layer(
            layer_id="layer-lines",
            ref_name="layer_1_source_index_pattern",
            label="1. Subway lines (by route color)",
            geo_field="geometry",
            tooltip=["route_id", "shape_id", "route_ids"],
            style=lines_style_by_route(),
            alpha=0.9,
            apply_global_time=False,
        ),
        docs_layer(
            layer_id="layer-stations",
            ref_name="layer_2_source_index_pattern",
            label="2. Stations (GTFS stops)",
            geo_field="location",
            tooltip=["stop_name", "stop_id"],
            # muted so problem markers win when zoomed
            style=vector_style_static(line="#888888", fill="#FFFFFF", size=3, line_width=1),
            alpha=0.7,
            apply_global_time=False,
        ),
        docs_layer(
            layer_id="layer-diverted",
            ref_name="layer_3_source_index_pattern",
            label="3. Live track diverted (by route)",
            geo_field="station.location",
            tooltip=["transit.route_id", "transit.train_id", "transit.actual_track", "station.name", "message"],
            style=diverted_style_by_route(),
            apply_global_time=True,
            kuery="transit.track_diverted: true and station.location: *",
        ),
        docs_layer(
            layer_id="layer-ene",
            ref_name="layer_4_source_index_pattern",
            label="4. Elevator/escalator outages (real)",
            geo_field="station.location",
            tooltip=["equipment.id", "transit.station_name", "transit.reason", "message"],
            style=vector_style_static(line="#996600", fill="#F2C75C", size=7, line_width=1),
            apply_global_time=True,
            kuery="station.location: *",
        ),
    ]

    attributes = {
        "title": "MTA Transit Network (demo stack)",
        "description": (
            "Decluttered: single GTFS lines layer colored by route_id (MTA palette), "
            "not one layer per line. Diverted markers use transit.route_id colors. "
            "Basemap: EMS_VECTOR_TILE."
        ),
        "layerListJSON": json.dumps(layer_list),
        "mapStateJSON": json.dumps(
            {
                "zoom": 11,
                "center": {"lon": -73.95, "lat": 40.75},
                "timeFilters": {"from": "now-7d", "to": "now"},
                "filters": [],
                "query": {"query": "", "language": "kuery"},
            }
        ),
        "uiStateJSON": "{}",
    }
    references = [
        {"name": "layer_1_source_index_pattern", "type": "index-pattern", "id": "mta-geo-lines"},
        {"name": "layer_2_source_index_pattern", "type": "index-pattern", "id": "mta-geo-stations"},
        {"name": "layer_3_source_index_pattern", "type": "index-pattern", "id": "mta-subway"},
        {"name": "layer_4_source_index_pattern", "type": "index-pattern", "id": "mta-ene"},
    ]

    code, resp = kb(
        "PUT",
        f"/api/saved_objects/map/{MAP_ID}",
        {"attributes": attributes, "references": references},
    )
    if code not in (200, 201):
        code, resp = kb(
            "POST",
            f"/api/saved_objects/map/{MAP_ID}?overwrite=true",
            {"attributes": attributes, "references": references},
        )
    print(code, json.dumps(resp)[:300] if isinstance(resp, dict) else resp)

    _, obj = kb("GET", f"/api/saved_objects/map/{MAP_ID}")
    layers = json.loads(obj["attributes"]["layerListJSON"])
    lines = next(l for l in layers if l.get("id") == "layer-lines")
    lc = lines["style"]["properties"]["lineColor"]
    print("lines lineColor type:", lc.get("type"), "mapType:", (lc.get("options") or {}).get("type"))
    print("palette stops:", len((lc.get("options") or {}).get("customColorPalette") or []))
    print("layer count:", len(layers))
    print(f"Map URL: {env('KIBANA_URL')}/s/{SPACE}/app/maps/map/{MAP_ID}")


if __name__ == "__main__":
    main()
