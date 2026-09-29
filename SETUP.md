# Set up this demo on your Elastic environment

Use this repo to stand up the **MTA Transit Observability** demo on **your** Elastic Cloud (or self-managed) deployment. Nothing in GitHub points at a shared cluster — you bring `ES_URL`, `KIBANA_URL`, and an API key.

**Repo:** https://github.com/dbluna-elastic/NYC-MTA-demo

---

## What you get

| Piece | Source |
|---|---|
| Live subway / railroad / alerts / elevators | Public MTA feeds → local **collector** → your Elasticsearch |
| OT / IT / security scenarios | Local **simulator** (always tagged `simulated`) |
| Dashboards, rules, map, Spaces | Bootstrap scripts against **your** Kibana |

Presenter talk track: [elastic/docs/DEMO_SCRIPT.md](elastic/docs/DEMO_SCRIPT.md)

---

## Prerequisites

- **Elastic Stack 9.x** (tested on 9.5.x) with Elasticsearch + Kibana
- Elastic Security enabled (detection rules + cases)
- **Python 3.11+**, `pip`, `curl`, `unzip`
- Optional: Docker / Docker Compose for long-running collector + simulator
- Network access to:
  - Your Elasticsearch and Kibana URLs
  - `https://api-endpoint.mta.info` (realtime)
  - `https://rrgtfsfeeds.s3.amazonaws.com` (static GTFS, for the map)

You do **not** need an MTA API key for the feeds used in this demo.

---

## 1. Clone the repo

```bash
git clone https://github.com/dbluna-elastic/NYC-MTA-demo.git
cd NYC-MTA-demo
```

---

## 2. Create Kibana Spaces (manual, once)

Bootstrap scripts write into these Space IDs. Create them in Kibana → **Stack Management → Spaces** before running scripts:

| Space ID | Purpose |
|---|---|
| `mta-demo` | Primary demo (map, dashboards, rules, case) |
| `nyct` | Agency shell (MSSP story) |
| `lirr` | Agency shell |
| `mnr` | Agency shell |
| `bt` | Agency shell |

Use those **exact** IDs (lowercase).

---

## 3. Create an API key

In Kibana → **Stack Management → API keys**, create a key that can:

- Manage index templates and data streams
- Index / create / read on `logs-mta.*`, `metrics-mta.*`, `logs-cef.*`, and geo indices (`mta-geo-*`, `mta-stop-ref`)
- Call Kibana APIs (saved objects, data views, Security rules/cases) — typically a key owned by a user with Kibana admin + Security privileges for Space `mta-demo`

Copy the encoded API key once; you will put it only in local `.env` (never commit it).

---

## 4. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:

```bash
ES_URL=https://YOUR_DEPLOYMENT.es.REGION.aws.elastic-cloud.com
ES_API_KEY=your_encoded_api_key_here
KIBANA_URL=https://YOUR_DEPLOYMENT.kb.REGION.aws.elastic-cloud.com

POLL_INTERVAL_SECONDS=30
# Comma-separated feed IDs from collector/feeds.yaml
COLLECTOR_ENABLED_FEEDS=subway_1234567S,subway_ace,alerts,ene
LOG_LEVEL=INFO
```

Tips:

- Use the **Elasticsearch** HTTPS URL for `ES_URL` (not Kibana).
- Start with a few feeds; enable more from `collector/feeds.yaml` as needed.
- `.env` is gitignored — do not commit it or paste keys into chat/issues.

---

## 5. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r collector/requirements.txt -r simulator/requirements.txt
bash collector/compile_protos.sh   # generates GTFS-RT / NYCT protobuf bindings
```

---

## 6. Bootstrap your cluster

**Option A — one shot** (recommended):

```bash
set -a && source .env && set +a
bash scripts/bootstrap_all.sh
```

That script:

1. Compiles protos  
2. Applies index templates + data streams + data views  
3. Validates public feeds  
4. Loads stop refdata + enrich  
5. Seeds simulator data once  
6. Imports Kibana dashboards/searches  
7. Creates detection rules + tabletop case  
8. Starts the ML job (best-effort)

**Option B — step by step** (same order as `bootstrap_all.sh`):

```bash
set -a && source .env && set +a
source .venv/bin/activate

python elastic/scripts/bootstrap_cluster.py
python scripts/validate_feeds.py
python collector/refdata.py
python elastic/scripts/setup_enrich.py
python simulator/simulator.py --once
python elastic/scripts/import_kibana_objects.py
python elastic/scripts/create_detection_rules.py
python elastic/scripts/create_tabletop_case.py
python elastic/scripts/setup_ml_job.py || true
```

---

## 7. Build the transit map (GeoJSON stack)

Repo may already include `geojson/subway/lines.geojson` and `stops.geojson`. To rebuild from official GTFS and publish the Kibana map:

```bash
bash scripts/build_transit_geo_stack.sh
```

This downloads GTFS if needed, converts shapes/stops → GeoJSON, indexes `mta-geo-lines` / `mta-geo-stations`, and creates map `mta-transit-network` in Space `mta-demo`.

If live diverted markers lack coordinates later:

```bash
python elastic/scripts/backfill_map_geo.py
```

---

## 8. Start live ingest

Keep two processes running (or use Compose).

**Local:**

```bash
source .venv/bin/activate
set -a && source .env && set +a

# Terminal 1 — real MTA feeds
python collector/collector.py

# Terminal 2 — labeled security / OT simulation
python simulator/simulator.py --interval 120 --attack-every 5
```

**Docker:**

```bash
docker compose up --build mta-collector mta-simulator
```

(`docker-compose.yml` reads the same `.env`.)

---

## 9. Verify in Kibana

Open: `$KIBANA_URL/s/mta-demo`

| Check | Where |
|---|---|
| Subway docs arriving | Discover → data view **MTA Subway Trips** |
| Map | Maps → **MTA Transit Network** |
| Ops story | Dashboard **mta-ops-scenarios** |
| NATCA / security | Dashboard **mta-natca-coverage** |
| Rules | Security → Rules (`mta-*`) |
| Tabletop | Security → Cases |
| Agency shells | Switch Space to `nyct` / `lirr` / `mnr` / `bt` |

Walkthrough script: [elastic/docs/DEMO_SCRIPT.md](elastic/docs/DEMO_SCRIPT.md)

Replay a denser attack burst:

```bash
python simulator/simulator.py --attack
```

---

## Data boundaries (important)

| Data | Real MTA? | How labeled |
|---|---|---|
| GTFS-RT trips, arrivals, alerts, E&E | Yes (public) | `labels.data_source: real` |
| IDMZ / Modbus / PLC / NTP / vendor VPN / vuln / TI | No | `labels.data_source: simulated`, `tags: SIMULATED` |

Never present simulated OT/IT as customer production telemetry.

---

## Optional components

| Profile / piece | Command / note |
|---|---|
| Mock Maximo webhook | `docker compose --profile maximo up mock-maximo` |
| Elastic Agent + CEF | `docker compose --profile agent up elastic-agent` (see `agent/elastic-agent.yml`) |
| Stop / E&E Socrata refdata only | `docker compose --profile refdata up mta-refdata` |

---

## Troubleshooting

| Symptom | What to try |
|---|---|
| `Missing ES_URL` / `ES_API_KEY` | Ensure `.env` is sourced; run from repo root |
| SSL / cert errors | Scripts often disable verify for lab use; confirm URL is HTTPS Elasticsearch endpoint |
| Data views 404 / Space missing | Create Spaces with IDs above, re-run `bootstrap_cluster.py` |
| Rules / case create fails | API key user needs Security privileges in `mta-demo` |
| Collector empty / stale | `python scripts/validate_feeds.py`; check `COLLECTOR_ENABLED_FEEDS` |
| Map empty lines | Run `bash scripts/build_transit_geo_stack.sh` |
| No diverted dots with geo | Run collector, then `python elastic/scripts/backfill_map_geo.py` |

---

## Hand-off checklist for another SE

- [ ] Clone repo; do not copy someone else’s `.env`
- [ ] Create Spaces + API key on **their** deployment
- [ ] Run bootstrap + geo stack + collector + simulator
- [ ] Confirm real trips in Discover and map loads
- [ ] Confirm simulated events tagged before any customer demo
- [ ] Use [DEMO_SCRIPT.md](elastic/docs/DEMO_SCRIPT.md); respect [README guardrails](README.md#guardrails)

---

## Tear-down (optional)

To remove demo artifacts from a shared cluster (manual):

1. Stop collector and simulator  
2. Delete data streams / indices matching `logs-mta.*`, `metrics-mta.*`, `logs-cef.*`, `mta-geo-*`  
3. Delete Space `mta-demo` (and agency Spaces) or only the saved objects inside them  
4. Delete detection rules tagged `mta-demo`  
5. Delete the API key  

Exact clean-up depends on whether the deployment is demo-only or shared with other work.
