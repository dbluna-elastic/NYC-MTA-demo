# MTA multi-layer map (GeoJSON + live feeds)

## Demo-friendly stack (bottom → top)

| # | Layer | Source | Index / file |
|---|---|---|---|
| 1 | Subway lines **by route color** | GTFS `shapes.txt` → GeoJSON | `mta-geo-lines` (`route_id` CATEGORICAL) |
| 2 | Stations (muted) | GTFS `stops.txt` → GeoJSON | `mta-geo-stations` |
| 3 | Live track diverted **by route** | Real collector | `logs-mta.subway_trip-*` |
| 4 | Elevator / escalator outages | Real E&E feed | `metrics-mta.ene_status-*` |

**Map (Space `mta-demo`):**  
https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/s/mta-demo/app/maps/map/mta-transit-network

## Declutter: color by route, not 29 layers

Do **not** split each subway line into its own Layers-panel entry (~29 `route_id`s). That clutters the UI more than the map.

Instead:

- One lines layer with **DYNAMIC CATEGORICAL** styling on `route_id` using official MTA hex colors.
- Diverted markers use the same palette on `transit.route_id` so problems keep line identity when zoomed.
- Stations stay small/white so they do not compete with problem markers.
- If you need a demo “solo the 7” toggle later, add a few trunk Kuery filters — not one layer per route.

Palette lives in [`elastic/scripts/create_transit_map.py`](../scripts/create_transit_map.py) as `MTA_ROUTE_COLORS`.

## Rebuild from GTFS (nyc-gtfs2geojson style)

```bash
cd /Users/davidbluna/Cursor/NYC-MTA
source .venv/bin/activate && set -a && source .env && set +a

python scripts/gtfs2geojson.py \
  --gtfs-zip samples/gtfs/gtfs_subway.zip \
  --out-dir geojson/subway

python scripts/load_geojson_to_es.py
python elastic/scripts/create_transit_map.py

# Or: ./scripts/build_transit_geo_stack.sh
```

Outputs:

- `geojson/subway/lines.geojson` — one LineString per `shape_id`, with `route_id` / `route_ids` from `trips.txt`
- `geojson/subway/stops.geojson` — one Point per stop

## Manual tweak in Maps UI

If a live layer shows no points:

1. Confirm docs have `station.location` (backfill: `python elastic/scripts/backfill_map_geo.py`).
2. Time range must cover recent collector data (**Last 7 days** is the map default).

If **Basemap** shows a red X (EMS blocked by network/VPN/CSP):

1. Delete the broken Basemap layer.
2. **Add layer** → Tile / EMS roadmap your network allows.
3. Layers 1–4 still provide full NYC geography without a basemap.
