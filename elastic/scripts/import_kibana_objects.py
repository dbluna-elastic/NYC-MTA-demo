#!/usr/bin/env python3
"""Create NATCA coverage + vuln SLA saved searches / dashboard in Space mta-demo."""

from __future__ import annotations

import json
import os
import ssl
import uuid
import urllib.error
import urllib.request
from pathlib import Path

SSL_CTX = ssl._create_unverified_context()

ROOT = Path(__file__).resolve().parents[2]


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


def env(name: str) -> str:
    load_dotenv()
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"Missing {name}")
    return v


def kb(method: str, path: str, body: dict | None = None, space: str = "mta-demo") -> tuple[int, dict]:
    base = env("KIBANA_URL").rstrip("/")
    url = f"{base}/s/{space}{path}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"ApiKey {env('ES_API_KEY')}",
            "kbn-xsrf": "true",
            "Content-Type": "application/json",
            "elastic-api-version": "2023-10-31",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"error": raw}


def upsert_so(so_type: str, so_id: str, attributes: dict, references: list | None = None) -> None:
    body = {
        "attributes": attributes,
        "references": references or [],
        "overwrite": True,
    }
    # Try saved objects API
    code, resp = kb("POST", f"/api/saved_objects/{so_type}/{so_id}", {**body, "id": so_id})
    if code in (200, 201):
        print(f"ok {so_type}/{so_id}")
        return
    # fallback create without id in path for some versions
    code2, resp2 = kb(
        "POST",
        f"/api/saved_objects/{so_type}/{so_id}?overwrite=true",
        {"attributes": attributes, "references": references or []},
    )
    print(f"{so_type}/{so_id}: {code}/{code2} {resp if code >= 400 else ''} {resp2 if code2 >= 400 else 'ok'}")


def main() -> None:
    # Lens-less markdown dashboard via legacy dashboard with markdown panels + search embeds is heavy.
    # Create saved searches (Discover) for each NATCA function + a dashboard linking them.

    searches = [
        (
            "mta-natca-intrusion",
            "NATCA: Unauthorized intrusion",
            "logs-mta.idmz-*,logs-mta.ot_asset-*,logs-mta.onboard-*,logs-mta.wireless-*",
            'transit.natca_function: "unauthorized_system_intrusion" OR tags: ATTACK',
        ),
        (
            "mta-natca-modification",
            "NATCA: Unauthorized modification",
            "logs-mta.idmz-*,logs-mta.netconfig-*,logs-mta.windows_ad-*",
            'transit.natca_function: "unauthorized_modification"',
        ),
        (
            "mta-natca-dos",
            "NATCA: Denial of service",
            "logs-mta.idmz-*",
            'transit.natca_function: "denial_of_service"',
        ),
        (
            "mta-natca-shutdown",
            "NATCA: Unplanned shutdown",
            "logs-mta.idmz-*",
            'transit.natca_function: "unplanned_shutdown"',
        ),
        (
            "mta-natca-remote",
            "NATCA: Unexpected remote logon",
            "logs-mta.remote_access-*,logs-mta.windows_ad-*",
            'transit.natca_function: "unexpected_remote_logon"',
        ),
        (
            "mta-natca-comm",
            "NATCA: Unauthorized communication",
            "logs-mta.idmz-*",
            'transit.natca_function: "unauthorized_communication" OR transit.ntp_fallback: true',
        ),
        (
            "mta-vuln-sla",
            "NATCA Vuln SLA (aging)",
            "logs-mta.vuln_finding-*",
            "transit.vuln_overdue: true OR vulnerability.severity: *",
        ),
        (
            "mta-track-diverted",
            "Scenario 1: Track diverted trains",
            "logs-mta.subway_trip-*",
            "transit.track_diverted: true",
        ),
        (
            "mta-ene-outages",
            "Scenario 2: Elevator/Escalator outages",
            "metrics-mta.ene_status-*",
            "labels.data_source: real",
        ),
        (
            "mta-ti-iocs",
            "Threat intel IOCs",
            "logs-mta.threat_intel-*",
            "labels.data_source: simulated",
        ),
    ]

    panels = []
    refs = []
    for i, (sid, title, index, query) in enumerate(searches):
        attrs = {
            "title": title,
            "description": "MTA demo saved search",
            "columns": ["message", "transit.natca_function", "labels.agency", "host.name"],
            "sort": [["@timestamp", "desc"]],
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps(
                    {
                        "index": sid + "-idx",
                        "query": {"query": query, "language": "kuery"},
                        "filter": [],
                    }
                )
            },
        }
        # Create data view per search title pattern for reliability
        dv_id = f"dv-{sid}"
        code, _ = kb("GET", f"/api/data_views/data_view/{dv_id}")
        if code != 200:
            kb(
                "POST",
                "/api/data_views/data_view",
                {
                    "data_view": {
                        "id": dv_id,
                        "title": index,
                        "name": title + " view",
                        "timeFieldName": "@timestamp",
                    }
                },
            )
        attrs["kibanaSavedObjectMeta"] = {
            "searchSourceJSON": json.dumps(
                {
                    "index": dv_id,
                    "query": {"query": query, "language": "kuery"},
                    "filter": [],
                }
            )
        }
        upsert_so(
            "search",
            sid,
            attrs,
            references=[{"name": "kibanaSavedObjectMeta.searchSourceJSON.index", "type": "index-pattern", "id": dv_id}],
        )
        # Also try referencing data view — Kibana 8+ uses index-pattern id equal to data view id
        panel_id = str(uuid.uuid4())
        panels.append(
            {
                "version": "1",
                "type": "search",
                "gridData": {
                    "x": (i % 2) * 24,
                    "y": (i // 2) * 12,
                    "w": 24,
                    "h": 12,
                    "i": panel_id,
                },
                "panelIndex": panel_id,
                "embeddableConfig": {"enhancements": {}},
                "panelRefName": f"panel_{i}",
            }
        )
        refs.append({"name": f"panel_{i}", "type": "search", "id": sid})

    # Coverage matrix markdown via dashboard description + panels
    dash_attrs = {
        "title": "MTA NATCA Detection Coverage + Vuln SLA",
        "description": (
            "Six NATCA 22.3.9 detection functions + vuln aging (Crit 30 / High 45 / Med 60 / Low 180). "
            "All simulated security data tagged labels.data_source:simulated. "
            "Open in Space mta-demo. Tabletop: run `python simulator/simulator.py --attack`."
        ),
        "panelsJSON": json.dumps(panels),
        "optionsJSON": json.dumps({"useMargins": True, "syncColors": False, "hidePanelTitles": False}),
        "timeRestore": False,
        "kibanaSavedObjectMeta": {
            "searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})
        },
        "version": 1,
    }
    upsert_so("dashboard", "mta-natca-coverage", dash_attrs, references=refs)

    # Ops dashboard
    ops_panels = []
    ops_refs = []
    for i, sid in enumerate(["mta-track-diverted", "mta-ene-outages"]):
        panel_id = str(uuid.uuid4())
        ops_panels.append(
            {
                "version": "1",
                "type": "search",
                "gridData": {"x": (i % 2) * 24, "y": (i // 2) * 16, "w": 24, "h": 16, "i": panel_id},
                "panelIndex": panel_id,
                "embeddableConfig": {},
                "panelRefName": f"panel_{i}",
            }
        )
        ops_refs.append({"name": f"panel_{i}", "type": "search", "id": sid})

    upsert_so(
        "dashboard",
        "mta-ops-scenarios",
        {
            "title": "MTA Ops Scenarios 1-2 (Track divergence + E&E)",
            "description": "Real public MTA feeds. Scenario 1 track_diverted; Scenario 2 elevator outages.",
            "panelsJSON": json.dumps(ops_panels),
            "optionsJSON": json.dumps({"useMargins": True}),
            "timeRestore": False,
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})
            },
            "version": 1,
        },
        references=ops_refs,
    )

    # Tag space default route hint
    print(
        "Dashboards ready in space mta-demo:\n"
        f"  {env('KIBANA_URL')}/s/mta-demo/app/dashboards#/view/mta-natca-coverage\n"
        f"  {env('KIBANA_URL')}/s/mta-demo/app/dashboards#/view/mta-ops-scenarios"
    )


if __name__ == "__main__":
    main()
