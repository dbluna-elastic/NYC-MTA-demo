# NATCA 22.3.9 Detection Coverage Matrix

| Function | Rule file | Data stream | MITRE ICS |
|---|---|---|---|
| Unauthorized system intrusion | `modbus_write_enterprise.esql` | `logs-mta.idmz-simulated` | T0855 Unauthorized Command Message |
| Unauthorized system modification | `plc_logic_outside_window.esql` | `logs-mta.idmz-simulated` | T0839 Module Firmware |
| Denial of service attack | `ot_dos_flood.esql` | `logs-mta.idmz-simulated` | T0814 Denial of Service |
| Unplanned shutdowns | `unplanned_shutdown.esql` | `logs-mta.idmz-simulated` | T0816 Device Restart/Shutdown |
| Unexpected remote logons | `vendor_remote_access.esql` | `logs-mta.remote_access-simulated` | T0886 Remote Services |
| Unauthorized internal/external communication | `ntp_public_fallback.esql` | `logs-mta.idmz-simulated` | T0885 Commonly Used Port / lateral |

Additional supporting rules:

- `unknown_asset.esql` — NATCA 8 / 16.8 inventory
- `vuln_sla_breach.esql` — NATCA 5 / 6 patch deadlines
- `threat_intel_match.esql` — RFP threat intelligence
- `pipeline_health.md` — NATCA 22.2.6 no-data guidance
