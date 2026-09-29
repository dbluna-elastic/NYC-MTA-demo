# Demo script — MTA Transit Observability

**Space:** `mta-demo`  
**Primary URL:** https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/s/mta-demo  

**Thesis:** Public MTA feeds already show ops truth. Labeled simulated OT/IT shows what “inside the fence” looks like in the same Elastic cloud.

---

## 1. Open — why this matters (30 sec)

MTA runs a city-scale machine: trains, stations, elevators, and the OT/IT that keeps them safe. Today we start with **what the public already publishes**, then show **how security telemetry from the IDMZ would land in the same place** — so ops and SOC aren’t on different planets.

---

## 2. Transit map — what you’re looking at

**Open:** [Maps → `mta-transit-network`](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/s/mta-demo/app/maps/map/mta-transit-network)

| Layer | What it is | How we got it |
|---|---|---|
| Colored subway lines | Official route geometry | Static GTFS shapes → GeoJSON → Elasticsearch (`mta-geo-lines`), styled by `route_id` with MTA colors |
| Stations | Stop points (muted) | Static GTFS stops → GeoJSON (`mta-geo-stations`) |
| Diverted-train markers | Live trips where scheduled track ≠ actual track | Collector polls MTA **GTFS-Realtime** (~every 30s), parses NYCT protobuf extensions, indexes `logs-mta.subway_trip-*` with `transit.track_diverted: true` |
| Elevator/escalator outages | Equipment not in service | Collector polls MTA **E&E JSON** feeds → `metrics-mta.ene_status-*` |

**Say:** “This isn’t a mock map. Lines and stations are from published GTFS. Train and diversion dots are live public feed data our collector pulls into Elastic. One layer stack — not 29 separate line layers — so the map stays readable.”

**Analogy (optional):** Diverted track is like landing on the wrong runway vs the plan — small mismatch, big cascade if nobody sees it early.

---

## 3. Ops dashboard — early warning

**Open:** [Dashboard `mta-ops-scenarios`](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/s/mta-demo/app/dashboards#/view/mta-ops-scenarios)

**What you’re looking at:** Charts/searches on real subway trips (track divergence) and elevator availability, with Maximo-style work orders only where we simulate the CMMS side.

**How we got the data:**

- **Real:** same collector → `logs-mta.subway_trip` / `metrics-mta.ene_status`
- **Simulated Maximo (if shown):** mock webhook / simulator, always tagged so it’s never confused with production

**Say:** “Ops question: can we spot divergence and accessibility outages in one view? Yes — because both already stream as events Elastic can search and alert on.”

---

## 4. Security — same Space, different signal

**Open:** [Dashboard `mta-natca-coverage`](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/s/mta-demo/app/dashboards#/view/mta-natca-coverage), then Security → Alerts / Cases

**What you’re looking at:** Detection coverage aligned to NATCA-style functions (unauthorized OT commands, PLC change outside window, DoS, vendor remote access, NTP public fallback, vuln SLA, threat intel). Alerts feed a tabletop **case** for L1 → OT escalate.

**How we got the data:**  
**Not** from MTA public APIs. The **simulator** generates labeled OT/IT events (`labels.data_source: simulated`, `tags: SIMULATED` / `ATTACK`) into streams like `logs-mta.idmz-simulated`. ES|QL rules fire on that traffic. That’s intentional: we don’t invent MTA OT; we show the *shape* of the SIEM story.

**Say:** “Green is real public transit. Everything in this security story is clearly labeled simulated — so the demo never pretends we have their bungalow logs. The point is: when that signal exists, it lives next to the train map, not in a separate tool.”

**Analogies (optional, pick one):**

- Unauthorized Modbus write → throwing a switch that isn’t on the interlocking plan
- Vendor VPN at odd hours → contractor badge that still works after the shift
- NTP to a public pool → clocks syncing off a stranger’s watch (OK as last resort; bad if it’s normal)
- Vuln SLA → deferred-maintenance board with hard deadlines, not IT theater

See also [SCENARIO_4B_TABLETOP.md](SCENARIO_4B_TABLETOP.md) and [natca_coverage.md](../rules/natca_coverage.md).

---

## 5. Multi-agency (30 sec)

**Switch Spaces:** `nyct` → `lirr` → `mnr` → `bt`

**What you’re looking at:** Agency-scoped Kibana Spaces (MSSP-style isolation shells).

**How:** Same Elastic deployment; objects/tenancy separated by Space — one tower, separate radio nets.

**Say:** “RFP-shaped story: L1 monitoring and SIEM hosting for agencies without building four stacks.”

---

## 6. Close (20 sec)

“Two data paths, one platform: **collector** pulls public GTFS-RT and E&E into Elastic for ops; **simulator** shows how IDMZ/security would land beside it. Public exhaust proves the ops story; labeled OT proves the security story.”

---

## Cheat sheet — don’t mix these up

| If they ask… | Answer |
|---|---|
| Are the trains real? | Yes — public MTA GTFS-RT, polled by our collector |
| Is OT/security real MTA? | No — simulated and tagged; pattern demo only |
| Where does it live? | Elastic Cloud, Space `mta-demo` |
| What’s the ask? | One pane of glass for service + cyber when they’re ready to bring internal feeds in |
