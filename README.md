# MTA Transit Observability Demo

Elastic Cloud demo: **real public MTA feeds** plus **labeled simulated OT/IT security** telemetry. Kibana Space **`mta-demo`** isolates all demo objects from Default.

**Cluster:** `gawdzilla-0d3e9e` (Elastic 9.5.x)  
**Primary Space:** https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/s/mta-demo  
**Agency Spaces (MSSP shells):** `nyct`, `lirr`, `mnr`, `bt`

### Live demo objects (Space `mta-demo`)

| Object | Link |
|---|---|
| NATCA coverage + vuln SLA dashboard | [/s/mta-demo/app/dashboards#/view/mta-natca-coverage](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/s/mta-demo/app/dashboards#/view/mta-natca-coverage) |
| Ops scenarios 1–2 | [/s/mta-demo/app/dashboards#/view/mta-ops-scenarios](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/s/mta-demo/app/dashboards#/view/mta-ops-scenarios) |
| Tabletop case | [Security → Cases](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/s/mta-demo/app/security/cases) |
| Detection rules | 9 ES\|QL rules (`mta-*`) in Security → Rules |
| ML job | `mta-track-divergence-count` (started) |
| Transit map (GTFS GeoJSON stack) | [/s/mta-demo/app/maps/map/mta-transit-network](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/s/mta-demo/app/maps/map/mta-transit-network) |

## Thesis

> Here is what your public exhaust already tells us. Now imagine the signal from inside the fence.

Simulated streams always carry `labels.data_source: simulated` and `tags: SIMULATED`.

## Quick start

**New environment / another user:** follow **[SETUP.md](SETUP.md)** (clone → Spaces → API key → bootstrap → map → live ingest).

```bash
cp .env.example .env   # set ES_URL, ES_API_KEY, KIBANA_URL
python3 -m venv .venv && source .venv/bin/activate
pip install -r collector/requirements.txt -r simulator/requirements.txt
bash collector/compile_protos.sh

# Bootstrap templates, data streams, data views
python elastic/scripts/bootstrap_cluster.py

# Phase 0 feed check
python scripts/validate_feeds.py

# Seed security scenario + NATCA coverage objects
python simulator/simulator.py --once
python elastic/scripts/import_kibana_objects.py
python elastic/scripts/create_detection_rules.py

# Live collector (all enabled feeds from .env)
python collector/collector.py
# or: docker compose up --build mta-collector mta-simulator
```

Presenter script: [elastic/docs/DEMO_SCRIPT.md](elastic/docs/DEMO_SCRIPT.md)
## Scenarios

| # | Name | Data |
|---|---|---|
| 1 | Track divergence early warning | Real subway GTFS-RT (`transit.track_diverted`) |
| 2 | Elevator availability | Real E&E JSON + mock Maximo webhook |
| 3 | Storm resiliency | Simulated pump levels + real alerts |
| 4A | IDMZ / OT detections | Simulated Modbus, PLC, NTP fallback |
| 4B | SOC day-in-the-life | Cases, TI, vuln SLA, agency Spaces |

See [elastic/docs/SCENARIO_4B_TABLETOP.md](elastic/docs/SCENARIO_4B_TABLETOP.md) and [elastic/rules/natca_coverage.md](elastic/rules/natca_coverage.md).

## Guardrails

- Do **not** claim CBTC 500 ms / 50 ms thresholds (not in NATCA).
- NTP: public pools are **last resort**, not a hard prohibition — detection is “fell back to public NTP.”
- MTA RFP SSE 0000499549 closed Aug 2025 — confirm awardee before customer positioning.

## Repo layout

```
collector/     # GTFS-RT + E&E poller
simulator/     # Labeled OT/IT/security generator
agent/         # Optional IDMZ Elastic Agent (CEF)
elastic/       # Templates, rules, Kibana scripts
samples/       # Phase 0 feed captures
```
