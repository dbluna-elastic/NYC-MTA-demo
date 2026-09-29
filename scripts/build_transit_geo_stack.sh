#!/usr/bin/env bash
# GTFS → GeoJSON → Elasticsearch → Kibana multi-layer map (demo stack)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
# shellcheck disable=SC1091
source .env
set +a
# shellcheck disable=SC1091
source .venv/bin/activate

GTFS_ZIP="${GTFS_ZIP:-samples/gtfs/gtfs_subway.zip}"
GTFS_URL="${GTFS_URL:-https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip}"

mkdir -p samples/gtfs geojson/subway

if [[ ! -f "$GTFS_ZIP" ]] || ! unzip -t "$GTFS_ZIP" >/dev/null 2>&1; then
  echo "Downloading GTFS from $GTFS_URL ..."
  curl -L --retry 5 --retry-delay 3 --max-time 900 -o "$GTFS_ZIP" "$GTFS_URL"
fi

echo "Converting shapes.txt / stops.txt → GeoJSON (nyc-gtfs2geojson style)..."
python scripts/gtfs2geojson.py --gtfs-zip "$GTFS_ZIP" --out-dir geojson/subway

echo "Indexing into Elasticsearch..."
python scripts/load_geojson_to_es.py

echo "Creating Kibana map (demo stack)..."
python elastic/scripts/create_transit_map.py

echo "Done. Open Space mta-demo → Maps → MTA Transit Network"
