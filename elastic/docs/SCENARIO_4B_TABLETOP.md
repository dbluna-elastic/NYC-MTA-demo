# Scenario 4B — SOC day in the life (tabletop)

**Space:** [mta-demo](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/s/mta-demo)

## Reset + replay

```bash
cd /Users/davidbluna/Cursor/NYC-MTA
set -a && source .env && set +a
python simulator/simulator.py --attack
```

## Walkthrough (15 min)

1. **Alert queue** — Security → Alerts in `mta-demo`. Expect Modbus write, vendor VPN, NTP fallback, unknown asset, vuln SLA.
2. **Attack Discovery** — Ask for a summary of the last hour of `tags: ATTACK` activity (IT + OT).
3. **Threat intel** — Discover `mta-ti-iocs` saved search; correlate `198.51.100.99` with remote access.
4. **Case** — Open a case "IDMZ tabletop YYYY-MM-DD", attach alerts, add note: L1 triage → escalate OT engineering.
5. **Vuln SLA exec panel** — Dashboard `mta-natca-coverage` / saved search `mta-vuln-sla` (Crit 30 / High 45 / Med 60 / Low 180).
6. **Multi-agency MSSP** — Switch Spaces `nyct` / `lirr` / `mnr` / `bt` to show agency isolation shells.
7. **Pipeline health** — Note no-data rules guidance in `elastic/rules/pipeline_health.md`.

## Positioning

Frames Elastic as the SIEM cloud an MSSP would host for MTA agencies (RFP: L1 monitoring, triage, SIEM hosting, threat intel) spanning IT and OT.
